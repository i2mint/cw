"""Result to stdout: how a function's return value becomes lines and an exit code.

This is the seam argh has **no hook for at all**, which is why ``t/xa``'s ``cli.py``
hand-rolls ``print(json.dumps(out, indent=2, default=str))`` *inside a command body*. In cw
it is one keyword argument::

    cw.dispatch(commands, egress=cw.json_egress)

Three egresses ship, and the only difference between the first two is which results count
as "several lines":

:func:`argh_egress`
    argh's ``isinstance(result, (GeneratorType, list, tuple))`` **whitelist**. A ``dict``
    prints on one line, a ``map`` object prints as ``<map object at 0x...>``, and a ``set``
    prints as ``{1}``. This is cw's default because D2 says the default is argh.

:func:`iterable_egress`
    The ``Iterable`` *protocol* instead, excluding ``str``, ``bytes`` and ``Mapping``. This
    is :data:`cw.MODERN`'s, and it is the whole difference.

:func:`json_egress`
    One JSON document, for a command whose result is structured data rather than lines.

**Streams resolve at call time.** ``argh`` binds ``output_file: IO = sys.stdout`` in a
signature default, so :func:`contextlib.redirect_stdout` and pytest's ``capsys`` capture
nothing from an argh CLI. cw takes ``out=None`` and looks up :data:`sys.stdout` *inside*
the call. That one line is what makes a cw CLI testable, and it is not a seam:

>>> import io
>>> buffer = io.StringIO()
>>> argh_egress(['first', 'second'], out=buffer)
0
>>> buffer.getvalue()
'first\\nsecond\\n'

``None`` prints nothing, but ``0``, ``False`` and ``''`` all do -- an argh rule worth
knowing, because it is the difference between a silent command and a command that prints a
blank line:

>>> buffer = io.StringIO()
>>> argh_egress(None, out=buffer), buffer.getvalue()
(0, '')
>>> buffer = io.StringIO()
>>> argh_egress(0, out=buffer), buffer.getvalue()
(0, '0\\n')
"""

import inspect
import json
import sys
from collections.abc import Iterable, Iterator, Mapping
from types import GeneratorType
from typing import Any, Optional, TextIO

__all__ = [
    "argh_egress",
    "iterable_egress",
    "json_egress",
    "write_lines",
    "confirm",
    "guard_no_coroutine",
]

#: How many spaces :func:`json_egress` indents by.
DFLT_JSON_INDENT = 2

#: The results :func:`argh_egress` writes one line each, rather than on one line. It is a
#: whitelist of concrete types, not the ``Iterable`` protocol, which is why a ``map`` object
#: prints its ``repr`` under ``cw.ARGH`` and its elements under ``cw.MODERN``.
ARGH_LINE_TYPES = (GeneratorType, list, tuple)

#: What :func:`iterable_egress` treats as a single value even though it is iterable.
NOT_LINES = (str, bytes, Mapping)

#: The answers :func:`confirm` accepts, lower-cased.
YES = ("y", "yes")
NO = ("n", "no")


def _stream(given: Optional[TextIO], fallback_name: str) -> TextIO:
    """``given``, or the named ``sys`` stream **looked up now** rather than at import.

    Every stream in this module goes through here. That is the whole implementation of
    "cw CLIs are testable and argh CLIs are not".
    """
    return getattr(sys, fallback_name) if given is None else given


def guard_no_coroutine(result: Any) -> None:
    """Raise an informative :class:`TypeError` if ``result`` is an un-awaited coroutine.

    v1 does not run event loops. argh's behaviour here is to print
    ``<coroutine object ...>`` and warn -- having never run the body -- which is worse than
    an error, so this is a deliberate, documented divergence from D2 rather than a gap in
    it. It lives at the *call site* (:func:`cw.cli.run`) instead of inside one egress, so
    that selecting a different egress cannot switch it off.

    >>> async def fetch(): ...
    >>> guard_no_coroutine(fetch())
    Traceback (most recent call last):
      ...
    TypeError: fetch returned a coroutine, and cw does not run event loops. Wrap the body
    in asyncio.run(...), or make the command synchronous.
    """
    if not inspect.iscoroutine(result):
        return
    name = getattr(getattr(result, "cr_code", None), "co_name", "the command")
    result.close()  # or Python warns "coroutine was never awaited" at collection time
    raise TypeError(
        f"{name} returned a coroutine, and cw does not run event loops. "
        "Wrap the body in asyncio.run(...), or make the command synchronous."
    )


def write_lines(
    lines: Iterable, /, *, out: Optional[TextIO] = None, flush: bool = True
) -> None:
    """Write ``str(line) + '\\n'`` for each item, **lazily**.

    Laziness is observable and is D2 row 18: a generator command that yields two lines and
    then prompts must have those two lines on screen before the prompt. So the iterable is
    never materialised, and each line is flushed as it is written (argh's ``always_flush``,
    which defaults on).

    >>> import io
    >>> buffer = io.StringIO()
    >>> write_lines(iter([1, None, 'three']), out=buffer)
    >>> buffer.getvalue()
    '1\\nNone\\nthree\\n'

    Laziness, shown rather than asserted -- the first line is on the stream before the
    second one has been computed:

    >>> buffer = io.StringIO()
    >>> def two_lines():
    ...     yield 'first'
    ...     print(f'(the stream already holds {buffer.getvalue()!r})')
    ...     yield 'second'
    >>> write_lines(two_lines(), out=buffer)
    (the stream already holds 'first\\n')
    """
    out = _stream(out, "stdout")
    flush_stream = getattr(out, "flush", None) if flush else None
    for line in lines:
        out.write(str(line))
        out.write("\n")
        if flush_stream is not None:
            flush_stream()


def argh_egress(
    result: Any, *, out: Optional[TextIO] = None, err: Optional[TextIO] = None
) -> int:
    """Seam 2's default: argh's type **whitelist**, footguns included.

    ``None`` writes nothing. A generator, ``list`` or ``tuple`` writes one line per item.
    *Everything else* -- including a ``dict``, a ``set`` and a ``map`` object -- writes one
    line, which is its ``str``.

    >>> import io
    >>> def show(result):
    ...     buffer = io.StringIO()
    ...     argh_egress(result, out=buffer)
    ...     return buffer.getvalue()
    >>> show(['a', 'b'])
    'a\\nb\\n'
    >>> show({'a': 1, 'b': 2})
    "{'a': 1, 'b': 2}\\n"
    >>> show(map(str, range(2)))                       # doctest: +ELLIPSIS
    '<map object at 0x...>\\n'
    >>> show(None)
    ''

    ``err`` is accepted and unused: it is part of the :data:`cw.Egress` contract, so that
    an egress which *does* write to the error stream is a drop-in replacement.
    """
    if result is None:
        return 0
    write_lines(result if isinstance(result, ARGH_LINE_TYPES) else [result], out=out)
    return 0


def iterable_egress(
    result: Any, *, out: Optional[TextIO] = None, err: Optional[TextIO] = None
) -> int:
    """:data:`cw.MODERN`'s egress: the ``Iterable`` protocol instead of argh's whitelist.

    A ``map``, a ``set``, a ``dict_keys`` -- anything iterable that is not a ``str``,
    ``bytes`` or ``Mapping`` -- writes one line per item.

    >>> import io
    >>> def show(result):
    ...     buffer = io.StringIO()
    ...     iterable_egress(result, out=buffer)
    ...     return buffer.getvalue()
    >>> show(map(str, range(2)))
    '0\\n1\\n'
    >>> show({'a': 1})
    "{'a': 1}\\n"
    >>> show('one line')
    'one line\\n'
    """
    if result is None:
        return 0
    lines = (
        [result]
        if isinstance(result, NOT_LINES) or not isinstance(result, Iterable)
        else result
    )
    write_lines(lines, out=out)
    return 0


def json_egress(
    result: Any,
    *,
    out: Optional[TextIO] = None,
    err: Optional[TextIO] = None,
    indent: int = DFLT_JSON_INDENT,
) -> int:
    """One JSON document, for a command whose result is data rather than lines.

    An iterator is materialised first (JSON has no streaming form), and anything JSON does
    not know is rendered with ``str`` rather than raising -- which is what
    ``t/xa/xa/cli.py``'s hand-rolled version does, and it is the behaviour a CLI wants.

    >>> import io
    >>> buffer = io.StringIO()
    >>> json_egress({'b': 1, 'a': [2, 3]}, out=buffer, indent=None)
    0
    >>> buffer.getvalue()
    '{"b": 1, "a": [2, 3]}\\n'

    >>> buffer = io.StringIO()
    >>> _ = json_egress(iter('ab'), out=buffer, indent=None)
    >>> buffer.getvalue()
    '["a", "b"]\\n'
    """
    if result is None:
        return 0
    out = _stream(out, "stdout")
    if isinstance(result, Iterator):
        result = list(result)
    out.write(json.dumps(result, indent=indent, default=str))
    out.write("\n")
    return 0


# --------------------------------------------------------------------------------------
# Interaction


def _prompt_for(action: str, default: Optional[bool]) -> str:
    """``'Delete it? (y/N)'`` -- argh's exact spelling, trailing space and all (there is
    none).

    >>> _prompt_for('Delete it', None), _prompt_for('Delete it', True)
    ('Delete it? (y/n)', 'Delete it? (Y/n)')
    """
    hint = {None: "y/n", True: "Y/n", False: "y/N"}[default]
    return f"{action}? ({hint})"


def _ask(prompt: str, *, in_: Optional[TextIO], out: Optional[TextIO]) -> str:
    """Show ``prompt``, read one line, strip the newline. ``EOFError`` at end of input.

    When neither stream is given this is :func:`input`, so an interactive user keeps
    readline's editing and history. When either is given the streams are used directly,
    which is what makes :func:`confirm` testable.
    """
    if in_ is None and out is None:
        return input(prompt)
    out = _stream(out, "stdout")
    out.write(prompt)
    out.flush()
    line = _stream(in_, "stdin").readline()
    if line == "":
        raise EOFError
    return line.rstrip("\n")


def confirm(
    action: str,
    /,
    *,
    default: Optional[bool] = None,
    skip: bool = False,
    in_: Optional[TextIO] = None,
    out: Optional[TextIO] = None,
) -> Optional[bool]:
    """A ``y/n`` prompt, reproducing ``argh.confirm`` -- the fleet's one interaction use.

    Args:
        action: What is about to happen, phrased as the subject of a question.
        default: What an empty or unrecognised answer means. ``None`` means "keep asking
            while the answer is empty, and return ``None`` if it is unrecognised".
        skip: Return ``default`` without prompting -- for a ``--yes`` flag.
        in_: Where the answer is read from. Defaults to :data:`sys.stdin`, resolved now.
        out: Where the prompt is written. Defaults to :data:`sys.stdout`, resolved now.

    >>> import io
    >>> out = io.StringIO()
    >>> confirm('Delete everything', in_=io.StringIO('y\\n'), out=out)
    True
    >>> out.getvalue()
    'Delete everything? (y/n)'

    A default is shown by which letter is capitalised, and is what an empty answer means:

    >>> confirm('Proceed', default=True, in_=io.StringIO('\\n'), out=io.StringIO())
    True
    >>> confirm('Proceed', default=False, in_=io.StringIO('\\n'), out=io.StringIO())
    False

    ``skip=True`` is how a ``--yes`` flag is spelt; nothing is read and nothing is written:

    >>> confirm('Proceed', default=True, skip=True) is True
    True

    Unlike the streams, the *questions* are not a seam: this is a y/n prompt, and anything
    richer is the caller's own code.
    """
    if skip:
        return default
    prompt = _prompt_for(action, default)
    while True:
        answer = _ask(prompt, in_=in_, out=out).lower()
        if answer in YES:
            return True
        if answer in NO:
            return False
        if answer == "" and default is None:
            continue  # argh keeps asking rather than returning an ambiguous None
        return default
