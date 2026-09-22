# cw.base

The small vocabulary cw’s other modules share: sentinels, errors, and help rendering.

This is the bottom of cw’s import graph. Everything else in `cw` imports from here and
nothing here imports from `cw`, so this module stays trivially cheap and trivially
testable.

What lives here:

`MISSING` / `HIDE`
: Two named singletons. `MISSING` means “no value was supplied”, which `None` cannot
  mean because `None` is an ordinary default. `HIDE` is the `config` value meaning
  “this parameter is not a command-line argument at all”.

`CommandError`
: The one exception a command may raise to say “this is an expected failure”: one line to
  stderr, no traceback, and an exit code.

`ArghHelpFormatter`
: The help look cw reproduces by default – a raw (unwrapped) description, and a help
  column that renders each parameter’s default with `repr`, `None` as `'-'`.

`Codec`
: The optional, per-parameter, *post-parse* decoder (the “ingress site”), for turning a
  token into something argparse’s `type=` must not be asked to build.

`Decode` / `Egress`
: The call contracts of two of cw’s three seams, named once so the rest of the package
  (and its users) can spell them.

```pycon
>>> HIDE
cw.HIDE
>>> CommandError('nope', code=7).code
7
```

### Module Attributes

| [`MISSING`](#cw.base.MISSING)         | "No value was supplied" -- distinct from `None`, which is an ordinary default value.                   |
|------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| [`HIDE`](#cw.base.HIDE)            | A `config` value meaning "this parameter is not a command-line argument at all".                       |
| [`Decode`](#cw.base.Decode)          | Seam 1.                                                                                                |
| [`Egress`](#cw.base.Egress)          | Seam 2.                                                                                                |
| [`DFLT_ERROR_CODE`](#cw.base.DFLT_ERROR_CODE) | The exit code a [`CommandError`](#cw.base.CommandError) uses when none is given. |
| [`DFLT_HELP`](#cw.base.DFLT_HELP)       | The help string cw gives a parameter that has none, so its default shows in the help column.           |

### Classes

| [`ArghHelpFormatter`](#cw.base.ArghHelpFormatter)(prog[, indent_increment, ...])   | The default help look: raw description, `repr`-ed defaults, `None` as `'-'`.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`Codec`](#cw.base.Codec)(decode[, passthrough])                       | A per-parameter, post-parse decoder for one parameter (the "ingress site").    |

### Exceptions

| [`CommandError`](#cw.base.CommandError)([message, code])   | An *expected* failure: one line to stderr, no traceback, `exit(code)`.   |
|----------------------------------------------------------------------------------|--------------------------------------------------------------------------|

### *class* cw.base.ArghHelpFormatter(prog, indent_increment=2, max_help_position=24, width=None)

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

### *class* cw.base.Codec(decode, passthrough=())

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

### *exception* cw.base.CommandError(message='', , code=1)

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

### cw.base.DFLT_ERROR_CODE *= 1*

The exit code a [`CommandError`](#cw.base.CommandError) uses when none is given.

### cw.base.DFLT_HELP *= '%(default)s'*

The help string cw gives a parameter that has none, so its default shows in the help
column. Turned off by `Convention.default_in_help=False`.

### cw.base.Decode

Seam 1. `(parameter, hint) -> add_argument kwargs`.

Given a [`inspect.Parameter`](https://docs.python.org/3/library/inspect.html#inspect.Parameter) and its type hint (whatever
`Convention.resolve_hints` decided a “hint” is), return one of:

* `None` – infer nothing for this parameter; argparse leaves the token a `str`;
* a callable – shorthand for `{'type': that_callable}`;
* a Mapping – *any* `add_argument` kwargs (`type`, `nargs`, `choices`,
  `action`, `const`, `required`, …).

The Mapping return is not optional generality: a type implies more than a converter
(`list[str]` implies `nargs='*'`, `Literal['a', 'b']` implies `choices`), so a
seam that could only return a callable could not carry the grammar it exists to carry.

alias of `Callable`[[[`Parameter`](https://docs.python.org/3/library/inspect.html#inspect.Parameter), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`None`](https://docs.python.org/3/builtins/constants.html#None) | `Callable`[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)] | [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

### cw.base.Egress

Seam 2. `(result, *, out, err) -> exit code`.

How a function’s return value becomes lines on a stream and a process exit code.

alias of `Callable`[[…], [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### cw.base.HIDE *= cw.HIDE*

A `config` value meaning “this parameter is not a command-line argument at all”.

The function’s own default applies instead. Its v1 consumer is a
[`functools.partial()`](https://docs.python.org/3/library/functools.html#functools.partial) whose pre-bound keyword [`inspect.signature()`](https://docs.python.org/3/library/inspect.html#inspect.signature) still
re-exposes; `HIDE` is how you stop that keyword from becoming a flag.

`HIDE` is used rather than the spelling `config[param] = None` because `None` is a
perfectly ordinary default value, and overloading it would be a latent bug.

### cw.base.MISSING *= cw.MISSING*

“No value was supplied” – distinct from `None`, which is an ordinary default value.
