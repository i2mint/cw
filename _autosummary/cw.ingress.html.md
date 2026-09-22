# cw.ingress

Namespace to call: the lines that honour `/`, `*args`, `*` and `**kwargs`.

This is the one job `i2.Sig.mk_args_and_kwargs` was going to buy, and it is a page of
[`inspect`](https://docs.python.org/3/library/inspect.html#module-inspect). argh does the same job in its own dispatcher without i2, and so does cw:
split `POSITIONAL_ONLY` and `POSITIONAL_OR_KEYWORD` into positional arguments, put
`KEYWORD_ONLY` into a keyword dict, extend the positionals with `VAR_POSITIONAL`, and
collect whatever is left over for `VAR_KEYWORD`.

[`mk_ingress()`](#cw.ingress.mk_ingress) returns a callable whose contract is `{name: value} -> (args, kwargs)`
– deliberately the *same* contract as `i2.wrapper.Ingress`, so that an i2 `Ingress`
remains a drop-in substitute for anyone who wants one. The contract is honoured; the
import is not paid. (It is reachable as `cw.ingress.mk_ingress` and is deliberately not
re-exported from the `cw` facade: nobody has asked for it as a public name.)

```pycon
>>> def move(source, /, destination='.', *extra, force=False, **options):
...     ...
>>> ingress = mk_ingress(move)
>>> ingress({'source': 'a', 'destination': 'b', 'extra': ['c', 'd'],
...          'force': True, 'dry_run': 'yes'})
(('a', 'b', 'c', 'd'), {'force': True, 'dry_run': 'yes'})
```

Note what that shows and what it hides. `source` is positional-only and `destination`
is not, yet both are passed positionally – because a parameter’s *kind* decides how it is
called, while [`cw.grammar`](cw.grammar.html.md#module-cw.grammar) decides, separately, whether it is spelt `dest` or
`--destination` on the command line. And `dry_run` reaches `**options` only because
something put it in the mapping; under `cw.ARGH` the parser never adds an argument
for `**options` at all, so in a real dispatch that key is simply never there.

## Why this module exists at all: the anti-example

The fleet’s own code carried this for years, in an example script that acquires METAR
weather observations. It is reproduced verbatim because it is the clearest statement of
the problem ingress solves:

```default
if __name__ == '__main__':
    try:
        import argh

        _acquire_metar_data = acquire_metar_data

        def acquire_metar_data(airport_ids=DFLT_AIRPORT_IDS,
                               hours_before_now=DFLT_HOURS_BEFORE_NOW):
            airport_ids = airport_ids.split(',')
            hours_before_now = int(hours_before_now)
            return _acquire_metar_data(airport_ids, hours_before_now)

        argh.dispatch_command(_acquire_metar_data)

    except ImportError:
        print("You don't have argh: Pity (you should really ")

        acquire_metar_data()
```

Read it slowly. The author knew perfectly well that a command line hands you strings and
that the underlying function wants a list and an int, so they wrote the coercion by hand,
in a shadowing wrapper, immediately above the dispatch call – and then dispatched
`_acquire_metar_data`, the *original*, uncoerced function. The wrapper is never called.
The coercion never runs. Nothing raises; the CLI just quietly passes `'KJFK,KBOS'` where
a list was meant. (The fallback branch is broken too: it calls the rebound name with no
arguments, and its message is a sentence that stops mid-word.)

That is what hand-written, call-site ingress costs. The lesson cw takes from it is that
string-to-object conversion is a *seam of the framework*, declared once next to the
parameter it converts (`decode=`, or `type=` in a per-parameter config), never a block
of glue that a reader has to diff against the dispatch call to see is dead.

### Functions

| [`mk_ingress`](#cw.ingress.mk_ingress)(func, /, \*[, codecs])   | Build `{param_name: value} -> (args, kwargs)` for one function.   |
|--------------------------------------------------------------------------------------|-------------------------------------------------------------------|

### cw.ingress.mk_ingress(func, , , codecs=None)

Build `{param_name: value} -> (args, kwargs)` for one function.

* **Parameters:**
  * **func** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – The command. Inspected once, here, not on every call.
  * **codecs** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]]) – Optional per-parameter post-parse decoders, keyed by parameter name.
    [`cw.cli`](cw.cli.html.md#module-cw.cli) fills this from each [`cw.grammar.ArgSpec`](cw.grammar.html.md#cw.grammar.ArgSpec)’s `codec`, so
    that the promotion of a bare callable to a [`cw.Codec`](cw.html.md#cw.Codec) happens in exactly
    one place. This is the “ingress site” of the two conversion sites – the other
    is argparse’s `type=`, and which one a conversion runs at is decided per
    parameter by which key you wrote.
* **Returns:**
  a callable taking one mapping and returning `(args, kwargs)`.
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]], [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

Four rules, each of which is observable, and three of which are argh’s:

A `*args` parameter re-expands by extension rather than being passed as a tuple,
which is why `def estimate(*agents)` needs no configuration at all:

```pycon
>>> mk_ingress(lambda *agents: None)({'agents': ['a', 'b']})
(('a', 'b'), {})
```

A parameter absent from the mapping falls back to the function’s own default. That is
what makes `cw.HIDE` work: the argument is gone from the command line, and the
function still receives the value it was partial-ed with.

```pycon
>>> def packages(project=None, *, config_type='setup.cfg'): ...
>>> mk_ingress(packages)({'project': 'p'})
(('p',), {'config_type': 'setup.cfg'})
```

A parameter that is neither supplied nor defaulted is an error naming the likely
cause, rather than a [`TypeError`](https://docs.python.org/3/builtins/exceptions.html#TypeError) from deep inside the call:

```pycon
>>> mk_ingress(lambda pool: None)({})
Traceback (most recent call last):
  ...
cw.ingress.IngressError: <lambda>: no value for parameter 'pool', and it has no
default. Was it hidden with cw.HIDE?
```

Leftover keys go to `**kwargs` when the function takes it, and are dropped when it
does not – and under `cw.ARGH` nothing ever creates such a key, because argh
contributes no command-line argument for `**kwargs` at all:

```pycon
>>> mk_ingress(lambda a, **rest: None)({'a': 1, 'extra': 2})
((1,), {'extra': 2})
>>> mk_ingress(lambda a: None)({'a': 1, 'extra': 2})
((1,), {})
```
