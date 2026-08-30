"""Namespace to call: the lines that honour ``/``, ``*args``, ``*`` and ``**kwargs``.

This is the one job ``i2.Sig.mk_args_and_kwargs`` was going to buy, and it is a page of
:mod:`inspect`. argh does the same job in its own dispatcher without i2, and so does cw:
split ``POSITIONAL_ONLY`` and ``POSITIONAL_OR_KEYWORD`` into positional arguments, put
``KEYWORD_ONLY`` into a keyword dict, extend the positionals with ``VAR_POSITIONAL``, and
collect whatever is left over for ``VAR_KEYWORD``.

:func:`mk_ingress` returns a callable whose contract is ``{name: value} -> (args, kwargs)``
-- deliberately the *same* contract as ``i2.wrapper.Ingress``, so that an i2 ``Ingress``
remains a drop-in substitute for anyone who wants one. The contract is honoured; the
import is not paid. (It is reachable as ``cw.ingress.mk_ingress`` and is deliberately not
re-exported from the ``cw`` facade: nobody has asked for it as a public name.)

>>> def move(source, /, destination='.', *extra, force=False, **options):
...     ...
>>> ingress = mk_ingress(move)
>>> ingress({'source': 'a', 'destination': 'b', 'extra': ['c', 'd'],
...          'force': True, 'dry_run': 'yes'})
(('a', 'b', 'c', 'd'), {'force': True, 'dry_run': 'yes'})

Note what that shows and what it hides. ``source`` is positional-only and ``destination``
is not, yet both are passed positionally -- because a parameter's *kind* decides how it is
called, while :mod:`cw.grammar` decides, separately, whether it is spelt ``dest`` or
``--destination`` on the command line. And ``dry_run`` reaches ``**options`` only because
something put it in the mapping; under :data:`cw.ARGH` the parser never adds an argument
for ``**options`` at all, so in a real dispatch that key is simply never there.
"""

import inspect
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

__all__ = ["mk_ingress"]

#: Parameter kinds that are passed by position, whatever their command-line spelling.
POSITIONAL_KINDS = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


class IngressError(KeyError):
    """A parsed namespace cannot be turned into a call to this function.

    In practice this means a parameter with no default was hidden from the command line
    (``config={'x': cw.HIDE}``), so nothing supplies it and the function's own signature
    cannot either.
    """

    def __str__(self) -> str:  # KeyError's repr()s its argument; this is a message
        return self.args[0]


class _Kinds:
    """``func``'s parameters, bucketed by kind once, at parser-build time.

    Everything :func:`mk_ingress` needs to know about a signature, computed before the
    first command line is ever seen -- ``inspect.signature`` is the expensive part and it
    happens once per command, not once per call.
    """

    __slots__ = (
        "name",
        "positional",
        "keyword_only",
        "var_positional",
        "var_keyword",
        "defaults",
    )

    def __init__(self, func: Any):
        parameters = list(inspect.signature(func).parameters.values())
        self.name = getattr(func, "__name__", repr(func))
        self.positional: List[str] = [
            p.name for p in parameters if p.kind in POSITIONAL_KINDS
        ]
        self.keyword_only: List[str] = [
            p.name for p in parameters if p.kind == p.KEYWORD_ONLY
        ]
        self.var_positional: Optional[str] = next(
            (p.name for p in parameters if p.kind == p.VAR_POSITIONAL), None
        )
        self.var_keyword: bool = any(p.kind == p.VAR_KEYWORD for p in parameters)
        self.defaults: Dict[str, Any] = {
            p.name: p.default for p in parameters if p.default is not p.empty
        }

    @property
    def named(self) -> frozenset:
        """Every parameter name the signature spells out, so leftovers can be spotted."""
        return frozenset(
            self.positional
            + self.keyword_only
            + ([self.var_positional] if self.var_positional else [])
        )


def mk_ingress(
    func: Any, /, *, codecs: Optional[Mapping[str, Callable[[Any], Any]]] = None
) -> Callable[[Mapping[str, Any]], Tuple[tuple, dict]]:
    """Build ``{param_name: value} -> (args, kwargs)`` for one function.

    Args:
        func: The command. Inspected once, here, not on every call.
        codecs: Optional per-parameter post-parse decoders, keyed by parameter name.
            :mod:`cw.cli` fills this from each :class:`cw.grammar.ArgSpec`'s ``codec``, so
            that the promotion of a bare callable to a :class:`cw.Codec` happens in exactly
            one place. This is the "ingress site" of the two conversion sites -- the other
            is argparse's ``type=``, and which one a conversion runs at is decided per
            parameter by which key you wrote.

    Returns:
        The ingress: a callable taking one mapping and returning ``(args, kwargs)``.

    Four rules, each of which is observable, and three of which are argh's:

    A ``*args`` parameter re-expands by extension rather than being passed as a tuple,
    which is why ``def estimate(*agents)`` needs no configuration at all:

    >>> mk_ingress(lambda *agents: None)({'agents': ['a', 'b']})
    (('a', 'b'), {})

    A parameter absent from the mapping falls back to the function's own default. That is
    what makes ``cw.HIDE`` work: the argument is gone from the command line, and the
    function still receives the value it was partial-ed with.

    >>> def packages(project=None, *, config_type='setup.cfg'): ...
    >>> mk_ingress(packages)({'project': 'p'})
    (('p',), {'config_type': 'setup.cfg'})

    A parameter that is neither supplied nor defaulted is an error naming the likely
    cause, rather than a :class:`TypeError` from deep inside the call:

    >>> mk_ingress(lambda pool: None)({})
    Traceback (most recent call last):
      ...
    cw.ingress.IngressError: <lambda>: no value for parameter 'pool', and it has no
    default. Was it hidden with cw.HIDE?

    Leftover keys go to ``**kwargs`` when the function takes it, and are dropped when it
    does not -- and under :data:`cw.ARGH` nothing ever creates such a key, because argh
    contributes no command-line argument for ``**kwargs`` at all:

    >>> mk_ingress(lambda a, **rest: None)({'a': 1, 'extra': 2})
    ((1,), {'extra': 2})
    >>> mk_ingress(lambda a: None)({'a': 1, 'extra': 2})
    ((1,), {})
    """
    kinds = _Kinds(func)
    codecs = dict(codecs or {})
    named = kinds.named

    def ingress(values: Mapping[str, Any]) -> Tuple[tuple, dict]:
        if codecs:
            values = {
                name: codecs[name](value) if name in codecs else value
                for name, value in values.items()
            }

        def value_of(name: str) -> Any:
            if name in values:
                return values[name]
            if name in kinds.defaults:
                return kinds.defaults[name]
            raise IngressError(
                f"{kinds.name}: no value for parameter {name!r}, and it has no default. "
                "Was it hidden with cw.HIDE?"
            )

        args = [value_of(name) for name in kinds.positional]
        if kinds.var_positional:
            args.extend(values.get(kinds.var_positional) or ())
        kwargs = {name: value_of(name) for name in kinds.keyword_only}
        if kinds.var_keyword:
            kwargs.update(
                (name, value)
                for name, value in values.items()
                if name not in named and not name.startswith("_")
            )
        return tuple(args), kwargs

    return ingress
