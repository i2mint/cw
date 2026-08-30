# ADR-0004: Grammar errata — `group_kwargs`, Mapping-key naming, and MODERN's help column

- **Status:** accepted
- **Date:** 2026-08-30
- **Deciders:** Thor Whalen
- **Issue:** [#11](https://github.com/i2mint/cw/issues/11)

## Context

Four corrections that verification passes found in the canonical spec. Each of them, written
as specified, would have shipped a wrong CLI — and three would have done it *silently*.
They are grouped in one ADR because they share a cause: names and display strings crossing
the boundary between cw's vocabulary and argparse's, where "obviously equivalent" is not.

## Decision

### 1. `group_kwargs['help']` is not invisible. Pass `group_kwargs` whole; drop nothing

argh (`assembling.py:669-672`):

```python
subsubparser = subparsers_action.add_parser(
    group_name, help=group_kwargs.get("title")
)
subparsers_action = subsubparser.add_subparsers(**group_kwargs)
```

The spec's finding was that `title` — not `help` — drives the **parent listing row**. That
part is right, and it means `t/xa`'s `group_kwargs={"help": "Postmortem archive (list, log,
forensics)."}` displays nothing in `xa --help` today. The spec's *instruction* — "DROPPED,
not translated" — is wrong: the whole `group_kwargs` also goes to `add_subparsers`, `help`
included, so it renders **inside** `xa arch --help`.

**Rule: pass `group_kwargs` whole to `add_subparsers`, and `help=group_kwargs.get('title')`
to `add_parser`. Drop nothing.** Verified in cw:

```
$ xa --help                          $ xa arch --help
positional arguments:                usage: xa arch [-h] {g-one,g-two} ...
  {arch}
    arch      ARCH TITLE             ARCH TITLE:
                                       {g-one,g-two}  Postmortem archive.
```

**Corollary that must survive refactoring:** `help=` is passed to `add_parser` **even when
it is `None`**. Without it argparse never creates the `_ChoicesPseudoAction`, and the group
row **vanishes** from the parent `--help` entirely — a silent regression in the fleet's only
two group users (`t/xa`, `t/priv`). Verified: with no `group_kwargs` at all, the `arch` row
is still present and simply carries no text.

A mutation that reads `help` instead of `title` turns 5 tests red; one that drops
`group_kwargs` from `add_subparsers` turns 4 red; one that omits `help=` from `add_parser`
turns 8 red. All three were run.

### 2. One naming function, applied to derived names **and** to Mapping keys **and** to config keys

The spec contradicted itself in a single sentence: *"a key wins **verbatim**, so
`'gen-secret'` → `gen-secret`, `'list'` → `list`, priv's `'parse_pth_paths'` →
`parse-pth-paths`"*. Verbatim and `parse_pth_paths → parse-pth-paths` cannot both hold.

**Rule: a key or `__all__` entry beats `__name__`, and is then hyphenated by the
convention.** It is the only reading that satisfies all three examples at once:

```
>>> import cw
>>> def f(): ...
>>> def g(): ...
>>> def h(): ...
>>> sorted(cw.commands_from({'gen-secret': f, 'list': g, 'parse_pth_paths': h}))
['gen-secret', 'list', 'parse-pth-paths']
```

`cw.grammar.cli_name` is that one function, and it is applied to command names, group names,
flag spellings **and** config keys. A mutation that lets a key win verbatim turns 17 tests
red.

**`config` is therefore keyed the way you type it on the command line, not the way the
Python identifier is spelled.** This is the single most likely thing for a migration to get
wrong, because it makes two adjacent dicts in the same file use two spellings — `COMMANDS`
keyed `packages_from_all_setup_cfgs` (from `__all__`), `CONFIG` keyed
`packages-from-all-setup-cfgs`.

### 3. A `config` key naming no command, group or parameter is a **hard error**

Which is what makes rule 2 survivable, and what closes the `MODERN` trap:

```
>>> import cw
>>> def g_one(x=1): ...
>>> cw.mk_parser({'git_ops': {'g_one': g_one}},
...              config={'git_ops': {'g-one': {'x': {'help': 'H'}}}},
...              convention=cw.MODERN)
Traceback (most recent call last):
  ...
cw.grammar.GrammarError: config key 'git_ops' matches no command or group. Known command
or group names: git-ops. Note that names are hyphenated by the convention, so a config
must be keyed the way the command line is typed.
```

Without the check, `convention=cw.MODERN` — which sets `hyphenate_groups=True` — would
rename the group, invalidate every config entry keyed by the old name, and produce a CLI
whose help text quietly lost a line. No error, no warning. With the check, the same call is
a startup failure that names the old key, the new name, and the reason.

The same rule holds one level down: `cw.grammar.specs_for_function` raises when a `config`
key matches no parameter, listing the real parameter names. The one exception is a function
that takes `**kwargs`, where an unmatched key becomes an argument delivered there — argh's
rule.

**A known gap, recorded rather than hidden:** there is no `dispatch(config=...)` spelling for
*group-level parser keywords*. `config[group]` is a mapping of commands, so a `'title'` key
inside it is (correctly) an error saying it matches no command. Group kwargs reach only
through `cw.add_commands(group_kwargs=...)`. The canonical spec §14.4 suggests
`config={'archive': {'title': ...}}` as xa's post-migration escape hatch; that spelling does
not exist. If a repo needs it, the addition is a per-group channel on `dispatch`, and it is
a new ADR.

### 4. `MODERN` keeps `default_in_help=True`

The spec gave `MODERN` `default_in_help=False`, which removes argh's `help='%(default)s'`
wart. But docstring-derived per-parameter help is **not in v1** (ADR-0006), so removing the
default leaves an undocumented flag with **no help column at all**:

```
ARGH                                     MODERN as specified
  -v, --verbose                  False     -v, --verbose
  -r RETRIES, --retries RETRIES  3         -r RETRIES, --retries RETRIES
```

`MODERN` is what the spec tells `t/priv` and `t/lacing` to flip to, so as specified it makes
their `--help` strictly worse than the argh they are leaving.

**Rule: `MODERN.default_in_help` stays `True` until docstring-derived help ships.** Showing
the default is a poor substitute for a description, but it is more information than a blank
column, and D2's promise is that `MODERN` is an *improvement*.

`Convention` also has **no `formatter_class` field** (ADR-0006 cut it as duplicated by
`**parser_kwargs`). A caller who wants argparse's own defaults renderer passes it where
argparse names it:

```python
cw.dispatch(COMMANDS, convention=cw.MODERN,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
```

## Consequences

- The parity corpus covers rule 1 with `group_kwargs` in three shapes —
  `{'help', 'title'}`, `{'help'}` only, and absent — asserting the parent row *and* the
  child `--help` in each. `t/xa`'s shape is the only one that reaches that code path, which
  is why ADR-0006 keeps `cw.add_commands` in the core.
- Rule 2 means a migration checklist item: **key `config` the way the command line reads.**
  It is in the README's migration section.
- Rule 3 converts a class of silent misconfiguration into startup failures. The cost is that
  a `config` written for one convention will not load under another until its keys are
  updated — which is the point.
- Rule 4 means `MODERN`'s help column still shows `repr(default)`. When docstring help
  ships (as `cw[docs]`, lazily importing `i2.doc_mint`), flipping `default_in_help` to
  `False` in `MODERN` becomes correct — and per ADR-0005 that is a change to `MODERN`, never
  to `ARGH`.

## Alternatives considered

- **Translate `group_kwargs['help']` to `add_parser(help=...)`** so xa's string finally
  displays in the parent row. Rejected: it is a visible D2 break, and the string is still
  displayed — one level down, where argh puts it. A repo that wants it in the parent row
  adds `'title'`.
- **Keys win verbatim** (the spec's first clause). Rejected: `parse_pth_paths` would become
  a command you invoke as `priv parse_pth_paths` while its neighbours hyphenate — argh
  hyphenates it today, so it is a D2 break and a fleet-visible one.
- **A `config` key that matches nothing is a warning, not an error.** Rejected: warnings on
  a console script go to stderr in production and are read by nobody. The failure mode being
  closed is silence, and a warning is a quieter silence.
- **Keep `MODERN.default_in_help=False` and ship docstring help in v1.** Rejected on scope:
  it needs `i2.doc_mint`, which is the one place i2 earns its way back in, behind an extra.
