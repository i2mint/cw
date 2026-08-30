"""Two fleet shapes that only exist once there is a parser: `t/priv` and `t/theremin`.

The grammar differential already pins how a *signature* becomes arguments. These two are
about what the assembled CLI does, and they are the two the migration is judged on:

* **`t/priv`** -- 47 top-level commands taken from a list of strings, three groups built by
  zero-argument factories, and one `functools.partial` whose command name argh gets wrong
  and whose pre-bound keyword argh re-exposes. argh cannot express this shape at all
  (it crashes on the partial and rejects a mapping), so the assertions are cw's own, and
  each one names the defect it removes.
* **`t/theremin`** -- ten declared arguments, five of them `nargs='?' const='list'`, and
  explicit short flags on parameters whose inferred short flag was suppressed by a
  collision. argh *can* express this, so it is a differential.
"""

import functools
import io

import pytest

import cw

from tests.capture import capture as _capture

# argh is a **dev** extra; CI installs `cw[test]`, which has none. Only the one test
# below that actually diffs against argh needs it, so the module imports without it and
# that test skips itself -- everything else here asserts cw's own behaviour and must run
# in the environment CI really uses.
try:
    import argh
except ImportError:  # pragma: no cover -- exercised by the `cw[test]` CI leg
    argh = None

requires_argh = pytest.mark.skipif(
    argh is None, reason="the live differential needs argh: pip install -e '.[dev]'"
)


# ------------------------------------------------------------------ t/priv, shape only


def packages_from_all_projects(proj_folder=None, *, config_type="setup.cfg"):
    """List packages found in every project."""
    return f"{proj_folder}:{config_type}"


def parse_pth_paths(pth_file="~/.pth"):
    """Parse a .pth file."""
    return pth_file


def git_status():
    """Show status."""
    return "clean"


def pkg_list():
    """List packages."""
    return "listed"


#: What `priv/commands.py` looks like after the migration: the `__all__` key is the
#: command name, and the three group sources are called, because Python has parentheses.
PRIV_COMMANDS = {
    "packages_from_all_setup_cfgs": functools.partial(
        packages_from_all_projects, config_type="setup.cfg"
    ),
    "parse_pth_paths": parse_pth_paths,
    "git_ops": {"status": git_status},
    "pkg": [pkg_list],
}

#: The partial pre-binds `config_type`; do not re-expose it as a flag.
PRIV_CONFIG = {"packages-from-all-setup-cfgs": {"config_type": cw.HIDE}}


def priv(argv):
    with pytest.warns(UserWarning) if not PRIV_CONFIG else _no_warning():
        return _capture(
            lambda out, err: cw.dispatch(
                PRIV_COMMANDS,
                list(argv),
                config=PRIV_CONFIG,
                out=out,
                err=err,
                prog="priv",
            )
        )


def _no_warning():
    import warnings

    return warnings.catch_warnings()


class TestPrivShape:
    def test_the_partial_gets_the_name_from_its_key(self):
        """Today's CLI registers `packages-from-all-projects` -- a different function."""
        code, out, _ = priv(["--help"])
        assert code == 0
        assert "packages-from-all-setup-cfgs" in out
        assert "packages-from-all-projects" not in out

    def test_the_pre_bound_keyword_is_gone_from_the_cli(self):
        _, out, _ = priv(["packages-from-all-setup-cfgs", "--help"])
        assert "--config-type" not in out

    def test_and_the_function_still_receives_it(self):
        """`cw.HIDE` removes the argument, not the value."""
        assert priv(["packages-from-all-setup-cfgs", "-p", "P"])[1] == "P:setup.cfg\n"

    def test_group_names_are_verbatim_under_argh(self):
        """`priv git_ops` is a string in priv's README and in two of its own messages."""
        _, out, _ = priv(["--help"])
        assert "git_ops" in out and "git-ops" not in out

    def test_a_group_command_runs(self):
        assert priv(["git_ops", "status"]) == (0, "clean\n", "")

    def test_a_factory_result_becomes_a_group_too(self):
        assert priv(["pkg", "pkg-list"]) == (0, "listed\n", "")

    def test_a_top_level_command_is_hyphenated_from_its_key(self):
        assert priv(["parse-pth-paths"])[1] == "~/.pth\n"

    def test_without_the_hide_line_the_leak_is_warned_about(self):
        with pytest.warns(UserWarning, match="config_type"):
            cw.mk_parser(PRIV_COMMANDS, prog="priv")


# --------------------------------------------------------- t/theremin, as a differential


def _declare(*flags, **kwargs):
    """`@argh.arg` and cw's `func._cw` from one call, so the two cannot drift.

    When argh is absent only cw's half is written, which is what the two cw-only
    assertions below need; the differential that needs both is skipped.
    """

    def decorate(func):
        if argh is not None:
            func = argh.arg(*flags, **kwargs)(func)
        name = (flags[-1] if len(flags) > 1 else flags[0]).lstrip("-").replace("-", "_")
        params = dict(getattr(func, "_cw", {}).get("params", {}))
        func._cw = {"params": {name: dict(kwargs, flags=list(flags)), **params}}
        return func

    return decorate


@_declare("-p", "--pipeline", nargs="?", const="list", default="theremin")
@_declare("-s", "--synth", nargs="?", const="list", default="sine")
@_declare("-k", "--scale", nargs="?", const="list", default=None)
@_declare("-n", "--seconds", default=10)
def theremin_cli(pipeline="theremin", synth="sine", scale=None, seconds=10):
    """Run the theremin."""
    return f"{pipeline}|{synth}|{scale}|{seconds}"


THEREMIN_ARGVS = [
    [],
    ["--help"],
    ["-p"],
    ["-p", "bass"],
    ["--pipeline"],
    ["--synth"],
    ["-s", "saw"],
    ["--scale"],
    ["-n", "3"],
]


@requires_argh
@pytest.mark.parametrize("argv", THEREMIN_ARGVS, ids=lambda a: " ".join(a) or "(none)")
def test_theremin_matches_argh(argv):
    """Including the two things that look like special cases and are neither.

    `--synth [SYNTH], -s [SYNTH]` renders long-first because the declared flags are
    *appended* to the inferred ones, and `--scale` gets no short flag at all because
    `synth`, `scale` and `seconds` all start with `s`. No line of cw knows about either.
    """
    # Imported here, not at module scope: that module needs argh at import time.
    from tests.argh_parity.test_cli_parity import run_argh

    left = run_argh(lambda p: p.set_default_command(theremin_cli), argv)
    right = _capture(
        lambda out, err: cw.dispatch(
            theremin_cli, list(argv), out=out, err=err, prog="x"
        )
    )
    for name, a, b in zip(("exit", "stdout", "stderr"), left, right):
        assert a == b, f"{argv} {name}: argh={a!r} cw={b!r}"


def test_the_declared_flags_are_appended_not_replaced():
    help_text = cw.mk_parser(theremin_cli, prog="theremin").format_help()
    assert "--synth [SYNTH], -s [SYNTH]" in help_text
    assert "-k, --scale" not in help_text and "--scale [SCALE]" in help_text


def test_the_sentinel_survives_a_codec():
    """The one case a `codec=` exists for, and the reason it is not at argparse's `type=`.

    `type=` would be applied to the string *default* and to the `const` as well, so a
    resolver at that site would be handed `'theremin'` and `'list'` and asked to import
    them. The ingress site sees the value after parsing, and `passthrough` keeps the
    sentinel out of the resolver's hands.
    """
    resolved = {"bass": "BASS-PIPELINE", "theremin": "THEREMIN-PIPELINE"}
    config = {
        "pipeline": {
            "codec": cw.Codec(decode=resolved.__getitem__, passthrough={"list"})
        }
    }
    outcomes = {
        tuple(argv): cw.dispatch(theremin_cli, argv, config=config, standalone=False)
        for argv in ([], ["-p"], ["-p", "bass"])
    }
    assert outcomes == {
        (): "THEREMIN-PIPELINE|sine|None|10",
        ("-p",): "list|sine|None|10",
        ("-p", "bass"): "BASS-PIPELINE|sine|None|10",
    }
