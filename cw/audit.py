"""Audit a migrated source tree for what is left of ``argh``.

Every other gate cw offers is blind to a *residual* ``argh`` by construction:
``cw.testing`` goldens characterize ``--help`` (a ``CommandError`` fires after dispatch,
past anything a help corpus reaches), ``python -m cw specs`` looks at one signature, and
``cw.compat`` only helps a module that switched to ``from cw import compat as argh``. This
module is the gate that reads the *source*, so a migration can be called finished by a
check that runs in CI instead of by a prose warning.

Five checks, each with a stable code:

``import``
    ``import argh`` / ``from argh import ...`` anywhere. The headline check.
``command-error``
    ``from argh import CommandError`` (or ``argh.CommandError`` through an alias). The one
    residual that silently changes runtime behaviour rather than merely failing to import:
    ``argh.CommandError is cw.CommandError`` is ``False``, so a raise of the former escapes
    ``cw.run`` as a traceback where argh printed ``CommandError: <msg>`` and exited 1.
``dispatch``
    A live ``argh.dispatch*`` / ``ArghParser`` / ``EntryPoint`` call, including under
    ``if __name__ == "__main__"`` (which looks dead and is not: ``python -m pkg.mod`` runs it).
``dependency``
    ``argh`` declared in ``pyproject.toml`` / ``setup.cfg`` / ``setup.py`` /
    ``requirements*.txt`` (the licence-exposure-only case when nothing imports it).
``discarded-exit``
    ``cw.dispatch(...)`` as a bare statement. cw *returns* the exit code where argh exited
    itself, so dropping it turns every non-zero exit into 0. Calls that pass ``out=`` /
    ``err=`` or ``standalone=False`` are capturing output (a test), and are not flagged,
    nor is anything in a test file.
``unparsable``
    A file that could not be read or parsed (Python 2, syntax newer than the interpreter
    running the audit, a NUL byte, absurd nesting). It fails the gate rather than being
    skipped: an audit cannot vouch for what it did not read. Exclude the directory.

Nothing here imports ``argh``, or anything but the standard library: it reads files, and
the answer is the same whether or not ``argh`` is installed on the machine running it.

>>> src = "from argh import CommandError\\n"
>>> [(f.line, f.code) for f in audit_source(src)]
[(1, 'command-error'), (1, 'import')]
>>> [f.code for f in audit_source("import argh\\nargh.dispatch_commands([f])\\n")]
['import', 'dispatch']
>>> audit_source("from cw import compat as argh\\nargh.dispatch_commands([f])\\n")
[]

A line can opt out, for the rare place that is *meant* to touch real argh (a parity test)::

    import argh  # cw-audit: ignore

Run it on a tree::

    python -m cw audit .

or gate on it in a consumer's own test suite::

    def test_no_residual_argh():
        from cw.audit import assert_no_argh
        assert_no_argh(Path(__file__).parents[1])
"""

import ast
import codecs
import re
import stat
import sys
import threading
import tokenize
import functools
from contextlib import contextmanager
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path

__all__ = [
    "Finding",
    "audit",
    "audit_source",
    "audit_dependencies",
    "format_findings",
    "assert_no_argh",
    "CODES",
    "DEFAULT_EXCLUDE_DIRS",
    "DEFAULT_EXCLUDE_TOP_DIRS",
    "IGNORE_PRAGMA",
]

#: The comment that exempts its line (any line of a multi-line statement).
IGNORE_PRAGMA = "cw-audit: ignore"
_PRAGMA = re.compile(r"#\s*cw-audit:\s*ignore\b")

#: Directory names never worth descending into, at any depth.
DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".tox",
        ".nox",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "site-packages",
    }
)

#: Directory names skipped only directly under the audited root. Deeper they are ordinary
#: package names (``pkg/build/``, ``pkg/env/``), so skipping them there would hide source.
#: Any directory holding a ``pyvenv.cfg`` is a virtualenv wherever it is.
DEFAULT_EXCLUDE_TOP_DIRS = frozenset({".venv", "venv", "env", "build", "dist"})

#: The names ``argh`` exports that start or run a command-line program.
ARGH_DISPATCH_NAMES = frozenset(
    {"dispatch", "dispatch_command", "dispatch_commands", "ArghParser", "EntryPoint"}
)

#: ``from argh import <these>`` binds a submodule, not a function.
_ARGH_SUBMODULES = frozenset(
    {
        "assembling",
        "completion",
        "constants",
        "decorators",
        "dispatching",
        "exceptions",
        "helpers",
        "interaction",
        "io",
        "utils",
    }
)

#: Keys (dashes and underscores equal) whose values are requirements.
_DEPENDENCY_KEYS = frozenset(
    {
        "dependencies",
        "requires",
        "requirements",
        "install_requires",
        "setup_requires",
        "tests_require",
        "extras_require",
        "optional_dependencies",
        "dev_dependencies",
        "extra_dependencies",
        "override_dependencies",
        "constraint_dependencies",
        "dependency_groups",
        "pypi_dependencies",
        "requires_extra",
    }
)

#: Tables whose *keys* are names of extras / groups, not of packages (``argh = ["cw"]``).
_GROUP_TABLES = frozenset(
    {"optional_dependencies", "extras_require", "requires_extra", "dependency_groups"}
)

#: ``argh`` as a requirement: with extras, then a specifier, marker or url, or nothing.
_SPEC = r"argh(?![-_.\w])\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;@(].*)?"
#: An ``#egg=argh`` fragment (optionally ``-<version>``, optionally followed by ``&...``).
_EGG = r".*[#&]egg=argh(?:-\d[\w.]*)?(?:&.*)?"
#: Quoted (pyproject, setup.py) anywhere on a line; bare (setup.cfg, requirements) as the line.
_QUOTED_REQUIREMENT = re.compile(rf"""["']\s*{_SPEC}["']""", re.I)
_BARE_REQUIREMENT = re.compile(rf"^(?:{_SPEC}|{_EGG})$", re.I)
#: ``{ argh = "^1" }`` -- a Poetry inline table.
_INLINE_ARGH = re.compile(r"[{,]\s*argh\s*=", re.I)
_PYTHON_SUFFIXES = (".py", ".pyi", ".pyw")
_REQUIREMENT_FILES = ("pyproject.toml", "setup.cfg", "setup.py")
_KEY = re.compile(r"^\s*(?:[\w.]*\(\s*)?([\w.-]+)\s*[=:](?![=/])\s*(.*)$")
_HEADER = re.compile(r"""^\[+\s*([^\]"'\s][^\]]*)\]+\s*(?:#.*)?$""")

CODES = {
    "import": "argh is imported",
    "command-error": "CommandError taken from argh, not cw",
    "dispatch": "argh dispatch still reachable",
    "dependency": "argh declared as a dependency",
    "discarded-exit": "cw.dispatch exit code discarded",
    "unparsable": "a file could not be read or parsed, so it was not checked",
}

_DEPENDENCY_WHY = (
    "argh is declared as a dependency (LGPL-3.0-or-later); drop it once nothing "
    "imports it."
)

_COMMAND_ERROR_WHY = (
    "argh.CommandError is not cw.CommandError, so a raise of it escapes cw.run as a "
    "traceback where argh printed 'CommandError: <msg>' and exited 1. Import it from cw."
)


@dataclass(frozen=True, order=True)
class Finding:
    """One residual: where it is, which check found it, and what to do.

    >>> str(Finding("a.py", 3, "import", "argh is imported"))
    'a.py:3: import: argh is imported'
    """

    path: str
    line: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


# --------------------------------------------------------------------------------------
# Python source: imports, dispatch calls, discarded exit codes


def _is_argh(module: str | None) -> bool:
    return bool(module) and (module == "argh" or module.startswith("argh."))


class _Visitor(ast.NodeVisitor):
    """Collect findings from one module's AST.

    Tracks which local names are bound to real ``argh`` (so ``from cw import compat as
    argh`` is rightly left alone) and to ``cw.dispatch`` / ``cw.run``.
    """

    def __init__(self) -> None:
        #: ``(first line, last line, code, message)``
        self.findings: list[tuple[int, int, str, str]] = []
        self.argh_modules: set[str] = set()  # names bound to argh or an argh submodule
        self.argh_names: dict[str, str] = {}  # local name -> argh attribute
        self.argh_star = False  # ``from argh import *``
        self.cw_modules: set[str] = set()  # names bound to cw / cw.cli
        self.cw_dispatchers: set[str] = set()  # names bound to cw.dispatch / cw.run
        self._main_guard_depth = 0

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        end = getattr(node, "end_lineno", None) or node.lineno
        self.findings.append((node.lineno, end, code, message))

    # -- imports -------------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _is_argh(alias.name):
                self._add(node, "import", f"import {alias.name}")
                # ``import argh.x`` binds ``argh``; ``import argh.x as y`` binds ``y``.
                self.argh_modules.add(alias.asname or "argh")
            elif alias.name in ("cw", "cw.cli"):
                self.cw_modules.add(alias.asname or "cw")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and _is_argh(node.module):
            names = ", ".join(alias.name for alias in node.names)
            self._add(node, "import", f"from {node.module} import {names}")
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "CommandError":
                    self._add(node, "command-error", _COMMAND_ERROR_WHY)
                elif alias.name == "*":
                    self.argh_star = True
                elif node.module == "argh" and alias.name in _ARGH_SUBMODULES:
                    self.argh_modules.add(local)
                else:
                    self.argh_names[local] = alias.name
        elif node.level == 0 and node.module in ("cw", "cw.cli"):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name in ("dispatch", "run"):
                    self.cw_dispatchers.add(local)
                elif alias.name == "cli":
                    self.cw_modules.add(local)
        self.generic_visit(node)

    # -- argh attribute use --------------------------------------------------------
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "CommandError":
            root = node.value
            while isinstance(root, ast.Attribute):  # argh.exceptions.CommandError
                root = root.value
            if isinstance(root, ast.Name) and root.id in self.argh_modules:
                self._add(node, "command-error", _COMMAND_ERROR_WHY)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if (
            self.argh_star
            and node.id == "CommandError"
            and isinstance(node.ctx, ast.Load)
        ):
            self._add(node, "command-error", _COMMAND_ERROR_WHY)

    # -- calls ---------------------------------------------------------------------
    def _argh_dispatch_name(self, func: ast.expr) -> str | None:
        """The argh dispatching name ``func`` calls, or None."""
        if isinstance(func, ast.Name):
            attr = self.argh_names.get(func.id)
            if attr is None and self.argh_star and func.id in ARGH_DISPATCH_NAMES:
                attr = func.id
            return attr if attr in ARGH_DISPATCH_NAMES else None
        if isinstance(func, ast.Attribute) and func.attr in ARGH_DISPATCH_NAMES:
            root = func.value
            while isinstance(root, ast.Attribute):  # argh.dispatching.dispatch
                root = root.value
            if isinstance(root, ast.Name) and root.id in self.argh_modules:
                return func.attr
        return None

    @staticmethod
    def _dynamic_import_target(node: ast.Call) -> str | None:
        """The constant module name of ``import_module("x")`` / ``__import__("x")``, or None."""
        func = node.func
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if called not in ("import_module", "__import__") or not node.args:
            return None
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
        return None

    def visit_Call(self, node: ast.Call) -> None:
        target = self._dynamic_import_target(node)
        if _is_argh(target):
            self._add(node, "import", f"dynamic import of {target}")
        name = self._argh_dispatch_name(node.func)
        if name:
            reach = (
                " It sits under an `if __name__ == '__main__'` guard, which looks "
                "dead but is reached by `python -m <module>`."
                if self._main_guard_depth
                else ""
            )
            self._add(node, "dispatch", f"argh.{name}(...) is still called.{reach}")
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if _is_main_guard(node.test):
            self.visit(node.test)
            self._main_guard_depth += 1
            for child in node.body:
                self.visit(child)
            self._main_guard_depth -= 1
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    # -- discarded exit code -------------------------------------------------------
    def _is_cw_dispatch(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in self.cw_dispatchers
        if isinstance(func, ast.Attribute) and func.attr in ("dispatch", "run"):
            root = func.value
            while isinstance(root, ast.Attribute):  # cw.cli.dispatch
                root = root.value
            return isinstance(root, ast.Name) and root.id in self.cw_modules
        return False

    @staticmethod
    def _captures_output(call: ast.Call) -> bool:
        """``out=`` / ``err=`` given, or ``standalone`` set to anything but True."""
        for keyword in call.keywords:
            if keyword.arg in ("out", "err"):
                return True
            if keyword.arg == "standalone":
                value = keyword.value
                if not (isinstance(value, ast.Constant) and value.value is True):
                    return True
        return False

    def visit_Expr(self, node: ast.Expr) -> None:
        call = node.value
        if (
            isinstance(call, ast.Call)
            and self._is_cw_dispatch(call.func)
            and not self._captures_output(call)
        ):
            self._add(
                node,
                "discarded-exit",
                "cw returns the exit code where argh exited itself; "
                "wrap it: `raise SystemExit(cw.dispatch(...))`.",
            )
        self.generic_visit(node)


def _is_main_guard(test: ast.expr) -> bool:
    """Is ``test`` ``__name__ == "__main__"`` (either order)?"""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    sides = [test.left, test.comparators[0]]
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    has_main = any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides)
    return has_name and has_main


#: Recursion allowance while analysing one file: a chain of ~500 ``a + b + ...`` terms is
#: ordinary generated code but already past the default limit of 1000 frames.
_ANALYSIS_RECURSION_LIMIT = 6000


@contextmanager
def _deep_recursion(limit: int = _ANALYSIS_RECURSION_LIMIT):
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(max(previous, limit))
    try:
        yield
    finally:
        sys.setrecursionlimit(previous)


#: Stack for the analysis thread. Python's recursion limit is only a count: the C stack it
#: eats differs per platform (Windows' 1 MB main-thread stack dies long before 6000
#: nested frames), so deep trees are analysed on a thread with room for them.
_ANALYSIS_STACK_BYTES = 256 * 1024 * 1024


def _on_big_stack(func):
    """``func`` as a function that runs on a big-stack thread with a raised recursion limit."""

    @functools.wraps(func)
    def run(*args, **kwargs):
        outcome: dict = {}

        def target():
            with _deep_recursion():
                try:
                    outcome["value"] = func(*args, **kwargs)
                except BaseException as exc:  # re-raised in the caller's thread
                    outcome["error"] = exc

        previous = threading.stack_size()
        try:
            threading.stack_size(_ANALYSIS_STACK_BYTES)
            thread = threading.Thread(target=target)
            thread.start()
        except (ValueError, RuntimeError):  # no such stack here: analyse in place
            return func(*args, **kwargs)
        finally:
            threading.stack_size(previous)
        thread.join()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]

    return run


def _decode_text(data: bytes) -> str:
    """Text of a metadata file: UTF-8 (BOM allowed) or UTF-16 (PowerShell's redirect)."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _decode(data: bytes) -> str:
    """Source text of ``data`` per PEP 263 (BOM and ``coding:`` cookie), never raising."""
    try:
        encoding, _ = tokenize.detect_encoding(BytesIO(data).readline)
    except (SyntaxError, LookupError):
        encoding = "utf-8"
    try:
        return data.decode(encoding)
    except (UnicodeError, LookupError):
        return data.decode("utf-8-sig", errors="replace")


def _pragma_lines(text: str) -> set[int]:
    """Line numbers carrying a real ``# cw-audit: ignore`` *comment* (not a string)."""
    try:
        return {
            token.start[0]
            for token in tokenize.generate_tokens(StringIO(text).readline)
            if token.type == tokenize.COMMENT and _PRAGMA.search(token.string)
        }
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return {
            n for n, line in enumerate(text.splitlines(), 1) if _PRAGMA.search(line)
        }


@_on_big_stack
def _visit_source(text: str) -> _Visitor:
    visitor = _Visitor()
    visitor.visit(ast.parse(text))
    return visitor


def audit_source(source: str | bytes, *, path: str = "<string>") -> list[Finding]:
    """Findings for one Python source (text or bytes), sorted by line.

    A file that cannot be analysed yields a single ``unparsable`` finding rather than an
    exception or silence: an audit that crashes on one bad file reports nothing about the
    rest, and one that skips it cannot vouch for it.

    >>> audit_source("import argh as a\\na.CommandError('x')")[1].code
    'command-error'
    >>> audit_source("import cw\\ncw.dispatch(f)")[0].code
    'discarded-exit'
    >>> audit_source("import cw\\nraise SystemExit(cw.dispatch(f))")
    []
    >>> audit_source("import cw, io\\ncw.dispatch(f, out=io.StringIO())")
    []
    >>> audit_source("import argh  # cw-audit: ignore")
    []
    >>> audit_source(b"\\xef\\xbb\\xbfimport argh\\n")[0].code
    'import'
    >>> audit_source("def (:")[0].code
    'unparsable'
    """
    text = _decode(source) if isinstance(source, bytes) else source
    try:
        visitor = _visit_source(text)
    except SyntaxError as exc:
        return [
            Finding(path, exc.lineno or 1, "unparsable", f"cannot parse: {exc.msg}")
        ]
    except (ValueError, RecursionError, MemoryError) as exc:
        reason = type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)
        return [Finding(path, 1, "unparsable", f"cannot analyse: {reason}")]
    pragmas = _pragma_lines(text)

    def ignored(first: int, last: int) -> bool:
        return any(n in pragmas for n in range(first, last + 1))

    return sorted(
        {
            Finding(path, first, code, message)
            for first, last, code, message in visitor.findings
            if not ignored(first, last)
        }
    )


# --------------------------------------------------------------------------------------
# Dependency declarations: pure grep, scoped to where requirements live


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _key_parts(name: str) -> list[str]:
    """``'Optional-Dependencies.cli'`` -> ``['optional_dependencies', 'cli']``."""
    return [part.strip().replace("-", "_") for part in name.lower().split(".")]


def _strip_comment(value: str) -> str:
    """``value`` without a trailing ``# comment`` (a ``#`` inside quotes is kept)."""
    quote = None
    for i, char in enumerate(value):
        if quote:
            quote = None if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (i == 0 or value[i - 1] in " \t,[]\"'"):
            return value[:i].rstrip()
    return value.rstrip()


def _in_dependency_table(header: str) -> bool:
    """Does a table header (``[tool.poetry.group.dev.dependencies]``) hold requirements?"""
    return any(part in _DEPENDENCY_KEYS for part in _key_parts(header))


def _requirement_lines(text: str, *, always: bool) -> Iterator[tuple[int, str]]:
    """``(lineno, candidate)`` for each line that may declare a requirement.

    A line qualifies when it sits in a table whose header has a dependency segment
    (``[project.optional-dependencies]``, ``[tool.poetry.dependencies]``,
    ``[options.extras_require]``), or under a dependency key (``dependencies =``,
    ``install_requires =``, ``requires =``) -- or always, for a requirements file. That
    scoping is what keeps ``name = "argh"``, ``keywords = ["argh"]`` and tool settings such
    as ``known-third-party = ["argh"]`` from reading as dependencies. The candidate has any
    ``key =`` prefix removed, except an ``argh = ...`` key itself (Poetry's spelling).
    """
    header = ""
    owner = None  # the key whose (possibly multi-line) value this line belongs to
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _PRAGMA.search(raw):
            continue
        if always:  # a requirements file: every line is a requirement
            line = re.sub(r"\s*(\\|--hash.*|\s#.*)$", "", line)
            yield lineno, line
            continue
        match = _HEADER.match(line)
        if match and not _KEY.match(line):
            header, owner = match.group(1), None
            # ``[tool.poetry.dependencies.argh]``: the table is the package.
            names = _key_parts(header)
            if names[-1] == "argh" and any(p in _DEPENDENCY_KEYS for p in names[:-1]):
                if names[-2] not in _GROUP_TABLES:
                    yield lineno, "argh"
            continue
        key = _KEY.match(line)
        value = line
        if key:
            parts = _key_parts(key.group(1))
            value, owner = key.group(2), parts
            is_package_key = parts[-1] == "argh" and (
                _in_dependency_table(header)
                or any(p in _DEPENDENCY_KEYS for p in parts[:-1])
            )
            in_group_table = _key_parts(header)[-1] in _GROUP_TABLES or (
                len(parts) > 1 and parts[-2] in _GROUP_TABLES
            )
            if is_package_key and not in_group_table:
                yield lineno, "argh"  # Poetry: ``argh = "^0.26"``
                continue
        elif line.startswith("]"):
            owner = None
            continue
        scoped = _in_dependency_table(header) or any(
            part in _DEPENDENCY_KEYS for part in owner or ()
        )
        if scoped:
            candidate = _strip_comment(value)
            yield lineno, "argh" if _INLINE_ARGH.search(candidate) else candidate


def audit_dependencies(
    text: str, *, path: str = "<string>", always: bool = False
) -> list[Finding]:
    """Findings for ``argh`` declared as a requirement in one metadata file's text.

    ``always`` treats every line as a candidate (a ``requirements.txt``).

    >>> text = '[project]\\nname = "argh"\\ndependencies = ["argh>=0.31", "x"]\\n'
    >>> [(f.line, f.code) for f in audit_dependencies(text)]
    [(3, 'dependency')]
    >>> audit_dependencies('keywords = ["argh"]\\ndependencies = ["arghh"]')
    []
    >>> audit_dependencies('[tool.ruff.lint.isort]\\nknown-third-party = ["argh"]')
    []
    >>> [f.line for f in audit_dependencies("x\\nargh>=0.26  # old\\n", always=True)]
    [2]
    >>> [f.line for f in audit_dependencies('[tool.poetry.dependencies]\\nargh = "^0.26"')]
    [2]
    >>> [f.line for f in audit_dependencies("[options]\\ninstall_requires = argh")]
    [2]
    """
    findings = []
    for lineno, candidate in _requirement_lines(text, always=always):
        if _QUOTED_REQUIREMENT.search(candidate) or _BARE_REQUIREMENT.match(candidate):
            findings.append(Finding(path, lineno, "dependency", _DEPENDENCY_WHY))
    return findings


@_on_big_stack
def _setup_py_dependencies(source: str, *, path: str) -> list[Finding]:
    """``argh`` in dependency keywords / dict entries of a ``setup.py``, found with ``ast``.

    A line scan cannot tell ``install_requires=`` from the keyword before it on the same
    line, nor follow ``install_requires=REQUIREMENTS``; the tree can (one assignment deep,
    anywhere in the file). The key may be a keyword of *any* call (``setup(...)``,
    ``my_setup(**kw)``, ``dict(...)``) or a string key of a dict literal -- legacy templates
    build ``setup_kwargs = dict(install_requires=[...])`` and splat it.
    """
    try:
        with _deep_recursion():
            tree = ast.parse(source)
            assigned: dict[str, ast.expr] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            assigned.setdefault(target.id, node.value)
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    if isinstance(node.target, ast.Name):
                        assigned.setdefault(node.target.id, node.value)

            def constants(node: ast.AST, seen: set[str]) -> Iterator[ast.Constant]:
                if isinstance(node, ast.Constant):
                    if isinstance(node.value, str):
                        yield node
                elif isinstance(node, ast.Name):
                    if node.id in assigned and node.id not in seen:
                        seen.add(node.id)
                        yield from constants(assigned[node.id], seen)
                elif isinstance(node, ast.Dict):  # the keys name extras, not packages
                    for value in node.values:
                        yield from constants(value, seen)
                else:
                    for child in ast.iter_child_nodes(node):
                        yield from constants(child, seen)

            def is_dependency_key(name: object) -> bool:
                return (
                    isinstance(name, str) and name.replace("-", "_") in _DEPENDENCY_KEYS
                )

            values: list[ast.expr] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    values += [
                        k.value for k in node.keywords if is_dependency_key(k.arg)
                    ]
                elif isinstance(node, ast.Dict):
                    values += [
                        v
                        for k, v in zip(node.keys, node.values, strict=True)
                        if isinstance(k, ast.Constant) and is_dependency_key(k.value)
                    ]
            pragmas = _pragma_lines(source)
            found = {}
            for value in values:
                for const in constants(value, set()):
                    text = const.value.strip()
                    if _BARE_REQUIREMENT.match(text) and const.lineno not in pragmas:
                        found[const.lineno] = Finding(
                            path, const.lineno, "dependency", _DEPENDENCY_WHY
                        )
            return list(found.values())
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []  # audit_source already reports the file as unparsable


# --------------------------------------------------------------------------------------
# Walking a tree


def _walk(
    root: Path,
    exclude_dirs: frozenset[str],
    top: frozenset[str],
    problems: list[Finding],
    *,
    base: Path,
    depth: int = 0,
) -> Iterator[Path]:
    """Files under ``root``, skipping excluded dirs, virtualenvs and symlinks that lead nowhere.

    A directory that cannot be listed is appended to ``problems``, not raised: the audit
    must say what it could not read rather than die on it.
    """
    if _is_regular_file(root):
        yield root
        return
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        problems.append(_unreadable(root, base, exc))
        return
    for path in children:
        try:
            if path.is_symlink() and (path.is_dir() or not path.exists()):
                continue  # a link can loop back up, leave the tree, or dangle
            if not path.is_dir():
                if _is_regular_file(path):  # a FIFO or socket would block the read
                    yield path
                continue
            name = path.name
            skip = (
                name in exclude_dirs
                or (depth == 0 and name in top)
                or name.endswith(".egg-info")
                or (path / "pyvenv.cfg").exists()
            )
        except OSError as exc:
            problems.append(_unreadable(path, base, exc))
            continue
        if not skip:
            yield from _walk(
                path, exclude_dirs, top, problems, base=base, depth=depth + 1
            )


def _is_regular_file(path: Path) -> bool:
    return stat.S_ISREG(path.stat().st_mode)


def _has_python_shebang(file: Path) -> bool:
    """True if an extensionless ``file`` starts with a ``#!`` line naming python."""
    try:
        with file.open("rb") as fh:
            first = fh.readline(256)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def _unreadable(path: Path, base: Path, exc: OSError) -> Finding:
    shown = path.relative_to(base).as_posix() if path != base else str(path)
    return Finding(shown, 1, "unparsable", f"cannot read: {exc.strerror or exc}")


def _is_requirements_file(path: Path) -> bool:
    if path.suffix not in (".txt", ".in"):
        return False
    return "requirements" in path.stem.lower() or path.parent.name == "requirements"


def _is_test_file(relative: Path) -> bool:
    """A test (judged by its path *below* the audited root) is not an entry point."""
    return (
        relative.name.startswith("test_")
        or relative.stem.endswith("_test")
        or relative.name == "conftest.py"
        or "tests" in relative.parts[:-1]
    )


def audit(
    path=".",
    *,
    exclude_dirs: Iterable[str] = DEFAULT_EXCLUDE_DIRS,
    exclude_top_dirs: Iterable[str] = DEFAULT_EXCLUDE_TOP_DIRS,
) -> list[Finding]:
    """Audit a file or a source tree; return every residual ``argh`` finding.

    ``path`` may be a directory (walked), a Python file (any suffix when named explicitly; ``.py``/``.pyi``/``.pyw`` or a python
    shebang when walked), or a metadata file.
    ``exclude_dirs`` are skipped at any depth; ``exclude_top_dirs`` only directly under
    ``path`` (``build``, ``dist``, ``.venv``...). Symlinked directories are not followed,
    and a directory with a ``pyvenv.cfg`` is a virtualenv. Paths in the findings are
    relative to ``path`` when it is a directory. A file that cannot be read or parsed is an
    ``unparsable`` finding, not silence.

    >>> import tempfile, pathlib
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     root = pathlib.Path(tmp)
    ...     _ = (root / "m.py").write_text("from argh import CommandError\\n")
    ...     _ = (root / "pyproject.toml").write_text('dependencies = ["argh"]\\n')
    ...     [(f.path, f.code) for f in audit(root)]
    [('m.py', 'command-error'), ('m.py', 'import'), ('pyproject.toml', 'dependency')]
    """
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"no such file or directory: {root}")
    base = root if root.is_dir() else root.parent
    findings: list[Finding] = []
    walk = _walk(
        root,
        frozenset(exclude_dirs),
        frozenset(exclude_top_dirs),
        findings,
        base=base,
    )
    for file in walk:
        relative = file.relative_to(base)
        shown = relative.as_posix()
        is_metadata = file.name in _REQUIREMENT_FILES or _is_requirements_file(file)
        is_python = (
            file.suffix in _PYTHON_SUFFIXES
            or (
                file == root and not is_metadata
            )  # a named file is audited, whatever its suffix
            or (not file.suffix and not is_metadata and _has_python_shebang(file))
        )
        if not (is_python or is_metadata):
            continue
        try:
            data = file.read_bytes()
        except OSError as exc:
            findings.append(
                Finding(shown, 1, "unparsable", f"cannot read: {exc.strerror}")
            )
            continue
        if is_python:
            found = audit_source(data, path=shown)
            if _is_test_file(relative):  # a test may drop the code
                found = [f for f in found if f.code != "discarded-exit"]
            findings.extend(found)
        if file.name == "setup.py":
            findings.extend(_setup_py_dependencies(_decode(data), path=shown))
        elif is_metadata:
            findings.extend(
                audit_dependencies(
                    _decode_text(data),
                    path=shown,
                    always=_is_requirements_file(file),
                )
            )
    return sorted(findings)


def format_findings(findings: Iterable[Finding]) -> str:
    """The report: one ``path:line: code: message`` per finding, or the all-clear.

    >>> format_findings([])
    'no residual argh found.'
    """
    findings = list(findings)
    if not findings:
        return "no residual argh found."
    return "\n".join(map(str, findings))


def assert_no_argh(path=".", **kwargs) -> None:
    """Raise ``AssertionError`` listing every residual ``argh`` under ``path``.

    The consumer-side gate: one line in a test suite makes a half-finished migration a red
    build. Keyword arguments go to :func:`audit`.
    """
    findings = audit(path, **kwargs)
    if findings:
        raise AssertionError(
            f"{len(findings)} residual argh finding(s):\n{format_findings(findings)}"
        )
