# cw.audit

Audit a migrated source tree for what is left of `argh`.

Every other gate cw offers is blind to a *residual* `argh` by construction:
`cw.testing` goldens characterize `--help` (a `CommandError` fires after dispatch,
past anything a help corpus reaches), `python -m cw specs` looks at one signature, and
`cw.compat` only helps a module that switched to `from cw import compat as argh`. This
module is the gate that reads the *source*, so a migration can be called finished by a
check that runs in CI instead of by a prose warning.

Five checks, each with a stable code:

`import`
: `import argh` / `from argh import ...` anywhere. The headline check.

`command-error`
: `from argh import CommandError` (or `argh.CommandError` through an alias). The one
  residual that silently changes runtime behaviour rather than merely failing to import:
  `argh.CommandError is cw.CommandError` is `False`, so a raise of the former escapes
  `cw.run` as a traceback where argh printed `CommandError: <msg>` and exited 1.

`dispatch`
: A live `argh.dispatch*` / `ArghParser` / `EntryPoint` call, including under
  `if __name__ == "__main__"` (which looks dead and is not: `python -m pkg.mod` runs it).

`dependency`
: `argh` declared in `pyproject.toml` / `setup.cfg` / `setup.py` /
  `requirements*.txt` (the licence-exposure-only case when nothing imports it).

`discarded-exit`
: `cw.dispatch(...)` as a bare statement. cw *returns* the exit code where argh exited
  itself, so dropping it turns every non-zero exit into 0. Calls that pass `out=` /
  `err=` or `standalone=False` are capturing output (a test), and are not flagged,
  nor is anything in a test file.

`unparsable`
: A file that could not be read or parsed (Python 2, syntax newer than the interpreter
  running the audit, a NUL byte, absurd nesting). It fails the gate rather than being
  skipped: an audit cannot vouch for what it did not read. Exclude the directory.

Nothing here imports `argh`, or anything but the standard library: it reads files, and
the answer is the same whether or not `argh` is installed on the machine running it.

```pycon
>>> src = "from argh import CommandError\n"
>>> [(f.line, f.code) for f in audit_source(src)]
[(1, 'command-error'), (1, 'import')]
>>> [f.code for f in audit_source("import argh\nargh.dispatch_commands([f])\n")]
['import', 'dispatch']
>>> audit_source("from cw import compat as argh\nargh.dispatch_commands([f])\n")
[]
```

A line can opt out, for the rare place that is *meant* to touch real argh (a parity test):

```default
import argh  # cw-audit: ignore
```

Run it on a tree:

```default
python -m cw audit .
```

or gate on it in a consumer’s own test suite:

```default
def test_no_residual_argh():
    from cw.audit import assert_no_argh
    assert_no_argh(Path(__file__).parents[1])
```

### Module Attributes

| [`IGNORE_PRAGMA`](#cw.audit.IGNORE_PRAGMA)            | The comment that exempts its line (any line of a multi-line statement).   |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`DEFAULT_EXCLUDE_DIRS`](#cw.audit.DEFAULT_EXCLUDE_DIRS)     | Directory names never worth descending into, at any depth.                |
| [`DEFAULT_EXCLUDE_TOP_DIRS`](#cw.audit.DEFAULT_EXCLUDE_TOP_DIRS) | Directory names skipped only directly under the audited root.             |

### Functions

| [`audit`](#cw.audit.audit)([path, exclude_dirs, exclude_top_dirs])   | Audit a file or a source tree; return every residual `argh` finding.       |
|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`audit_source`](#cw.audit.audit_source)(source, \*[, path])                | Findings for one Python source (text or bytes), sorted by line.            |
| [`audit_dependencies`](#cw.audit.audit_dependencies)(text, \*[, path, always])    | Findings for `argh` declared as a requirement in one metadata file's text. |
| [`format_findings`](#cw.audit.format_findings)(findings)                       | The report: one `path:line: code: message` per finding, or the all-clear.  |
| [`assert_no_argh`](#cw.audit.assert_no_argh)([path])                          | Raise `AssertionError` listing every residual `argh` under `path`.         |

### Classes

| [`Finding`](#cw.audit.Finding)(path, line, code, message)   | One residual: where it is, which check found it, and what to do.   |
|---------------------------------------------------------------------------------------|--------------------------------------------------------------------|

### cw.audit.DEFAULT_EXCLUDE_DIRS *= frozenset({'.git', '.hg', '.mypy_cache', '.nox', '.pytest_cache', '.ruff_cache', '.tox', '_\_pycache_\_', 'node_modules', 'site-packages'})*

Directory names never worth descending into, at any depth.

### cw.audit.DEFAULT_EXCLUDE_TOP_DIRS *= frozenset({'.venv', 'build', 'dist', 'env', 'venv'})*

Directory names skipped only directly under the audited root. Deeper they are ordinary
package names (`pkg/build/`, `pkg/env/`), so skipping them there would hide source.
Any directory holding a `pyvenv.cfg` is a virtualenv wherever it is.

### *class* cw.audit.Finding(path, line, code, message)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One residual: where it is, which check found it, and what to do.

```pycon
>>> str(Finding("a.py", 3, "import", "argh is imported"))
'a.py:3: import: argh is imported'
```

### cw.audit.IGNORE_PRAGMA *= 'cw-audit: ignore'*

The comment that exempts its line (any line of a multi-line statement).

### cw.audit.assert_no_argh(path='.', \*\*kwargs)

Raise `AssertionError` listing every residual `argh` under `path`.

The consumer-side gate: one line in a test suite makes a half-finished migration a red
build. Keyword arguments go to [`audit()`](#cw.audit.audit).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### cw.audit.audit(path='.', , exclude_dirs=frozenset({'.git', '.hg', '.mypy_cache', '.nox', '.pytest_cache', '.ruff_cache', '.tox', '_\_pycache_\_', 'node_modules', 'site-packages'}), exclude_top_dirs=frozenset({'.venv', 'build', 'dist', 'env', 'venv'}))

Audit a file or a source tree; return every residual `argh` finding.

`path` may be a directory (walked), a `.py` / `.pyi` file, or a metadata file.
`exclude_dirs` are skipped at any depth; `exclude_top_dirs` only directly under
`path` (`build`, `dist`, `.venv`…). Symlinked directories are not followed,
and a directory with a `pyvenv.cfg` is a virtualenv. Paths in the findings are
relative to `path` when it is a directory. A file that cannot be read or parsed is an
`unparsable` finding, not silence.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Finding`](#cw.audit.Finding)]

```pycon
>>> import tempfile, pathlib
>>> with tempfile.TemporaryDirectory() as tmp:
...     root = pathlib.Path(tmp)
...     _ = (root / "m.py").write_text("from argh import CommandError\n")
...     _ = (root / "pyproject.toml").write_text('dependencies = ["argh"]\n')
...     [(f.path, f.code) for f in audit(root)]
[('m.py', 'command-error'), ('m.py', 'import'), ('pyproject.toml', 'dependency')]
```

### cw.audit.audit_dependencies(text, , path='<string>', always=False)

Findings for `argh` declared as a requirement in one metadata file’s text.

`always` treats every line as a candidate (a `requirements.txt`).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Finding`](#cw.audit.Finding)]

```pycon
>>> text = '[project]\nname = "argh"\ndependencies = ["argh>=0.31", "x"]\n'
>>> [(f.line, f.code) for f in audit_dependencies(text)]
[(3, 'dependency')]
>>> audit_dependencies('keywords = ["argh"]\ndependencies = ["arghh"]')
[]
>>> audit_dependencies('[tool.ruff.lint.isort]\nknown-third-party = ["argh"]')
[]
>>> [f.line for f in audit_dependencies("x\nargh>=0.26  # old\n", always=True)]
[2]
>>> [f.line for f in audit_dependencies('[tool.poetry.dependencies]\nargh = "^0.26"')]
[2]
>>> [f.line for f in audit_dependencies("[options]\ninstall_requires = argh")]
[2]
```

### cw.audit.audit_source(source, , path='<string>')

Findings for one Python source (text or bytes), sorted by line.

A file that cannot be analysed yields a single `unparsable` finding rather than an
exception or silence: an audit that crashes on one bad file reports nothing about the
rest, and one that skips it cannot vouch for it.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Finding`](#cw.audit.Finding)]

```pycon
>>> audit_source("import argh as a\na.CommandError('x')")[1].code
'command-error'
>>> audit_source("import cw\ncw.dispatch(f)")[0].code
'discarded-exit'
>>> audit_source("import cw\nraise SystemExit(cw.dispatch(f))")
[]
>>> audit_source("import cw, io\ncw.dispatch(f, out=io.StringIO())")
[]
>>> audit_source("import argh  # cw-audit: ignore")
[]
>>> audit_source(b"\xef\xbb\xbfimport argh\n")[0].code
'import'
>>> audit_source("def (:")[0].code
'unparsable'
```

### cw.audit.format_findings(findings)

The report: one `path:line: code: message` per finding, or the all-clear.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> format_findings([])
'no residual argh found.'
```
