# cw — your functions, as a command-line tool

```python
import cw


def greet(name, *, loudly=False):
    """Say hello to someone."""
    return f"HELLO {name}" if loudly else f"hello {name}"


raise SystemExit(cw.dispatch(greet))  # that is the whole CLI
```

```console
$ python greet.py world --loudly
HELLO world
```

`pip install cw` — no dependencies, MIT, and `import cw` costs stdlib only.

---

## What it does

You hand `cw.dispatch` a function, a list of functions, a dict, or a module. It reads the
signatures, builds an `argparse` parser, calls the function you asked for, prints what it
returned, and returns an exit code. Nothing to decorate, nothing to declare.

```console
$ python greet.py --help
usage: greet.py [-h] [-l] name

Say hello to someone.

positional arguments:
  name          -

options:
  -h, --help    show this help message and exit
  -l, --loudly  False

$ python greet.py
usage: greet.py [-h] [-l] name
greet.py: error: the following arguments are required: name
$ echo $?
2
```

The parser `cw` builds is a **plain `argparse.ArgumentParser`**, never a subclass. That is
deliberate and load-bearing: `argcomplete.autocomplete()` is argparse-typed at its
signature, so shell completion works on a cw CLI with the same
`# PYTHON_ARGCOMPLETE_OK` marker and no adapter.

### More than one command

Pass anything with several functions in it. A **callable value is a command**; a **mapping
or iterable value is a group**:

```python
import cw


def add(a: int, b: int):
    """Add two numbers."""
    return a + b


def ls(path=".", *, long=False):
    """List a directory."""
    return [f"{path}/one", f"{path}/two"]


COMMANDS = {"add": add, "list": ls, "git-ops": {"add": add}}
raise SystemExit(cw.dispatch(COMMANDS, prog="tool"))
```

```console
$ tool --help
usage: tool [-h] {add,list,git-ops} ...

positional arguments:
  {add,list,git-ops}
    add               Add two numbers.
    list              List a directory.
    git-ops

options:
  -h, --help          show this help message and exit

$ tool add 2 3
5
$ tool list -p /tmp
/tmp/one
/tmp/two
```

Six forms of `obj`, each decided by the **value**, never by a string DSL:

| `obj` | becomes |
|---|---|
| any callable | **one command**, with no command word at all |
| `[f, g]` — any iterable | commands named from each `__name__` |
| `{'name': f}` — a mapping | commands named **by the key** |
| `{'grp': <any of the above>}` | a **group** (one level deep, argh's limit) |
| a module, or any object | its public callable attributes; `__all__`, if present, is the name list |
| `'pkg.mod:name'` — a string | **always exactly one command**, imported lazily |

A name from a key or `__all__` beats `__name__`, and is then hyphenated:
`{'parse_pth_paths': f}` gives you `parse-pth-paths`.

### What a command's return value does

`None` prints nothing. A list, a tuple or a **generator** prints one line per item — lazily,
flushing as it goes, so a long-running command streams. Anything else prints as one line,
`dict`s included. `0`, `False` and `''` do print.

```python
>>> import cw
>>> def lines():
...     return ['a', 'b']
>>> cw.dispatch(lines, [])
a
b
0
```

Raise `cw.CommandError` for an expected failure: one line to stderr, no traceback, and an
exit code you choose. Any other exception keeps its traceback, because a bug deserves one.

## `config` — this call's particulars

`config` is a plain dict, **shaped exactly like `obj`** and keyed the way you type it on the
command line. Its leaves are `add_argument` keyword arguments:

```python
CONFIG = {
    "path": {"help": "the directory to list", "metavar": "DIR"},
    "long": {"flags": ["-l", "--long"], "help": "one line per entry"},
}
cw.dispatch(ls, config=CONFIG, prog="ls")
```

```console
$ ls --help
usage: ls [-h] [-p DIR] [-l]

List a directory.

options:
  -h, --help          show this help message and exit
  -p DIR, --path DIR  the directory to list (default: '.')
  -l, --long          one line per entry (default: False)
```

For several commands it nests the same way `obj` does —
`{'git-ops': {'add': {'a': {'help': '...'}}}}` — and **a key that names no command, group or
parameter is a startup error**, listing the names that do exist. That is on purpose: a
mis-keyed config entry that silently does nothing is the failure mode this rule exists to
kill.

Two leaf values are not `add_argument` kwargs:

- `cw.HIDE` removes a parameter from the command line entirely, leaving it to its own
  default. This is how you keep a dependency-injection parameter out of the CLI.
- `{'codec': callable}` decodes a parsed token *after* parsing — the place for a `str -> object`
  conversion that `argparse`'s `type=` would get wrong, because argparse applies `type=` to
  defaults and to `const` too.

```python
>>> def serve(host='0.0.0.0', port=8080, pool=None):
...     return f'{host}:{port}'
>>> parser = cw.mk_parser(serve, config={'pool': cw.HIDE})
>>> [a.dest for a in parser._actions][1:]
['host', 'port']
```

## `convention` — what the defaults ARE

`config` is per call; `convention` is per **context** — a repo, a house style, the fleet.
It is a frozen dataclass of nine fields, and two values ship.

**`cw.ARGH` is the default, and it reproduces `argh` 0.31.3 bit-for-bit** — footguns
included. That is the point: a repo swaps its dispatcher for cw and its `--help` does not
move. Concretely, under `ARGH`:

- a parameter **with a default becomes an option**, one without becomes a positional;
- `bool=True` becomes `store_false` (so `--loudly` on `loudly=True` turns it *off*);
- an option's help column is `repr(default)` unless you give it one;
- short flags come from the first character, and **if two parameters share one, neither gets
  a short flag** — `-h` is always lost to `--help`;
- a `dict` return value is **not** iterated; a `map` object prints as `<map object at 0x...>`;
- `**kwargs` is silently dropped from the parser.

**`cw.MODERN` is the same grammar with the sharp edges filed off** — and it is one keyword:

```python
cw.dispatch(COMMANDS, convention=cw.MODERN)
```

It makes a parameter positional only when the signature says so (`*`-keyword-only becomes an
option), resolves type annotations even when you have overridden something, hyphenates group
names, iterates anything iterable that is not a `str`/`bytes`/`Mapping`, and unwraps
`Optional[X]`, `Enum` and `pathlib.Path`.

```python
>>> import cw
>>> def counted():
...     return map(str, range(2))
>>> cw.dispatch(counted, [])                        # ARGH: a map is not a list
<map object at 0x...>
0
>>> cw.dispatch(counted, [], convention=cw.MODERN)  # MODERN: anything iterable
0
1
0
```

Every improvement cw has ships as a named convention value that **defaults off**. There is
no third value and no `Convention(...)` you are expected to build; if you want one,
`dataclasses.replace(cw.ARGH, short_flags=False)` is a `Convention`.

**The house idiom is `functools.partial`**, not a cw-specific binder:

```python
import functools, cw

dispatch = functools.partial(cw.dispatch, convention=cw.MODERN, prog="mytool")
```

**One `ARGH` behaviour worth knowing before it surprises you:** under `cw.ARGH`, *any*
`config` entry (or `@compat.arg`) on a function switches type-annotation inference off for
**the whole function** — so adding a `help` string to one parameter can change another
parameter's coercion from `int` to `str`. That is argh's rule (`can_use_hints =
not declared_args`), reproduced deliberately; see [ADR-0003](docs/adr/0003-the-merge-ladder.md).
`convention=cw.MODERN` is the way out.

## Escape hatches

Everything above is `cw.dispatch`, which is the composition of two functions you can use
separately.

**Build a parser, run it later.** `mk_parser` is pure — no parsing, no I/O, no side
effects — which is what makes it inspectable from a test:

```python
>>> parser = cw.mk_parser(COMMANDS, prog='tool')
>>> type(parser) is __import__('argparse').ArgumentParser
True
>>> cw.run(parser, ['add', '2', '3'])
5
0
```

The convention travels *with* the parser, so `convention=cw.MODERN` stays one act even
when build and run are two calls. (How that works — one reserved `set_defaults` key on a
parser that is deliberately not a subclass — is
[ADR-0002](docs/adr/0002-the-ingress-stash.md).)

**Bind a function to a parser you built yourself:**

```python
>>> import argparse
>>> parser = argparse.ArgumentParser(prog='count')
>>> parser.add_argument('--verbose', action='store_true') and None
>>> def tally(word, *, times=1):
...     return [word] * times
>>> _ = cw.set_default_command(parser, tally)
>>> cw.run(parser, ['hi', '-t', '2'])
hi
hi
0
```

**Grow a parser one group at a time.** The shape `t/priv` and `i/wads` use — a parser
object, then repeated `add_commands` — is `cw.add_commands`, and it is the only way to pass
per-group `add_subparsers` keywords such as `title`:

```python
>>> parser = cw.mk_parser([], prog='priv')
>>> def status(): "Say how things are."
>>> _ = cw.add_commands(parser, [status], group_name='git_ops',
...                     group_kwargs={'title': 'Git operations'})
>>> cw.run(parser, ['git_ops', 'status'])
0
```

`cw.mk_parser([], prog=...)` is the empty-parser seed. A plain `argparse.ArgumentParser()`
works too and renders identically — `add_commands` gives every subparser
`cw.ArghHelpFormatter` when the parent still carries argparse's stock one, which is exactly
what argh does — but then the *root* parser's own `--help` uses argparse's formatter, again
exactly as under argh. Pass `formatter_class=cw.ArghHelpFormatter` yourself if you want the
root to match too.

**`add_commands` takes any `obj` `dispatch` takes, a mapping included** — so a group whose
members you want to name yourself is a mapping, exactly as it would be inside `dispatch`:

```python
>>> parser = cw.mk_parser([], prog='priv')
>>> _ = cw.add_commands(parser, {'st': status}, group_name='git_ops',
...                     group_kwargs={'title': 'Git operations'})
>>> cw.run(parser, ['git_ops', 'st'])
0
```

### Wanting a group `title` from the mapping form

`cw.dispatch({'archive': {...}})` builds the group, but a single mapping has nowhere to put
the group's own `add_subparsers` keywords. **That is deliberate, not a gap**: `add_commands`
already takes a mapping *and* `group_kwargs`, so the answer is two calls rather than a
fourth behaviour-carrying keyword on `dispatch`
([#31](https://github.com/i2mint/cw/issues/31),
[ADR-0008](docs/adr/0008-no-fourth-channel-for-group-kwargs.md)). The console-script idiom
is:

```python
TOP_COMMANDS = {"list": list_cmd, "info": info_cmd}
ARCHIVE_COMMANDS = {"list": archive_list_cmd, "log": archive_log_cmd}


def mk_parser():
    parser = cw.mk_parser(TOP_COMMANDS, prog="xa")
    cw.add_commands(
        parser,
        ARCHIVE_COMMANDS,
        group_name="archive",
        group_kwargs={"title": "Postmortem archive"},
    )
    return parser


def main():
    raise SystemExit(cw.run(mk_parser()))
```

Two things bite people here, and cw's error messages now name both:

- **`group_kwargs['help']` is silently inert; you want `'title'`.** The group's row in the
  *parent's* `--help` is fed by `add_parser(help=...)`, which both argh and cw source from
  `group_kwargs['title']`. `help` is forwarded to `add_subparsers()`, where argparse
  accepts it and renders it nowhere a reader looks. cw reproduces argh exactly — that is
  the product — but it is a trap that shipped a group description nobody ever saw in at
  least one fleet repo.
- **`cw.run` *returns* an exit code where argh's `parser.dispatch()` raised it.** Splitting
  the build from the run is precisely when the `raise SystemExit(...)` gets dropped, and a
  console script that starts exiting `0` on a usage error breaks every CI step that checks
  `$?`. Nothing else catches it: unit tests pass, and a `--help` diff shows nothing.

Trying it any of the other three ways is an error that names this one:

```pycon
>>> cw.dispatch({"archive": {"log": status}}, [], group_kwargs={"title": "T"})
Traceback (most recent call last):
  ...
TypeError: 'group_kwargs' cannot be passed here. cw's group keywords belong to
cw.add_commands, ...
```

**A mapping value must be the commands, not the factory that returns them.** A callable
value is always a *command*, because there is no way to tell a zero-argument factory from a
command that takes no arguments — so write the parentheses:

```python
>>> def dispatch_funcs():
...     return [status]
>>> list(cw.commands_from({'git_ops': dispatch_funcs()}))     # a GROUP
['git_ops']
>>> list(cw.commands_from({'git_ops': dispatch_funcs}))       # a COMMAND
['git-ops']
```

Note the hyphen in the second one: `{'git_ops': dispatch_funcs}` — no parentheses — gives
you a *command* called `git-ops` that prints the reprs of the group's members, exit 0.

**Capture the output.** `out=` and `err=` are plain parameters resolved at *call* time, so a
test can pass a `StringIO` — something an `argh` CLI cannot do, because argh binds
`output_file=sys.stdout` in a signature default:

```python
>>> import io
>>> out = io.StringIO()
>>> cw.dispatch(lines, [], out=out)
0
>>> out.getvalue()
'a\nb\n'
```

They capture argparse's own `--help`, `usage:` and `error:` output. They do **not** capture a
command body's own `print()`, which goes where the process's `print` goes — as it does under
argh.

**Skip the CLI entirely.** `standalone=False` makes the same call an ordinary function call:
nothing printed, nothing caught, the function's own return value:

```python
>>> cw.dispatch(greet, ['world', '--loudly'], standalone=False)
'HELLO world'
```

**Change how results are printed** — `egress=` is one keyword:

```python
>>> cw.dispatch(lambda: {'a': 1}, [], egress=cw.json_egress)
{
  "a": 1
}
0
```

`cw.argh_egress` (the default), `cw.iterable_egress` (MODERN's) and `cw.json_egress` ship;
an egress is any `(result, *, out, err) -> int`.

**Change how types are inferred** — `decode=` is one keyword, taking
`(inspect.Parameter, hint) -> add_argument kwargs | callable | None`. `cw.argh_decode` and
`cw.modern_decode` ship.

Those three — `decode=`, `egress=`, `convention=` — are cw's only seams, and the list of
things that are deliberately **not** seams is as binding as the list that are. Both are in
[ADR-0001](docs/adr/0001-the-v1-seam-table.md).

**Shell completion:**

```bash
pip install 'cw[completion]'
```

then put `# PYTHON_ARGCOMPLETE_OK` at the top of your console script. `cw.run` calls
`argcomplete` for you when it is installed, and does nothing when it is not.

## Migrating from `argh`

`cw` replaces `argh` (LGPL-3.0-or-later) with an MIT package that reproduces its grammar.
There are two steps and you can stop after the first for as long as you like.

**Step 1 — one line.** `cw.compat` implements argh's eleven measured names:

```diff
-import argh
+from cw import compat as argh
```

Everything warns once, on first use; `CW_COMPAT_QUIET=1` silences it for a repo that has
decided to live here for a while. Declare the dependency as:

```toml
dependencies = ["cw>=0.1,<0.2"]
```

**Grep for three import forms before you do it.** The one-line change rewrites `import
argh`; it cannot rewrite a name or a submodule somebody imported directly.

| grep for | why it breaks | write instead |
|---|---|---|
| `from argh import CommandError` | the module still imports argh, and cw will not catch an exception class it has never heard of — `CommandError: boom` / exit 1 becomes an unhandled traceback. **The shim structurally cannot fix this one**; it is the single highest-value line on the checklist. | `from cw import CommandError` |
| `from argh.assembling import NameMappingPolicy` | `cw.compat` is a module, not a package, so there is no `cw.compat.assembling` | `from cw.compat import NameMappingPolicy` |
| `argh.interaction.confirm` | same reason — there is no `interaction` namespace | `argh.confirm` (i.e. `cw.confirm`) |

Each of the last two raises an `AttributeError` naming the replacement, so a missed one is a
startup failure rather than a silent change.

**Step 2 — delete the compat import.** `dispatch_commands(funcs)` becomes
`cw.dispatch(funcs)`; `@argh.arg(...)` decorators become one `config` dict; `argh`'s
`__name__`-mutation trick for renaming a command becomes a mapping key.

**Prove the migration did nothing.** `cw.testing` records a CLI's behaviour before the change
and replays it after:

```bash
# on the old code -- this half imports no cw
python -m cw.testing characterize 'mytool' --cases ./cases.txt -o before.json
# on the new
python -m cw.testing replay before.json --prog 'mytool'
# ... and, when the migration promised --help would not move:
python -m cw.testing replay before.json --prog 'mytool' --strict-help
python -m cw.testing diff-help before.json --prog 'mytool'   # read it, do not assert it
```

`replay` asserts the exit code and both streams in full for every non-`--help` case, and the
normalised `usage:` line for a `--help` one. A `--help` **body** that moved is reported as
the non-fatal `help-differs` — never as `identical` — because a change of *formatter* moves
only the help column and the description block and would otherwise be invisible.
`--strict-help` makes it fatal; `diff-help` prints it for a human.

The recording half **imports no `cw`** — it is one file you can copy into a repo that will
never depend on cw, which is most of them.

Two things to expect, both argh's rules that cw reproduces:

- `config` keys are spelled the way the **command line** reads (`parse-pth-paths`), while
  `obj` keys and `__all__` entries are Python identifiers. Adjacent dicts, two spellings.
  A wrong key is a startup error, not a silent drop.
- Under `cw.ARGH`, one `config` entry disables annotation inference for the whole function
  (above, and [ADR-0003](docs/adr/0003-the-merge-ladder.md)).

## cw's own CLI

```bash
python -m cw specs 'mypkg.cli:main'    # what flags would this function get, and why?
python -m cw help  'mypkg.cli:main'    # the --help cw would print for it
python -m cw parity                    # cw's own migration gate, 8 shapes / 137 cases
```

`specs` is the one that earns its place day to day — it answers *"why did that parameter not
get a short flag?"* without building, running or importing anybody's `__main__`.

## Resolving a function from a string

`cw.resolution` is older than the dispatcher and independent of it: it turns a string
specification into a callable, which is what lets a CLI accept *a function* as a parameter
value.

```python
>>> from cw import resolve_to_function, parse_ast_spec
>>> resolve_to_function('builtins.len')([1, 2, 3])
3
>>> resolve_to_function('str.upper()', parse_ast_spec)('hello')
'HELLO'
```

Both spellings of a reference work — the dot path above, and the `'pkg.mod:name'` colon
form the rest of cw uses (`python -m cw`, `mk_parser`'s `obj:`, `commands_from`):

```python
>>> import os.path
>>> resolve_to_function('os.path:join') is os.path.join
True
```

`parse_json_spec`, `parse_ast_spec` and `parse_spec_with_dot_path` are the three spec
grammars; `resource_inputs` wraps a function so that named parameters are resolved on the
way in. It is the one place cw touches a third-party package, and it is an optional extra:

```bash
pip install 'cw[resource]'
```

## Install

```bash
pip install cw                  # the CLI. no dependencies.
pip install 'cw[completion]'    # + argcomplete, for shell completion
pip install 'cw[resource]'      # + i2, for cw.resource_inputs
pip install 'cw[dev]'           # + pytest and argh, to run the differential test suite
```

Python 3.10+.

## Design notes

Eight decisions, with their evidence, in [`docs/adr/`](docs/adr/):

| | |
|---|---|
| [ADR-0001](docs/adr/0001-the-v1-seam-table.md) | The three seams, and everything that is deliberately not one |
| [ADR-0002](docs/adr/0002-the-ingress-stash.md) | How a plain `ArgumentParser` carries its convention and ingress into `run` |
| [ADR-0003](docs/adr/0003-the-merge-ladder.md) | The four-tier merge ladder is argh's field-specific merge, not `dict.update` |
| [ADR-0004](docs/adr/0004-grammar-errata.md) | `group_kwargs`, mapping-key naming, MODERN's help column |
| [ADR-0005](docs/adr/0005-release-and-rollback-policy.md) | Release, pinning and rollback — `cw.ARGH` is frozen once published |
| [ADR-0006](docs/adr/0006-the-v1-cut-list.md) | What v1 does not ship, and where each cut comes back |
| [ADR-0007](docs/adr/0007-what-the-adversarial-review-changed.md) | What three adversarial reviews changed, and the blind spots that hid it |
| [ADR-0008](docs/adr/0008-no-fourth-channel-for-group-kwargs.md) | Why a group's `group_kwargs` gets no channel in the mapping form |

Two properties worth stating because they are easy to lose and hard to get back:
`cw.mk_parser` returns a **plain** `ArgumentParser`, and **`import cw` pulls stdlib only** —
both are asserted by tests, not by intention.
