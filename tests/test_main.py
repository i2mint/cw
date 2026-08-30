"""`python -m cw`: cw's own CLI, which is built with cw.

Dogfood. If cw could not build its own CLI comfortably -- a mapping of three plain
functions, one of which is a generator -- that would be worth knowing before 66 fleet
console scripts find out.
"""

import io
import subprocess
import sys

import pytest

import cw
from cw.__main__ import COMMANDS, main


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = cw.dispatch(COMMANDS, argv, out=out, err=err, prog="cw")
    return code, out.getvalue(), err.getvalue()


def test_the_three_commands_are_there():
    assert "specs" in cw.mk_parser(COMMANDS).format_help()
    code, out, _ = run(["--help"])
    assert code == 0
    for command in ("specs", "help", "parity"):
        assert command in out


def test_specs_shows_the_arguments_a_function_would_get():
    code, out, err = run(["specs", "cw.egress:confirm"])
    assert code == 0 and err == ""
    assert "action" in out and "--skip" in out


def test_specs_under_modern_differs_from_argh():
    _, under_argh, _ = run(["specs", "cw.egress:confirm"])
    _, under_modern, _ = run(["specs", "cw.egress:confirm", "-c", "modern"])
    assert under_argh != under_modern


def test_an_unknown_convention_is_one_line_and_a_non_zero_exit():
    code, out, err = run(["specs", "cw.egress:confirm", "-c", "nope"])
    assert code == 1 and out == ""
    assert (
        err
        == "CommandError: no convention named 'nope'. Choose one of: argh, modern.\n"
    )


def test_help_prints_the_help_cw_would_print():
    code, out, _ = run(["help", "cw.egress:write_lines"])
    assert code == 0 and out.startswith("usage: write_lines")


def test_parity_runs_the_real_gate(capsys):
    """`cw.testing` has landed, so this is now the gate itself, reached the other way.

    `capsys` rather than `run`'s buffers: cw redirects argparse's output, not a command
    body's, so `parity`'s report goes where the process's own `print` goes. That is the
    documented behaviour of `out=`, not an accident of this test.
    """
    assert run(["parity"])[0] == 0
    assert capsys.readouterr().out.strip().endswith(": identical")


def test_parity_says_so_if_cw_testing_is_missing(monkeypatch):
    """The honest failure, still asserted -- an installed cw could be missing its goldens.

    A `None` in `sys.modules` is the documented way to make an import of that name raise
    `ImportError`. The attribute has to go too: once a submodule has been imported, `from
    cw import testing` reads it off the package object and never consults `sys.modules` at
    all -- so patching only the one leaves the import succeeding and the simulation false.
    """
    monkeypatch.setitem(sys.modules, "cw.testing", None)
    monkeypatch.delattr(cw, "testing", raising=False)
    code, out, err = run(["parity"])
    assert code == 1 and out == ""
    assert "cw.testing is not available" in err


def test_parity_delegates_to_cw_testing_when_it_exists(monkeypatch):
    """`cw.testing` is a later issue; this pins the delegation it will be plugged into."""
    import types

    fake = types.ModuleType("cw.testing")
    seen = {}

    def fake_parity(goldens_dir=None):
        seen["dir"] = goldens_dir
        return 3

    fake.parity = fake_parity
    monkeypatch.setitem(sys.modules, "cw.testing", fake)
    monkeypatch.setattr(cw, "testing", fake, raising=False)
    code, out, _ = run(["parity", "-g", "goldens/"])
    assert (code, out, seen) == (3, "", {"dir": "goldens/"})


def test_it_actually_runs_as_a_module():
    """The one thing an in-process test cannot prove: `python -m cw` resolves."""
    result = subprocess.run(
        [sys.executable, "-m", "cw", "specs", "cw.egress:write_lines"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "lines" in result.stdout


def test_main_returns_an_exit_code():
    assert main(["specs", "cw.egress:write_lines"]) == 0
