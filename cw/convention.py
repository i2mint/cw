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
>>> ARGH.decode.__name__, ARGH.egress.__name__
('argh_decode', 'argh_egress')
>>> MODERN.naming, MODERN.resolve_hints, MODERN.hints_when_declared
('by_name_if_kwonly', True, True)
>>> MODERN.decode.__name__, MODERN.egress.__name__
('modern_decode', 'iterable_egress')

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

``decode`` and ``egress`` -- two of cw's three seams -- are fields here rather than only
``dispatch`` keywords, for one reason: if ``MODERN`` did not carry its own, flipping to it
would need a coordinated three-keyword edit at every call site, and a seam whose
replacement touches every caller is in the wrong place. So ``dispatch(decode=...)`` and
``dispatch(egress=...)`` default to ``None``, meaning *take the convention's*.

**The merge ladder** -- what a convention presides over -- is four tiers, later wins::

    1. signature inference     kind, default, name, flag spellings
    2. hint inference          convention.decode(param, hint)
    3. function attribute      func._cw['params'][param]     (cw.compat.arg writes it)
    4. config                  config[...][param]            (this call's particulars)

Tiers 3 and 4 both count as "declared", so either one switches tier 2 off for the *whole*
function unless ``hints_when_declared`` says otherwise; and the merge is argh's
field-specific one, not ``dict.update`` (ADR-0003). It is implemented once, as
:func:`cw.grammar.specs_for_function`, and lives there rather than here because it is the
only place that knows what a :class:`cw.grammar.ArgSpec` is. There is no second copy.

``formatter_class`` is deliberately **not** a field (ADR-0006): it is already an
``argparse.ArgumentParser`` keyword, and cw invents no vocabulary for anything argparse
already names. :func:`cw.mk_parser` defaults it to :class:`cw.ArghHelpFormatter` and passes
whatever you give it straight through, to the top parser and to every subparser.
"""

import dataclasses

from cw.base import Decode, Egress
from cw.egress import argh_egress, iterable_egress
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
    #: Seam 2: ``(result, *, out, err) -> exit code``.
    egress: Egress = argh_egress


#: cw's default in every entry point: argh 0.31.3's grammar, footguns included.
ARGH = Convention()

#: The same machinery with the improvements switched on. ``naming`` follows parameter
#: kind rather than the presence of a default, annotations are actually resolved and
#: still consulted when a parameter is overridden, groups are hyphenated like commands,
#: ``decode`` additionally understands ``Optional[X]``, ``Enum`` and ``pathlib``, and
#: ``egress`` iterates anything iterable rather than argh's three-type whitelist.
#:
#: ``default_in_help`` stays ``True`` here (ADR-0004 rule 4): docstring-derived per-parameter
#: help is not in v1, so turning the default off would leave an undocumented flag with an
#: empty help column -- strictly worse than argh, in the value the fleet is told to adopt.
MODERN = Convention(
    naming=BY_NAME_IF_KWONLY,
    hyphenate_groups=True,
    hints_when_declared=True,
    resolve_hints=True,
    decode=modern_decode,
    egress=iterable_egress,
)
