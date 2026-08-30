"""Record the argh goldens for :func:`cw.testing.parity`. **Developer-only. Run once.**

    python misc/record_goldens.py                     # record every shape
    python misc/record_goldens.py theremin xa         # or just these

``argh`` is not a runtime dependency of cw, and it is not a **test** dependency either.
That is deliberate and it is the reason this script lives under ``misc/`` rather than under
``tests/``: the same landing window ships ``wads licence-check``, and a cw whose own test
suite pulled LGPL-3.0-or-later argh would be that tool's first and most embarrassing
finding. Recording is a one-time act on a machine that happens to have argh installed. The
committed goldens carry no argh code -- only the bytes argh produced.

What is recorded, per case: exit code, stdout, stderr, the normalised ``usage:`` line, and
(for ``--help`` cases) the full help body as a tier-3 snapshot. The environment is pinned by
:data:`cw.testing.RECORDING_ENV`, so re-recording on a second machine with the same argh and
Python produces a byte-identical file.

To re-record after changing a fixture::

    pip install 'argh==0.31.3'
    python misc/record_goldens.py
    git diff cw/tests/goldens/       # review EVERY line: this is the thing being asserted
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argh  # noqa: E402 - the whole point of this file
import importlib.metadata  # noqa: E402

from cw.testing import (  # noqa: E402
    GOLDEN_VERSION,
    RECORDING_ENV,
    _record,
    capture,
    pinned_env,
    write_golden,
)
from cw.tests import fixtures  # noqa: E402

#: The argh this corpus is recorded against. A different one is not automatically wrong,
#: but it is automatically a decision, so the script refuses rather than guessing.
PINNED_ARGH = "0.31.3"

GOLDENS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cw",
    "tests",
    "goldens",
)


def argh_outcome(shape, argv) -> dict:
    """Run one case through argh, capturing what a shell would see.

    The parser is rebuilt per case on purpose. argh's ``@arg`` mutates the function it
    decorates, and ``add_commands`` mutates the parser; a parser reused across cases would
    be recording the accumulated state of the previous ones.
    """
    fixtures.use_command_error(argh.CommandError)
    parser = shape.argh_build(argh, argparse)
    return capture(lambda: _dispatch(parser, argv))


def _dispatch(parser, argv) -> int:
    """``argh.dispatch``, normalised to "returns an exit code".

    argh's ``dispatch`` returns ``None`` and lets ``SystemExit`` out; :func:`capture` turns
    the ``SystemExit`` into a code, and this turns the ``None`` into ``0``. Together they
    reproduce what the interpreter does with a console script's ``main()``.
    """
    argh.dispatch(parser, list(argv))
    return 0


def record(shape) -> dict:
    """The golden for one shape."""
    with pinned_env():
        cases = [
            _record(lambda a: argh_outcome(shape, a), argv) for argv in shape.cases
        ]
    return {
        "cw_golden": GOLDEN_VERSION,
        "shape": shape.name,
        "models": shape.models,
        "pins": shape.pins,
        "rows": sorted(shape.rows),
        "prog": [shape.prog],
        "env": dict(RECORDING_ENV),
        "newlines": "lf",
        "recorded_with": {
            "tool": "argh",
            "version": importlib.metadata.version("argh"),
            "python": ".".join(str(n) for n in sys.version_info[:3]),
        },
        "note": (
            "Recorded in-process from real argh against cw/tests/fixtures.py. argh is not "
            "a dependency of cw; see misc/record_goldens.py."
        ),
        "cases": cases,
    }


def main(argv=None) -> int:
    """Record the named shapes, or all of them."""
    names = list(argv if argv is not None else sys.argv[1:]) or list(fixtures.SHAPES)
    found = importlib.metadata.version("argh")
    if found != PINNED_ARGH:
        print(
            f"refusing to record: this corpus is pinned to argh {PINNED_ARGH}, "
            f"but argh {found} is installed. Install the pinned version, or change "
            f"PINNED_ARGH deliberately and re-record everything.",
            file=sys.stderr,
        )
        return 1
    for name in names:
        shape = fixtures.shape_named(name)
        golden = record(shape)
        path = os.path.join(GOLDENS_DIR, f"{shape.name}.json")
        write_golden(golden, path)
        print(f"{shape.name:12s} {len(golden['cases']):3d} cases -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
