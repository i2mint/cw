# cw

Tools to wire a string-only environment to a Python function call.

`cw` is a codec layer between a string-only environment – the command line – and a
Python function call, with somewhere to put the `str -> object` conversion on the way in
and the `result -> stdout` conversion on the way out:

```default
argv (strings)
  |
  |  ARGPARSE -- lexing, --help, usage:, subparsers, and the type= site
  v
Namespace  {dest: str | list[str] | bool | None}
  |
  |  INGRESS -- Namespace -> (args, kwargs), honouring /, *args, * and **kwargs
  v
(args, kwargs) --> f --> result
                          |
                          |  EGRESS -- result -> lines -> exit code
                          v
                     stdout + exit code
```

Two properties are load-bearing rather than incidental:

* **cw produces a plain** [`argparse.ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser), never a subclass, so tools that
  are argparse-typed at their signature (`argcomplete.autocomplete`) keep working.
* \*\*Importing `cw` costs stdlib only.\*\* The one third-party dependency, `i2`, is
  imported inside [`cw.resource_inputs()`](#cw.resource_inputs) and nowhere else, and is an optional extra
  (`pip install 'cw[resource]'`). `tests/test_import_is_cheap.py` asserts this in a
  fresh subprocess, which is the only place the claim can honestly be checked.

```pycon
>>> import cw, io
>>> def greet(name, *, loudly=False):
...     '''Say hello to someone.'''
...     return f'HELLO {name}' if loudly else f'hello {name}'
>>> out = io.StringIO()
>>> cw.dispatch(greet, ['world', '--loudly'], out=out)
0
>>> out.getvalue()
'HELLO world\n'
```

The same command as a function, for a test that does not want a CLI at all:

```pycon
>>> cw.dispatch(greet, ['world'], standalone=False)
'hello world'
```

```pycon
>>> cw.resolve_to_function('builtins.len') is len
True
```

### Functions

| [`add_commands`](#cw.add_commands)(parser, obj, /, \*[, ...])           | Add `obj`'s commands to an existing parser, optionally under one group.         |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`dispatch`](#cw.dispatch)(obj[, argv, config, convention, ...])    | The front door: `dispatch == run o mk_parser`.                                  |
| [`enable_completion`](#cw.enable_completion)(parser, /, \*[, silent])        | Offer `parser` to `argcomplete`, if it is installed.                            |
| [`mk_parser`](#cw.mk_parser)(obj, /, \*[, config, convention, ...])  | Build the parser `obj` describes.                                               |
| [`run`](#cw.run)(parser[, argv, config, convention, ...])      | Parse `argv` with `parser`, call the command it names, and report.              |
| [`set_default_command`](#cw.set_default_command)(parser, func, /, \*[, ...])   | Bind one function to `parser`: add its arguments, and stash how to call it.     |
| [`commands_from`](#cw.commands_from)(obj, /, \*[, convention, \_depth])  | `obj` -> `{name: callable}`, with a nested mapping for each group.              |
| [`argh_decode`](#cw.argh_decode)(param, hint)                          | Seam 1's default: argh's annotation guesser, if-branch for if-branch.           |
| [`cli_name`](#cw.cli_name)(name, /, \*[, hyphenate])                | The one name-mangling rule, applied to commands, groups, flags and config keys. |
| [`command_name`](#cw.command_name)(func, /, \*[, hyphenate])            | The command word for a callable: its `__name__`, with `_` becoming `-`.         |
| [`modern_decode`](#cw.modern_decode)(param, hint)                        | Seam 1's shipped alternative: `Optional[X]`, `Enum` and `pathlib` support.      |
| [`argh_egress`](#cw.argh_egress)(result, \*[, out, err])               | Seam 2's default: argh's type **whitelist**, footguns included.                 |
| [`confirm`](#cw.confirm)(action, /, \*[, default, skip, in_, out]) | A `y/n` prompt, reproducing `argh.confirm` -- the fleet's one interaction use.  |
| [`iterable_egress`](#cw.iterable_egress)(result, \*[, out, err])           | `cw.MODERN`'s egress: the `Iterable` protocol instead of argh's whitelist.      |
| [`json_egress`](#cw.json_egress)(result, \*[, out, err, indent])       | One JSON document, for a command whose result is data rather than lines.        |
| [`write_lines`](#cw.write_lines)(lines, /, \*[, out, flush])           | Write `str(line) + '\n'` for each item, **lazily**.                             |
| [`parse_ast_spec`](#cw.parse_ast_spec)(func_spec)                         | Parse AST-formatted function call specification.                                |
| [`parse_json_spec`](#cw.parse_json_spec)(func_spec)                        | Parse JSON-formatted function specification.                                    |
| [`parse_spec_with_dot_path`](#cw.parse_spec_with_dot_path)(func_spec)               | Default parser for simple dot-path function specifications.                     |
| [`resolve_func_from_dot_path`](#cw.resolve_func_from_dot_path)(dot_path)              | Resolve a function from a dot-separated import path.                            |
| [`resolve_to_function`](#cw.resolve_to_function)(func_spec[, ...])             | Resolve various function specifications into callable functions.                |
| [`resource_inputs`](#cw.resource_inputs)(func, resource, \*[, ...])        | Wrap a function to source specified inputs through configurable resolvers.      |

### Classes

| [`ArghHelpFormatter`](#cw.ArghHelpFormatter)(prog[, indent_increment, ...])   | The default help look: raw description, `repr`-ed defaults, `None` as `'-'`.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`Codec`](#cw.Codec)(decode[, passthrough])                       | A per-parameter, post-parse decoder for one parameter (the "ingress site").    |
| [`Convention`](#cw.Convention)([naming, short_flags, ...])             | The grammar switches, as one hashable value.                                   |

### Exceptions

| [`CommandError`](#cw.CommandError)([message, code])   | An *expected* failure: one line to stderr, no traceback, `exit(code)`.       |
|----------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`BoundKeywordWarning`](#cw.BoundKeywordWarning)             | A `functools.partial`'s pre-bound keyword is still exposed as a CLI option.  |
| [`CommandTreeError`](#cw.CommandTreeError)                | `obj` does not describe a command tree, and guessing would ship a wrong CLI. |
| [`GrammarError`](#cw.GrammarError)                    | A signature and its overrides cannot be reconciled into a CLI.               |
| [`IngressError`](#cw.IngressError)                    | A parsed namespace cannot be turned into a call to this function.            |

### *class* cw.ArghHelpFormatter(prog, indent_increment=2, max_help_position=24, width=None)

Bases: [`ArgumentDefaultsHelpFormatter`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentDefaultsHelpFormatter), [`RawDescriptionHelpFormatter`](https://docs.python.org/3/library/argparse.html#argparse.RawDescriptionHelpFormatter)

The default help look: raw description, `repr`-ed defaults, `None` as `'-'`.

Three behaviours, all reproduced from recorded help output rather than transcribed from
any implementation:

1. the description and epilog are **not** re-wrapped (from
   [`argparse.RawDescriptionHelpFormatter`](https://docs.python.org/3/library/argparse.html#argparse.RawDescriptionHelpFormatter));
2. a help string that does not already mention the default gets
   `' (default: ...)'` appended (from
   [`argparse.ArgumentDefaultsHelpFormatter`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentDefaultsHelpFormatter));
3. every `%(...)s` field in a help string is filled from the action, with three
   adjustments: a `default` renders as `repr(default)`, or as
   `NONE_IN_HELP` when it is `None`; anything carrying a `__name__`
   (a `type`, a callable default) renders as that name; and `choices` render
   joined by `CHOICES_SEPARATOR`.

The three class attributes below are the parametrization point – subclass and rebind
one to change the look, and pass your subclass as `formatter_class`.

```pycon
>>> import argparse
>>> parser = argparse.ArgumentParser(prog='demo', add_help=False,
...                                  formatter_class=ArghHelpFormatter)
>>> _ = parser.add_argument('--scale', default=None, help=DFLT_HELP)
>>> _ = parser.add_argument('--name', default='ann', help=DFLT_HELP)
>>> _ = parser.add_argument('--n', default=3, help=DFLT_HELP)
>>> _ = parser.add_argument('--flag', action='store_true', help=DFLT_HELP)
>>> collapsed = ' '.join(parser.format_help().split())
```

`None` is a dash, and every other default is its `repr`:

```pycon
>>> '--scale SCALE -' in collapsed
True
>>> "--name NAME 'ann'" in collapsed
True
>>> '--n N 3' in collapsed
True
>>> '--flag False' in collapsed
True
```

A help string of your own keeps the `ArgumentDefaultsHelpFormatter` suffix, and the
default in it is `repr`-ed too:

```pycon
>>> _ = parser.add_argument('--mine', default='e', help='an explicit help string')
>>> "an explicit help string (default: 'e')" in ' '.join(parser.format_help().split())
True
```

A `type` or a callable default renders by name rather than by `repr`:

```pycon
>>> parser = argparse.ArgumentParser(prog='demo', add_help=False,
...                                  formatter_class=ArghHelpFormatter)
>>> _ = parser.add_argument('--n', type=int, default=1, help='%(type)s')
>>> _ = parser.add_argument('--pick', choices=['a', 'b'], help='%(choices)s')
>>> collapsed = ' '.join(parser.format_help().split())
>>> '--n N int' in collapsed
True
>>> '--pick {a,b} a, b' in collapsed
True
```

#### CHOICES_SEPARATOR *= ', '*

What `choices` are joined by when a help string interpolates `%(choices)s`.

#### NONE_IN_HELP *= '-'*

What a `None` default renders as in the help column.

#### *static* render_default(obj,)

How a non-`None` default is rendered. `repr`, so a `str` keeps its quotes and
is distinguishable from the bare word.

### *exception* cw.BoundKeywordWarning

Bases: [`UserWarning`](https://docs.python.org/3/builtins/exceptions.html#UserWarning)

A `functools.partial`’s pre-bound keyword is still exposed as a CLI option.

Its own category so that a repo which has decided the flag is fine can silence exactly
this warning without changing its CLI, and without silencing anything else:

```default
warnings.filterwarnings('ignore', category=cw.BoundKeywordWarning)
```

### *class* cw.Codec(decode, passthrough=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A per-parameter, post-parse decoder for one parameter (the “ingress site”).

argparse’s `type=` is the wrong place for a *semantic* decoder – one that maps a
token to something that is not a scalar – because argparse also applies `type=` to a
string `default` and to a `const`. A decoder that resolves names to objects would
therefore be handed the sentinel and the default too. So cw offers a second,
**opt-in**, per-parameter site, which runs after parsing.

Two fields and deliberately nothing else: `nargs` / `const` / `default` / `help`
/ flag spellings are *token grammar* and belong in `config`, next to every other
`add_argument` keyword.

* **Parameters:**
  * **decode** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – `value -> value`. Called only on strings.
  * **passthrough** ([`Container`](https://docs.python.org/3/library/typing.html#typing.Container)) – Values `decode` must never see, so a sentinel can survive.

It applies if and only if the value is a `str`, which is argparse’s own `type=`
rule:

```pycon
>>> codec = Codec(decode=str.upper)
>>> codec('abc')
'ABC'
>>> codec(3)
3
>>> codec(None) is None
True
```

Elementwise for a list-valued (`nargs`) parameter:

```pycon
>>> codec(['a', 'b'])
['A', 'B']
```

And never on a passthrough value – which is what lets a sentinel survive:

```pycon
>>> pick = Codec(decode=str.upper, passthrough={'list'})
>>> pick('list'), pick('bass')
('list', 'BASS')
```

### *exception* cw.CommandError(message='', , code=1)

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

An *expected* failure: one line to stderr, no traceback, `exit(code)`.

Anything else a command raises keeps its traceback, because an unexpected failure is a
bug and a bug deserves one.

* **Parameters:**
  * **message** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The single line written to the error stream.
  * **code** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The process exit code. Keyword-only.

```pycon
>>> err = CommandError('no such thing')
>>> str(err), err.code
('no such thing', 1)
>>> CommandError('bad config', code=7).code
7
```

It is an ordinary exception, so it raises and catches like one:

```pycon
>>> try:
...     raise CommandError('nope', code=3)
... except CommandError as err:
...     print(f'{err} -> exit {err.code}')
nope -> exit 3
```

### *exception* cw.CommandTreeError

Bases: [`TypeError`](https://docs.python.org/3/builtins/exceptions.html#TypeError)

`obj` does not describe a command tree, and guessing would ship a wrong CLI.

### *class* cw.Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The grammar switches, as one hashable value.

Every field is read somewhere in `cw.grammar` or `cw.commands`; a field that
changed nothing would be exactly the speculative generality this design refuses.

```pycon
>>> Convention() == ARGH
True
>>> hash(Convention()) == hash(ARGH)
True
```

#### decode(hint)

Seam 1: `(Parameter, hint) -> add_argument kwargs | callable | None`.

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### default_in_help *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= True*

Give every argument the help string `'%(default)s'`.

#### egress(, out=None, err=None)

Seam 2: `(result, *, out, err) -> exit code`.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### hints_when_declared *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

Keep inferring from type hints even when a parameter has been overridden. argh
switches hint inference off for the *whole function* as soon as one `@arg`
appears; ADR-0003 extends “overridden” to cover `config` entries too.

#### hyphenate_commands *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= True*

`a_b` becomes the command `a-b`.

#### hyphenate_groups *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

`git_ops` becomes the group `git-ops`. argh leaves a group name verbatim.

#### naming *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'by_name_if_has_default'*

a default makes it an option) or
`BY_NAME_IF_KWONLY` (keyword-only makes it an option; a default only makes a
positional optional).

* **Type:**
  `BY_NAME_IF_HAS_DEFAULT` (argh’s legacy rule

#### resolve_hints *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

Resolve annotations with [`typing.get_type_hints()`](https://docs.python.org/3/library/typing.html#typing.get_type_hints) instead of reading
`__annotations__` raw. `False` reproduces argh’s blindness to PEP 563, under
which every annotation is a string and therefore infers nothing.

#### short_flags *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= True*

Infer `-x` from a parameter’s first character – suppressed when two parameters
share one, and always lost to `--help` for `h`.

### *exception* cw.GrammarError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A signature and its overrides cannot be reconciled into a CLI.

Raised eagerly, at parser-construction time, so a mis-keyed `config` entry is a
startup failure with a message rather than a flag that silently never appears.

### *exception* cw.IngressError

Bases: [`KeyError`](https://docs.python.org/3/builtins/exceptions.html#KeyError)

A parsed namespace cannot be turned into a call to this function.

In practice this means a parameter with no default was hidden from the command line
(`config={'x': cw.HIDE}`), so nothing supplies it and the function’s own signature
cannot either.

### cw.add_commands(parser, obj, /, \*, group_name=None, namespace=None, group_kwargs=None, namespace_kwargs=None, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), decode=None)

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

`obj` is anything [`cw.dispatch()`](#cw.dispatch) takes, **a mapping included** – which is what
makes this the answer to “a group in the mapping form wants `title=`” (issue #31,
ADR-0008). Seed the parser with [`mk_parser()`](#cw.mk_parser) rather than `ArgumentParser()` so
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

### cw.argh_decode(param, hint)

Seam 1’s default: argh’s annotation guesser, if-branch for if-branch.

A type implies more than a converter, which is why this returns a mapping of
`add_argument` kwargs rather than a callable: `list[str]` implies `nargs='*'`,
`Literal['a', 'b']` implies `choices`, `Optional[int]` implies
`required=False`. The covered set is exactly argh’s – `str`, `int`, `float`,
`bool`, `list`, `list[T]`, `Literal[...]` and `Union`/`Optional` – and
nothing else, because argh recognises nothing else.

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

```pycon
>>> p = inspect.Parameter('x', inspect.Parameter.KEYWORD_ONLY)
>>> argh_decode(p, int)
{'type': <class 'int'>}
>>> argh_decode(p, typing.Literal['a', 'b'])
{'choices': ('a', 'b'), 'type': <class 'str'>}
>>> argh_decode(p, list[int]) == {'nargs': '*', 'type': int}
True
>>> argh_decode(p, typing.Optional[int]) == {'type': int, 'required': False}
True
>>> argh_decode(p, dict)          # not in argh's if-chain: no inference at all
{}
```

### cw.argh_egress(result, , out=None, err=None)

Seam 2’s default: argh’s type **whitelist**, footguns included.

`None` writes nothing. A generator, `list` or `tuple` writes one line per item.
*Everything else* – including a `dict`, a `set` and a `map` object – writes one
line, which is its `str`.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

```pycon
>>> import io
>>> def show(result):
...     buffer = io.StringIO()
...     argh_egress(result, out=buffer)
...     return buffer.getvalue()
>>> show(['a', 'b'])
'a\nb\n'
>>> show({'a': 1, 'b': 2})
"{'a': 1, 'b': 2}\n"
>>> show(map(str, range(2)))
'<map object at 0x...>\n'
>>> show(None)
''
```

`err` is accepted and unused: it is part of the `cw.Egress` contract, so that
an egress which *does* write to the error stream is a drop-in replacement.

### cw.cli_name(name, , , hyphenate=True)

The one name-mangling rule, applied to commands, groups, flags and config keys.

ADR-0004 rule 2: derived names and the keys you address them by must go through the
*same* function, or a `config` written in one spelling silently misses a command
named in the other.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> cli_name('git_ops'), cli_name('git_ops', hyphenate=False)
('git-ops', 'git_ops')
```

### cw.command_name(func, , , hyphenate=True)

The command word for a callable: its `__name__`, with `_` becoming `-`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> def pack_go(): ...
>>> command_name(pack_go)
'pack-go'
```

Anything without a `__name__` – a `functools.partial`, a callable instance –
has no name to derive, and guessing one is how you ship the wrong CLI:

```pycon
>>> import functools
>>> command_name(functools.partial(pack_go))
Traceback (most recent call last):
  ...
TypeError: cannot derive a command name from functools.partial(...): it has no
__name__. Pass it explicitly with the mapping form: cw.dispatch({"my-command": obj})
```

### cw.commands_from(obj, , , convention=None, \_depth=0)

`obj` -> `{name: callable}`, with a nested mapping for each group.

* **Parameters:**
  * **obj** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Any of the six forms in this module’s docstring.
  * **convention** – Supplies `hyphenate_commands` and `hyphenate_groups`. Defaults to
    `cw.ARGH`.
* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), `Union`[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]
* **Returns:**
  A mapping of command-line name to callable, whose values may themselves be such a
  mapping – one level deep, no further.

A mapping value that is itself a mapping or a list is a group, which is how `t/xa`
gets two different commands both called `list`:

```pycon
>>> def list_cmd(): ...
>>> def archive_list_cmd(): ...
>>> tree = commands_from({'list': list_cmd,
...                       'archive': {'list': archive_list_cmd}})
>>> {name: sorted(value) if isinstance(value, dict) else value.__name__
...  for name, value in tree.items()}
{'list': 'list_cmd', 'archive': ['list']}
```

Group names are **verbatim** under `cw.ARGH` – `priv git_ops` is a string in
priv’s own README – and hyphenated under `cw.MODERN`:

```pycon
>>> import cw
>>> def g(): ...
>>> list(commands_from({'git_ops': [g]}))
['git_ops']
>>> list(commands_from({'git_ops': [g]}, convention=cw.MODERN))
['git-ops']
```

A zero-argument factory that *returns* commands is not called for you, because there is
no way to tell one from a command that happens to take no arguments – and Python
already has parentheses:

```pycon
>>> def dispatch_funcs():
...     return [g]
>>> list(commands_from({'git_ops': dispatch_funcs()}))
['git_ops']
```

A list of attribute *names* – `priv.__all__` is 47 strings – is refused, with the
two spellings that do work:

```pycon
>>> commands_from(['ls', 'rm'])
Traceback (most recent call last):
  ...
cw.commands.CommandTreeError: 'ls' is a string, and a list of strings is ambiguous: it
could be attribute names or object references. Pass the module itself (its __all__ is
used), or spell the mapping: {name: getattr(module, name) for name in module.__all__}.
```

### cw.confirm(action, , , default=None, skip=False, in_=None, out=None)

A `y/n` prompt, reproducing `argh.confirm` – the fleet’s one interaction use.

* **Parameters:**
  * **action** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What is about to happen, phrased as the subject of a question.
  * **default** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – What an empty or unrecognised answer means. `None` means “keep asking
    while the answer is empty, and return `None` if it is unrecognised”.
  * **skip** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Return `default` without prompting – for a `--yes` flag.
  * **in_** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TextIO`](https://docs.python.org/3/library/typing.html#typing.TextIO)]) – Where the answer is read from. Defaults to [`sys.stdin`](https://docs.python.org/3/library/sys.html#sys.stdin), resolved now.
  * **out** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TextIO`](https://docs.python.org/3/library/typing.html#typing.TextIO)]) – Where the prompt is written. Defaults to [`sys.stdout`](https://docs.python.org/3/library/sys.html#sys.stdout), resolved now.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

```pycon
>>> import io
>>> out = io.StringIO()
>>> confirm('Delete everything', in_=io.StringIO('y\n'), out=out)
True
>>> out.getvalue()
'Delete everything? (y/n)'
```

A default is shown by which letter is capitalised, and is what an empty answer means:

```pycon
>>> confirm('Proceed', default=True, in_=io.StringIO('\n'), out=io.StringIO())
True
>>> confirm('Proceed', default=False, in_=io.StringIO('\n'), out=io.StringIO())
False
```

`skip=True` is how a `--yes` flag is spelt; nothing is read and nothing is written:

```pycon
>>> confirm('Proceed', default=True, skip=True) is True
True
```

Unlike the streams, the *questions* are not a seam: this is a y/n prompt, and anything
richer is the caller’s own code.

### cw.dispatch(obj, argv=None, \*, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), decode=None, egress=None, out=None, err=None, standalone=True, completion=True, \*\*parser_kwargs)

The front door: `dispatch == run o mk_parser`.

Everything [`mk_parser()`](#cw.mk_parser) and [`run()`](#cw.run) take, in one call. The console-script
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

### cw.enable_completion(parser, , , silent=True)

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

### cw.iterable_egress(result, , out=None, err=None)

`cw.MODERN`’s egress: the `Iterable` protocol instead of argh’s whitelist.

A `map`, a `set`, a `dict_keys` – anything iterable that is not a `str`,
`bytes` or `Mapping` – writes one line per item.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

```pycon
>>> import io
>>> def show(result):
...     buffer = io.StringIO()
...     iterable_egress(result, out=buffer)
...     return buffer.getvalue()
>>> show(map(str, range(2)))
'0\n1\n'
>>> show({'a': 1})
"{'a': 1}\n"
>>> show('one line')
'one line\n'
```

### cw.json_egress(result, , out=None, err=None, indent=2)

One JSON document, for a command whose result is data rather than lines.

An iterator is materialised first (JSON has no streaming form), and anything JSON does
not know is rendered with `str` rather than raising – which is what
`t/xa/xa/cli.py`’s hand-rolled version does, and it is the behaviour a CLI wants.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

```pycon
>>> import io
>>> buffer = io.StringIO()
>>> json_egress({'b': 1, 'a': [2, 3]}, out=buffer, indent=None)
0
>>> buffer.getvalue()
'{"b": 1, "a": [2, 3]}\n'
```

```pycon
>>> buffer = io.StringIO()
>>> _ = json_egress(iter('ab'), out=buffer, indent=None)
>>> buffer.getvalue()
'["a", "b"]\n'
```

### cw.mk_parser(obj, /, \*, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), decode=None, \*\*parser_kwargs)

Build the parser `obj` describes. No parsing, no I/O, no side effects.

* **Parameters:**
  * **obj** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – A callable, a list, a mapping, a module, or a `'pkg.mod:name'` reference –
    see [`cw.commands`](cw.commands.html.md#module-cw.commands) for what each one means.
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]) – This call’s particulars, keyed the way you address the thing on the command
    line: `{param: add_argument_kwargs}` for a single command,
    `{command: {param: ...}}` for several, nested once more for a group.
  * **convention** ([`Convention`](cw.convention.html.md#cw.convention.Convention)) – What the defaults ARE. `cw.ARGH` by default.
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
completion happens in [`run()`](#cw.run), which is also where argh does it.

### cw.modern_decode(param, hint)

Seam 1’s shipped alternative: `Optional[X]`, `Enum` and `pathlib` support.

Composition is fall-through, not a registry: three `if`s and then
`return argh_decode(param, hint)`. Nothing to register, nothing to order.

`Optional[X]` is unwrapped to `X` rather than read as “the first member wins”,
which is the single most useful difference: under argh, `n: int | None = None`
quietly becomes `nargs='?'`.

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

```pycon
>>> p = inspect.Parameter('x', inspect.Parameter.KEYWORD_ONLY)
>>> modern_decode(p, typing.Optional[int]) == {'type': int}
True
>>> modern_decode(p, pathlib.Path) == {'type': pathlib.Path}
True
>>> class Colour(enum.Enum):
...     RED = 'r'
>>> decoded = modern_decode(p, Colour)
>>> decoded['type']('RED'), decoded['type']('r')
(<Colour.RED: 'r'>, <Colour.RED: 'r'>)
```

The help column advertises what the converter accepts, rather than member `repr`s
the converter would reject:

```pycon
>>> decoded['metavar']
'{RED}'
```

Abstract sequence interfaces mean what they say, which argh-compatible mode
cannot do — argh recognises `list` and nothing else:

```pycon
>>> modern_decode(p, typing.Sequence[str]) == {'nargs': '*', 'type': str}
True
>>> argh_decode(p, typing.Sequence[str])
{}
```

### cw.parse_ast_spec(func_spec)

Parse AST-formatted function call specification.

Expected format: ‘function_name(arg1=value1, arg2=value2)’

* **Parameters:**
  **func_spec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – String representing a function call with keyword arguments
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  Tuple of (function_name, parameters_dict)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If the expression is malformed or unsafe

### Examples

```pycon
>>> parse_ast_spec('len()')
('len', {})
```

```pycon
>>> parse_ast_spec('str.replace(old="a", new="b")')
('str.replace', {'old': 'a', 'new': 'b'})
```

```pycon
>>> parse_ast_spec('range(start=0, stop=10)')
('range', {'start': 0, 'stop': 10})
```

### cw.parse_json_spec(func_spec)

Parse JSON-formatted function specification.

Expected format: ‘{“func”: “function_name”, “params”: {“key”: “value”}}’

* **Parameters:**
  **func_spec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – JSON string with func and params keys
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  Tuple of (function_name, parameters_dict)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If JSON is malformed or missing required keys

### Examples

```pycon
>>> parse_json_spec('{"func": "len", "params": {}}')
('len', {})
```

```pycon
>>> parse_json_spec('{"func": "str.replace", "params": {"old": "a", "new": "b"}}')
('str.replace', {'old': 'a', 'new': 'b'})
```

### cw.parse_spec_with_dot_path(func_spec)

Default parser for simple dot-path function specifications.

Validates that func_spec is a dot path (`'pkg.mod.name'`) or a colon reference
(`'pkg.mod:name'`) – word characters and dots, with at most one colon – then
returns it as-is with empty kwargs.

* **Parameters:**
  **func_spec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Function specification string
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  Tuple of (function_key, kwargs_dict)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If func_spec contains invalid characters

### Examples

```pycon
>>> parse_spec_with_dot_path('os.path.join')
('os.path.join', {})
```

```pycon
>>> parse_spec_with_dot_path('len')
('len', {})
```

```pycon
>>> parse_spec_with_dot_path('os.path:join')
('os.path:join', {})
```

### cw.resolve_func_from_dot_path(dot_path)

Resolve a function from a dot-separated import path.

Both spellings of a reference are accepted: the dot path this function is named
after, and the `'pkg.mod:name'` colon form the rest of cw documents (see
[`cw.commands.import_object()`](cw.commands.html.md#cw.commands.import_object)). The colon form is the unambiguous one – it
says where the module ends and the attribute path begins.

* **Parameters:**
  **dot_path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – String like ‘os.path.join’, ‘builtins.len’, ‘str.upper’, or the
  colon form ‘os.path:join’ / ‘json:JSONDecoder.decode’
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)
* **Returns:**
  The resolved callable function
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If the path cannot be resolved to a callable

### Examples

```pycon
>>> import os.path
>>> join_func = resolve_func_from_dot_path('os.path.join')
>>> join_func('a', 'b') == os.path.join('a', 'b')   # a separator, whichever OS
True
```

```pycon
>>> len_func = resolve_func_from_dot_path('builtins.len')
>>> len_func([1, 2, 3])
3
```

```pycon
>>> upper_func = resolve_func_from_dot_path('str.upper')
>>> upper_func('hello')
'HELLO'
```

The colon form resolves to the very same object:

```pycon
>>> resolve_func_from_dot_path('os.path:join') is os.path.join
True
>>> resolve_func_from_dot_path('json:JSONDecoder.decode')
<function JSONDecoder.decode at ...>
```

### cw.resolve_to_function(func_spec, func_key_and_kwargs=<function parse_ast_spec>, get_func=<function resolve_func_from_dot_path>)

Resolve various function specifications into callable functions.

This is the main entry point for function resolution. It handles:

- Direct callable objects (returned as-is)
- String specifications parsed via func_key_and_kwargs
- Function lookup via get_func
- Parameter binding via functools.partial

* **Parameters:**
  * **func_spec** (`Union`[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable), [`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncSpec`)]) – Function specification (callable, string, etc.)
  * **func_key_and_kwargs** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncSpec`)], [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncKey`, bound= [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]) – Parser function to extract key and params from spec.
    By default, will parse dot-path function names and call expressions.
  * **get_func** ([`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncKey`, bound= [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)), [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)] | [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncKey`, bound= [`str`](https://docs.python.org/3/builtins/stdtypes.html#str))], [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)]) – Function or mapping to resolve function keys to callables
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)
* **Returns:**
  Resolved callable function, potentially with bound parameters
* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If func_spec type is unsupported or resolved function not callable
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If function resolution fails

### Examples

```pycon
>>> # Direct callable
>>> resolve_to_function(len)
<built-in function len>
```

```pycon
>>> # Simple string (dot path)
>>> length_func = resolve_to_function('builtins.len')
>>> length_func([1, 2, 3])
3
```

```pycon
>>> # JSON format
>>> json_func = resolve_to_function(
...     '{"func": "builtins.len", "params": {}}',
...     parse_json_spec
... )
>>> json_func([1, 2, 3])
3
```

```pycon
>>> # AST format
>>> ast_func = resolve_to_function('str.upper()', parse_ast_spec)
>>> ast_func('hello')
'HELLO'
```

```pycon
>>> # Colon reference -- the spelling the rest of cw documents
>>> import os.path
>>> resolve_to_function('os.path:join') is os.path.join
True
```

### cw.resource_inputs(func, resource, \*, default_ingress=<function resolve_to_function>)

Wrap a function to source specified inputs through configurable resolvers.

This decorator transforms specified function arguments using resolver functions,
making it particularly useful for CLI contexts where string inputs need to be
resolved to actual objects/functions.

* **Parameters:**
  * **func** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)) – The function to wrap
  * **resource** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`None`](https://docs.python.org/3/builtins/constants.html#None) | [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable) | [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – 

    Dict mapping parameter names to resource specifications:
    - None: use default_ingress (resolve_to_function by default)
    - Callable: use the callable directly as resolver
    - Dict: use as kwargs for partial(default_ingress, \*\*dict)
  * **default_ingress** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)) – Default resolver function (default: resolve_to_function)
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)
* **Returns:**
  Wrapped function with resource resolution applied to specified parameters

### Examples

```pycon
>>> def func(apple, banana, carrot):
...     return f"{apple=}, {banana=}, {carrot=}"
>>>
>>> from cw.resolution import parse_ast_spec
>>> function_store = {'a': lambda: 1, 'b': lambda: 2}
>>>
>>> wrapped_func = resource_inputs(
...     func,
...     resource=dict(
...         apple=None,  # Use default resolve_to_function
...         carrot=dict(
...             func_key_and_kwargs=parse_ast_spec,
...             get_func=function_store.get
...         )
...     )
... )
>>>
```

Now apple will be resolved via resolve_to_function
carrot will be resolved via resolve_to_function with custom params
banana remains unchanged (passed through as-is)

```pycon
>>> # apple='builtins.len' -> resolve_to_function('builtins.len') -> len function
>>> # banana='test' -> unchanged (no resource specified)
>>> # carrot='a()' -> parsed as AST, resolved via function_store
>>> result = wrapped_func('builtins.len', 'test', 'a()')
>>> 'apple=<built-in function len>' in result
True
>>> "banana='test'" in result
True
>>> 'carrot=<function' in result and 'lambda' in result
True
```

### cw.run(parser, argv=None, , config=None, convention=None, egress=None, out=None, err=None, standalone=True, completion=True)

Parse `argv` with `parser`, call the command it names, and report.

* **Parameters:**
  * **parser** ([`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)) – Any parser – one from [`mk_parser()`](#cw.mk_parser), or a hand-built one that has been
    given a function by [`set_default_command()`](#cw.set_default_command).
  * **argv** – The argument strings. `None` means [`sys.argv`](https://docs.python.org/3/library/sys.html#sys.argv) `[1:]`. Keyword or
    positional: four fleet call sites spell it as a keyword.
  * **config** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]) – Per-parameter particulars, when they were not given at build time. Only the
    `codec=` entries can still take effect this late; the rest is token grammar
    and is already in the parser.
  * **convention** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Convention`](cw.convention.html.md#cw.convention.Convention)]) – Overrides the one the parser was built with – which is what supplies
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

### cw.set_default_command(parser, func, /, \*, config=None, convention=Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>), command=None)

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

### cw.write_lines(lines, , , out=None, flush=True)

Write `str(line) + '\n'` for each item, **lazily**.

Laziness is observable and is D2 row 18: a generator command that yields two lines and
then prompts must have those two lines on screen before the prompt. So the iterable is
never materialised, and each line is flushed as it is written (argh’s `always_flush`,
which defaults on).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> import io
>>> buffer = io.StringIO()
>>> write_lines(iter([1, None, 'three']), out=buffer)
>>> buffer.getvalue()
'1\nNone\nthree\n'
```

Laziness, shown rather than asserted – the first line is on the stream before the
second one has been computed:

```pycon
>>> buffer = io.StringIO()
>>> def two_lines():
...     yield 'first'
...     print(f'(the stream already holds {buffer.getvalue()!r})')
...     yield 'second'
>>> write_lines(two_lines(), out=buffer)
(the stream already holds 'first\n')
```

### Modules

| [`base`](cw.base.html.md#module-cw.base)             | The small vocabulary cw's other modules share: sentinels, errors, and help rendering.   |
|----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`cli`](cw.cli.html.md#module-cw.cli)               | The argparse surface: building a parser, and running one.                               |
| [`commands`](cw.commands.html.md#module-cw.commands)     | Turning an object into the `{name: callable}` tree a parser is built from.              |
| [`compat`](cw.compat.html.md#module-cw.compat)         | Transitional argh shim: a one-line import change retires a repo.                        |
| [`convention`](cw.convention.html.md#module-cw.convention) | What cw's defaults ARE, as one frozen value per context.                                |
| [`egress`](cw.egress.html.md#module-cw.egress)         | Result to stdout: how a function's return value becomes lines and an exit code.         |
| [`grammar`](cw.grammar.html.md#module-cw.grammar)       | How a Python signature becomes command-line arguments.                                  |
| [`ingress`](cw.ingress.html.md#module-cw.ingress)       | Namespace to call: the lines that honour `/`, `*args`, `*` and `**kwargs`.              |
| [`resolution`](cw.resolution.html.md#module-cw.resolution) | Function resolution utilities for CLI parameterization.                                 |
| [`testing`](cw.testing.html.md#module-cw.testing)       | Record a CLI's behaviour before a migration and assert it after.                        |
