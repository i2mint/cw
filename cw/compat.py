"""Transitional argh shim: a one-line import change retires a repo.

**Deprecated from day one.** This module exists so that a repo can stop depending on
LGPL-3.0-or-later ``argh`` *today*, in a diff a reviewer can read in one glance::

    -import argh
    +from cw import compat as argh

and then migrate to cw's real API on its own schedule. New code should never import it.
Every name warns once, on first use; ``CW_COMPAT_QUIET=1`` silences the lot for a repo that
has decided to live here for a while.

The surface is the fleet's entire *measured* argh usage -- nothing speculative:
``dispatch_commands`` 34 · ``dispatch_command`` 30 · ``ArghParser`` 27 · ``dispatch`` 19 ·
``arg`` 17 · ``add_commands`` 15 · ``NameMappingPolicy`` 4 · ``CommandError`` 4 ·
``completion`` 2 · ``confirm`` 1, plus ``set_default_command``.

Every function here is **three statements or fewer**. That is the design gauge, not a
coding-style preference: :func:`arg` is thin *because* cw's merge ladder already has a
function-attribute tier for it to write into, and if ``@arg`` had needed real work, the
ladder would have been in the wrong shape. The one function with a body worth reading is
:func:`dispatch`, and everything in it is argh-compatibility, not cw.

Four things this shim does **not** do, each of which a literal reading of argh's signatures
would have got wrong:

1. **It does not swallow argparse's exit code.** ``argh.dispatch_commands`` is typed
   ``-> None``, but in argh the ``SystemExit(2)`` from a usage error propagates out of
   ``main()``. ``cw.dispatch`` *returns* that 2 instead, so a literal ``-> None`` shim
   would make every migrated console script exit **0** on a bad command line -- across 64
   dispatch-style call sites, breaking any CI step that checks ``$?``. These shims re-raise
   a non-zero code.
2. **It does not bind ``sys.stdout`` in a signature default.** argh's
   ``output_file: IO = sys.stdout`` is bound at import (``dispatching.py:77``), which is why
   ``redirect_stdout`` and pytest's ``capsys`` capture nothing from an argh CLI. That is the
   single worst defect in argh's dispatch surface, and putting it back into the shim that
   19 call sites will use would be an odd thing to do. Streams resolve at call time.
3. **It does not forward argh's dispatch keywords to ``ArgumentParser``.** They are split
   out explicitly (:data:`_ARGH_DISPATCH_KWARGS`), or ``dispatch_commands(...,
   output_file=f)`` would raise ``TypeError: ArgumentParser.__init__() got an unexpected
   keyword argument``.
4. **It accepts BOTH ``group_name=`` and ``namespace=``.** argh 0.30 renamed the keyword
   with no alias, leaving four fleet call sites passing something nothing reads. Accepting
   both revives them -- a change from "would crash" to "works", which is worth knowing
   about before you run one.

And one thing it deliberately refuses to do: ``named``, ``aliases`` and ``add_subcommands``
have zero uses anywhere in the fleet and are **not** shipped. A module ``__getattr__``
raises an informative error instead. ``named`` in particular was specified as a shim that
writes ``func._cw['name']`` -- which nothing reads, so it would silently do nothing, which
is worse than the :class:`AttributeError` it existed to prevent.

**One trap the shim structurally cannot fix**, and which belongs on every migration
checklist: ``from argh import CommandError``. A module that imported the *name* rather than
the module still imports argh after the one-line change, and cw will not catch an exception
class it has never heard of, so ``CommandError: boom`` / exit 1 becomes an unhandled
traceback. Grep for it.

>>> import io
>>> from cw import compat as argh
>>> def hello(name, *, loudly=False):
...     '''Greet someone.'''
...     return f'HELLO {name}' if loudly else f'hello {name}'
>>> argh.dispatch_command(hello, ['world'], output_file=io.StringIO())
>>> argh.dispatch_command(hello, ['world'], output_file=None)
'hello world\\n'
"""

import argparse
import enum
import functools
import os
import sys
import warnings
from typing import Any, Callable, Mapping, Optional

import cw
from cw.base import MISSING
from cw.cli import add_commands as _cw_add_commands
from cw.cli import dispatch as _cw_dispatch
from cw.cli import mk_parser as _cw_mk_parser
from cw.cli import run as _cw_run
from cw.cli import set_default_command as _cw_set_default_command

__all__ = [
    "ArghParser",
    "CommandError",
    "NameMappingPolicy",
    "add_commands",
    "arg",
    "completion",
    "confirm",
    "dispatch",
    "dispatch_command",
    "dispatch_commands",
    "set_default_command",
]

#: argh's expected-failure exception, which is cw's. Not an alias to keep around: it is the
#: same class, so ``except argh.CommandError`` in migrated code catches what cw raises.
CommandError = cw.CommandError

#: The environment variable that silences this module's deprecation warnings. A repo living
#: in Wave 0 for a while sets it once rather than filtering warnings at every entry point.
QUIET_ENV = "CW_COMPAT_QUIET"

#: argh's ``dispatch`` keywords, which are **not** ``ArgumentParser`` keywords. Forwarding
#: ``**kw`` blindly to :func:`cw.dispatch` -- whose own ``**parser_kwargs`` go straight to
#: ``ArgumentParser`` -- would turn any one of them into a ``TypeError``. Zero fleet call
#: sites pass one today, but argh's own signature accepts them all, so a migration must not
#: be the thing that discovers it.
_ARGH_DISPATCH_KWARGS = (
    "add_help_command",
    "always_flush",
    "completion",
    "errors_file",
    "namespace",
    "output_file",
    "raw_output",
    "skip_unknown_args",
)

#: Names already warned about, so each one warns once per process rather than once per call.
_WARNED = set()


class NameMappingPolicy(str, enum.Enum):
    """argh's naming policy, **exported** -- which argh itself never did.

    ``hasattr(argh, 'NameMappingPolicy')`` is ``False``, so
    ``illustration/__main__.py:23``'s ``getattr`` guard is a permanent silent no-op and
    ``ir/__main__.py:19-34`` needs a triple-nested try/except to reach it. Both work
    against this.

    The values are cw's :data:`cw.Convention` ``naming`` strings, so a policy passed here
    reaches cw without a translation table in between.

    >>> NameMappingPolicy.BY_NAME_IF_HAS_DEFAULT.value
    'by_name_if_has_default'
    """

    BY_NAME_IF_HAS_DEFAULT = cw.BY_NAME_IF_HAS_DEFAULT
    BY_NAME_IF_KWONLY = cw.BY_NAME_IF_KWONLY


def _deprecated(func):
    """Warn once, on first use, that ``func`` is transitional. Silenced by the env var.

    A decorator rather than a line in each body, so "every shim is three statements" stays
    a statement about the shims and not about how they were counted.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if func.__name__ not in _WARNED and not os.environ.get(QUIET_ENV):
            _WARNED.add(func.__name__)
            warnings.warn(
                f"cw.compat.{func.__name__} is a transitional argh shim. Migrate to cw's "
                f"own API (see cw.dispatch); set {QUIET_ENV}=1 to silence this.",
                DeprecationWarning,
                stacklevel=2,
            )
        return func(*args, **kwargs)

    return wrapper


def _convention_for(name_mapping_policy) -> Any:
    """The :data:`cw.Convention` an argh ``name_mapping_policy`` asks for.

    ``None`` means argh's dispatch default, which is cw's default too -- that asymmetry
    (argh's ``dispatch_*`` defaults the policy while ``add_commands`` does not) is exactly
    what cw removes by having one default everywhere.

    >>> _convention_for(None) is cw.ARGH
    True
    >>> _convention_for(NameMappingPolicy.BY_NAME_IF_KWONLY).naming
    'by_name_if_kwonly'
    """
    import dataclasses

    if name_mapping_policy is None:
        return cw.ARGH
    naming = getattr(name_mapping_policy, "value", name_mapping_policy)
    return dataclasses.replace(cw.ARGH, naming=naming)


def _split_kwargs(kwargs: Mapping) -> tuple:
    """``(argh dispatch kwargs, ArgumentParser kwargs)`` -- repair 3 above.

    >>> _split_kwargs({'output_file': None, 'prog': 'x'})
    ({'output_file': None}, {'prog': 'x'})
    """
    mine = {k: v for k, v in kwargs.items() if k in _ARGH_DISPATCH_KWARGS}
    return mine, {k: v for k, v in kwargs.items() if k not in _ARGH_DISPATCH_KWARGS}


def _finish(code: int, captured) -> Optional[str]:
    """What an argh dispatch entry point returns, and how it exits -- repairs 1 and 2.

    ``output_file=None`` means "give me the string" (argh's own documented behaviour), and
    anything else means "this is a console script": return ``None``, but let a non-zero
    exit code out, because that is what argh's propagating ``SystemExit`` did and what
    every CI step checking ``$?`` is relying on.
    """
    if captured is not None:
        return captured.getvalue()
    if code:
        raise SystemExit(code)
    return None


def _run_with_streams(build, argv, argh_kwargs: Mapping) -> Optional[str]:
    """Build a parser, run it, and honour argh's stream keywords. The shim's one body.

    ``output_file=None`` is argh's "return the string instead of printing" mode, spelled
    here as a :class:`io.StringIO` that :func:`_finish` reads back.
    """
    import io

    output_file = argh_kwargs.get("output_file", MISSING)
    captured = io.StringIO() if output_file is None else None
    code = _cw_run(
        build(),
        argv,
        out=captured if captured is not None else _stream_or_none(output_file),
        err=_stream_or_none(argh_kwargs.get("errors_file", MISSING)),
        completion=argh_kwargs.get("completion", True),
    )
    return _finish(code, captured)


def _stream_or_none(given):
    """``None`` for "cw, resolve this at call time", else the stream the caller passed.

    :data:`cw.MISSING` is what "the caller said nothing" looks like, and it must not become
    ``sys.stdout`` here -- resolving it now is precisely the argh defect repair 2 is about.

    >>> _stream_or_none(MISSING) is None
    True
    """
    return None if given is MISSING else given


# =======================================================================================
# The eleven names
# =======================================================================================


@_deprecated
def dispatch(parser: argparse.ArgumentParser, argv=None, **kwargs) -> Optional[str]:
    """argh's ``dispatch``: run a parser that already has its commands.

    Accepts argh's ``output_file`` / ``errors_file`` / ``completion`` and the four keywords
    that were verified to have zero fleet uses, so a call site that passes one gets cw's
    behaviour rather than a ``TypeError``. ``output_file=None`` returns the output string.

    >>> import io
    >>> from cw import compat as argh
    >>> parser = argh.ArghParser(prog='demo')
    >>> def ping():
    ...     return 'pong'
    >>> parser.add_commands([ping])
    >>> parser.dispatch(['ping'], output_file=None)
    'pong\\n'
    """
    argh_kwargs, parser_kwargs = _split_kwargs(kwargs)
    _reject(parser_kwargs, "dispatch")
    return _run_with_streams(lambda: parser, argv, argh_kwargs)


@_deprecated
def dispatch_commands(functions, argv=None, **kwargs) -> Optional[str]:
    """argh's ``dispatch_commands``: build a parser for ``functions`` and run it.

    The fleet's most-used argh name (34 call sites). Unlike argh's, a usage error still
    exits 2 rather than 0.

    >>> import io
    >>> from cw import compat as argh
    >>> def add(a: int, b: int):
    ...     return a + b
    >>> argh.dispatch_commands([add], ['add', '2', '3'], output_file=None)
    '5\\n'
    """
    argh_kwargs, parser_kwargs = _split_kwargs(kwargs)
    policy = parser_kwargs.pop("name_mapping_policy", None)
    return _run_with_streams(
        lambda: _cw_mk_parser(
            functions, convention=_convention_for(policy), **parser_kwargs
        ),
        argv,
        argh_kwargs,
    )


@_deprecated
def dispatch_command(function, argv=None, *, old_name_mapping_policy=True, **kwargs):
    """argh's ``dispatch_command``: one function, no command word.

    ``old_name_mapping_policy`` is accepted and ignored, as it is in argh when it is
    ``True`` -- which is the only value any fleet call site passes, and is cw's default
    everywhere.
    """
    argh_kwargs, parser_kwargs = _split_kwargs(kwargs)
    policy = parser_kwargs.pop("name_mapping_policy", None)
    return _run_with_streams(
        lambda: _cw_mk_parser(
            function, convention=_convention_for(policy), **parser_kwargs
        ),
        argv,
        argh_kwargs,
    )


@_deprecated
def add_commands(
    parser: argparse.ArgumentParser,
    functions,
    *,
    name_mapping_policy=None,
    group_name: Optional[str] = None,
    namespace: Optional[str] = None,
    group_kwargs: Optional[Mapping] = None,
    namespace_kwargs: Optional[Mapping] = None,
    func_kwargs: Optional[Mapping] = None,
) -> None:
    """argh's ``add_commands``, accepting the pre-0.30 spelling as well.

    ``namespace=`` / ``namespace_kwargs=`` were renamed to ``group_name=`` /
    ``group_kwargs=`` in argh 0.30 with no alias, which left ``wads/__init__.py:98``,
    ``hedger/__main__.py:26``, ``ke/__main__.py:24`` and ``ek/__main__.py:24`` passing a
    keyword nothing reads. Accepting both makes those four call sites work -- flag it in
    the migration notes, because "would crash" becoming "works" is still a change.

    >>> import argparse
    >>> from cw import compat as argh
    >>> def status():
    ...     '''Say how things are.'''
    >>> parser = argparse.ArgumentParser(prog='priv')
    >>> argh.add_commands(parser, [status], namespace='git_ops')
    >>> parser.format_usage()
    'usage: priv [-h] {git_ops} ...\\n'
    """
    _reject_func_kwargs(func_kwargs)
    _cw_add_commands(
        parser,
        functions,
        group_name=group_name,
        namespace=namespace,
        group_kwargs=group_kwargs,
        namespace_kwargs=namespace_kwargs,
        convention=_convention_for(name_mapping_policy),
    )


@_deprecated
def set_default_command(
    parser, function, *, name_mapping_policy=None, **kwargs
) -> None:
    """argh's ``set_default_command``: make ``function`` the parser's only command."""
    _cw_set_default_command(
        parser, function, convention=_convention_for(name_mapping_policy), **kwargs
    )


def arg(*flags: str, **add_argument_kwargs) -> Callable:
    """argh's ``@arg``: declare one argument's particulars on the function itself.

    Three statements, because cw's merge ladder already has a function-attribute tier
    (``func._cw['params'][param]``) for this to write into. ``_cw`` is a plain attribute on
    purpose: it is the documented contract, and it is what lets a repo declare CLI details
    without importing cw at all.

    Not deprecated by a warning, unlike the rest of this module -- it is a decorator
    evaluated at import time, so warning on it would fire before anybody could act, and it
    is the one name here whose target (a plain attribute) is a supported cw contract rather
    than a shim.

    >>> from cw import compat as argh
    >>> @argh.arg('-i', '--ignore', nargs='*')
    ... def quickstart(project_dir, *, ignore=None):
    ...     '''Start a project.'''
    >>> quickstart._cw['params']['ignore']
    {'nargs': '*', 'flags': ['-i', '--ignore']}
    """

    def decorate(func):
        param = _param_name_of(flags)
        # Innermost decorator runs first but must read last: argh's own `insert(0, ...)`.
        declared = {
            param: dict(add_argument_kwargs, flags=list(flags)),
            **getattr(func, "_cw", {}).get("params", {}),
        }
        func._cw = dict(getattr(func, "_cw", {}), params=declared)
        return func

    return decorate


@_deprecated
def confirm(action: str, default=None, skip=False, **kwargs):
    """argh's ``confirm``: a yes/no prompt, with argh's exact wording.

    >>> import io
    >>> from cw import compat as argh
    >>> argh.confirm('Go', skip=True) is None
    True
    """
    return cw.confirm(action, default=default, skip=skip, **kwargs)


class ArghParser(argparse.ArgumentParser):
    """argh's ``ArgumentParser`` subclass -- 27 fleet call sites.

    The three convenience methods, and nothing else. Note that this is the **only** class
    in cw that subclasses :class:`argparse.ArgumentParser`, and it exists solely because
    those 27 call sites already do. :func:`cw.mk_parser` returns a plain
    ``ArgumentParser``, which is what keeps ``argcomplete.autocomplete`` -- typed against
    ``argparse.ArgumentParser`` -- working for the ten fleet files marked
    ``# PYTHON_ARGCOMPLETE_OK``.

    >>> from cw import compat as argh
    >>> def ping():
    ...     return 'pong'
    >>> parser = argh.ArghParser(prog='demo')
    >>> parser.add_commands([ping])
    >>> parser.dispatch(['ping'], output_file=None)
    'pong\\n'
    """

    def add_commands(self, *args, **kwargs) -> None:
        """:func:`cw.compat.add_commands`, on this parser."""
        return add_commands(self, *args, **kwargs)

    def set_default_command(self, *args, **kwargs) -> None:
        """:func:`cw.compat.set_default_command`, on this parser."""
        return set_default_command(self, *args, **kwargs)

    def dispatch(self, *args, **kwargs):
        """:func:`cw.compat.dispatch`, on this parser."""
        return dispatch(self, *args, **kwargs)


class _Completion:
    """``argh.completion``, the submodule two fleet files reach into.

    A namespace rather than a module because there is exactly one function behind it, and
    a one-function module would be a file whose only content is an import.
    """

    @staticmethod
    def autocomplete(parser) -> bool:
        """``argh.completion.autocomplete``: offer ``parser`` to argcomplete."""
        return cw.enable_completion(parser)


#: ``argh.completion.autocomplete(parser)`` keeps working after the import swap.
completion = _Completion()


# =======================================================================================
# Helpers, and the three names that are deliberately absent
# =======================================================================================


def _param_name_of(flags) -> str:
    """``('-i', '--ignore') -> 'ignore'`` -- argh's ``naive_guess_func_arg_name``.

    >>> _param_name_of(('-i', '--ignore')), _param_name_of(('project',))
    ('ignore', 'project')
    """
    if len(flags) == 1:
        return flags[0].lstrip("-").replace("-", "_")
    for flag in flags:
        if flag.startswith("--"):
            return flag[2:].replace("-", "_")
    raise ValueError(
        f"cannot guess which parameter {flags} refers to. argh guesses from the long "
        f"flag, so give one -- @arg('-i', '--ignore') rather than @arg('-i')."
    )


def _reject_func_kwargs(func_kwargs) -> None:
    """Refuse a non-empty ``func_kwargs`` rather than mis-translating it.

    argh's ``func_kwargs`` is a mapping of **ArgumentParser** keywords applied to every
    subcommand's parser (``assembling.py:630-635``) -- *not* ``add_argument`` keywords, and
    therefore not a cw ``config``, whose leaves are per-parameter. cw has no per-command
    parser-keyword channel, and inventing one for a keyword **no fleet call site passes**
    would be shipping a feature to nobody.

    So it stays in the signature -- a call site that names it must not fail at import-shim
    time on a ``TypeError`` about an unexpected keyword -- and says so plainly if used. The
    first repo that actually needs it will produce a real requirement instead of a guess.
    """
    if func_kwargs:
        raise NotImplementedError(
            "cw.compat.add_commands accepts argh's `func_kwargs` but does not implement "
            "it: it is a mapping of ArgumentParser keywords applied to every subcommand, "
            "which cw has no channel for, and no fleet call site passes it. If you need "
            "it, build the parser yourself -- cw.mk_parser returns a plain "
            "argparse.ArgumentParser -- and open an issue on i2mint/cw."
        )


def _reject(parser_kwargs: Mapping, where: str) -> None:
    """Refuse leftover keywords with a message that says which call is wrong."""
    if parser_kwargs:
        raise TypeError(
            f"cw.compat.{where}() got unexpected keyword argument(s) "
            f"{', '.join(sorted(parser_kwargs))}. A parser that already exists takes no "
            f"build-time keywords; pass them to ArgumentParser() or to cw.mk_parser()."
        )


#: argh names with **zero** uses anywhere in the fleet, and why each one is not shipped.
#: A module ``__getattr__`` raises these rather than shipping a shim, because a shim that
#: does the wrong thing quietly is worse than the AttributeError it replaces.
_NOT_SHIPPED = {
    "named": (
        "argh's `named` renames a command. cw takes the name from a mapping KEY -- "
        "`{'load': do_load}` -- which also lets two commands share a name in different "
        "groups. (The shim originally specified for this wrote func._cw['name'], which "
        "nothing reads: it would have silently done nothing.)"
    ),
    "aliases": (
        "argh's `aliases` adds alternative command names. cw has no equivalent in v1; "
        "a mapping can name the same callable twice if you need one."
    ),
    "add_subcommands": (
        "argh's `add_subcommands` is `add_commands(..., group_name=...)` with the "
        "arguments in a different order. Use cw.compat.add_commands(parser, funcs, "
        "group_name='...')."
    ),
    "EntryPoint": "argh's `EntryPoint` is a registry object, not a function. Use a mapping.",
    "wrap_errors": "Zero fleet uses. Raise cw.CommandError from the command instead.",
    "raw_output": "Not a name -- it is a `dispatch` keyword, and it is accepted as one.",
    "ArghNamespace": "An argh internal. cw's parsers produce a plain argparse.Namespace.",
}


def __getattr__(name: str):
    """Explain the deliberately-absent names, rather than failing with a bare message.

    >>> from cw import compat as argh
    >>> try:
    ...     argh.named
    ... except AttributeError as exc:
    ...     print('does not ship `named`' in str(exc), 'mapping KEY' in str(exc))
    True True
    >>> argh.no_such_thing_at_all
    Traceback (most recent call last):
      ...
    AttributeError: module 'cw.compat' has no attribute 'no_such_thing_at_all'
    """
    if name in _NOT_SHIPPED:
        raise AttributeError(
            f"cw.compat does not ship `{name}`, and it has zero uses across the fleet's "
            f"argh-touching files. {_NOT_SHIPPED[name]}"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
