"""cw's own CLI, built with cw.

``python -m cw`` is dogfood: every command below is a plain function, and the parser that
serves them is :func:`cw.dispatch` on a mapping. If cw could not build its own CLI
comfortably, that would be worth knowing before 66 fleet console scripts find out.

Three commands::

    python -m cw specs  'pkg.mod:func'     # the command-line arguments cw would build
    python -m cw help   'pkg.mod:func'     # the --help cw would print for it
    python -m cw parity                    # the one-command migration test

``specs`` is the one that earns its place day to day: it answers "what flags does this
function actually get, and why did that one not get a short flag" without building, running
or importing anybody's ``__main__``.
"""

import sys

from cw.commands import import_object
from cw.convention import ARGH, MODERN
from cw.grammar import specs_for_function

__all__ = ["specs", "help_for", "parity", "COMMANDS"]

#: The conventions ``--convention`` accepts, by the name you type.
CONVENTIONS = {"argh": ARGH, "modern": MODERN}


def _convention_named(name: str):
    """The :class:`cw.Convention` called ``name``, or a message naming the real ones."""
    try:
        return CONVENTIONS[name]
    except KeyError:
        from cw.base import CommandError

        raise CommandError(
            f"no convention named {name!r}. Choose one of: {', '.join(CONVENTIONS)}."
        ) from None


def specs(ref, *, convention="argh"):
    """Show the command-line arguments cw would build for a function.

    REF is a 'pkg.mod:name' reference, e.g. 'json:dumps'.
    """
    func = import_object(ref)
    for spec in specs_for_function(func, convention=_convention_named(convention)):
        args, kwargs = spec.add_argument_args()
        shown = ", ".join(f"{key}={value!r}" for key, value in sorted(kwargs.items()))
        yield f"{' '.join(args):24s} {shown}"


def help_for(ref, *, convention="argh"):
    """Print the --help that cw would produce for a function.

    REF is a 'pkg.mod:name' reference, e.g. 'json:dumps'.
    """
    from cw.cli import mk_parser

    parser = mk_parser(
        ref, convention=_convention_named(convention), prog=ref.rpartition(":")[2]
    )
    return parser.format_help()


def parity(goldens_dir=None):
    """Run the recorded-golden migration test (cw.testing).

    Its result is an exit code rather than something to print, so it is raised rather than
    returned -- `SystemExit` is how a command says "this is the process's answer".
    """
    try:
        from cw import testing
    except ImportError as exc:
        from cw.base import CommandError

        raise CommandError(f"cw.testing is not available: {exc}") from exc
    raise SystemExit(testing.parity(goldens_dir))


#: ``python -m cw``'s command tree. A plain mapping, exactly like a fleet repo's.
COMMANDS = {"specs": specs, "help": help_for, "parity": parity}


def main(argv=None) -> int:
    """The ``python -m cw`` entry point."""
    from cw.cli import dispatch

    return dispatch(COMMANDS, argv, prog="cw", description=__doc__.split("\n\n")[0])


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
