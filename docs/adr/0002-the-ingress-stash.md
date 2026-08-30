# ADR-0002: How a plain `ArgumentParser` carries convention, config and ingress into `run`

- **Status:** accepted
- **Date:** 2026-08-30
- **Deciders:** Thor Whalen
- **Issue:** [#9](https://github.com/i2mint/cw/issues/9)

## Context

cw's most load-bearing constraint is that `mk_parser` returns a **plain**
`argparse.ArgumentParser`, never a subclass:

```python
def mk_parser(obj, /, *, config=None, convention=ARGH, decode=None, **parser_kwargs) -> argparse.ArgumentParser
def run(parser, argv=None, *, ...) -> int
```

That is what keeps `argcomplete` alive across ten fleet repos: `argcomplete.autocomplete`
is argparse-typed at its signature, and ten `# PYTHON_ARGCOMPLETE_OK` markers survive the
migration untouched only because cw hands over the real thing. `argh` gets to keep state on
`ArghParser` (a subclass). cw cannot.

But `run` needs state that only `mk_parser` knew: **which function** this subcommand calls,
**how** to turn the parsed `Namespace` into that function's `(args, kwargs)`, and **under
which convention** the whole thing was built. A build-and-run pass on the prototype found
three defects that made `run` unimplementable as specified:

1. **`run` had no `convention=`.** The spec says `egress=None` means "take the
   convention's" — and `run` had no way to reach one. A `MODERN` parser run through the
   published `run` silently got `ARGH`'s egress, which also falsifies the spec's own
   argument that `convention=cw.MODERN` is "one act".
2. **`run(parser)` had no channel for `config`**, so per-parameter codecs could not reach
   the ingress. The prototype invented `parser.set_defaults(_cw_config=...)` — an unnamed
   private key that would collide with a parameter of that name.
3. **`run`'s stated reason for existing did not work.** The published API had no
   `set_default_command`; the "hand-build a parser and still use cw's ingress/egress"
   justification only worked through a private function.

This is the trickiest mechanism in cw, and it is non-obvious to a reader who *expects* a
parser subclass. Hence this ADR.

## Decision

### 1. One reserved `set_defaults` key: `'_cw'`

`cw.cli.RESERVED_DEST = '_cw'`. Every parser and subparser cw builds carries exactly one
extra namespace entry under that key, holding a frozen `_Stash`:

```python
@dataclass(frozen=True)
class _Stash:
    convention: Convention
    func: Optional[Callable] = None      # None on a parser that only holds subcommands
    ingress: Optional[Callable] = None
    config: Optional[Mapping] = None
```

This is the same mechanism argh uses (`parser.set_defaults(function=...)` +
`DEST_FUNCTION`, `argh/constants.py:54`), with cw's name reserved and its collision made
loud. `run` reads it back with `parser.get_default(RESERVED_DEST)` before parsing and
`getattr(namespace, RESERVED_DEST)` after.

**A parameter named `_cw` is a startup error, never silent corruption:**

```
>>> import cw
>>> def f(_cw=1): ...
>>> cw.mk_parser(f)
Traceback (most recent call last):
  ...
cw.grammar.GrammarError: f: the parameter '_cw' collides with the namespace key cw
reserves for its own use. Rename the parameter, or hide it with cw.HIDE.
```

(Without the check, argh's own grammar would have inferred the option strings
`['--', '---cw']` from `_cw` and argparse would have rejected them with a message
mentioning neither cw nor the parameter. `cw.HIDE` is the documented workaround.)

`_cw` is stripped from the values before the ingress runs, so a command never sees it.

### 2. The stash carries convention and config; `run`'s keywords override

`run` gains **both** `convention=` and `config=`, and both default to `None` meaning "use
the stash's". Resolution order, in `run`:

```python
stash = parser.get_default(RESERVED_DEST)          # the top parser's
stash = getattr(namespace, RESERVED_DEST, None) or stash   # the CHOSEN subcommand's wins
convention = convention or stash.convention        # run's keyword wins over both
egress = egress if egress is not None else convention.egress
```

**The chosen subcommand's stash beats the top parser's**, because it is the one that knows
which function was selected and under which convention it was built. A group added with
`add_commands(..., convention=MODERN)` inside an `ARGH` parser is rare, and getting it
wrong would be silent.

So `convention=cw.MODERN` stays *one* act even when build and run are two calls:

```
>>> import cw, io
>>> def counted():
...     return map(str, range(2))
>>> parser = cw.mk_parser(counted, convention=cw.MODERN)
>>> out = io.StringIO()
>>> cw.run(parser, [], out=out)
0
>>> out.getvalue()
'0\n1\n'
```

(`map` is not in argh's `(GeneratorType, list, tuple)` whitelist, so under `ARGH` this
prints `<map object at 0x...>`. The two lines are `MODERN`'s `iterable_egress` arriving
through the stash.)

A `config` codec reaches the ingress either way — baked in at build time, or passed to
`run`:

```
>>> def load(spec='builtins.len'):
...     return spec.__name__ if callable(spec) else f'not resolved: {spec!r}'
>>> codec_config = {'spec': {'codec': cw.resolve_to_function}}
>>> out = io.StringIO()
>>> cw.run(cw.mk_parser(load, config=codec_config), ['--spec', 'builtins.sum'], out=out)
0
>>> out.getvalue()
'sum\n'
>>> out = io.StringIO()
>>> cw.run(cw.mk_parser(load), ['--spec', 'builtins.sum'], out=out, config=codec_config)
0
>>> out.getvalue()
'sum\n'
```

**Caveat, and it is a real one:** `run(config=...)` re-inspects the function to rebuild the
ingress, so only the `codec=` half of a leaf can still take effect that late. The rest of a
leaf is token grammar and is already frozen into the parser — passing
`config={'x': {'help': 'h'}}` to `run` does nothing to `--help`. Pass `config` to
`mk_parser`/`dispatch` unless you specifically want a late codec.

### 3. `set_default_command` is exported

`cw.set_default_command(parser, func, *, config=None, convention=ARGH)` binds a function
onto a parser you built yourself and stashes its ingress, so `run`'s "a repo can hand-build
a parser and still use cw's ingress and egress" is a true claim rather than an aspirational
one. (`cw.add_commands` is its multi-command sibling; see ADR-0006 on why it survived the
cut list.) Binding onto a parser that already declared a colliding flag raises
`argparse.ArgumentError` — argparse's own error, at the point of the collision.

### 4. `argv` is POSITIONAL_OR_KEYWORD on both `run` and `dispatch`

Not positional-only. Four fleet call sites spell it as a keyword (`lacing/cli.py:290`,
`illustration/__main__.py:27`, `ov/__main__.py:190`, `hearing/cli.py:297`), and with a
positional-only `argv` the `**parser_kwargs` catch-all swallows the keyword and produces
`TypeError: ArgumentParser.__init__() got an unexpected keyword argument 'argv'` — an error
that names neither cw nor `argv`'s real position. Relatedly, an unknown `**parser_kwargs`
key now raises a `TypeError` that names cw and lists what `argparse.ArgumentParser`
actually accepts.

### 5. `out=`/`err=` capture argparse's output, but never a command body's `print`

`--help`, `usage:` and `error:` come from argparse, not from egress, so `out=`/`err=` can
only capture them by redirecting. cw redirects **around `parser.parse_args` only** — never
around the command body:

```python
with _redirect(out if out is not sys.stdout else None, ...):
    namespace = parser.parse_args(argv)
```

So `out=io.StringIO()` captures `--help`, the usage line and argparse's `error:`, while a
command's own `print()` goes exactly where the process's `print` goes — as it does under
argh. The redirect is a process-global mutation, and confining it to the parse means it is
held for microseconds and cannot swallow anything a command chose to write itself. A
command that wants its output captured should **return** it; that is what the egress seam
is for.

## Consequences

- cw can never keep per-subcommand state as a parser *attribute*, and should not start:
  `_cw` is the one channel, and adding a second would reintroduce exactly the ambiguity
  this ADR closes.
- `_cw` is now a name cw has taken. It is not a plausible parameter name, the collision is
  a startup error naming the fix, and `cw.HIDE` is the escape hatch.
- `run` is genuinely usable on a hand-built parser, which is what makes `t/coact`'s test
  suite monkeypatch-free.
- A `Namespace` produced by cw carries one entry a caller did not ask for. Anything reading
  the raw namespace (nothing in the fleet does) must skip `_cw`.
- The redirect decision means `capsys` tests of a cw CLI see command output on the real
  stdout and argparse's output in `out=`. That is a divergence from the spec's marketing
  ("what makes cw CLIs testable with capsys") and is documented rather than papered over.

## Alternatives considered

- **Subclass `ArgumentParser`** and keep the state as attributes. Rejected outright: it is
  the one thing that would break `argcomplete` across ten repos, and it is the reason cw
  is argparse-based at all.
- **A module-level `WeakKeyDictionary[parser -> stash]`.** Works, and keeps the namespace
  clean, but it is invisible global state that does not survive pickling, does not survive
  a parser crossing a process boundary, and gives a debugging reader nothing to `print`.
  The `set_defaults` key shows up in `parser.get_default` and in `vars(namespace)`, which
  is how argh does it and how it should be found.
- **Require `run` to be given everything explicitly** (no stash at all). Rejected: it makes
  `dispatch` the only ergonomic entry point and turns "build here, run there" — the shape
  19 fleet call sites already use — into a chore.
- **Redirect around the whole call** so `out=` captures command `print`s too. Rejected: it
  diverges from argh (a D2 break), holds a process-global mutation for the entire command
  body, and would silently capture output a command deliberately sent elsewhere.
