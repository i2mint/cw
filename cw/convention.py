"""What cw's defaults ARE, as one frozen value per context.

``config`` and ``convention`` are the fleet's existing pair of words -- ``streamlitfront``'s
``mk_app(objs, config=None, convention=None)`` already uses them with exactly these
meanings, so cw rhymes with it rather than inventing a third vocabulary:

``convention``
    *What the defaults are.* A frozen dataclass, swapped per **context** -- a repo, a
    house style, the whole fleet. Rebinding it is how a project's per-call ``config``
    entries shrink to nothing.

``config``
    *This call's particulars.* A plain mapping, swapped per **call**.

Two values ship:

>>> ARGH.naming, ARGH.short_flags, ARGH.resolve_hints
('by_name_if_has_default', True, False)
>>> MODERN.naming, MODERN.resolve_hints, MODERN.hints_when_declared
('by_name_if_kwonly', True, True)

:data:`ARGH` is the default everywhere, and it reproduces argh 0.31.3 including the parts
nobody likes. Every improvement is opt-in, and opting in is **one** act:

>>> import functools, cw
>>> dispatch = functools.partial(cw.dispatch, convention=MODERN)  # doctest: +SKIP

That is the whole mechanism -- there is no ``cw.bind`` and no ``set_dispatch_defaults``.
Anything in between is a :func:`dataclasses.replace`:

>>> import dataclasses
>>> half_way = dataclasses.replace(ARGH, resolve_hints=True)
>>> half_way.resolve_hints, half_way.naming
(True, 'by_name_if_has_default')

Seam 2 (``egress``) becomes a field here the moment ``cw.egress`` exists; it is left out
rather than declared as a ``None`` that would have to mean two things at once.

``decode`` is a field rather than only a ``dispatch`` keyword for one reason: if ``MODERN``
did not carry its own, flipping to it would need a coordinated two-keyword edit at every
call site, and a seam whose replacement touches every caller is in the wrong place.
"""

import dataclasses

from cw.base import Decode
from cw.grammar import (
    BY_NAME_IF_HAS_DEFAULT,
    BY_NAME_IF_KWONLY,
    argh_decode,
    modern_decode,
)

__all__ = [
    "Convention",
    "ARGH",
    "MODERN",
    "BY_NAME_IF_HAS_DEFAULT",
    "BY_NAME_IF_KWONLY",
]


@dataclasses.dataclass(frozen=True)
class Convention:
    """The grammar switches, as one hashable value.

    Every field is read somewhere in ``cw.grammar`` or ``cw.commands``; a field that
    changed nothing would be exactly the speculative generality this design refuses.

    >>> Convention() == ARGH
    True
    >>> hash(Convention()) == hash(ARGH)
    True
    """

    #: ``BY_NAME_IF_HAS_DEFAULT`` (argh's legacy rule: a default makes it an option) or
    #: ``BY_NAME_IF_KWONLY`` (keyword-only makes it an option; a default only makes a
    #: positional optional).
    naming: str = BY_NAME_IF_HAS_DEFAULT
    #: Infer ``-x`` from a parameter's first character -- suppressed when two parameters
    #: share one, and always lost to ``--help`` for ``h``.
    short_flags: bool = True
    #: ``a_b`` becomes the command ``a-b``.
    hyphenate_commands: bool = True
    #: ``git_ops`` becomes the group ``git-ops``. argh leaves a group name verbatim.
    hyphenate_groups: bool = False
    #: Give every argument the help string ``'%(default)s'``.
    default_in_help: bool = True
    #: Keep inferring from type hints even when a parameter has been overridden. argh
    #: switches hint inference off for the *whole function* as soon as one ``@arg``
    #: appears; ADR-0003 extends "overridden" to cover ``config`` entries too.
    hints_when_declared: bool = False
    #: Resolve annotations with :func:`typing.get_type_hints` instead of reading
    #: ``__annotations__`` raw. ``False`` reproduces argh's blindness to PEP 563, under
    #: which every annotation is a string and therefore infers nothing.
    resolve_hints: bool = False
    #: Seam 1: ``(Parameter, hint) -> add_argument kwargs | callable | None``.
    decode: Decode = argh_decode


#: cw's default in every entry point: argh 0.31.3's grammar, footguns included.
ARGH = Convention()

#: The same machinery with the improvements switched on. ``naming`` follows parameter
#: kind rather than the presence of a default, annotations are actually resolved and
#: still consulted when a parameter is overridden, groups are hyphenated like commands,
#: and ``decode`` additionally understands ``Optional[X]``, ``Enum`` and ``pathlib``.
MODERN = Convention(
    naming=BY_NAME_IF_KWONLY,
    hyphenate_groups=True,
    hints_when_declared=True,
    resolve_hints=True,
    decode=modern_decode,
)
