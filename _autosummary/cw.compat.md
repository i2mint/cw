# cw.compat

Transitional argh shim: a one-line import change retires a repo.

**Deprecated from day one.** This module exists so that a repo can stop depending on
LGPL-3.0-or-later `argh` *today*, in a diff a reviewer can read in one glance:

```default
-import argh
+from cw import compat as argh
```

and then migrate to cw’s real API on its own schedule. New code should never import it.
Every name warns once, on first use; `CW_COMPAT_QUIET=1` silences the lot for a repo that
has decided to live here for a while.

The surface is the fleet’s entire *measured* argh usage – nothing speculative:
`dispatch_commands` 34 · `dispatch_command` 30 · `ArghParser` 27 · `dispatch` 19 ·
`arg` 17 · `add_commands` 15 · `NameMappingPolicy` 4 · `CommandError` 4 ·
`completion` 2 · `confirm` 1, plus `set_default_command`.

Every function here is **three statements or fewer**. That is the design gauge, not a
coding-style preference: [`arg()`](#cw.compat.arg) is thin *because* cw’s merge ladder already has a
function-attribute tier for it to write into, and if `@arg` had needed real work, the
ladder would have been in the wrong shape. The one function with a body worth reading is
[`dispatch()`](#cw.compat.dispatch), and everything in it is argh-compatibility, not cw.

Four things this shim does **not** do, each of which a literal reading of argh’s signatures
would have got wrong:

1. **It does not swallow argparse’s exit code.** `argh.dispatch_commands` is typed
   `-> None`, but in argh the `SystemExit(2)` from a usage error propagates out of
   `main()`. `cw.dispatch` *returns* that 2 instead, so a literal `-> None` shim
   would make every migrated console script exit **0** on a bad command line – across 64
   dispatch-style call sites, breaking any CI step that checks `$?`. These shims re-raise
   a non-zero code.
2. \*\*It does not bind `sys.stdout` in a signature default.\*\* argh’s
   `output_file: IO = sys.stdout` is bound at import (`dispatching.py:77`), which is why
   `redirect_stdout` and pytest’s `capsys` capture nothing from an argh CLI. That is the
   single worst defect in argh’s dispatch surface, and putting it back into the shim that
   19 call sites will use would be an odd thing to do. Streams resolve at call time.
3. \*\*It does not forward argh’s dispatch keywords to `ArgumentParser`.\*\* They are split
   out explicitly (`_ARGH_DISPATCH_KWARGS`), or `dispatch_commands(...,
   output_file=f)` would raise `TypeError: ArgumentParser.__init__() got an unexpected
   keyword argument`.
4. \*\*It accepts BOTH `group_name=` and `namespace=`.\*\* argh 0.30 renamed the keyword
   with no alias, leaving four fleet call sites passing something nothing reads. Accepting
   both revives them – a change from “would crash” to “works”, which is worth knowing
   about before you run one.

And one thing it deliberately refuses to do: `named`, `aliases` and `add_subcommands`
have zero uses anywhere in the fleet and are **not** shipped. A module `__getattr__`
raises an informative error instead. `named` in particular was specified as a shim that
writes `func._cw['name']` – which nothing reads, so it would silently do nothing, which
is worse than the [`AttributeError`](https://docs.python.org/3/builtins/exceptions.html#AttributeError) it existed to prevent.

**One trap the shim structurally cannot fix**, and which belongs on every migration
checklist: `from argh import CommandError`. A module that imported the *name* rather than
the module still imports argh after the one-line change, and cw will not catch an exception
class it has never heard of, so `CommandError: boom` / exit 1 becomes an unhandled
traceback. Grep for it.

```pycon
>>> import io
>>> from cw import compat as argh
>>> def hello(name, *, loudly=False):
...     '''Greet someone.'''
...     return f'HELLO {name}' if loudly else f'hello {name}'
>>> argh.dispatch_command(hello, ['world'], output_file=io.StringIO())
>>> argh.dispatch_command(hello, ['world'], output_file=None)
'hello world\n'
```

### Module Attributes

| [`CommandError`](#cw.compat.CommandError)([message, code])   | argh's expected-failure exception, which is cw's.                           |
|----------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`completion`](#cw.compat.completion)                      | `argh.completion.autocomplete(parser)` keeps working after the import swap. |

### Functions

| [`add_commands`](#cw.compat.add_commands)(parser, functions, \*[, ...])       | argh's `add_commands`, accepting the pre-0.30 spelling as well.           |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`arg`](#cw.compat.arg)(\*flags, \*\*add_argument_kwargs)            | argh's `@arg`: declare one argument's particulars on the function itself. |
| [`confirm`](#cw.compat.confirm)(action[, default, skip])                 | argh's `confirm`: a yes/no prompt, with argh's exact wording.             |
| [`dispatch`](#cw.compat.dispatch)(parser[, argv])                         | argh's `dispatch`: run a parser that already has its commands.            |
| [`dispatch_command`](#cw.compat.dispatch_command)(function[, argv, ...])          | argh's `dispatch_command`: one function, no command word.                 |
| [`dispatch_commands`](#cw.compat.dispatch_commands)(functions[, argv])             | argh's `dispatch_commands`: build a parser for `functions` and run it.    |
| [`set_default_command`](#cw.compat.set_default_command)(parser, function, \*[, ...]) | argh's `set_default_command`: make `function` the parser's only command.  |

### Classes

| [`ArghParser`](#cw.compat.ArghParser)(\*args, \*\*kwargs)   | argh's `ArgumentParser` subclass -- 27 fleet call sites.           |
|-----------------------------------------------------------------------------------|--------------------------------------------------------------------|
| [`NameMappingPolicy`](#cw.compat.NameMappingPolicy)(\*values)      | argh's naming policy, **exported** -- which argh itself never did. |

### Exceptions

| [`CommandError`](#cw.compat.CommandError)([message, code])   | argh's expected-failure exception, which is cw's.   |
|----------------------------------------------------------------------------------|-----------------------------------------------------|

### *class* cw.compat.ArghParser(\*args, \*\*kwargs)

Bases: [`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)

argh’s `ArgumentParser` subclass – 27 fleet call sites.

The three convenience methods, and nothing else. Note that this is the **only** class
in cw that subclasses [`argparse.ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser), and it exists solely because
those 27 call sites already do. [`cw.mk_parser()`](cw.md#cw.mk_parser) returns a plain
`ArgumentParser`, which is what keeps `argcomplete.autocomplete` – typed against
`argparse.ArgumentParser` – working for the ten fleet files marked
`# PYTHON_ARGCOMPLETE_OK`.

```pycon
>>> from cw import compat as argh
>>> def ping():
...     return 'pong'
>>> parser = argh.ArghParser(prog='demo')
>>> parser.add_commands([ping])
>>> parser.dispatch(['ping'], output_file=None)
'pong\n'
```

It defaults `formatter_class` exactly as argh’s own `ArghParser.__init__` does.
Without that line the one-line migration changes `--help` for every repo that holds
a parser object: a `None` default renders `None` instead of argh’s `-`, a string
default loses its quotes, and a multi-paragraph docstring is reflowed into one.

```pycon
>>> from cw import ArghHelpFormatter
>>> ArghParser(prog='demo').formatter_class is ArghHelpFormatter
True
```

#### add_commands(\*args, \*\*kwargs)

[`cw.compat.add_commands()`](#cw.compat.add_commands), on this parser.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### dispatch(\*args, \*\*kwargs)

[`cw.compat.dispatch()`](#cw.compat.dispatch), on this parser.

#### set_default_command(\*args, \*\*kwargs)

[`cw.compat.set_default_command()`](#cw.compat.set_default_command), on this parser.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *exception* cw.compat.CommandError(message='', , code=1)

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

argh’s expected-failure exception, which is cw’s. Not an alias to keep around: it is the
same class, so `except argh.CommandError` in migrated code catches what cw raises.

### *class* cw.compat.NameMappingPolicy(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

argh’s naming policy, **exported** – which argh itself never did.

`hasattr(argh, 'NameMappingPolicy')` is `False`, so
`illustration/__main__.py:23`’s `getattr` guard is a permanent silent no-op and
`ir/__main__.py:19-34` needs a triple-nested try/except to reach it. Both work
against this.

The values are cw’s [`cw.Convention`](cw.md#cw.Convention) `naming` strings, so a policy passed here
reaches cw without a translation table in between.

```pycon
>>> NameMappingPolicy.BY_NAME_IF_HAS_DEFAULT.value
'by_name_if_has_default'
```

### cw.compat.add_commands(parser, functions, , name_mapping_policy=None, group_name=None, namespace=None, group_kwargs=None, namespace_kwargs=None, func_kwargs=None)

argh’s `add_commands`, accepting the pre-0.30 spelling as well.

`namespace=` / `namespace_kwargs=` were renamed to `group_name=` /
`group_kwargs=` in argh 0.30 with no alias, which left `wads/__init__.py:98`,
`hedger/__main__.py:26`, `ke/__main__.py:24` and `ek/__main__.py:24` passing a
keyword nothing reads. Accepting both makes those four call sites work – flag it in
the migration notes, because “would crash” becoming “works” is still a change.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> import argparse
>>> from cw import compat as argh
>>> def status():
...     '''Say how things are.'''
>>> parser = argparse.ArgumentParser(prog='priv')
>>> argh.add_commands(parser, [status], namespace='git_ops')
>>> parser.format_usage()
'usage: priv [-h] {git_ops} ...\n'
```

### cw.compat.arg(\*flags, \*\*add_argument_kwargs)

argh’s `@arg`: declare one argument’s particulars on the function itself.

Three statements, because cw’s merge ladder already has a function-attribute tier
(`func._cw['params'][param]`) for this to write into. `_cw` is a plain attribute on
purpose: it is the documented contract, and it is what lets a repo declare CLI details
without importing cw at all.

Not deprecated by a warning, unlike the rest of this module – it is a decorator
evaluated at import time, so warning on it would fire before anybody could act, and it
is the one name here whose target (a plain attribute) is a supported cw contract rather
than a shim.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)

```pycon
>>> from cw import compat as argh
>>> @argh.arg('-i', '--ignore', nargs='*')
... def quickstart(project_dir, *, ignore=None):
...     '''Start a project.'''
>>> quickstart._cw['params']['ignore']
{'nargs': '*', 'flags': ['-i', '--ignore']}
```

Two argh keywords are *not* `add_argument` keywords and are handled the way argh
handles them. `dest=` says which parameter a differently-spelt flag refers to
(`argh/decorators.py:143-146`), so it decides the key rather than being passed on:

```pycon
>>> @argh.arg('--al', dest='alpha', help='aliased')
... def scale(alpha=1): ...
>>> sorted(scale._cw['params'])
['alpha']
```

And `completer=` is argcomplete’s per-argument hook, which `add_argument` rejects;
it travels in the leaf and [`cw.cli`](cw.cli.md#module-cw.cli) assigns it to the action it creates.

```pycon
>>> @argh.arg('--host', completer=lambda **kw: ['localhost'])
... def serve(host='0.0.0.0'): ...
>>> callable(serve._cw['params']['host']['completer'])
True
```

### cw.compat.completion *= <cw.compat._Completion object>*

`argh.completion.autocomplete(parser)` keeps working after the import swap.

### cw.compat.confirm(action, default=None, skip=False, \*\*kwargs)

argh’s `confirm`: a yes/no prompt, with argh’s exact wording.

```pycon
>>> import io
>>> from cw import compat as argh
>>> argh.confirm('Go', skip=True) is None
True
```

### cw.compat.dispatch(parser, argv=None, \*\*kwargs)

argh’s `dispatch`: run a parser that already has its commands.

Accepts argh’s `output_file` / `errors_file` / `completion` and the four keywords
that were verified to have zero fleet uses, so a call site that passes one gets cw’s
behaviour rather than a `TypeError`. `output_file=None` returns the output string.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> import io
>>> from cw import compat as argh
>>> parser = argh.ArghParser(prog='demo')
>>> def ping():
...     return 'pong'
>>> parser.add_commands([ping])
>>> parser.dispatch(['ping'], output_file=None)
'pong\n'
```

### cw.compat.dispatch_command(function, argv=None, , old_name_mapping_policy=True, \*\*kwargs)

argh’s `dispatch_command`: one function, no command word.

`old_name_mapping_policy` is accepted and ignored, as it is in argh when it is
`True` – which is the only value any fleet call site passes, and is cw’s default
everywhere.

### cw.compat.dispatch_commands(functions, argv=None, \*\*kwargs)

argh’s `dispatch_commands`: build a parser for `functions` and run it.

The fleet’s most-used argh name (34 call sites). Unlike argh’s, a usage error still
exits 2 rather than 0.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> import io
>>> from cw import compat as argh
>>> def add(a: int, b: int):
...     return a + b
>>> argh.dispatch_commands([add], ['add', '2', '3'], output_file=None)
'5\n'
```

### cw.compat.set_default_command(parser, function, , name_mapping_policy=None, \*\*kwargs)

argh’s `set_default_command`: make `function` the parser’s only command.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
