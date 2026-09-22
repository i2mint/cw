# cw.grammar

How a Python signature becomes command-line arguments.

This is cw’s riskiest module and its most opinionated one: it reproduces argh 0.31.3’s
signature-to-`argparse` inference exactly, footguns included, because a CLI that reads
*almost* like the one it replaces is worse than one that reads nothing like it.

argh arrives at its grammar through two uncoordinated code paths – an annotation guesser
(`TypingHintArgSpecGuesser`) and a default-value guesser
(`guess_extra_parser_add_argument_spec_kwargs`) – which collide on `bool` and are
reconciled by two copy-pasted hand-patches. Here they are \*\*one function with one
precedence order\*\*: [`specs_for_function()`](#cw.grammar.specs_for_function).

Three things this module deliberately does *not* do:

* It never imports [`argparse`](https://docs.python.org/3/library/argparse.html#module-argparse). It produces [`ArgSpec`](#cw.grammar.ArgSpec) values – plain data –
  and [`ArgSpec.add_argument_args()`](#cw.grammar.ArgSpec.add_argument_args) turns one into the `(args, kwargs)` of an
  `add_argument` call. `cw.cli` is the only module that makes that call.
* It has no notion of a command tree, a parser, or a namespace. One function in, a list
  of arguments out.
* It hardcodes no policy. Every switch is read off the `convention` argument, so
  `convention=cw.MODERN` is one act that changes all of them at once.

The whole grammar in one look:

```pycon
>>> def greet(name, greeting='hello', *, shout=False, times: int = 1):
...     'Say hello.'
>>> for spec in specs_for_function(greet):
...     print(spec.param_name, spec.flags, spec.add_argument_kwargs())
name ['name'] {'help': '%(default)s'}
greeting ['-g', '--greeting'] {'default': 'hello', 'type': <class 'str'>, 'help': '%(default)s'}
shout ['-s', '--shout'] {'default': False, 'action': 'store_true', 'help': '%(default)s'}
times ['-t', '--times'] {'default': 1, 'type': <class 'int'>, 'help': '%(default)s'}
```

Read that output slowly, because every line of it is an argh compatibility decision:
`greeting` has a default so it becomes an *option* (`BY_NAME_IF_HAS_DEFAULT`);
`shout=False` becomes `store_true` (and `shout=True` would become `store_false`);
the short flags come from first characters and would vanish entirely if two parameters
shared one; and every help string is `'%(default)s'`, which
[`cw.base.ArghHelpFormatter`](cw.base.html.md#cw.base.ArghHelpFormatter) renders as `repr(default)`.

### Module Attributes

| [`ZERO_OR_MORE`](#cw.grammar.ZERO_OR_MORE)           | `argparse.ZERO_OR_MORE` -- "any number of values, including none".                                                                              |
|-------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| [`OPTIONAL`](#cw.grammar.OPTIONAL)               | `argparse.OPTIONAL` -- "one value, or none".                                                                                                    |
| [`BY_NAME_IF_HAS_DEFAULT`](#cw.grammar.BY_NAME_IF_HAS_DEFAULT) | A parameter is named on the command line iff it has a default value (argh's legacy policy, and the one every fleet script was written against). |
| [`BY_NAME_IF_KWONLY`](#cw.grammar.BY_NAME_IF_KWONLY)      | A parameter is named on the command line iff it is keyword-only.                                                                                |

### Functions

| [`argh_decode`](#cw.grammar.argh_decode)(param, hint)                           | Seam 1's default: argh's annotation guesser, if-branch for if-branch.           |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`modern_decode`](#cw.grammar.modern_decode)(param, hint)                         | Seam 1's shipped alternative: `Optional[X]`, `Enum` and `pathlib` support.      |
| [`cli_name`](#cw.grammar.cli_name)(name, /, \*[, hyphenate])                 | The one name-mangling rule, applied to commands, groups, flags and config keys. |
| [`command_name`](#cw.grammar.command_name)(func, /, \*[, hyphenate])             | The command word for a callable: its `__name__`, with `_` becoming `-`.         |
| [`specs_for_function`](#cw.grammar.specs_for_function)(func, /, \*[, convention, ...]) | The whole grammar: one function in, its command-line arguments out.             |

### Classes

| [`ArgSpec`](#cw.grammar.ArgSpec)(param_name, flags[, required, ...])   | One command-line argument, as data, before argparse ever sees it.   |
|------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|

### Exceptions

| [`GrammarError`](#cw.grammar.GrammarError)   | A signature and its overrides cannot be reconciled into a CLI.   |
|-----------------------------------------------------------------|------------------------------------------------------------------|

### *class* cw.grammar.ArgSpec(param_name, flags, required=cw.MISSING, default=cw.MISSING, nargs=None, extra=<factory>, codec=None, hidden=False, completer=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One command-line argument, as data, before argparse ever sees it.

`required`, `default` and `nargs` are held in their own fields rather than in
`extra` because argh merges them by rules that `dict.update` does not have (see
[`update()`](#cw.grammar.ArgSpec.update)), and reproducing that merge is what makes `--help` byte-identical.

```pycon
>>> spec = ArgSpec('verbose', ['-v', '--verbose'], default=False)
>>> spec.add_argument_args()
(('-v', '--verbose'), {'default': False})
>>> spec.is_positional
False
```

#### add_argument_args()

The full `(args, kwargs)` of the `add_argument` call this spec describes.

A positional is registered under its **command-line** name, hyphens and all –
exactly as argh does – because argparse reads that one string twice, and the two
readings cannot be separated: it is the `{a,b}`-or-`project-dir` displayed in
`usage:` *and* the name in `error: argument project-dir: ...`. Synthesising a
`metavar` instead would win the second reading and lose the first, silently
turning `{a,b}` into `project-dir` for any hyphenated positional carrying
`choices`.

The price is a `dest` with a hyphen in it, which no Python call can use.
[`argparse_dest`](#cw.grammar.ArgSpec.argparse_dest) names it and [`cw.cli`](cw.cli.html.md#module-cw.cli) renames it back on the way into
the call – one dictionary lookup, in one place.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)

```pycon
>>> spec = ArgSpec('project_dir', ['project-dir'])
>>> spec.add_argument_args()
(('project-dir',), {})
>>> spec.argparse_dest
'project-dir'
```

#### add_argument_kwargs()

The `**kwargs` half of the `add_argument` call.

`extra` is applied last, which reproduces argh’s
`dict(kwargs, **other_add_parser_kwargs)` – including the quirk that a `nargs`
guessed from a list-valued default overrides an explicitly declared one.

* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### *property* argparse_dest *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The namespace key argparse will store this argument under.

argparse derives it from the first long option (`--project-dir` ->
`project_dir`) or, for a positional, from the name itself – hyphens intact.

```pycon
>>> ArgSpec('project_dir', ['-p', '--project-dir']).argparse_dest
'project_dir'
>>> ArgSpec('project_dir', ['project-dir']).argparse_dest
'project-dir'
```

#### codec *: [Codec](cw.base.html.md#cw.base.Codec) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

The optional post-parse decoder (`cw.ingress`’s site, not argparse’s `type=`).

#### completer *: [Any](https://docs.python.org/3/library/typing.html#typing.Any)* *= None*

argcomplete’s per-argument completer. Not an `add_argument` keyword – argparse
rejects it – so it travels here and `cw.cli` assigns it to the created action,
which is where `argcomplete` looks for it.

#### default *: [Any](https://docs.python.org/3/library/typing.html#typing.Any)* *= cw.MISSING*

`add_argument(default=...)`; `MISSING` means “do not pass it”.

#### extra *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

`type`, `action`, `choices`, `help`…

* **Type:**
  Every other `add_argument` keyword

#### flags *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

Option strings (`['-v', '--verbose']`) or a single positional CLI name.

#### *classmethod* from_override(param_name, override)

Build a spec from an override leaf – `add_argument` kwargs plus cw’s three.

The three cw additions are `flags` (explicit option strings, hyphenated the way
argh hyphenates `@arg`’s), `codec` (the post-parse decoder), and the whole
leaf being `cw.HIDE`, which [`specs_for_function()`](#cw.grammar.specs_for_function) handles before it
gets here.

* **Return type:**
  [`ArgSpec`](#cw.grammar.ArgSpec)

```pycon
>>> ArgSpec.from_override(
...     'synth', {'flags': ['-s'], 'nargs': '?'})
ArgSpec(param_name='synth', flags=['-s'], required=cw.MISSING, default=cw.MISSING,
        nargs='?', extra={}, codec=None, hidden=False, completer=None)
```

#### hidden *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

keep the parameter, drop the CLI argument.

* **Type:**
  Set by a `cw.HIDE` override

#### *property* is_positional *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Is this a positional argument (as opposed to an option)?

```pycon
>>> ArgSpec('x', ['x']).is_positional
True
```

#### nargs *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

`add_argument(nargs=...)`; `None` means “do not pass it”.

#### param_name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The name of the Python parameter this argument feeds.

#### required *: [Any](https://docs.python.org/3/library/typing.html#typing.Any)* *= cw.MISSING*

`add_argument(required=...)`; `MISSING` means “do not pass it”.

#### update(other)

Merge an override into this spec, by argh’s rules (`argh/dto.py:33-50`).

Four rules, none of which is `dict.update`, and each of which is observable:

* `flags` **append**: the inferred spellings survive and the declared ones are
  added after them if new. This is why theremin’s `@arg('--synth', '-s')` on a
  parameter whose short flag was suppressed renders `--synth [SYNTH], -s [SYNTH]`
  – long first – with no special case anywhere.
* `required` and `default` are taken only when the override *has* one.
* `nargs` is taken only when the override’s is **truthy**, so there is no way to
  unset an inferred `nargs` (argh has no spelling for it either; see ADR-0003).
* everything else is a plain `dict.update`.

```pycon
>>> inferred = ArgSpec('synth', ['--synth'], default='sine')
>>> inferred.update(ArgSpec('synth', ['--synth', '-s'], nargs='?'))
>>> inferred.flags
['--synth', '-s']
```

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### cw.grammar.BY_NAME_IF_HAS_DEFAULT *= 'by_name_if_has_default'*

A parameter is named on the command line iff it has a default value (argh’s legacy
policy, and the one every fleet script was written against).

### cw.grammar.BY_NAME_IF_KWONLY *= 'by_name_if_kwonly'*

A parameter is named on the command line iff it is keyword-only. Position and
optionality become independent, which is what most people expect.

### *exception* cw.grammar.GrammarError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A signature and its overrides cannot be reconciled into a CLI.

Raised eagerly, at parser-construction time, so a mis-keyed `config` entry is a
startup failure with a message rather than a flag that silently never appears.

### cw.grammar.OPTIONAL *= '?'*

`argparse.OPTIONAL` – “one value, or none”.

### cw.grammar.ZERO_OR_MORE *= '\*'*

`argparse.ZERO_OR_MORE` – “any number of values, including none”.

### cw.grammar.argh_decode(param, hint)

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

### cw.grammar.cli_name(name, , , hyphenate=True)

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

### cw.grammar.command_name(func, , , hyphenate=True)

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

### cw.grammar.modern_decode(param, hint)

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

### cw.grammar.specs_for_function(func, , , convention=None, config=None, decode=None, parser_adds_help=True)

The whole grammar: one function in, its command-line arguments out.

Four tiers, later wins, merged field-by-field per ADR-0003 (argh’s
`ParserAddArgumentSpec.update`, *not* `dict.update`):

```default
1. signature inference     kind, default, name, flag spellings
2. hint inference          decode(param, hint)
3. function attribute      func._cw['params'][param]     (cw.compat.arg writes it)
4. config                  config[param]                 (this call's particulars)
```

Tier 2 is skipped entirely – for *every* parameter of the function – when tier 3 or
tier 4 is non-empty and `convention.hints_when_declared` is false. That is argh’s
`can_use_hints = not declared_args`: one override anywhere disables type inference
everywhere in that function. ADR-0003 extends “declared” to cover `config` too, so
that migrating an `@argh.arg` into a `config` entry does not silently switch hint
inference back on.

A `config` leaf of `cw.HIDE` removes the argument from the command line while
leaving the parameter to its own default:

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`ArgSpec`](#cw.grammar.ArgSpec)]

```pycon
>>> def serve(host='0.0.0.0', port=8080, pool=None):
...     ...
>>> [s.flags for s in specs_for_function(serve, config={'pool': HIDE})]
[['--host'], ['--port']]
```

(`--port` and `--pool` share a first character, so neither gets a short flag, and
`--host` loses `-h` to `--help`. Both rules are argh’s.)

A `config` key naming no parameter is an error, not a silent no-op – unless the
function takes `**kwargs`, in which case the argument is added and delivered there
(argh’s rule):

```pycon
>>> specs_for_function(serve, config={'prot': {'help': 'typo'}})
Traceback (most recent call last):
  ...
cw.grammar.GrammarError: serve: override for 'prot' matches no parameter. This
function's parameters are: host, port, pool
```
