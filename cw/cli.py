"""The argparse surface: building a parser, and running one.

Three functions, and the third is the composition of the first two::

    parser = cw.mk_parser(obj, ...)        # build.  Pure: no parsing, no I/O.
    code   = cw.run(parser, argv, ...)     # parse, call, print, return an exit code.
    code   = cw.dispatch(obj, argv, ...)   # == run(mk_parser(obj))

:func:`mk_parser` returns a **plain** :class:`argparse.ArgumentParser`, never a subclass.
That is load-bearing rather than tasteful: ``argcomplete.autocomplete(argument_parser:
argparse.ArgumentParser, ...)`` is argparse-typed at its signature, so eight fleet repos and
ten ``# PYTHON_ARGCOMPLETE_OK`` markers survive the migration untouched -- which the one
fleet repo that moved to ``typer`` could not manage.

Because the parser is plain, cw cannot keep per-subcommand state on it as an attribute.
It travels instead in one reserved ``set_defaults`` key, :data:`RESERVED_DEST`, which
carries the target function, its ingress and the convention that built it. A parameter of
that name is an error naming the collision, never silent corruption.

>>> import cw, io
>>> def greet(name, *, loudly=False):
...     '''Say hello.'''
...     return f'HELLO {name}' if loudly else f'hello {name}'
>>> out = io.StringIO()
>>> cw.dispatch(greet, ['world'], out=out)
0
>>> out.getvalue()
'hello world\\n'

``standalone=False`` turns the same call into an ordinary function call -- nothing is
printed, nothing is caught, and you get the function's own return value:

>>> cw.dispatch(greet, ['world', '--loudly'], standalone=False)
'HELLO world'
"""

import argparse
import contextlib
import dataclasses
import functools
import inspect
import os
import sys
import warnings
from collections.abc import Mapping
from typing import Any, Callable, Optional, TextIO

from cw.base import ArghHelpFormatter, CommandError
from cw.commands import commands_from, import_object, is_command
from cw.convention import ARGH, Convention
from cw.egress import guard_no_coroutine
from cw.grammar import GrammarError, specs_for_function
from cw.ingress import mk_ingress

__all__ = [
    "mk_parser",
    "run",
    "dispatch",
    "add_commands",
    "set_default_command",
    "enable_completion",
    "BoundKeywordWarning",
    "RESERVED_DEST",
]


class BoundKeywordWarning(UserWarning):
    """A ``functools.partial``'s pre-bound keyword is still exposed as a CLI option.

    Its own category so that a repo which has decided the flag is fine can silence exactly
    this warning without changing its CLI, and without silencing anything else::

        warnings.filterwarnings('ignore', category=cw.BoundKeywordWarning)
    """


#: The one ``set_defaults`` key cw reserves on the parsers it builds. Everything a built
#: parser needs to tell :func:`run` -- which function this subcommand is, how to call it,
#: and under which convention -- travels in it.
RESERVED_DEST = "_cw"

#: The exit code argparse itself uses for a usage error, and therefore the one :func:`run`
#: reports when it catches one.
USAGE_ERROR_CODE = 2

#: cw keywords that are real, but not on *this* call. Without this, ``mk_parser(f,
#: egress=...)`` reports that ``argparse.ArgumentParser`` has no such keyword and lists
#: argparse's parameters -- true, and the least useful true thing to say. A seam is one
#: keyword argument, but not every seam is on every entry point: ``egress`` runs after the
#: call, so it belongs to :func:`run` and :func:`dispatch`, and ``decode`` shapes the
#: parser, so it belongs to :func:`mk_parser`, :func:`dispatch` and :func:`add_commands`.
SEAMS_ELSEWHERE = {
    "egress": (
        "cw's egress seam turns a return value into output, which happens when a command "
        "runs -- so it is a keyword of cw.run and cw.dispatch, not of cw.mk_parser. To "
        "bind it to a parser instead, put it on the convention: "
        "convention=dataclasses.replace(cw.ARGH, egress=my_egress)."
    ),
    "ingress": (
        "cw has no `ingress=` keyword. The namespace-to-call step is built from the "
        "function's own signature (cw.ingress.mk_ingress); per-parameter conversion is "
        "spelled config={'param': {'codec': ...}} or, for a whole convention, decode=."
    ),
}

#: Set it to silence :class:`BoundKeywordWarning` for a console script that has nowhere to
#: put a ``warnings.filterwarnings`` line. Named to rhyme with ``CW_COMPAT_QUIET``.
QUIET_ENV = "CW_QUIET"


@dataclasses.dataclass(frozen=True)
class _Stash:
    """What a built parser tells :func:`run`, carried in one namespace attribute.

    ``func`` is ``None`` on a parser that only holds subcommands: reaching :func:`run` with
    that still set means no subcommand was chosen, which is the usage-line case.
    """

    convention: Convention
    func: Optional[Callable] = None
    ingress: Optional[Callable] = None
    config: Optional[Mapping] = None
    #: ``{argparse dest: python parameter name}``, for the hyphenated positionals argh
    #: registers under a name no Python call can use. Empty for every other argument.
    renames: Mapping[str, str] = dataclasses.field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Building


def _new_parser(convention: Convention, parser_kwargs: dict) -> argparse.ArgumentParser:
    """An ``ArgumentParser`` with cw's default look, and a readable error for a typo.

    ``prog``, ``description``, ``epilog``, ``formatter_class``, ``allow_abbrev`` and
    friends pass through verbatim -- cw invents no vocabulary for anything argparse already
    names -- so a misspelling would otherwise surface as a bare ``ArgumentParser.__init__``
    ``TypeError`` that never mentions cw.
    """
    parser_kwargs.setdefault("formatter_class", ArghHelpFormatter)
    misplaced = sorted(set(parser_kwargs) & set(SEAMS_ELSEWHERE))
    if misplaced:
        raise TypeError(
            "; ".join(f"{name}: {SEAMS_ELSEWHERE[name]}" for name in misplaced)
        )
    try:
        return argparse.ArgumentParser(**parser_kwargs)
    except TypeError as exc:
        accepted = ", ".join(
            name
            for name in inspect.signature(argparse.ArgumentParser).parameters
            if name != "self"
        )
        raise TypeError(
            f"cw passes unknown keyword arguments straight to "
            f"argparse.ArgumentParser, and it rejected one: {exc}. "
            f"argparse.ArgumentParser accepts: {accepted}."
        ) from exc


def _child_formatter(formatter_class) -> type:
    """The formatter every subparser gets, given the one its parent carries.

    argh hands ``PARSER_FORMATTER`` to every subparser it creates -- *unconditionally*,
    even under a plain ``argparse.ArgumentParser`` whose own formatter it leaves alone
    (verified against argh 0.31.3). So ``argparse.ArgumentParser() + add_commands`` gives
    argh-looking subcommands and a stock root, and cw must do the same or the one-line
    migration changes ``--help`` for every repo that holds a parser object: a ``None``
    default printing ``None`` instead of ``-``, a string default losing its quotes, and a
    multi-paragraph docstring reflowed into one.

    cw promotes only the *stock* formatter rather than overriding unconditionally, so an
    explicit ``formatter_class=`` still means what it says. The root parser is never
    touched here -- :func:`mk_parser` defaults it at construction, ``ArghParser.__init__``
    defaults it for the 27 fleet call sites that use it, and a parser somebody else built
    keeps whatever they gave it, exactly as under argh.
    """
    return (
        ArghHelpFormatter
        if formatter_class is argparse.HelpFormatter
        else formatter_class
    )


def _func_label(func: Any) -> str:
    """A stable, address-free name for ``func``, partials included.

    ``repr(functools.partial(f))`` embeds ``f``'s hex ``id()``, which makes any message
    built from it differ on every run -- unusable in a golden, and noise in a warning.
    """
    if isinstance(func, functools.partial):
        return f"functools.partial({_func_label(func.func)})"
    return getattr(func, "__name__", None) or type(func).__name__


def _warn_bound_keywords(func: Any, specs, *, command: Optional[str] = None) -> None:
    """Warn about a ``functools.partial``'s pre-bound keyword that is still a CLI flag.

    :func:`inspect.signature` keeps a partial's bound keyword (Python moves it to
    keyword-only), so cw renders it as an option unless told not to. cw does **not**
    auto-hide it: ``inspect.signature`` is cw's single source of truth for everything else,
    and silently diverging from it would be a second, subtler bug than the one being fixed.
    A warning names the leak and the one line that closes it.

    It reads the finished ``specs`` rather than the signature, so that hiding the keyword
    silences the warning -- a warning you cannot act on is noise. Three further properties
    matter, because this fires on *every* invocation of a CLI that has such a command,
    ``--help`` included:

    * it names the **command** whose config key would close it, not a ``'<command>'``
      placeholder, so the suggested line can be pasted;
    * it carries no ``id()``, so the text is the same on every run; and
    * it is a :class:`BoundKeywordWarning`, so a repo that has decided the flag is fine can
      silence exactly this one -- ``warnings.filterwarnings('ignore',
      category=cw.BoundKeywordWarning)``, or :data:`QUIET_ENV` for a console script that
      has nowhere to put that line -- **without** changing its CLI. Hiding the parameter
      also silences it, but that removes a flag argh exposed, which is not the same thing.
    """
    if not isinstance(func, functools.partial) or os.environ.get(QUIET_ENV):
        return
    bound = set(func.keywords or ())
    for spec in specs:
        if spec.param_name in bound:
            key = (
                f"{{{command!r}: {{{spec.param_name!r}: cw.HIDE}}}}"
                if command is not None
                else f"{{{spec.param_name!r}: cw.HIDE}}"
            )
            warnings.warn(
                f"{_func_label(func)}: the pre-bound keyword {spec.param_name!r} is "
                f"still exposed as a command-line option. Hide it with config={key}, or "
                f"silence this with {QUIET_ENV}=1 to keep the flag.",
                BoundKeywordWarning,
                stacklevel=4,
            )


def set_default_command(
    parser: argparse.ArgumentParser,
    func: Callable,
    /,
    *,
    config: Optional[Mapping] = None,
    convention: Convention = ARGH,
    command: Optional[str] = None,
) -> argparse.ArgumentParser:
    """Bind one function to ``parser``: add its arguments, and stash how to call it.

    This is what makes ``run``'s reason for existing true -- a repo can hand-build a
    parser, ``add_argument`` to it, bind a function here, and still get cw's ingress and
    egress:

    >>> import argparse, cw, io
    >>> from cw.cli import set_default_command
    >>> parser = argparse.ArgumentParser(prog='count')
    >>> def tally(word, *, times=1):
    ...     return [word] * times
    >>> _ = set_default_command(parser, tally)
    >>> out = io.StringIO()
    >>> cw.run(parser, ['hi', '-t', '2'], out=out)
    0
    >>> out.getvalue()
    'hi\\nhi\\n'

    The function's docstring becomes the parser's description, unless the parser already
    has one -- argh's rule, and it is what lets ``description=`` override it.

    ``command`` is the command word this function is bound to, when there is one. It is used
    only in messages -- it is what lets the ``functools.partial`` warning print the
    ``config`` key you would actually paste rather than a ``'<command>'`` placeholder -- so
    a caller binding a single command has no reason to pass it.
    """
    specs = specs_for_function(
        func, convention=convention, config=config, parser_adds_help=parser.add_help
    )
    _warn_bound_keywords(func, specs, command=command)
    for spec in specs:
        if spec.param_name == RESERVED_DEST:
            raise GrammarError(
                f"{_func_label(func)}: the parameter {RESERVED_DEST!r} "
                "collides with the namespace key cw reserves for its own use. Rename the "
                "parameter, or hide it with cw.HIDE."
            )
        args, kwargs = spec.add_argument_args()
        try:
            action = parser.add_argument(*args, **kwargs)
        except Exception as exc:
            raise GrammarError(_cannot_add(func, spec, exc)) from exc
        if spec.completer is not None:
            # argcomplete reads it off the action, which is why it cannot be an
            # add_argument keyword. argh assigns it in the same place.
            action.completer = spec.completer
    if not parser.description:
        parser.description = inspect.getdoc(func)
    codecs = {spec.param_name: spec.codec for spec in specs if spec.codec is not None}
    renames = {
        spec.argparse_dest: spec.param_name
        for spec in specs
        if spec.argparse_dest != spec.param_name
    }
    _stash(
        parser,
        _Stash(
            convention=convention,
            func=func,
            ingress=mk_ingress(func, codecs=codecs),
            config=config,
            renames=renames,
        ),
    )
    return parser


def _cannot_add(func: Any, spec, exc: Exception) -> str:
    """The message for an ``add_argument`` call argparse refused.

    argparse says ``no`` in three different exception types and none of the messages names
    the function, the parameter or the flags -- ``ValueError: dest= is required for options
    like '---pool'`` is the whole of what a user sees otherwise. argh wraps all of them
    (``AssemblingError: {func}: cannot add {param} as {flags}: {reason}``) and cw must not
    be *worse* than the library it replaces at the one moment a migration goes wrong.

    The leading-underscore case gets an extra sentence, because it is a reproduced argh
    footgun with a documented one-line fix that the raw message cannot mention.
    """
    flags = "/".join(spec.flags)
    message = f"{_func_label(func)}: cannot add {spec.param_name!r} as {flags}: {exc}"
    if any(flag.startswith("---") or flag == "--" for flag in spec.flags):
        message += (
            f". A parameter named {spec.param_name!r} starts with an underscore, which "
            "argh -- and therefore cw -- hyphenates into an unusable flag. Hide it with "
            f"config={{{spec.param_name!r}: cw.HIDE}} (it keeps its default), or rename it."
        )
    return message


def _stash(parser: argparse.ArgumentParser, stash: _Stash) -> None:
    parser.set_defaults(**{RESERVED_DEST: stash})


def _subparsers_of(parser: argparse.ArgumentParser) -> argparse.Action:
    """The parser's subparsers action, created on first use.

    ``add_subparsers`` may be called only once per parser, so a second ``add_commands``
    against the same parser has to find the first one's.
    """
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return parser.add_subparsers()


def _add_command(
    subparsers: argparse.Action,
    name: str,
    func: Callable,
    *,
    config,
    convention,
    formatter_class,
) -> None:
    """One subcommand. Its listing row is its raw ``__doc__``, which is argh's choice."""
    command_parser = subparsers.add_parser(
        name, help=func.__doc__, formatter_class=formatter_class
    )
    set_default_command(
        command_parser, func, config=config, convention=convention, command=name
    )


def _add_group(
    subparsers: argparse.Action,
    name: str,
    members: Mapping,
    *,
    config,
    convention,
    formatter_class,
    group_kwargs=None,
) -> None:
    """One group of subcommands -- the only level of nesting there is.

    Two details, both of which a plausible implementation gets wrong and neither of which
    is visible until someone reads ``--help``:

    * the **parent's listing row** reads ``group_kwargs['title']``, not ``['help']``; and
    * ``help=`` must be passed to ``add_parser`` **even when it is None**, because that is
      what makes argparse create the pseudo-action -- omit it and the group vanishes from
      the parent's ``--help`` entirely.

    The whole ``group_kwargs`` mapping then goes to ``add_subparsers``, ``help`` included,
    where it renders inside the group's own ``--help``. Nothing is dropped.
    """
    group_kwargs = dict(group_kwargs or {})
    holder = subparsers.add_parser(
        name, help=group_kwargs.get("title"), formatter_class=formatter_class
    )
    inner = holder.add_subparsers(**group_kwargs)
    _stash(holder, _Stash(convention=convention))
    _add_tree(
        holder,
        members,
        config=config,
        convention=convention,
        formatter_class=formatter_class,
        subparsers=inner,
    )


def _check_config_keys(tree: Mapping, config: Mapping, *, what: str) -> None:
    """A ``config`` key naming no command is a startup error, never a silent no-op.

    This is the rule that closes the trap where ``convention=cw.MODERN`` renames a group
    (``hyphenate_groups``) and every config entry keyed by the old name quietly stops
    applying. Keys and names go through one naming function, so a mismatch is a bug, and a
    bug should be loud.
    """
    unknown = [key for key in config if key not in tree]
    if unknown:
        known = ", ".join(tree) or "(none)"
        plural = len(unknown) > 1
        raise GrammarError(
            f"config key{'s' if plural else ''} "
            f"{', '.join(repr(key) for key in unknown)} "
            f"{'match' if plural else 'matches'} no {what}. "
            f"Known {what} names: {known}. Note that names are hyphenated by the "
            "convention, so a config must be keyed the way the command line is typed."
        )


def _add_tree(
    parser: argparse.ArgumentParser,
    tree: Mapping,
    *,
    config: Mapping,
    convention: Convention,
    formatter_class,
    subparsers: Optional[argparse.Action] = None,
) -> None:
    """Add every command and group in ``tree`` to ``parser``'s subparsers."""
    _check_config_keys(tree, config, what="command or group")
    subparsers = _subparsers_of(parser) if subparsers is None else subparsers
    for name, value in tree.items():
        adder = _add_command if is_command(value) else _add_group
        adder(
            subparsers,
            name,
            value,
            config=config.get(name) or {},
            convention=convention,
            formatter_class=formatter_class,
        )


def _with_decode(convention: Convention, decode) -> Convention:
    """``convention``, or a copy of it carrying an explicitly passed ``decode=``."""
    return (
        convention if decode is None else dataclasses.replace(convention, decode=decode)
    )


def mk_parser(
    obj: Any,
    /,
    *,
    config: Optional[Mapping] = None,
    convention: Convention = ARGH,
    decode=None,
    **parser_kwargs,
) -> argparse.ArgumentParser:
    """Build the parser ``obj`` describes. No parsing, no I/O, no side effects.

    Args:
        obj: A callable, a list, a mapping, a module, or a ``'pkg.mod:name'`` reference --
            see :mod:`cw.commands` for what each one means.
        config: This call's particulars, keyed the way you address the thing on the command
            line: ``{param: add_argument_kwargs}`` for a single command,
            ``{command: {param: ...}}`` for several, nested once more for a group.
        convention: What the defaults ARE. :data:`cw.ARGH` by default.
        decode: Seam 1, overriding ``convention.decode`` when given.
        parser_kwargs: Passed verbatim to :class:`argparse.ArgumentParser` --
            ``prog``, ``description``, ``epilog``, ``formatter_class``, ``allow_abbrev``.

    Returns:
        A plain :class:`argparse.ArgumentParser`. Not a subclass -- see the module
        docstring for why that is load-bearing.

    >>> import argparse, cw
    >>> def ls(path='.'): ...
    >>> type(cw.mk_parser(ls)) is argparse.ArgumentParser
    True

    A single callable is one command with no command word; anything else is subcommands:

    >>> cw.mk_parser(ls, prog='x').format_usage()
    'usage: x [-h] [-p PATH]\\n'
    >>> cw.mk_parser([ls], prog='x').format_usage()
    'usage: x [-h] {ls} ...\\n'

    Completion is **not** fired here. :func:`argcomplete.autocomplete` reads the
    environment and may exit the process, and ``mk_parser`` is what a test inspects; so
    completion happens in :func:`run`, which is also where argh does it.
    """
    convention = _with_decode(convention, decode)
    if isinstance(obj, str):
        obj = import_object(obj)
    parser = _new_parser(convention, parser_kwargs)
    if is_command(obj):
        set_default_command(parser, obj, config=config, convention=convention)
    else:
        _stash(parser, _Stash(convention=convention))
        _add_tree(
            parser,
            commands_from(obj, convention=convention),
            config=config or {},
            convention=convention,
            formatter_class=_child_formatter(parser.formatter_class),
        )
    return parser


def add_commands(
    parser: argparse.ArgumentParser,
    obj: Any,
    /,
    *,
    group_name: Optional[str] = None,
    namespace: Optional[str] = None,
    group_kwargs: Optional[Mapping] = None,
    namespace_kwargs: Optional[Mapping] = None,
    config: Optional[Mapping] = None,
    convention: Convention = ARGH,
    decode=None,
) -> argparse.ArgumentParser:
    """Add ``obj``'s commands to an existing parser, optionally under one group.

    ``namespace=`` and ``namespace_kwargs=`` are argh's pre-0.30 spellings of
    ``group_name=`` and ``group_kwargs=``. argh renamed them with no alias, which left four
    fleet call sites passing a keyword nothing reads; accepting both revives them.

    When ``group_name`` is given, ``config`` is keyed by *command* name -- ``config`` always
    has the same shape as the ``obj`` beside it, and here that ``obj`` is the group's
    members.

    >>> import argparse, cw
    >>> from cw.cli import add_commands
    >>> def status(): ...
    >>> parser = argparse.ArgumentParser(prog='priv')
    >>> _ = add_commands(parser, [status], group_name='git_ops')
    >>> parser.format_usage()
    'usage: priv [-h] {git_ops} ...\\n'
    """
    convention = _with_decode(convention, decode)
    group_name = group_name if group_name is not None else namespace
    group_kwargs = group_kwargs if group_kwargs is not None else namespace_kwargs
    tree = commands_from(obj, convention=convention)
    config = dict(config or {})
    if parser.get_default(RESERVED_DEST) is None:
        _stash(parser, _Stash(convention=convention))
    if group_name is None:
        _add_tree(
            parser,
            tree,
            config=config,
            convention=convention,
            formatter_class=_child_formatter(parser.formatter_class),
        )
        return parser
    _check_config_keys(tree, config, what="command")
    _add_group(
        _subparsers_of(parser),
        group_name,
        tree,
        config=config,
        convention=convention,
        formatter_class=_child_formatter(parser.formatter_class),
        group_kwargs=group_kwargs,
    )
    return parser


# --------------------------------------------------------------------------------------
# Completion


def enable_completion(
    parser: argparse.ArgumentParser, /, *, silent: bool = True
) -> bool:
    """Offer ``parser`` to ``argcomplete``, if it is installed.

    Args:
        parser: The parser to complete against. A plain ``ArgumentParser`` -- which is what
            ``argcomplete.autocomplete`` is typed for, and the reason cw never subclasses.
        silent: Swallow the ``ImportError`` when ``argcomplete`` is absent, which is the
            point: completion is an optional extra (``pip install 'cw[completion]'``) and a
            CLI must run without it. ``silent=False`` re-raises, for a script that means to
            require it.

    Returns:
        Whether completion was enabled.

    The import is inside the function on purpose. ``import cw`` costs stdlib only, and a
    module-scope third-party import here would quietly undo that for all 66 console
    scripts. There is a test that greps for it.

    >>> import argparse
    >>> from cw.cli import enable_completion
    >>> enable_completion(argparse.ArgumentParser()) in (True, False)
    True
    """
    try:
        import argcomplete
    except ImportError:
        if not silent:
            raise
        return False
    argcomplete.autocomplete(parser)
    return True


# --------------------------------------------------------------------------------------
# Running


def _stream(given: Optional[TextIO], name: str) -> TextIO:
    """``given``, or the named ``sys`` stream looked up now rather than at import."""
    return getattr(sys, name) if given is None else given


def _exit_code(exc: SystemExit, err: TextIO) -> int:
    """A ``SystemExit`` as the integer :func:`run` returns, mimicking the interpreter.

    ``SystemExit(None)`` is success, an ``int`` is itself, and anything else is a message:
    Python prints it to stderr and exits 1, and so does cw, so that
    ``raise SystemExit(cw.dispatch(...))`` ends the process the same way argh did.
    """
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    err.write(f"{exc.code}\n")
    return 1


def _redirect(out: Optional[TextIO], err: Optional[TextIO]):
    """Point argparse's own output at ``out``/``err`` for the duration of parsing.

    ``--help``, ``usage:`` and ``error:`` come from argparse and never pass through the
    egress, so this is the only way an explicit ``out=`` can capture them. It wraps
    **parsing only**, never the command body: a command's own ``print`` goes where the
    process's ``print`` goes, exactly as under argh, and redirecting it would be a
    surprising, process-global side effect of asking for a string.
    """
    stack = contextlib.ExitStack()
    if out is not None:
        stack.enter_context(contextlib.redirect_stdout(out))
    if err is not None:
        stack.enter_context(contextlib.redirect_stderr(err))
    return stack


def run(
    parser: argparse.ArgumentParser,
    argv=None,
    *,
    config: Optional[Mapping] = None,
    convention: Optional[Convention] = None,
    egress=None,
    out: Optional[TextIO] = None,
    err: Optional[TextIO] = None,
    standalone: bool = True,
    completion: bool = True,
) -> Any:
    """Parse ``argv`` with ``parser``, call the command it names, and report.

    Args:
        parser: Any parser -- one from :func:`mk_parser`, or a hand-built one that has been
            given a function by :func:`set_default_command`.
        argv: The argument strings. ``None`` means :data:`sys.argv` ``[1:]``. Keyword or
            positional: four fleet call sites spell it as a keyword.
        config: Per-parameter particulars, when they were not given at build time. Only the
            ``codec=`` entries can still take effect this late; the rest is token grammar
            and is already in the parser.
        convention: Overrides the one the parser was built with -- which is what supplies
            ``egress`` when you do not pass one.
        egress: Seam 2, overriding ``convention.egress`` when given.
        out: Where results go. ``None`` means :data:`sys.stdout`, resolved **now**.
        err: Where an expected failure goes. ``None`` means :data:`sys.stderr`, now.
        standalone: ``True`` prints and returns an exit code; ``False`` returns the
            function's own value and lets everything propagate.
        completion: Offer the parser to ``argcomplete`` before parsing, as argh does.

    Returns:
        An ``int`` exit code when ``standalone``, else whatever the command returned.

    The convention travels with the parser, so flipping to :data:`cw.MODERN` stays one act
    even when the build and the run are two calls:

    >>> import cw, io
    >>> def counted():
    ...     return map(str, range(2))
    >>> parser = cw.mk_parser(counted, convention=cw.MODERN)
    >>> out = io.StringIO()
    >>> cw.run(parser, [], out=out)
    0
    >>> out.getvalue()
    '0\\n1\\n'

    An expected failure is one line and an exit code; an unexpected one keeps its
    traceback, because a bug deserves one:

    >>> err = io.StringIO()
    >>> def risky():
    ...     raise cw.CommandError('no such pipeline', code=3)
    >>> cw.dispatch(risky, [], err=err)
    3
    >>> err.getvalue()
    'CommandError: no such pipeline\\n'
    """
    stash = parser.get_default(RESERVED_DEST)
    out = _stream(out, "stdout")
    err = _stream(err, "stderr")
    argv = sys.argv[1:] if argv is None else list(argv)

    if completion:
        enable_completion(parser)

    with _redirect(
        out if out is not sys.stdout else None, err if err is not sys.stderr else None
    ):
        try:
            namespace = parser.parse_args(argv)
        except SystemExit as exc:
            if not standalone:
                raise
            return _exit_code(exc, err)

    # The stash the *subcommand* left behind wins over the top parser's, because it is
    # the one that knows which function was chosen and under which convention it was
    # built -- an `add_commands(..., convention=MODERN)` group inside an ARGH parser is
    # rare, but getting it wrong would be silent.
    stash = getattr(namespace, RESERVED_DEST, None) or stash
    if stash is None or stash.func is None:
        parser.print_usage(out)
        return 0 if standalone else None

    convention = convention or stash.convention
    egress = egress if egress is not None else convention.egress
    args, kwargs = _call_args(stash, namespace, config=config, convention=convention)
    if not standalone:
        return stash.func(*args, **kwargs)
    try:
        result = stash.func(*args, **kwargs)
        guard_no_coroutine(result)
        return egress(result, out=out, err=err)
    except CommandError as exc:
        err.write(f"{type(exc).__name__}: {exc}\n")
        return exc.code
    except SystemExit as exc:
        return _exit_code(exc, err)


def _call_args(stash: _Stash, namespace, *, config, convention) -> tuple:
    """``(args, kwargs)`` for the stashed command, from the parsed namespace."""
    renames = stash.renames or {}
    values = {
        renames.get(name, name): value
        for name, value in vars(namespace).items()
        if name != RESERVED_DEST
    }
    ingress = stash.ingress
    if config is not None:
        specs = specs_for_function(stash.func, convention=convention, config=config)
        ingress = mk_ingress(
            stash.func,
            codecs={s.param_name: s.codec for s in specs if s.codec is not None},
        )
    return ingress(values)


def dispatch(
    obj: Any,
    argv=None,
    *,
    config: Optional[Mapping] = None,
    convention: Convention = ARGH,
    decode=None,
    egress=None,
    out: Optional[TextIO] = None,
    err: Optional[TextIO] = None,
    standalone: bool = True,
    completion: bool = True,
    **parser_kwargs,
) -> Any:
    """The front door: ``dispatch == run o mk_parser``.

    Everything :func:`mk_parser` and :func:`run` take, in one call. The console-script
    idiom is::

        def main():
            raise SystemExit(cw.dispatch(COMMANDS, prog='priv'))

    and the house dispatch -- the thing that makes a project's per-call configs shrink to
    nothing -- is :func:`functools.partial`, not a cw-specific binder::

        dispatch = functools.partial(cw.dispatch, convention=cw.MODERN, prog='priv')

    >>> import cw, io
    >>> def add(a: int, b: int):
    ...     return a + b
    >>> out = io.StringIO()
    >>> cw.dispatch(add, ['2', '3'], out=out)
    0
    >>> out.getvalue()
    '5\\n'

    A usage error is argparse's, and keeps argparse's exit code -- which matters, because a
    console script that starts exiting 0 on a bad command line breaks every CI step that
    checks it:

    >>> cw.dispatch(add, ['nope'], out=io.StringIO(), err=io.StringIO())
    2
    """
    parser = mk_parser(
        obj, config=config, convention=convention, decode=decode, **parser_kwargs
    )
    return run(
        parser,
        argv,
        convention=convention,
        egress=egress,
        out=out,
        err=err,
        standalone=standalone,
        completion=completion,
    )
