# cw.convention

What cw’s defaults ARE, as one frozen value per context.

`config` and `convention` are the fleet’s existing pair of words – `streamlitfront`’s
`mk_app(objs, config=None, convention=None)` already uses them with exactly these
meanings, so cw rhymes with it rather than inventing a third vocabulary:

`convention`
: *What the defaults are.* A frozen dataclass, swapped per **context** – a repo, a
  house style, the whole fleet. Rebinding it is how a project’s per-call `config`
  entries shrink to nothing.

`config`
: *This call’s particulars.* A plain mapping, swapped per **call**.

Two values ship:

```pycon
>>> ARGH.naming, ARGH.short_flags, ARGH.resolve_hints
('by_name_if_has_default', True, False)
>>> ARGH.decode.__name__, ARGH.egress.__name__
('argh_decode', 'argh_egress')
>>> MODERN.naming, MODERN.resolve_hints, MODERN.hints_when_declared
('by_name_if_kwonly', True, True)
>>> MODERN.decode.__name__, MODERN.egress.__name__
('modern_decode', 'iterable_egress')
```

[`ARGH`](#cw.convention.ARGH) is the default everywhere, and it reproduces argh 0.31.3 including the parts
nobody likes. Every improvement is opt-in, and opting in is **one** act:

```pycon
>>> import functools, cw
>>> dispatch = functools.partial(cw.dispatch, convention=MODERN)
```

That is the whole mechanism – there is no `cw.bind` and no `set_dispatch_defaults`.
Anything in between is a [`dataclasses.replace()`](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace):

```pycon
>>> import dataclasses
>>> half_way = dataclasses.replace(ARGH, resolve_hints=True)
>>> half_way.resolve_hints, half_way.naming
(True, 'by_name_if_has_default')
```

`decode` and `egress` – two of cw’s three seams – are fields here rather than only
`dispatch` keywords, for one reason: if `MODERN` did not carry its own, flipping to it
would need a coordinated three-keyword edit at every call site, and a seam whose
replacement touches every caller is in the wrong place. So `dispatch(decode=...)` and
`dispatch(egress=...)` default to `None`, meaning *take the convention’s*.

**The merge ladder** – what a convention presides over – is four tiers, later wins:

```default
1. signature inference     kind, default, name, flag spellings
2. hint inference          convention.decode(param, hint)
3. function attribute      func._cw['params'][param]     (cw.compat.arg writes it)
4. config                  config[...][param]            (this call's particulars)
```

Tiers 3 and 4 both count as “declared”, so either one switches tier 2 off for the *whole*
function unless `hints_when_declared` says otherwise; and the merge is argh’s
field-specific one, not `dict.update` (ADR-0003). It is implemented once, as
[`cw.grammar.specs_for_function()`](cw.grammar.md#cw.grammar.specs_for_function), and lives there rather than here because it is the
only place that knows what a [`cw.grammar.ArgSpec`](cw.grammar.md#cw.grammar.ArgSpec) is. There is no second copy.

`formatter_class` is deliberately **not** a field (ADR-0006): it is already an
`argparse.ArgumentParser` keyword, and cw invents no vocabulary for anything argparse
already names. [`cw.mk_parser()`](cw.md#cw.mk_parser) defaults it to [`cw.ArghHelpFormatter`](cw.md#cw.ArghHelpFormatter) and passes
whatever you give it straight through, to the top parser and to every subparser.

### Module Attributes

| [`ARGH`](#cw.convention.ARGH)   | argh 0.31.3's grammar, footguns included.             |
|---------------------------------------------------------|-------------------------------------------------------|
| [`MODERN`](#cw.convention.MODERN) | The same machinery with the improvements switched on. |

### Classes

| [`Convention`](#cw.convention.Convention)([naming, short_flags, ...])   | The grammar switches, as one hashable value.   |
|-------------------------------------------------------------------------------------------|------------------------------------------------|

### cw.convention.ARGH *= Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>)*

argh 0.31.3’s grammar, footguns included.

* **Type:**
  cw’s default in every entry point

### *class* cw.convention.Convention(naming='by_name_if_has_default', short_flags=True, hyphenate_commands=True, hyphenate_groups=False, default_in_help=True, hints_when_declared=False, resolve_hints=False, decode=<function argh_decode>, egress=<function argh_egress>)

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

### cw.convention.MODERN *= Convention(naming='by_name_if_kwonly', short_flags=True, hyphenate_commands=True, hyphenate_groups=True, default_in_help=True, hints_when_declared=True, resolve_hints=True, decode=<function modern_decode>, egress=<function iterable_egress>)*

The same machinery with the improvements switched on. `naming` follows parameter
kind rather than the presence of a default, annotations are actually resolved and
still consulted when a parameter is overridden, groups are hyphenated like commands,
`decode` additionally understands `Optional[X]`, `Enum` and `pathlib`, and
`egress` iterates anything iterable rather than argh’s three-type whitelist.

`default_in_help` stays `True` here (ADR-0004 rule 4): docstring-derived per-parameter
help is not in v1, so turning the default off would leave an undocumented flag with an
empty help column – strictly worse than argh, in the value the fleet is told to adopt.
