# cw.cli

The argparse surface: building a parser, and running one.

Three functions, and the third is the composition of the first two:

```default
parser = cw.mk_parser(obj, ...)        # build.  Pure: no parsing, no I/O.
code   = cw.run(parser, argv, ...)     # parse, call, print, return an exit code.
code   = cw.dispatch(obj, argv, ...)   # == run(mk_parser(obj))
```

[`mk_parser()`](#cw.cli.mk_parser) returns a **plain** [`argparse.ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser), never a subclass.
That is load-bearing rather than tasteful: `argcomplete.autocomplete(argument_parser:
argparse.ArgumentParser, ...)` is argparse-typed at its signature, so eight fleet repos and
ten `# PYTHON_ARGCOMPLETE_OK` markers survive the migration untouched – which the one
fleet repo that moved to `typer` could not manage.

Because the parser is plain, cw cannot keep per-subcommand state on it as an attribute.
It travels instead in one reserved `set_defaults` key, [`RESERVED_DEST`](#cw.cli.RESERVED_DEST), which
carries the target function, its ingress and the convention that built it. A parameter of
that name is an error naming the collision, never silent corruption.

```pycon
>>> import cw, io
>>> def greet(name, *, loudly=False):
...     '''Say hello.'''
...     return f'HELLO {name}' if loudly else f'hello {name}'
>>> out = io.StringIO()
>>> cw.dispatch(greet, ['world'], out=out)
0
>>> out.getvalue()
'hello world\n'
```

`standalone=False` turns the same call into an ordinary function call – nothing is
printed, nothing is caught, and you get the function’s own return value:

```pycon
>>> cw.dispatch(greet, ['world', '--loudly'], standalone=False)
'HELLO world'
```

### Module Attributes

| [`RESERVED_DEST`](#cw.cli.RESERVED_DEST)   | The one `set_defaults` key cw reserves on the parsers it builds.   |
|------------------------------------------------------------------|--------------------------------------------------------------------|

### Functions

| [`mk_parser`](#cw.cli.mk_parser)(obj, /, \*[, config, convention, ...])   | Build the parser `obj` describes.                                           |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`run`](#cw.cli.run)(parser[, argv, config, convention, ...])       | Parse `argv` with `parser`, call the command it names, and report.          |
| [`dispatch`](#cw.cli.dispatch)(obj[, argv, config, convention, ...])     | The front door: `dispatch == run o mk_parser`.                              |
| [`add_commands`](#cw.cli.add_commands)(parser, obj, /, \*[, ...])            | Add `obj`'s commands to an existing parser, optionally under one group.     |
| [`set_default_command`](#cw.cli.set_default_command)(parser, func, /, \*[, ...])    | Bind one function to `parser`: add its arguments, and stash how to call it. |
| [`enable_completion`](#cw.cli.enable_completion)(parser, /, \*[, silent])         | Offer `parser` to `argcomplete`, if it is installed.                        |

### Exceptions

| [`BoundKeywordWarning`](#cw.cli.BoundKeywordWarning)   | A `functools.partial`'s pre-bound keyword is still exposed as a CLI option.   |
|------------------------------------------------------------------------|-------------------------------------------------------------------------------|

### *exception* cw.cli.BoundKeywordWarning

Bases: [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning)

A `functools.partial`’s pre-bound keyword is still exposed as a CLI option.

Its own category so that a repo which has decided the flag is fine can silence exactly
this warning without changing its CLI, and without silencing anything else:

```default
warnings.filterwarnings('ignore', category=cw.BoundKeywordWarning)
```

### cw.cli.RESERVED_DEST *= '_cw'*

The one `set_defaults` key cw reserves on the parsers it builds. Everything a built
parser needs to tell [`run()`](#cw.cli.run) – which function this subcommand is, how to call it,
and under which convention – travels in it.

### cw.cli.add_commands(parser, obj, /, \*, group_name=None, namespace=None, group_kwargs=None, namespace_kwargs=None, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), decode=None)

Add `obj`’s commands to an existing parser, optionally under one group.

`namespace=` and `namespace_kwargs=` are argh’s pre-0.30 spellings of
`group_name=` and `group_kwargs=`. argh renamed them with no alias, which left four
fleet call sites passing a keyword nothing reads; accepting both revives them.

When `group_name` is given, `config` is keyed by *command* name – `config` always
has the same shape as the `obj` beside it, and here that `obj` is the group’s
members.

* **Return type:**
  [`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)

```pycon
>>> import argparse, cw
>>> from cw.cli import add_commands
>>> def status(): ...
>>> parser = argparse.ArgumentParser(prog='priv')
>>> _ = add_commands(parser, [status], group_name='git_ops')
>>> parser.format_usage()
'usage: priv [-h] {git_ops} ...\n'
```

`obj` is anything [`cw.dispatch()`](cw.md#cw.dispatch) takes, **a mapping included** – which is what
makes this the answer to “a group in the mapping form wants `title=`” (issue #31,
ADR-0008). Seed the parser with [`mk_parser()`](#cw.cli.mk_parser) rather than `ArgumentParser()` so
the root gets cw’s formatter too, and remember that `cw.run` *returns* the exit code
rather than raising it:

```pycon
>>> parser = cw.mk_parser({'info': status}, prog='xa')
>>> _ = add_commands(parser, {'log': status}, group_name='archive',
...                  group_kwargs={'title': 'Postmortem archive'})
>>> parser.format_usage()
'usage: xa [-h] {info,archive} ...\n'
>>> 'Postmortem archive' in parser.format_help()
True
```

The group’s row in the **parent’s** `--help` is fed by `group_kwargs['title']`, and
only by that. `help` is accepted, forwarded to `add_subparsers` and rendered
nowhere – see `_add_group()`, which is where that is implemented and explained.

### cw.cli.dispatch(obj, argv=None, \*, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), decode=None, egress=None, out=None, err=None, standalone=True, completion=True, \*\*parser_kwargs)

The front door: `dispatch == run o mk_parser`.

Everything [`mk_parser()`](#cw.cli.mk_parser) and [`run()`](#cw.cli.run) take, in one call. The console-script
idiom is:

```default
def main():
    raise SystemExit(cw.dispatch(COMMANDS, prog='priv'))
```

and the house dispatch – the thing that makes a project’s per-call configs shrink to
nothing – is [`functools.partial()`](https://docs.python.org/3/library/functools.html#functools.partial), not a cw-specific binder:

```default
dispatch = functools.partial(cw.dispatch, convention=cw.MODERN, prog='priv')
```

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

```pycon
>>> import cw, io
>>> def add(a: int, b: int):
...     return a + b
>>> out = io.StringIO()
>>> cw.dispatch(add, ['2', '3'], out=out)
0
>>> out.getvalue()
'5\n'
```

A usage error is argparse’s, and keeps argparse’s exit code – which matters, because a
console script that starts exiting 0 on a bad command line breaks every CI step that
checks it:

```pycon
>>> cw.dispatch(add, ['nope'], out=io.StringIO(), err=io.StringIO())
2
```

### cw.cli.enable_completion(parser, , , silent=True)

Offer `parser` to `argcomplete`, if it is installed.

* **Parameters:**
  * **parser** ([`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)) – The parser to complete against. A plain `ArgumentParser` – which is what
    `argcomplete.autocomplete` is typed for, and the reason cw never subclasses.
  * **silent** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Swallow the `ImportError` when `argcomplete` is absent, which is the
    point: completion is an optional extra (`pip install 'cw[completion]'`) and a
    CLI must run without it. `silent=False` re-raises, for a script that means to
    require it.
* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
* **Returns:**
  Whether completion was enabled.

The import is inside the function on purpose. `import cw` costs stdlib only, and a
module-scope third-party import here would quietly undo that for all 66 console
scripts. There is a test that greps for it.

```pycon
>>> import argparse
>>> from cw.cli import enable_completion
>>> enable_completion(argparse.ArgumentParser()) in (True, False)
True
```

### cw.cli.mk_parser(obj, /, \*, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), decode=None, \*\*parser_kwargs)

Build the parser `obj` describes. No parsing, no I/O, no side effects.

* **Parameters:**
  * **obj** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – A callable, a list, a mapping, a module, or a `'pkg.mod:name'` reference –
    see [`cw.commands`](cw.commands.md#module-cw.commands) for what each one means.
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]) – This call’s particulars, keyed the way you address the thing on the command
    line: `{param: add_argument_kwargs}` for a single command,
    `{command: {param: ...}}` for several, nested once more for a group.
  * **convention** ([`Convention`](cw.convention.md#cw.convention.Convention)) – What the defaults ARE. `cw.ARGH` by default.
  * **decode** – Seam 1, overriding `convention.decode` when given.
  * **parser_kwargs** – Passed verbatim to [`argparse.ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser) –
    `prog`, `description`, `epilog`, `formatter_class`, `allow_abbrev`.
* **Return type:**
  [`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)
* **Returns:**
  A plain [`argparse.ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser). Not a subclass – see the module
  docstring for why that is load-bearing.

```pycon
>>> import argparse, cw
>>> def ls(path='.'): ...
>>> type(cw.mk_parser(ls)) is argparse.ArgumentParser
True
```

A single callable is one command with no command word; anything else is subcommands:

```pycon
>>> cw.mk_parser(ls, prog='x').format_usage()
'usage: x [-h] [-p PATH]\n'
>>> cw.mk_parser([ls], prog='x').format_usage()
'usage: x [-h] {ls} ...\n'
```

Completion is **not** fired here. `argcomplete.autocomplete()` reads the
environment and may exit the process, and `mk_parser` is what a test inspects; so
completion happens in [`run()`](#cw.cli.run), which is also where argh does it.

### cw.cli.run(parser, argv=None, , config=None, convention=None, egress=None, out=None, err=None, standalone=True, completion=True)

Parse `argv` with `parser`, call the command it names, and report.

* **Parameters:**
  * **parser** ([`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)) – Any parser – one from [`mk_parser()`](#cw.cli.mk_parser), or a hand-built one that has been
    given a function by [`set_default_command()`](#cw.cli.set_default_command).
  * **argv** – The argument strings. `None` means [`sys.argv`](https://docs.python.org/3/library/sys.html#sys.argv) `[1:]`. Keyword or
    positional: four fleet call sites spell it as a keyword.
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]) – Per-parameter particulars, when they were not given at build time. Only the
    `codec=` entries can still take effect this late; the rest is token grammar
    and is already in the parser.
  * **convention** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Convention`](cw.convention.md#cw.convention.Convention)]) – Overrides the one the parser was built with – which is what supplies
    `egress` when you do not pass one.
  * **egress** – Seam 2, overriding `convention.egress` when given.
  * **out** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TextIO`](https://docs.python.org/3/library/typing.html#typing.TextIO)]) – Where results go. `None` means [`sys.stdout`](https://docs.python.org/3/library/sys.html#sys.stdout), resolved **now**.
  * **err** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TextIO`](https://docs.python.org/3/library/typing.html#typing.TextIO)]) – Where an expected failure goes. `None` means [`sys.stderr`](https://docs.python.org/3/library/sys.html#sys.stderr), now.
  * **standalone** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – `True` prints and returns an exit code; `False` returns the
    function’s own value and lets everything propagate.
  * **completion** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Offer the parser to `argcomplete` before parsing, as argh does.
* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
* **Returns:**
  An `int` exit code when `standalone`, else whatever the command returned.

The convention travels with the parser, so flipping to `cw.MODERN` stays one act
even when the build and the run are two calls:

```pycon
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

An expected failure is one line and an exit code; an unexpected one keeps its
traceback, because a bug deserves one:

```pycon
>>> err = io.StringIO()
>>> def risky():
...     raise cw.CommandError('no such pipeline', code=3)
>>> cw.dispatch(risky, [], err=err)
3
>>> err.getvalue()
'CommandError: no such pipeline\n'
```

### cw.cli.set_default_command(parser, func, /, \*, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), command=None)

Bind one function to `parser`: add its arguments, and stash how to call it.

This is what makes `run`’s reason for existing true – a repo can hand-build a
parser, `add_argument` to it, bind a function here, and still get cw’s ingress and
egress:

* **Return type:**
  [`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)

```pycon
>>> import argparse, cw, io
>>> from cw.cli import set_default_command
>>> parser = argparse.ArgumentParser(prog='count')
>>> def tally(word, *, times=1):
...     return [word] * times
>>> _ = set_default_command(parser, tally)
>>> out = io.StringIO()
>>> cw.run(parser, ['hi', '-t', '2'], out=out)
0
>>> out.getvalue()
'hi\nhi\n'
```

The function’s docstring becomes the parser’s description, unless the parser already
has one – argh’s rule, and it is what lets `description=` override it.

`command` is the command word this function is bound to, when there is one. It is used
only in messages – it is what lets the `functools.partial` warning print the
`config` key you would actually paste rather than a `'<command>'` placeholder – so
a caller binding a single command has no reason to pass it.
