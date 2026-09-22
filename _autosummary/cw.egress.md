# cw.egress

Result to stdout: how a function’s return value becomes lines and an exit code.

This is the seam argh has **no hook for at all**, which is why `t/xa`’s `cli.py`
hand-rolls `print(json.dumps(out, indent=2, default=str))` *inside a command body*. In cw
it is one keyword argument:

```default
cw.dispatch(commands, egress=cw.json_egress)
```

Three egresses ship, and the only difference between the first two is which results count
as “several lines”:

[`argh_egress()`](#cw.egress.argh_egress)
: argh’s `isinstance(result, (GeneratorType, list, tuple))` **whitelist**. A `dict`
  prints on one line, a `map` object prints as `<map object at 0x...>`, and a `set`
  prints as `{1}`. This is cw’s default because D2 says the default is argh.

[`iterable_egress()`](#cw.egress.iterable_egress)
: The `Iterable` *protocol* instead, excluding `str`, `bytes` and `Mapping`. This
  is `cw.MODERN`’s, and it is the whole difference.

[`json_egress()`](#cw.egress.json_egress)
: One JSON document, for a command whose result is structured data rather than lines.

**Streams resolve at call time.** `argh` binds `output_file: IO = sys.stdout` in a
signature default, so [`contextlib.redirect_stdout()`](https://docs.python.org/3/library/contextlib.html#contextlib.redirect_stdout) and pytest’s `capsys` capture
nothing from an argh CLI. cw takes `out=None` and looks up [`sys.stdout`](https://docs.python.org/3/library/sys.html#sys.stdout) *inside*
the call. That one line is what makes a cw CLI testable, and it is not a seam:

```pycon
>>> import io
>>> buffer = io.StringIO()
>>> argh_egress(['first', 'second'], out=buffer)
0
>>> buffer.getvalue()
'first\nsecond\n'
```

`None` prints nothing, but `0`, `False` and `''` all do – an argh rule worth
knowing, because it is the difference between a silent command and a command that prints a
blank line:

```pycon
>>> buffer = io.StringIO()
>>> argh_egress(None, out=buffer), buffer.getvalue()
(0, '')
>>> buffer = io.StringIO()
>>> argh_egress(0, out=buffer), buffer.getvalue()
(0, '0\n')
```

### Functions

| [`argh_egress`](#cw.egress.argh_egress)(result, \*[, out, err])               | Seam 2's default: argh's type **whitelist**, footguns included.                                                                          |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| [`iterable_egress`](#cw.egress.iterable_egress)(result, \*[, out, err])           | `cw.MODERN`'s egress: the `Iterable` protocol instead of argh's whitelist.                                                               |
| [`json_egress`](#cw.egress.json_egress)(result, \*[, out, err, indent])       | One JSON document, for a command whose result is data rather than lines.                                                                 |
| [`write_lines`](#cw.egress.write_lines)(lines, /, \*[, out, flush])           | Write `str(line) + '\n'` for each item, **lazily**.                                                                                      |
| [`confirm`](#cw.egress.confirm)(action, /, \*[, default, skip, in_, out]) | A `y/n` prompt, reproducing `argh.confirm` -- the fleet's one interaction use.                                                           |
| [`guard_no_coroutine`](#cw.egress.guard_no_coroutine)(result)                        | Raise an informative [`TypeError`](https://docs.python.org/3/builtins/exceptions.html#TypeError) if `result` is an un-awaited coroutine. |

### cw.egress.argh_egress(result, , out=None, err=None)

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

### cw.egress.confirm(action, , , default=None, skip=False, in_=None, out=None)

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

### cw.egress.guard_no_coroutine(result)

Raise an informative [`TypeError`](https://docs.python.org/3/builtins/exceptions.html#TypeError) if `result` is an un-awaited coroutine.

v1 does not run event loops. argh’s behaviour here is to print
`<coroutine object ...>` and warn – having never run the body – which is worse than
an error, so this is a deliberate, documented divergence from D2 rather than a gap in
it. It lives at the *call site* ([`cw.cli.run()`](cw.cli.md#cw.cli.run)) instead of inside one egress, so
that selecting a different egress cannot switch it off.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> async def fetch(): ...
>>> guard_no_coroutine(fetch())
Traceback (most recent call last):
  ...
TypeError: fetch returned a coroutine, and cw does not run event loops. Wrap the body
in asyncio.run(...), or make the command synchronous.
```

### cw.egress.iterable_egress(result, , out=None, err=None)

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

### cw.egress.json_egress(result, , out=None, err=None, indent=2)

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

### cw.egress.write_lines(lines, , , out=None, flush=True)

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
