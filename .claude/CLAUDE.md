# cw

A codec layer wiring a string-only environment (the command line) to a Python
function call: `argv -> Namespace -> (args, kwargs) -> f -> result -> stdout`.
The MIT-licensed, in-house replacement for `argh` (LGPL-3.0-or-later).

## Module map (`cw/`)

- `base.py` — bottom of the import graph: sentinels, errors, help rendering.
  Everything else imports from here.
- `grammar.py` — **the riskiest, most opinionated module**: how a Python
  signature becomes command-line arguments (reproduces argh 0.31.3's behavior
  deliberately — see `docs/adr/0004-grammar-errata.md`).
- `ingress.py` — `Namespace -> (args, kwargs)`, honouring `/`, `*args`, `*`, `**kwargs`.
- `egress.py` — `result -> stdout lines + exit code` — a seam argh has **no
  hook for at all**.
- `cli.py` — the argparse surface: build a parser, run one; produces a **plain**
  `argparse.ArgumentParser`, never a subclass (so `argcomplete.autocomplete`
  and other argparse-typed tools keep working).
- `commands.py` — turns an object (function, list, mapping, module, instance,
  or `'pkg.mod:name'` string) into the `{name: callable}` tree a parser is
  built from.
- `convention.py` — `cw`'s defaults, one frozen value per context.
- `resolution.py` — resolves function specs from various formats; `resource_inputs`
  needs the `resource` extra (real `i2`, not the LGPL package cw replaces).
- `compat.py` — **deprecated from day one**: a transitional argh shim so a repo
  can retire an `argh` dependency with a one-line import change.
- `testing.py` — record a CLI's behaviour before a migration, assert it after;
  deliberately standalone (only stdlib imports — see D4 in the ADRs).

## Tests & lint (verified)

```bash
uv venv .venv && uv pip install -e ".[dev]"
.venv/bin/pytest -v --tb=short   # 972 passed, 2 skipped, 1 environment-dependent failure (see gotcha)
.venv/bin/ruff check .
```
Or `wads ci-local` (`[tool.wads.ci.install].extras = "test"` — **required**: a
bare `uv pip install -e .` leaves `cw.resolution`'s i2-dependent tests/doctests
failing).

**Gotcha found verifying:** `tests/argh_parity/test_compat_parity.py::TestArgDeclarations::test_completer_reaches_the_action`
failed locally — it asserts on real `argh`'s own parser action gaining a
`.completer` attribute, which didn't happen in this environment (argh version/
`argcomplete` availability), not a `cw` bug. `tests/argh_parity/` is a
differential suite (cw vs. real argh) that self-skips when `argh` is absent;
`cw` itself never imports `argh` at runtime — `test_import_is_cheap.py` enforces
that import costs stdlib only.

## Docs

- `docs/adr/0001`-`0008`: the v1 seam table, ingress stash, merge ladder, grammar
  errata, release/rollback policy, v1 cut list, what adversarial review changed,
  no-fourth-channel-for-group-kwargs.

## Dependents

41 packages import `cw` (fleet dependency graph), including `appshelf`,
`astern`, `crowsnest`, `liaise`, `openloops`, `priv`, `wads` — see
`fleet_dependents.json` for the full list. Check dependents' CLI tests before
changing `grammar.py`, `ingress.py`, or `egress.py`'s public behaviour.
