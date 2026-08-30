# 0007 — What the adversarial review changed

**Status:** accepted (2026-08-30). Supersedes canonical-spec §9.3 and amends
[0001](0001-the-v1-seam-table.md) and [0005](0005-release-and-rollback-policy.md).

## Context

Three independent reviewers went over `build-v1` at `f94ed12` with instructions to refute
it. Between them they wrote a fresh differential of ~123 cases, migrated all seven hard-case
fleet repos with running code, diffed the live installed `priv` CLI, and drove argcomplete's
`COMP_LINE` protocol end to end. The grammar survived: 88 pure signature/annotation/collision
cases and 20 end-to-end invocations came back byte-identical to argh 0.31.3, PEP 563 is
handled, the seams are real, and `import cw` is stdlib-only and cheaper than argh.

Four of their findings are not defects in the implementation of a decision. They are
defects in the **decision**, and each one had a test suite and a gate that structurally
could not see it. That is what this ADR is for.

## Decision

### 1. A hyphenated positional is registered under its command-line name, as argh does

Spec §9.3 permitted exactly one divergence and asserted it was invisible: argh writes
`add_argument('project-dir')`, producing a `dest` no Python call can use; cw wrote
`add_argument('project_dir', metavar='project-dir')` and needed no repair.

It is not invisible. **argparse reads that one string twice** — once as the name displayed
in `usage:` and `--help` (`HelpFormatter._metavar_formatter`, where `metavar` beats
`choices`) and once as the name in `error: argument ...` (`_get_action_name`, where
`metavar` beats `dest`). A synthesised `metavar` wins the second reading and loses the
first, so a hyphenated positional carrying `choices` printed

```
usage: prog [-h] project-dir        # cw
usage: prog [-h] {a,b}              # argh
```

with an identical error message — which is why every error-level test agreed.

cw now registers the hyphenated name and renames the `dest` back on the way into the call
(`ArgSpec.argparse_dest` → `_Stash.renames` → `_call_args`, one dictionary lookup in one
place). There is no permitted divergence left, and `tests/argh_parity/harness.py` no longer
forgives anything: `dest` and `metavar` are compared as they are.

**Why the gate could not see it.** Every `choices` case in both corpora was on an *option*,
and every `Literal`-annotated positional had a one-word name. The blind spot was
shape-shaped, not case-count-shaped. `cw/tests/fixtures.py` gains `lacing convert-tree`
— a hyphenated positional with `Literal` choices, with a `--help` case — so
`python -m cw.testing parity` fails on a reintroduction (verified: `3 DIFFER`).

### 2. Subparsers get cw's formatter; a parser somebody else built keeps its own

`formatter_class` was defaulted only where `mk_parser` *builds* the parser. The 25 fleet
files that hold a parser object (`ArghParser()`, or `argparse.ArgumentParser()` then
`add_commands`) got argparse's stock formatter, so the advertised one-line migration
changed `--help` for every one of them: `-` became `None`, `'0.0.0.0'` became `0.0.0.0`,
and a multi-paragraph docstring was reflowed into one.

The rule is argh's, read off argh 0.31.3 rather than guessed:

| built how | argh's formatter | cw's |
|---|---|---|
| `ArghParser(...)` | set in `__init__` | set in `__init__` |
| `argparse.ArgumentParser()` + `set_default_command` | **untouched** | **untouched** |
| `argparse.ArgumentParser()` + `add_commands`, root | **untouched** | **untouched** |
| ... its subparsers | `PARSER_FORMATTER`, unconditionally | `cw.ArghHelpFormatter`, when the parent still carries argparse's stock one |

The obvious fix — promote the formatter in `set_default_command` too — is **wrong**, and
the differential caught it: argh leaves the root alone there, so promoting it would have
removed one divergence by adding another. cw promotes only the stock formatter rather than
overriding unconditionally, so an explicit `formatter_class=` still means what it says.

`tests/argh_parity/test_compat_parity.py` is the test that should have existed: it renders
help through every `cw.compat` entry point and diffs it against live argh, root and
subparsers alike. The missing line was only the first casualty of the missing differential.

### 3. `replay` never reports "identical" about a `--help` body that moved

Tier 3 snapshots the `--help` body and asserts only the normalised `usage:` line, because
`--help` wraps to `COLUMNS` and because CPython itself rewrites it (3.13 renders
`-i, --ignore VALUE` where 3.12 rendered `-i VALUE, --ignore VALUE`). That is still right
for `parity`, which replays committed goldens across a version matrix.

But a change of *formatter* moves only the help column and the description block, so §1 and
§2 above were both invisible to the tool cw ships for exactly this purpose: `replay` printed
`6/6 identical` on a migration whose `--help` visibly changed.

`replay` now compares the body through `normalise_help` — paragraph structure kept, wrapping
collapsed, therefore width-independent — and reports a case whose body moved as the
non-fatal status **`help-differs`**. `--strict-help` makes it fatal; `diff-help` still prints
it unnormalised for a human. The gate never *fails* on a rewrap, and it never *lies* about a
reflow.

### 4. Errors at parser-construction time name cw, the function and the parameter

argparse refuses an `add_argument` call with `ArgumentError`, `ValueError` **or**
`TypeError`; cw caught the first. So `config=` — a new surface with no argh equivalent, and
therefore the likeliest place a migrating repo errs — produced bare messages naming neither
cw nor the function nor the parameter, which is strictly worse than the argh being replaced.
The handler is argh's own scope now (`except Exception`), keeping the
`GrammarError: {func}: cannot add {param!r} as {flags}: {reason}` form that ADR-0005's
rollback transcript already showed a user seeing. A leading-underscore parameter — the argh
footgun cw reproduces on purpose — gets an extra sentence naming `cw.HIDE`.

## Also changed, without amending a decision

- **Two commands may not derive the same name.** argh raises `conflicting subparser`; cw
  kept the last one, so `dispatch([run_a, run_b])` ran the wrong function and returned 0.
  Now `CommandTreeError`, naming both callables.
- **`@arg(..., completer=...)` and `@arg(..., dest=...)` work**, which they must: cw is
  argparse-based *specifically* so argcomplete keeps working for the ten fleet files marked
  `# PYTHON_ARGCOMPLETE_OK`, and the shim those repos migrate through could not express a
  completer at all. `completer` is an `ArgSpec` field assigned to the created action, as
  argh does; `dest` decides which parameter a declaration names, as argh does.
- **`cw.MODERN`'s `Enum` help advertises what the converter accepts.** `choices` must hold
  converted values, so it holds members, which render as `{Col.RED,Col.BLUE}` — tokens the
  converter rejects. `metavar` carries the member names.
- **`BoundKeywordWarning`** is its own category, names the command whose `config` key closes
  it, and carries no `id()`. `CW_QUIET=1` silences it for a console script with nowhere to
  put a `filterwarnings` line — the previous advice (`cw.HIDE`) silenced it by *removing a
  flag argh exposed*, which is not the same thing.
- **`egress=` on `mk_parser`** now says which call carries that seam instead of listing
  `argparse.ArgumentParser`'s parameters. ADR-0001's seam table gains the row that says
  where each seam lives; the seams themselves are unchanged.
- **`cw.resolve_object` is not promoted to the package root.** Zero call sites in cw or the
  fleet, an uncovered body, and a TODO saying to merge it away. It stays at
  `cw.resolution.resolve_object`, where 0.0.15 already shipped it; v1 does not commit to it
  at the facade. `cw.CommandTreeError`, `cw.IngressError` and `cw.BoundKeywordWarning` are
  exported instead — they are raised through the public entry points and were not catchable
  by name.
- **CI installs `cw[test]`.** `[tool.wads.ci.install] extras = "test"` was missing, so wads'
  reusable workflow ran a bare `uv pip install -e .` and three shipped `cw.resolution` items
  failed on a missing `i2`. Two in-repo comments asserted the opposite and were wrong.

## Consequences

- The parity corpus is 8 shapes / **137** cases. ADR-0005's rollback transcript is otherwise
  unchanged: the same mutation still produces `36 DIFFER`, re-verified.
- Spec §9.3's "one permitted divergence" is retired. cw's grammar has **no** divergence from
  argh 0.31.3 that any test forgives.
- The lesson worth keeping is not any of the four fixes. It is that all four hid in the same
  place: a suite that asserted *behaviour* everywhere and *rendering* nowhere. Three of them
  were found by writing a differential that renders. Adding a case to a corpus is cheap;
  noticing that a corpus has a shape-shaped hole is not, and the only defence found so far
  is an adversary with a different harness.
