"""Run a CLI call and collect ``(exit code, stdout, stderr)`` -- stdlib only.

Lives in its own module so that a test needing it does **not** thereby need ``argh``.
It used to be a private helper inside ``tests/argh_parity/test_cli_parity.py``, which
made every importer inherit that package's argh requirement; ``tests/test_fleet_shapes.py``
imported it for assertions that are cw's own, and so failed to collect under
``pip install -e '.[test]'`` -- the extra cw's CI actually installs.
"""

import contextlib
import io


def capture(call):
    """``call(out, err) -> code``, with argparse's own output captured into the buffers.

    Both halves matter. ``out``/``err`` are handed to the call because that is how cw is
    told where to write; the ``redirect_*`` wrappers catch what argparse prints on its own
    account (``--help``, ``usage:``, ``error:``), which it sends to the real streams.

    >>> capture(lambda out, err: print('hi', file=out) or 0)
    (0, 'hi\\n', '')

    A ``SystemExit`` is an answer, not a crash -- it is what argparse raises on a usage
    error, and its code is the process's exit code:

    >>> capture(lambda out, err: (_ for _ in ()).throw(SystemExit(2)))
    (2, '', '')
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = call(out, err)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()
