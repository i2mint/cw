"""How a Python signature becomes command-line arguments.

This is cw's riskiest module and its most opinionated one: it reproduces argh 0.31.3's
signature-to-``argparse`` inference exactly, footguns included, because a CLI that reads
*almost* like the one it replaces is worse than one that reads nothing like it.

argh arrives at its grammar through two uncoordinated code paths -- an annotation guesser
(``TypingHintArgSpecGuesser``) and a default-value guesser
(``guess_extra_parser_add_argument_spec_kwargs``) -- which collide on ``bool`` and are
reconciled by two copy-pasted hand-patches. Here they are **one function with one
precedence order**: :func:`specs_for_function`.

Three things this module deliberately does *not* do:

* It never imports :mod:`argparse`. It produces :class:`ArgSpec` values -- plain data --
  and :meth:`ArgSpec.add_argument_args` turns one into the ``(args, kwargs)`` of an
  ``add_argument`` call. ``cw.cli`` is the only module that makes that call.
* It has no notion of a command tree, a parser, or a namespace. One function in, a list
  of arguments out.
* It hardcodes no policy. Every switch is read off the ``convention`` argument, so
  ``convention=cw.MODERN`` is one act that changes all of them at once.

The whole grammar in one look:

>>> def greet(name, greeting='hello', *, shout=False, times: int = 1):
...     'Say hello.'
>>> for spec in specs_for_function(greet):
...     print(spec.param_name, spec.flags, spec.add_argument_kwargs())
name ['name'] {'help': '%(default)s'}
greeting ['-g', '--greeting'] {'default': 'hello', 'type': <class 'str'>, 'help': '%(default)s'}
shout ['-s', '--shout'] {'default': False, 'action': 'store_true', 'help': '%(default)s'}
times ['-t', '--times'] {'default': 1, 'type': <class 'int'>, 'help': '%(default)s'}

Read that output slowly, because every line of it is an argh compatibility decision:
``greeting`` has a default so it becomes an *option* (``BY_NAME_IF_HAS_DEFAULT``);
``shout=False`` becomes ``store_true`` (and ``shout=True`` would become ``store_false``);
the short flags come from first characters and would vanish entirely if two parameters
shared one; and every help string is ``'%(default)s'``, which
:class:`cw.base.ArghHelpFormatter` renders as ``repr(default)``.
"""

import dataclasses
import enum
import inspect
import pathlib
import typing
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from cw.base import HIDE, MISSING, DFLT_HELP, Codec

__all__ = [
    "ArgSpec",
    "GrammarError",
    "argh_decode",
    "modern_decode",
    "cli_name",
    "command_name",
    "infer_specs",
    "specs_for_function",
    "BY_NAME_IF_HAS_DEFAULT",
    "BY_NAME_IF_KWONLY",
    "ZERO_OR_MORE",
    "OPTIONAL",
]


# --------------------------------------------------------------------------------------
# Vocabulary
#
# These are argparse's own spellings, repeated here as constants rather than imported,
# because this module must not import argparse (see the module docstring).

#: ``argparse.ZERO_OR_MORE`` -- "any number of values, including none".
ZERO_OR_MORE = "*"

#: ``argparse.OPTIONAL`` -- "one value, or none".
OPTIONAL = "?"

#: A parameter is named on the command line iff it has a default value (argh's legacy
#: policy, and the one every fleet script was written against).
BY_NAME_IF_HAS_DEFAULT = "by_name_if_has_default"

#: A parameter is named on the command line iff it is keyword-only. Position and
#: optionality become independent, which is what most people expect.
BY_NAME_IF_KWONLY = "by_name_if_kwonly"

#: The types argh's annotation guesser recognises as scalars. Nothing more, because argh
#: has nothing more.
BASIC_TYPES = (str, int, float, bool)

#: ``add_argument`` kwargs that :meth:`ArgSpec.update` merges field-by-field rather than
#: by ``dict.update`` -- see :class:`ArgSpec`.
FIELD_MERGED_KEYS = ("required", "nargs", "default")

_UNION_TYPES: tuple = (typing.Union,)
try:  # pragma: no cover - py>=3.10 always has it; the fallback is for older readers
    from types import UnionType

    _UNION_TYPES = (typing.Union, UnionType)
except ImportError:  # pragma: no cover
    pass

_NONE_TYPE = type(None)


class GrammarError(ValueError):
    """A signature and its overrides cannot be reconciled into a CLI.

    Raised eagerly, at parser-construction time, so a mis-keyed ``config`` entry is a
    startup failure with a message rather than a flag that silently never appears.
    """


# --------------------------------------------------------------------------------------
# The unit of the grammar


@dataclasses.dataclass
class ArgSpec:
    """One command-line argument, as data, before argparse ever sees it.

    ``required``, ``default`` and ``nargs`` are held in their own fields rather than in
    ``extra`` because argh merges them by rules that ``dict.update`` does not have (see
    :meth:`update`), and reproducing that merge is what makes ``--help`` byte-identical.

    >>> spec = ArgSpec('verbose', ['-v', '--verbose'], default=False)
    >>> spec.add_argument_args()
    (('-v', '--verbose'), {'default': False})
    >>> spec.is_positional
    False
    """

    #: The name of the Python parameter this argument feeds.
    param_name: str
    #: Option strings (``['-v', '--verbose']``) or a single positional CLI name.
    flags: List[str]
    #: ``add_argument(required=...)``; ``MISSING`` means "do not pass it".
    required: Any = MISSING
    #: ``add_argument(default=...)``; ``MISSING`` means "do not pass it".
    default: Any = MISSING
    #: ``add_argument(nargs=...)``; ``None`` means "do not pass it".
    nargs: Optional[str] = None
    #: Every other ``add_argument`` keyword: ``type``, ``action``, ``choices``, ``help``...
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)
    #: The optional post-parse decoder (``cw.ingress``'s site, not argparse's ``type=``).
    codec: Optional[Codec] = None
    #: Set by a ``cw.HIDE`` override: keep the parameter, drop the CLI argument.
    hidden: bool = False
    #: argcomplete's per-argument completer. Not an ``add_argument`` keyword -- argparse
    #: rejects it -- so it travels here and ``cw.cli`` assigns it to the created action,
    #: which is where ``argcomplete`` looks for it.
    completer: Any = None

    @property
    def is_positional(self) -> bool:
        """Is this a positional argument (as opposed to an option)?

        >>> ArgSpec('x', ['x']).is_positional
        True
        """
        return not self.flags[0].startswith("-")

    def update(self, other: "ArgSpec") -> None:
        """Merge an override into this spec, by argh's rules (``argh/dto.py:33-50``).

        Four rules, none of which is ``dict.update``, and each of which is observable:

        * ``flags`` **append**: the inferred spellings survive and the declared ones are
          added after them if new. This is why theremin's ``@arg('--synth', '-s')`` on a
          parameter whose short flag was suppressed renders ``--synth [SYNTH], -s [SYNTH]``
          -- long first -- with no special case anywhere.
        * ``required`` and ``default`` are taken only when the override *has* one.
        * ``nargs`` is taken only when the override's is **truthy**, so there is no way to
          unset an inferred ``nargs`` (argh has no spelling for it either; see ADR-0003).
        * everything else is a plain ``dict.update``.

        >>> inferred = ArgSpec('synth', ['--synth'], default='sine')
        >>> inferred.update(ArgSpec('synth', ['--synth', '-s'], nargs='?'))
        >>> inferred.flags
        ['--synth', '-s']
        """
        for flag in other.flags:
            if flag not in self.flags:
                self.flags.append(flag)
        if other.required is not MISSING:
            self.required = other.required
        if other.default is not MISSING:
            self.default = other.default
        if other.nargs:
            self.nargs = other.nargs
        if other.codec is not None:
            self.codec = other.codec
        if other.completer is not None:
            self.completer = other.completer
        self.extra.update(other.extra)

    def add_argument_kwargs(self) -> Dict[str, Any]:
        """The ``**kwargs`` half of the ``add_argument`` call.

        ``extra`` is applied last, which reproduces argh's
        ``dict(kwargs, **other_add_parser_kwargs)`` -- including the quirk that a ``nargs``
        guessed from a list-valued default overrides an explicitly declared one.
        """
        kwargs: Dict[str, Any] = {}
        if self.required is not MISSING:
            kwargs["required"] = self.required
        if self.default is not MISSING:
            kwargs["default"] = self.default
        if self.nargs:
            kwargs["nargs"] = self.nargs
        return dict(kwargs, **self.extra)

    def add_argument_args(self) -> tuple:
        """The full ``(args, kwargs)`` of the ``add_argument`` call this spec describes.

        A positional is registered under its **command-line** name, hyphens and all --
        exactly as argh does -- because argparse reads that one string twice, and the two
        readings cannot be separated: it is the ``{a,b}``-or-``project-dir`` displayed in
        ``usage:`` *and* the name in ``error: argument project-dir: ...``. Synthesising a
        ``metavar`` instead would win the second reading and lose the first, silently
        turning ``{a,b}`` into ``project-dir`` for any hyphenated positional carrying
        ``choices``.

        The price is a ``dest`` with a hyphen in it, which no Python call can use.
        :attr:`argparse_dest` names it and :mod:`cw.cli` renames it back on the way into
        the call -- one dictionary lookup, in one place.

        >>> spec = ArgSpec('project_dir', ['project-dir'])
        >>> spec.add_argument_args()
        (('project-dir',), {})
        >>> spec.argparse_dest
        'project-dir'
        """
        kwargs = self.add_argument_kwargs()
        if self.is_positional:
            return (self.flags[0],), kwargs
        return tuple(self.flags), kwargs

    @property
    def argparse_dest(self) -> str:
        """The namespace key argparse will store this argument under.

        argparse derives it from the first long option (``--project-dir`` ->
        ``project_dir``) or, for a positional, from the name itself -- hyphens intact.

        >>> ArgSpec('project_dir', ['-p', '--project-dir']).argparse_dest
        'project_dir'
        >>> ArgSpec('project_dir', ['project-dir']).argparse_dest
        'project-dir'
        """
        if "dest" in self.extra:
            return self.extra["dest"]
        if self.is_positional:
            return self.flags[0]
        long = next(
            (flag for flag in self.flags if flag.startswith("--")), self.flags[0]
        )
        return long.lstrip("-").replace("-", "_")

    @classmethod
    def from_override(cls, param_name: str, override: Mapping[str, Any]) -> "ArgSpec":
        """Build a spec from an override leaf -- ``add_argument`` kwargs plus cw's three.

        The three cw additions are ``flags`` (explicit option strings, hyphenated the way
        argh hyphenates ``@arg``'s), ``codec`` (the post-parse decoder), and the whole
        leaf being :data:`cw.HIDE`, which :func:`specs_for_function` handles before it
        gets here.

        >>> ArgSpec.from_override('synth', {'flags': ['-s'], 'nargs': '?'})
        ArgSpec(param_name='synth', flags=['-s'], required=cw.MISSING, default=cw.MISSING,
                nargs='?', extra={}, codec=None, hidden=False, completer=None)
        """
        if not isinstance(override, Mapping):
            raise GrammarError(
                f"the override for {param_name!r} must be a mapping of add_argument "
                f"keyword arguments (or cw.HIDE), not {override!r}"
            )
        rest = dict(override)
        flags = [cli_name(flag) for flag in rest.pop("flags", ())]
        codec = rest.pop("codec", None)
        if codec is not None and not isinstance(codec, Codec):
            codec = Codec(decode=codec)
        # argcomplete's own keyword, which argparse's add_argument rejects. argh pops it
        # the same way and assigns it to the action it just created.
        completer = rest.pop("completer", None)
        spec = cls(param_name=param_name, flags=flags, codec=codec, completer=completer)
        # argh's `make_from_kwargs` POPS these three out of the kwargs dict so that
        # `update` can merge them by their own rules. Same here.
        for key in FIELD_MERGED_KEYS:
            if key in rest:
                setattr(spec, key, rest.pop(key))
        spec.extra = rest
        return spec


# --------------------------------------------------------------------------------------
# Seam 1: decode -- a resolved type hint becomes add_argument kwargs


def argh_decode(param: inspect.Parameter, hint: Any) -> Mapping[str, Any]:
    """Seam 1's default: argh's annotation guesser, if-branch for if-branch.

    A type implies more than a converter, which is why this returns a mapping of
    ``add_argument`` kwargs rather than a callable: ``list[str]`` implies ``nargs='*'``,
    ``Literal['a', 'b']`` implies ``choices``, ``Optional[int]`` implies
    ``required=False``. The covered set is exactly argh's -- ``str``, ``int``, ``float``,
    ``bool``, ``list``, ``list[T]``, ``Literal[...]`` and ``Union``/``Optional`` -- and
    nothing else, because argh recognises nothing else.

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
    """
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)

    if hint in BASIC_TYPES:
        return {"type": hint}
    if hint in (list, typing.List):
        return {"nargs": ZERO_OR_MORE}
    if origin is typing.Literal:
        return {"choices": args, "type": type(args[0])}
    if any(origin is union for union in _UNION_TYPES):
        return _decode_union(args)
    if origin is list:
        guessed: Dict[str, Any] = {"nargs": ZERO_OR_MORE}
        if args and args[0] in BASIC_TYPES:
            guessed["type"] = args[0]
        return guessed
    return {}


def _decode_union(args: Sequence[Any]) -> Dict[str, Any]:
    """argh's ``Union`` branch: the FIRST member decides, ``None`` makes it optional."""
    guessed: Dict[str, Any] = {}
    first = args[0]
    if first in BASIC_TYPES:
        guessed["type"] = first
    if first in (list, typing.List):
        guessed["nargs"] = ZERO_OR_MORE
    if first is not typing.List and typing.get_origin(first) is list:
        guessed["nargs"] = ZERO_OR_MORE
        item_args = typing.get_args(first)
        if item_args and item_args[0] in BASIC_TYPES:
            guessed["type"] = item_args[0]
    if _NONE_TYPE in args:
        guessed["required"] = False
    return guessed


def modern_decode(param: inspect.Parameter, hint: Any) -> Mapping[str, Any]:
    """Seam 1's shipped alternative: ``Optional[X]``, ``Enum`` and ``pathlib`` support.

    Composition is fall-through, not a registry: three ``if``\\ s and then
    ``return argh_decode(param, hint)``. Nothing to register, nothing to order.

    ``Optional[X]`` is unwrapped to ``X`` rather than read as "the first member wins",
    which is the single most useful difference: under argh, ``n: int | None = None``
    quietly becomes ``nargs='?'``.

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

    The help column advertises what the converter accepts, rather than member ``repr``\\ s
    the converter would reject:

    >>> decoded['metavar']
    '{RED}'
    """
    hint = _unwrap_optional(hint)
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        # `choices` must hold the CONVERTED values (argparse checks after `type` runs), so
        # it holds members -- but members render as `Col.RED`, which the converter would
        # then reject. `metavar` decides what is displayed, so it advertises the member
        # names, which are exactly what may be typed.
        return {
            "type": _enum_by_name_then_value(hint),
            "choices": tuple(hint),
            "metavar": "{" + ",".join(member.name for member in hint) + "}",
        }
    if isinstance(hint, type) and issubclass(hint, pathlib.PurePath):
        return {"type": pathlib.Path}
    return argh_decode(param, hint)


def _unwrap_optional(hint: Any) -> Any:
    """``Optional[X]`` -> ``X``; anything else unchanged."""
    if any(typing.get_origin(hint) is union for union in _UNION_TYPES):
        rest = [arg for arg in typing.get_args(hint) if arg is not _NONE_TYPE]
        if len(rest) == 1:
            return rest[0]
    return hint


def _enum_by_name_then_value(enum_class: type) -> Callable[[str], Any]:
    """A ``type=`` converter reading an ``Enum`` by member name, then by value."""

    def decode(token: str) -> Any:
        try:
            return enum_class[token]
        except KeyError:
            return enum_class(token)

    # argparse interpolates %(type)s from `type.__name__`, and the help formatter
    # replaces any object having one; borrow the enum's so both read well.
    decode.__name__ = enum_class.__name__
    return decode


def _as_add_argument_kwargs(decoded: Any) -> Dict[str, Any]:
    """Normalise a ``decode`` return value: ``None`` | callable | Mapping -> kwargs."""
    if decoded is None:
        return {}
    if isinstance(decoded, Mapping):
        return dict(decoded)
    if callable(decoded):
        return {"type": decoded}
    raise GrammarError(
        f"a decode function must return None, a callable or a mapping of add_argument "
        f"keyword arguments; got {decoded!r}"
    )


# --------------------------------------------------------------------------------------
# Naming


def cli_name(name: str, /, *, hyphenate: bool = True) -> str:
    """The one name-mangling rule, applied to commands, groups, flags and config keys.

    ADR-0004 rule 2: derived names and the keys you address them by must go through the
    *same* function, or a ``config`` written in one spelling silently misses a command
    named in the other.

    >>> cli_name('git_ops'), cli_name('git_ops', hyphenate=False)
    ('git-ops', 'git_ops')
    """
    return name.replace("_", "-") if hyphenate else name


def command_name(func: Any, /, *, hyphenate: bool = True) -> str:
    """The command word for a callable: its ``__name__``, with ``_`` becoming ``-``.

    >>> def pack_go(): ...
    >>> command_name(pack_go)
    'pack-go'

    Anything without a ``__name__`` -- a ``functools.partial``, a callable instance --
    has no name to derive, and guessing one is how you ship the wrong CLI:

    >>> import functools
    >>> command_name(functools.partial(pack_go))
    Traceback (most recent call last):
      ...
    TypeError: cannot derive a command name from functools.partial(...): it has no
    __name__. Pass it explicitly with the mapping form: cw.dispatch({"my-command": obj})
    """
    name = getattr(func, "__name__", None)
    if name is None:
        raise TypeError(
            f"cannot derive a command name from {func!r}: it has no __name__. "
            'Pass it explicitly with the mapping form: cw.dispatch({"my-command": obj})'
        )
    return cli_name(name, hyphenate=hyphenate)


# --------------------------------------------------------------------------------------
# Tier 1 + 2: the signature, and the hints


def _short_flag_collisions(signature: inspect.Signature) -> frozenset:
    """First characters shared by two or more *named* parameters.

    argh's rule, and the one that surprises everyone: a collision suppresses the short
    flag for **both** parameters rather than giving it to the first. That is why
    ``wads pack populate_pkg_dir``'s 34 parameters have almost no short flags, and why it
    is data rather than a heuristic -- adding a parameter can silently remove another
    parameter's flag.

    Note the set is computed from every parameter that *could* be named (has a default,
    or is keyword-only), regardless of whether the naming policy actually names it.
    """
    named = [
        p.name
        for p in signature.parameters.values()
        if p.default is not p.empty or p.kind == p.KEYWORD_ONLY
    ]
    first_chars = [name[0] for name in named]
    return frozenset(char for char in set(first_chars) if first_chars.count(char) > 1)


def _flag_spellings(param_name: str, collisions: frozenset, short_flags: bool) -> tuple:
    """``('name-with-hyphens',), ('-n', '--name-with-hyphens')`` for one parameter."""
    hyphenated = cli_name(param_name)
    positional = [hyphenated]
    if short_flags and param_name[0] not in collisions:
        options = [f"-{hyphenated[0]}", f"--{hyphenated}"]
    else:
        options = [f"--{hyphenated}"]
    return positional, options


def _hints_of(func: Any, *, resolve: bool) -> Dict[str, Any]:
    """The annotations a decode function will be shown.

    ``resolve=False`` is argh's behaviour: read ``__annotations__`` raw, which under
    ``from __future__ import annotations`` means every hint is a *string* and therefore
    matches nothing in the if-chain. That silently disables argh's coercion in roughly a
    third of the fleet's annotated CLI files; it is reproduced, not fixed, because D2 says
    improvements are opt-in (``convention=cw.MODERN`` resolves them).
    """
    raw = dict(getattr(func, "__annotations__", None) or {})
    if not resolve:
        return raw
    try:
        return typing.get_type_hints(func)
    except (NameError, TypeError):
        # An unresolvable forward reference. Degrade to argh's raw reading rather than
        # failing to build a CLI over an annotation nobody asked us to resolve.
        return raw


def infer_specs(
    func: Any,
    /,
    *,
    convention=None,
    decode=None,
    use_hints: bool = True,
) -> List[ArgSpec]:
    """Tiers 1 and 2 of the ladder: the signature, then its type hints.

    The two argh code paths this replaces disagree about ``bool``, and argh patches the
    disagreement twice, in two branches, with the same three lines. Here the annotation
    result and the signature result meet in one place and the ``bool`` rule is stated
    once: a hint of ``bool`` on a parameter with a ``bool`` default is dropped, because
    ``type=bool`` and ``action='store_true'`` cannot both be passed to ``add_argument``.

    >>> def f(path, *, verbose: bool = False, tags: list = None):
    ...     ...
    >>> [(s.param_name, s.flags, s.extra) for s in infer_specs(f)]
    [('path', ['path'], {}),
     ('verbose', ['-v', '--verbose'], {}),
     ('tags', ['-t', '--tags'], {'nargs': '*'})]
    """
    convention = convention if convention is not None else _default_convention()
    decode = decode if decode is not None else convention.decode
    signature = inspect.signature(func)
    collisions = _short_flag_collisions(signature)
    hints = _hints_of(func, resolve=convention.resolve_hints) if use_hints else {}
    by_name = convention.naming == BY_NAME_IF_HAS_DEFAULT
    specs: List[ArgSpec] = []

    for param in signature.parameters.values():
        positional, options = _flag_spellings(
            param.name, collisions, convention.short_flags
        )
        default = param.default if param.default is not param.empty else MISSING
        extra: Dict[str, Any] = {}
        if param.name in hints:
            extra = _as_add_argument_kwargs(decode(param, hints[param.name]))

        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            spec = ArgSpec(param.name, list(positional), default=default, extra=extra)
            if default is not MISSING:
                if by_name:
                    spec.flags = list(options)
                else:
                    spec.nargs = OPTIONAL
            if use_hints:
                # `required=` is meaningless on a positional, so Optional[X]'s
                # `required=False` is re-read as "an optional positional".
                if spec.extra.pop("required", True) is False:
                    spec.nargs = OPTIONAL
                if by_name:
                    _drop_redundant_bool_type(spec)
            specs.append(spec)

        elif param.kind == param.KEYWORD_ONLY:
            spec = ArgSpec(param.name, list(positional), default=default, extra=extra)
            if by_name:
                if default is not MISSING:
                    spec.flags = list(options)
            else:
                spec.flags = list(options)
                if default is MISSING:
                    spec.required = True
            if use_hints:
                _drop_redundant_bool_type(spec)
            specs.append(spec)

        elif param.kind == param.VAR_POSITIONAL:
            specs.append(
                ArgSpec(param.name, list(positional), nargs=ZERO_OR_MORE, extra=extra)
            )

        # VAR_KEYWORD contributes nothing at all. argh has no branch for it, so `**kwargs`
        # is silently absent from the parser; cw reproduces the silence. Name the
        # parameters you want on the command line, or hand them in through `config`.

    return specs


def _drop_redundant_bool_type(spec: ArgSpec) -> None:
    """``type=bool`` + a ``bool`` default -> drop the type; ``store_true`` supersedes it."""
    if isinstance(spec.default, bool) and spec.extra.get("type") is bool:
        del spec.extra["type"]


# --------------------------------------------------------------------------------------
# The default-value guesser, and the finishing touches


def _guess_from_default(spec: ArgSpec) -> Dict[str, Any]:
    """argh's second inference path: what the *default value* implies.

    Four rules, in argh's own order and with argh's own guards:

    ====================================  =================================
    a ``bool`` default, on an option       ``store_false`` / ``store_true``
    a ``list``/``tuple`` default           ``nargs='*'``
    any other non-``None`` default         ``type=type(default)``
    a ``choices`` with no type yet         ``type=type(choices[0])``
    ====================================  =================================

    ``bool=True`` becoming ``store_false`` is the one everybody trips on: a parameter
    that defaults to on gets a flag that turns it *off*, keeping its own name. It is
    reproduced because a fleet of scripts is written against it.
    """
    guessed: Dict[str, Any] = {}
    extra = spec.extra
    default = spec.default

    if default is not MISSING and default is not None:
        if isinstance(default, bool):
            # Not applicable to positionals: argparse's _StoreTrueAction takes no nargs.
            if not spec.is_positional and extra.get("action") is None:
                guessed["action"] = "store_false" if default else "store_true"
        elif extra.get("type") is None:
            if isinstance(default, (list, tuple)):
                if "nargs" not in extra:
                    guessed["nargs"] = ZERO_OR_MORE
            elif extra.get("action", "store") in ("store", "append"):
                guessed["type"] = type(default)

    choices = extra.get("choices")
    if choices and "type" not in list(guessed) + list(extra):
        guessed["type"] = type(choices[0])
    return guessed


def finalise_spec(
    spec: ArgSpec, /, *, parser_adds_help: bool = True, default_in_help: bool = True
) -> ArgSpec:
    """The last three things argh does to every spec, in argh's order.

    1. the default-value guesses land **over** the hint guesses (which is how a
       ``nargs`` guessed from a list default beats an explicitly declared one -- argh's
       quirk, reproduced);
    2. an argument with no help gets ``'%(default)s'``, which
       :class:`cw.base.ArghHelpFormatter` renders as ``repr(default)``;
    3. ``-h`` is taken away from whoever inferred or declared it, because ``--help``
       owns it. A parameter named ``host`` never gets a short flag.

    >>> finalise_spec(ArgSpec('host', ['-h', '--host'], default='localhost')).flags
    ['--host']
    """
    spec.extra.update(_guess_from_default(spec))
    if default_in_help and "help" not in spec.extra:
        spec.extra["help"] = DFLT_HELP
    if parser_adds_help and "-h" in spec.flags:
        spec.flags = [flag for flag in spec.flags if flag != "-h"]
    return spec


# --------------------------------------------------------------------------------------
# The ladder


def specs_for_function(
    func: Any,
    /,
    *,
    convention=None,
    config: Optional[Mapping[str, Any]] = None,
    decode: Optional[Callable] = None,
    parser_adds_help: bool = True,
) -> List[ArgSpec]:
    """The whole grammar: one function in, its command-line arguments out.

    Four tiers, later wins, merged field-by-field per ADR-0003 (argh's
    ``ParserAddArgumentSpec.update``, *not* ``dict.update``)::

        1. signature inference     kind, default, name, flag spellings
        2. hint inference          decode(param, hint)
        3. function attribute      func._cw['params'][param]     (cw.compat.arg writes it)
        4. config                  config[param]                 (this call's particulars)

    Tier 2 is skipped entirely -- for *every* parameter of the function -- when tier 3 or
    tier 4 is non-empty and ``convention.hints_when_declared`` is false. That is argh's
    ``can_use_hints = not declared_args``: one override anywhere disables type inference
    everywhere in that function. ADR-0003 extends "declared" to cover ``config`` too, so
    that migrating an ``@argh.arg`` into a ``config`` entry does not silently switch hint
    inference back on.

    A ``config`` leaf of :data:`cw.HIDE` removes the argument from the command line while
    leaving the parameter to its own default:

    >>> def serve(host='0.0.0.0', port=8080, pool=None):
    ...     ...
    >>> [s.flags for s in specs_for_function(serve, config={'pool': HIDE})]
    [['--host'], ['--port']]

    (``--port`` and ``--pool`` share a first character, so neither gets a short flag, and
    ``--host`` loses ``-h`` to ``--help``. Both rules are argh's.)

    A ``config`` key naming no parameter is an error, not a silent no-op -- unless the
    function takes ``**kwargs``, in which case the argument is added and delivered there
    (argh's rule):

    >>> specs_for_function(serve, config={'prot': {'help': 'typo'}})
    Traceback (most recent call last):
      ...
    cw.grammar.GrammarError: serve: override for 'prot' matches no parameter. This
    function's parameters are: host, port, pool
    """
    convention = convention if convention is not None else _default_convention()
    declared = dict((getattr(func, "_cw", None) or {}).get("params", {}))
    config = dict(config or {})

    use_hints = convention.hints_when_declared or not (declared or config)
    specs = infer_specs(func, convention=convention, decode=decode, use_hints=use_hints)
    by_param = {spec.param_name: spec for spec in specs}
    order = list(by_param)

    for tier in (declared, config):
        for key, override in tier.items():
            param_name = key.replace("-", "_")
            if override is HIDE:
                if param_name not in by_param:
                    raise _no_such_parameter(func, key, by_param)
                by_param[param_name].hidden = True
                continue
            over = ArgSpec.from_override(param_name, override)
            if param_name in by_param:
                _check_same_kind(func, by_param[param_name], over)
                by_param[param_name].update(over)
            elif _accepts_var_keyword(func):
                if not over.flags:
                    over.flags = [f"--{cli_name(param_name)}"]
                by_param[param_name] = over
                order.append(param_name)
            else:
                raise _no_such_parameter(func, key, by_param)

    return [
        finalise_spec(
            by_param[name],
            parser_adds_help=parser_adds_help,
            default_in_help=convention.default_in_help,
        )
        for name in order
        if not by_param[name].hidden
    ]


def _accepts_var_keyword(func: Any) -> bool:
    """Does ``func`` take ``**kwargs``? Asked only when an override matches no parameter,
    so the common path inspects the signature exactly once."""
    return any(
        p.kind == p.VAR_KEYWORD for p in inspect.signature(func).parameters.values()
    )


def _no_such_parameter(func, key, by_param) -> GrammarError:
    known = ", ".join(by_param) or "(none)"
    return GrammarError(
        f"{getattr(func, '__name__', func)}: override for {key!r} matches no parameter. "
        f"This function's parameters are: {known}"
    )


def _check_same_kind(func, inferred: ArgSpec, override: ArgSpec) -> None:
    """An override may refine an argument; it may not turn a positional into an option."""
    if not override.flags or override.is_positional == inferred.is_positional:
        return
    kind = {True: "positional", False: "an option"}
    raise GrammarError(
        f"{getattr(func, '__name__', func)}: {inferred.param_name!r} is "
        f"{kind[inferred.is_positional]} in the signature but "
        f"{kind[override.is_positional]} in the override "
        f"({', '.join(override.flags)}). Give the parameter a default value to make it "
        f"an option, or drop the leading dashes to make it positional."
    )


def _default_convention():
    """``cw.ARGH``, imported late so that ``convention`` may import ``grammar``."""
    from cw.convention import ARGH

    return ARGH
