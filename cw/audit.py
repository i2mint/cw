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
    itself, so dropping it turns every non-zero exit into 0. Calls that pass ``out=``,
    ``err=`` or ``standalone=`` are capturing output (a test), and are not flagged.

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
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
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
    "IGNORE_PRAGMA",
]

#: The comment that exempts its line.
IGNORE_PRAGMA = "cw-audit: ignore"

#: Directories never worth descending into.
DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "build",
        "dist",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "site-packages",
    }
)

#: The names ``argh`` exports that start or run a command-line program.
ARGH_DISPATCH_NAMES = frozenset(
    {"dispatch", "dispatch_command", "dispatch_commands", "ArghParser", "EntryPoint"}
)

#: Keys whose quoted values are metadata, not requirements.
_NON_REQUIREMENT_KEYS = frozenset(
    {"name", "keywords", "description", "summary", "authors", "maintainers"}
)

#: ``argh`` as a requirement: with extras, then a specifier, marker or url, or nothing.
_SPEC = r"argh(?![-_.\w])\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;@][^\"']*)?"
#: Quoted (pyproject, setup.py) anywhere on a line; bare (setup.cfg, requirements) as the line.
_QUOTED_REQUIREMENT = re.compile(rf"""["']\s*{_SPEC}["']""", re.I)
_BARE_REQUIREMENT = re.compile(rf"^{_SPEC}$", re.I)
_REQUIREMENT_FILES = ("pyproject.toml", "setup.cfg", "setup.py")
_KEY = re.compile(r"^\s*([\w.-]+)\s*=")

CODES = {
    "import": "argh is imported",
    "command-error": "CommandError taken from argh, not cw",
    "dispatch": "argh dispatch still reachable",
    "dependency": "argh declared as a dependency",
    "discarded-exit": "cw.dispatch exit code discarded",
}

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
        self.findings: list[tuple[int, str, str]] = []
        self.argh_modules: set[str] = set()  # names bound to the argh module
        self.argh_names: dict[str, str] = {}  # local name -> argh attribute
        self.cw_modules: set[str] = set()  # names bound to cw / cw.cli
        self.cw_dispatchers: set[str] = set()  # names bound to cw.dispatch / cw.run
        self._main_guard_depth = 0

    # -- imports -------------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _is_argh(alias.name):
                self.findings.append((node.lineno, "import", f"import {alias.name}"))
                if alias.asname:
                    self.argh_modules.add(alias.asname)
                elif alias.name == "argh":
                    self.argh_modules.add("argh")
            elif alias.name in ("cw", "cw.cli"):
                self.cw_modules.add(alias.asname or alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and _is_argh(node.module):
            names = ", ".join(alias.name for alias in node.names)
            self.findings.append(
                (node.lineno, "import", f"from {node.module} import {names}")
            )
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "CommandError":
                    self.findings.append(
                        (node.lineno, "command-error", _COMMAND_ERROR_WHY)
                    )
                elif alias.name == "*":
                    continue
                else:
                    self.argh_names[local] = alias.name
        elif node.level == 0 and node.module in ("cw", "cw.cli"):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name in ("dispatch", "run"):
                    self.cw_dispatchers.add(local)
        self.generic_visit(node)

    # -- argh attribute use --------------------------------------------------------
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr == "CommandError"
            and isinstance(node.value, ast.Name)
            and node.value.id in self.argh_modules
        ):
            self.findings.append((node.lineno, "command-error", _COMMAND_ERROR_WHY))
        self.generic_visit(node)

    # -- calls ---------------------------------------------------------------------
    def _argh_dispatch_name(self, func: ast.expr) -> str | None:
        """The argh dispatching name ``func`` calls, or None."""
        if isinstance(func, ast.Name):
            attr = self.argh_names.get(func.id)
            return attr if attr in ARGH_DISPATCH_NAMES else None
        if isinstance(func, ast.Attribute) and func.attr in ARGH_DISPATCH_NAMES:
            root = func.value
            while isinstance(root, ast.Attribute):  # argh.dispatching.dispatch
                root = root.value
            if isinstance(root, ast.Name) and root.id in self.argh_modules:
                return func.attr
        return None

    def visit_Call(self, node: ast.Call) -> None:
        name = self._argh_dispatch_name(node.func)
        if name:
            reach = (
                " It sits under an `if __name__ == '__main__'` guard, which looks "
                "dead but is reached by `python -m <module>`."
                if self._main_guard_depth
                else ""
            )
            self.findings.append(
                (node.lineno, "dispatch", f"argh.{name}(...) is still called.{reach}")
            )
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

    def visit_Expr(self, node: ast.Expr) -> None:
        call = node.value
        if isinstance(call, ast.Call) and self._is_cw_dispatch(call.func):
            capturing = {"out", "err", "standalone"}
            if not capturing & {kw.arg for kw in call.keywords}:
                self.findings.append(
                    (
                        node.lineno,
                        "discarded-exit",
                        "cw returns the exit code where argh exited itself; "
                        "wrap it: `raise SystemExit(cw.dispatch(...))`.",
                    )
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


def audit_source(source: str, *, path: str = "<string>") -> list[Finding]:
    """Findings for one Python source string, sorted by line.

    A file that does not parse yields a single ``syntax`` finding rather than an exception:
    an audit that crashes on one bad file reports nothing about the rest.

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
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 1, "syntax", f"cannot parse: {exc.msg}")]
    visitor = _Visitor()
    visitor.visit(tree)
    lines = source.splitlines()

    def ignored(lineno: int) -> bool:
        return 0 < lineno <= len(lines) and IGNORE_PRAGMA in lines[lineno - 1]

    return sorted(
        {
            Finding(path, lineno, code, message)
            for lineno, code, message in visitor.findings
            if not ignored(lineno)
        }
    )


# --------------------------------------------------------------------------------------
# Dependency declarations: pure grep


def _requirement_lines(text: str) -> Iterator[tuple[int, str]]:
    """``(lineno, line)`` for every line that could hold a requirement.

    Skips comments, metadata keys (``name``, ``keywords``, ...) and the items of a
    multi-line array under one of those keys.
    """
    array_key = None  # the key of the multi-line array we are inside, if any
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = _KEY.match(line)
        if key:
            array_key = key.group(1).lower() if "]" not in line else None
        elif line.startswith("]"):
            array_key = None
        owner = key.group(1).lower() if key else array_key
        if owner in _NON_REQUIREMENT_KEYS or IGNORE_PRAGMA in raw:
            continue
        yield lineno, line


def audit_dependencies(text: str, *, path: str = "<string>") -> list[Finding]:
    """Findings for ``argh`` declared as a requirement in one metadata file's text.

    >>> text = '[project]\\nname = "argh"\\ndependencies = ["argh>=0.31", "x"]\\n'
    >>> [(f.line, f.code) for f in audit_dependencies(text)]
    [(3, 'dependency')]
    >>> audit_dependencies('keywords = ["argh"]\\ndependencies = ["arghh"]')
    []
    >>> [f.line for f in audit_dependencies("x\\nargh>=0.26  # old\\n")]
    [2]
    """
    findings = []
    for lineno, line in _requirement_lines(text):
        # Strip a trailing comment so "argh # why" matches as a bare requirement.
        code = re.sub(r"\s+#.*$", "", line)
        if _QUOTED_REQUIREMENT.search(code) or _BARE_REQUIREMENT.match(code):
            findings.append(
                Finding(
                    path,
                    lineno,
                    "dependency",
                    "argh is declared as a dependency (LGPL-3.0-or-later); drop it "
                    "once nothing imports it.",
                )
            )
    return findings


# --------------------------------------------------------------------------------------
# Walking a tree


def _walk(root: Path, exclude_dirs: Iterable[str]) -> Iterator[Path]:
    excluded = set(exclude_dirs)
    if root.is_file():
        yield root
        return
    for path in sorted(root.iterdir()):
        if path.is_dir():
            if path.name not in excluded and not path.name.endswith(".egg-info"):
                yield from _walk(path, excluded)
        else:
            yield path


def _is_requirements_file(path: Path) -> bool:
    return path.name.startswith("requirements") and path.suffix in (".txt", ".in")


def _is_test_file(path: Path) -> bool:
    return (
        path.name.startswith("test_")
        or path.stem.endswith("_test")
        or path.name == "conftest.py"
        or "tests" in path.parts
    )


def audit(
    path=".", *, exclude_dirs: Iterable[str] = DEFAULT_EXCLUDE_DIRS
) -> list[Finding]:
    """Audit a file or a source tree; return every residual ``argh`` finding.

    ``path`` may be a directory (walked, skipping ``exclude_dirs``), a ``.py`` file, or a
    metadata file. Paths in the findings are relative to ``path`` when it is a directory.

    >>> import tempfile, pathlib
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     root = pathlib.Path(tmp)
    ...     _ = (root / "m.py").write_text("from argh import CommandError\\n")
    ...     _ = (root / "pyproject.toml").write_text('dependencies = ["argh"]\\n')
    ...     [(f.path, f.code) for f in audit(root)]
    [('m.py', 'command-error'), ('m.py', 'import'), ('pyproject.toml', 'dependency')]
    """
    root = Path(path)
    base = root if root.is_dir() else root.parent
    findings: list[Finding] = []
    for file in _walk(root, exclude_dirs):
        shown = str(file.relative_to(base))
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if file.suffix == ".py":
            found = audit_source(text, path=shown)
            if _is_test_file(file):  # a test is not an entry point: it may drop a code
                found = [f for f in found if f.code != "discarded-exit"]
            findings.extend(found)
            if file.name == "setup.py":
                findings.extend(audit_dependencies(text, path=shown))
        elif file.name in _REQUIREMENT_FILES or _is_requirements_file(file):
            findings.extend(audit_dependencies(text, path=shown))
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
