"""`cw.cli`: the parser cw builds, the stash it travels in, and the run that uses it.

Two constraints dominate this module and both are asserted here rather than described:

* `mk_parser` returns a **plain** `argparse.ArgumentParser` and performs no I/O, because
  `argcomplete.autocomplete` is argparse-typed and `mk_parser` is what a test inspects;
* everything `run` needs about a subcommand travels in **one reserved namespace key**,
  since a plain parser has nowhere else to put it -- and a collision with that key is an
  error naming it, never silent corruption.
"""

import argparse
import contextlib
import dataclasses
import functools
import io
import pathlib
import re
import sys
import warnings

import pytest

import cw
from cw.cli import RESERVED_DEST, add_commands, enable_completion, set_default_command
from cw.grammar import ArgSpec, GrammarError


def echo(word, *, loud=False):
    """Echo a word."""
    return word.upper() if loud else word


def counted():
    """Return a map object -- the shape where ARGH and MODERN differ."""
    return map(str, range(2))


def _leaf_help(parser, *path):
    """The `--help` of a subcommand, reached by walking the subparser actions."""
    for name in path:
        subparsers = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        parser = subparsers.choices[name]
    return parser.format_help()


def capture(obj, argv, **kwargs):
    """`(exit_code, stdout, stderr)` from one dispatch."""
    out, err = io.StringIO(), io.StringIO()
    code = cw.dispatch(obj, argv, out=out, err=err, prog="x", **kwargs)
    return code, out.getvalue(), err.getvalue()


class TestMkParserIsPlainAndPure:
    def test_returns_the_argparse_class_itself(self):
        """Not a subclass: `argcomplete.autocomplete(parser: ArgumentParser)` is typed."""
        assert type(cw.mk_parser(echo)) is argparse.ArgumentParser

    def test_subparsers_are_plain_too(self):
        parser = cw.mk_parser({"echo": echo, "grp": {"echo": echo}})
        subparsers = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        assert type(subparsers.choices["echo"]) is argparse.ArgumentParser
        assert type(subparsers.choices["grp"]) is argparse.ArgumentParser

    def test_performs_no_io(self):
        """Completion reads the environment and can exit the process; not at build time."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cw.mk_parser({"echo": echo, "grp": {"echo": echo}}, prog="x")
        assert (out.getvalue(), err.getvalue()) == ("", "")

    def test_does_not_fire_completion(self, monkeypatch):
        fired = []
        monkeypatch.setattr(
            cw.cli, "enable_completion", lambda *a, **k: fired.append(1)
        )
        cw.mk_parser(echo)
        assert fired == []
        cw.dispatch(echo, ["hi"], out=io.StringIO())
        assert fired == [1], "completion fires at dispatch time, as it does in argh"

    def test_parser_kwargs_pass_through_verbatim(self):
        parser = cw.mk_parser(
            echo, prog="x", description="D", epilog="E", allow_abbrev=False
        )
        assert (parser.prog, parser.description, parser.epilog) == ("x", "D", "E")
        assert parser.allow_abbrev is False

    def test_the_default_formatter_is_cws_and_reaches_subparsers(self):
        parser = cw.mk_parser({"echo": echo})
        assert parser.formatter_class is cw.ArghHelpFormatter
        subparsers = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        assert subparsers.choices["echo"].formatter_class is cw.ArghHelpFormatter

    def test_a_given_formatter_reaches_subparsers_too(self):
        parser = cw.mk_parser(
            {"echo": echo, "grp": {"echo": echo}},
            formatter_class=argparse.RawTextHelpFormatter,
        )
        subparsers = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        assert (
            subparsers.choices["echo"].formatter_class is argparse.RawTextHelpFormatter
        )
        assert (
            subparsers.choices["grp"].formatter_class is argparse.RawTextHelpFormatter
        )

    def test_an_unknown_parser_kwarg_names_cw_and_the_real_ones(self):
        with pytest.raises(TypeError) as caught:
            cw.mk_parser(echo, prgo="x")
        message = str(caught.value)
        assert "cw" in message and "argparse.ArgumentParser accepts" in message


class TestTheStash:
    def test_the_reserved_key_carries_the_command(self):
        parser = cw.mk_parser(echo)
        stash = parser.get_default(RESERVED_DEST)
        assert stash.func is echo and callable(stash.ingress)

    def test_a_parameter_of_the_reserved_name_is_an_informative_error(self):
        def clash(_cw=1): ...

        with pytest.raises(GrammarError, match=re.escape(RESERVED_DEST)):
            cw.mk_parser(clash)

    def test_the_reserved_key_never_reaches_the_function(self):
        seen = {}

        def catch_all(**rest):
            seen.update(rest)

        cw.dispatch(catch_all, [], standalone=False)
        assert seen == {}

    def test_the_convention_travels_with_the_parser(self):
        """`mk_parser(convention=MODERN)` + `run` must not silently get ARGH's egress."""
        out = io.StringIO()
        cw.run(cw.mk_parser(counted, convention=cw.MODERN), [], out=out)
        assert out.getvalue() == "0\n1\n"
        out = io.StringIO()
        cw.run(cw.mk_parser(counted), [], out=out)
        assert out.getvalue().startswith("<map object")

    def test_run_overrides_the_stashed_convention(self):
        out = io.StringIO()
        cw.run(cw.mk_parser(counted), [], convention=cw.MODERN, out=out)
        assert out.getvalue() == "0\n1\n"

    def test_run_config_reaches_the_ingress_codec(self):
        """The channel a build-and-run pass found missing from the published `run`."""
        seen = {}

        def load(pipeline="theremin"):
            seen["pipeline"] = pipeline

        parser = cw.mk_parser(load)
        cw.run(
            parser,
            ["--pipeline", "bass"],
            config={"pipeline": {"codec": str.upper}},
            standalone=False,
        )
        assert seen == {"pipeline": "BASS"}


class TestSeamsAreOneKeywordEach:
    def test_egress_overrides_the_conventions(self):
        out = io.StringIO()
        cw.dispatch(lambda: {"a": 1}, [], egress=cw.json_egress, out=out)
        assert out.getvalue() == '{\n  "a": 1\n}\n'

    def test_egress_none_takes_the_conventions(self):
        for convention, expected in ((cw.ARGH, "<map object"), (cw.MODERN, "0\n1\n")):
            out = io.StringIO()
            cw.dispatch(counted, [], convention=convention, egress=None, out=out)
            assert out.getvalue().startswith(expected)

    def test_decode_overrides_the_conventions(self):
        """Seam 1 as a keyword: a decode that makes every parameter an int."""
        seen = {}

        def add(a: str, b: str):
            seen.update(a=a, b=b)

        cw.dispatch(add, ["2", "3"], decode=lambda param, hint: int, standalone=False)
        assert seen == {"a": 2, "b": 3}

    def test_decode_none_takes_the_conventions(self):
        seen = {}

        def load(*, path: pathlib.Path = None):
            seen["path"] = path

        cw.dispatch(load, ["--path", "/tmp"], convention=cw.MODERN, standalone=False)
        assert seen["path"] == pathlib.Path("/tmp")
        cw.dispatch(load, ["--path", "/tmp"], convention=cw.ARGH, standalone=False)
        assert seen["path"] == "/tmp"

    def test_convention_is_one_act_at_one_call_site(self):
        dispatch = functools.partial(cw.dispatch, convention=cw.MODERN, prog="priv")
        out = io.StringIO()
        dispatch(counted, [], out=out)
        assert out.getvalue() == "0\n1\n"


class TestStandalone:
    def test_true_returns_an_exit_code(self):
        assert capture(echo, ["hi"]) == (0, "hi\n", "")

    def test_false_returns_the_functions_value_and_prints_nothing(self):
        out = io.StringIO()
        assert cw.dispatch(echo, ["hi"], out=out, standalone=False) == "hi"
        assert out.getvalue() == ""

    def test_false_lets_a_command_error_propagate(self):
        def risky():
            raise cw.CommandError("nope")

        with pytest.raises(cw.CommandError):
            cw.dispatch(risky, [], standalone=False)

    def test_false_lets_a_usage_error_propagate(self):
        with pytest.raises(SystemExit):
            cw.dispatch(echo, ["--nope"], standalone=False, err=io.StringIO())

    def test_a_bare_system_exit_is_success(self):
        """`SystemExit()` means "stop, successfully" -- to Python and therefore to cw."""

        def done():
            raise SystemExit

        assert capture(done, []) == (0, "", "")

    def test_a_system_exit_message_goes_to_stderr_and_exits_1(self):
        """What the interpreter would do, done one stack frame earlier."""

        def done():
            raise SystemExit("bye")

        assert capture(done, []) == (1, "", "bye\n")

    def test_a_usage_error_keeps_argparses_exit_code(self):
        """A console script that starts exiting 0 on a bad command line breaks CI."""
        code, _, err = capture(echo, ["hi", "--nope"])
        assert code == 2 and "unrecognized arguments" in err
        assert capture(echo, [])[0] == 2


class TestArgvIsAKeywordToo:
    def test_argv_as_a_keyword(self):
        """Four fleet call sites spell it this way, and `**parser_kwargs` would eat it."""
        assert cw.dispatch(echo, argv=["hi"], standalone=False) == "hi"
        assert cw.run(cw.mk_parser(echo), argv=["hi"], standalone=False) == "hi"

    def test_argv_none_reads_sys_argv(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "hi"])
        assert cw.dispatch(echo, standalone=False) == "hi"


class TestGroups:
    def test_group_kwargs_reach_both_places(self):
        parser = argparse.ArgumentParser(prog="x")
        add_commands(
            parser, [echo], group_name="arch", group_kwargs={"help": "H", "title": "T"}
        )
        assert "T" in parser.format_help()
        assert "H" not in parser.format_help(), "the parent row reads title, not help"
        subparsers = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        assert "H" in subparsers.choices["arch"].format_help()

    def test_a_group_row_survives_with_no_group_kwargs_at_all(self):
        """`help=` must be passed even as None, or argparse never makes the row."""
        parser = cw.mk_parser({"arch": [echo]}, prog="x")
        assert "arch" in parser.format_help()

    def test_the_namespace_spelling_still_works(self):
        """argh renamed `namespace=` to `group_name=` with no alias; cw takes both."""
        parser = argparse.ArgumentParser(prog="x")
        add_commands(parser, [echo], namespace="arch", namespace_kwargs={"title": "T"})
        assert "arch" in parser.format_help() and "T" in parser.format_help()

    def test_a_group_command_runs(self):
        assert capture({"arch": {"echo": echo}}, ["arch", "echo", "hi"]) == (
            0,
            "hi\n",
            "",
        )

    def test_two_add_commands_calls_share_one_subparsers_action(self):
        parser = argparse.ArgumentParser(prog="x")
        add_commands(parser, [echo])
        add_commands(parser, [counted], group_name="grp")
        assert "echo" in parser.format_help() and "grp" in parser.format_help()


class TestConfigKeysAreChecked:
    def test_an_unknown_command_key_is_a_hard_error(self):
        with pytest.raises(GrammarError, match="matche?s? no command"):
            cw.mk_parser({"echo": echo}, config={"ehco": {"word": {"help": "h"}}})

    def test_an_unknown_group_key_is_a_hard_error(self):
        with pytest.raises(GrammarError, match="matche?s? no command"):
            cw.mk_parser(
                {"grp": {"echo": echo}},
                config={"grp": {"ehco": {"word": {"help": "h"}}}},
            )

    def test_the_modern_group_rename_now_fails_loudly(self):
        """Under MODERN `git_ops` becomes `git-ops`; a stale config key must not vanish."""
        commands = {"git_ops": {"echo": echo}}
        config = {"git_ops": {"echo": {"word": {"help": "HELPED"}}}}
        assert "HELPED" in _leaf_help(
            cw.mk_parser(commands, config=config), "git_ops", "echo"
        )
        with pytest.raises(GrammarError, match="hyphenated by the convention"):
            cw.mk_parser(commands, config=config, convention=cw.MODERN)

    def test_the_hyphenated_key_works_under_modern(self):
        parser = cw.mk_parser(
            {"git_ops": {"echo": echo}},
            config={"git-ops": {"echo": {"word": {"help": "HELPED"}}}},
            convention=cw.MODERN,
        )
        assert "HELPED" in _leaf_help(parser, "git-ops", "echo")

    def test_an_unknown_parameter_key_is_a_hard_error(self):
        with pytest.raises(GrammarError, match="matches no parameter"):
            cw.mk_parser(echo, config={"wrod": {"help": "h"}})


class TestPartialWarnsAboutLeakedKeywords:
    def test_the_warning_names_the_keyword_and_the_hide_line(self):
        def packages_from_all_projects(project=None, *, config_type="setup.cfg"): ...

        partial = functools.partial(packages_from_all_projects, config_type="setup.cfg")
        with pytest.warns(UserWarning, match="cw.HIDE") as caught:
            cw.mk_parser(partial)
        assert len(caught) == 1
        assert "'config_type'" in str(caught[0].message)

    def test_hiding_it_silences_the_warning_and_removes_the_flag(self):
        def packages_from_all_projects(project=None, *, config_type="setup.cfg"): ...

        partial = functools.partial(packages_from_all_projects, config_type="setup.cfg")
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            parser = cw.mk_parser(partial, config={"config_type": cw.HIDE})
        assert "--config-type" not in parser.format_help()

    def test_an_ordinary_function_warns_about_nothing(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            cw.mk_parser(echo)


class TestSetDefaultCommandOnAHandBuiltParser:
    def test_run_works_on_a_parser_cw_did_not_build(self):
        parser = argparse.ArgumentParser(prog="count")
        set_default_command(parser, echo)
        out = io.StringIO()
        assert cw.run(parser, ["hi"], out=out) == 0
        assert out.getvalue() == "hi\n"

    def test_an_existing_description_is_not_overwritten(self):
        parser = argparse.ArgumentParser(prog="x", description="MINE")
        set_default_command(parser, echo)
        assert parser.description == "MINE"

    def test_the_docstring_becomes_the_description_otherwise(self):
        parser = argparse.ArgumentParser(prog="x")
        set_default_command(parser, echo)
        assert parser.description == "Echo a word."

    def test_a_flag_that_already_exists_is_an_informative_error(self):
        parser = argparse.ArgumentParser(prog="x")
        parser.add_argument("--loud")
        with pytest.raises(GrammarError, match="cannot add"):
            set_default_command(parser, echo)

    def test_a_parser_with_no_command_prints_its_usage(self):
        code, out, err = capture({}, [])
        assert code == 0 and out.startswith("usage:") and err == ""


class TestCompletion:
    def test_returns_whether_it_was_enabled(self):
        assert enable_completion(argparse.ArgumentParser()) in (True, False)

    def test_absent_argcomplete_is_not_fatal(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "argcomplete", None)
        with monkeypatch.context() as patched:
            patched.setattr(
                "builtins.__import__",
                _raising_import("argcomplete"),
            )
            assert enable_completion(argparse.ArgumentParser()) is False
            with pytest.raises(ImportError):
                enable_completion(argparse.ArgumentParser(), silent=False)


def _raising_import(blocked):
    real = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def fake(name, *args, **kwargs):
        if name == blocked:
            raise ImportError(f"no module named {name!r}")
        return real(name, *args, **kwargs)

    return fake


def test_the_argparse_import_perimeter():
    """The mechanical guard: only these four modules may know about argparse.

    Keeping type inference and call wiring free of argparse is the cheapest thing that
    stops the two concerns from re-fusing, and it is a mechanism rather than a promise.
    """
    package = pathlib.Path(cw.__file__).parent
    importers = {
        str(path.relative_to(package))
        for path in sorted(package.rglob("*.py"))
        if re.search(r"^\s*(import argparse|from argparse)", path.read_text(), re.M)
    }
    assert importers == {"base.py", "cli.py", "compat.py", "testing.py"}, (
        "expected argparse only in base.py, cli.py, compat.py and testing.py -- "
        "grammar, convention, commands, ingress and egress must stay free of it, so "
        "type inference and call wiring cannot quietly re-fuse with the parser"
    )


def test_the_parity_fixtures_take_argparse_as_an_argument_rather_than_importing_it():
    """`cw/tests/fixtures.py` ships inside the package, so it lives under the same rule.

    It needs both ``argparse`` and ``argh`` to describe how argh would have built each
    shape, and it takes them as *parameters* -- which is what lets the fixtures ship with
    cw while the argh they describe stays a developer-only install.
    """
    from cw.tests import fixtures

    source = pathlib.Path(fixtures.__file__).read_text()
    assert not re.search(r"^\s*(import argh|import argparse)", source, re.M)
    assert "def argh_build" in source or "argh_build=lambda argh, argparse" in source


def test_a_group_built_with_another_convention_keeps_it():
    """The stash is per subcommand, so a mixed-convention parser stays coherent."""

    def counted():
        return map(str, range(2))

    parser = cw.mk_parser({"plain": counted}, prog="x")
    add_commands(
        parser, {"counted": counted}, group_name="modern", convention=cw.MODERN
    )
    out = io.StringIO()
    cw.run(parser, ["plain"], out=out)
    assert out.getvalue().startswith("<map object")
    out = io.StringIO()
    cw.run(parser, ["modern", "counted"], out=out)
    assert out.getvalue() == "0\n1\n"


# =======================================================================================
# add_argument failures name cw, the function and the parameter
# =======================================================================================


class TestAnAddArgumentFailureIsInformative:
    """argparse refuses an argument in three different exception types.

    None of its messages names the function, the parameter or the flags. argh wraps all of
    them (`AssemblingError: {func}: cannot add {param} as {flags}: {reason}`), and cw must
    not be *worse* than the library it replaces at the one moment a migration goes wrong.
    Only `argparse.ArgumentError` was caught before, so `config=` -- a brand new surface
    with no argh equivalent, and therefore the likeliest place to make a mistake -- raised
    bare `ValueError`s and `TypeError`s.
    """

    @staticmethod
    def leaf(alpha=1):
        """A command."""

    @pytest.mark.parametrize(
        "leaf_config, underlying",
        [
            ({"bogus": 1}, TypeError),  # unknown add_argument keyword
            ({"nargs": 2, "metavar": ("A",)}, ValueError),  # metavar/nargs mismatch
            ({"action": "nope"}, ValueError),  # unknown action
            ({"type": "notacallable"}, ValueError),  # non-callable type
        ],
    )
    def test_every_argparse_refusal_is_wrapped(self, leaf_config, underlying):
        with pytest.raises(cw.GrammarError) as error:
            cw.mk_parser(self.leaf, config={"alpha": leaf_config}, prog="p")
        message = str(error.value)
        assert "leaf: cannot add 'alpha' as -a/--alpha" in message
        assert isinstance(error.value.__cause__, underlying)

    def test_a_duplicate_flag_is_wrapped_too(self):
        """The `argparse.ArgumentError` case, which was the only one caught before."""

        def two(pool=1, port=2): ...

        with pytest.raises(cw.GrammarError) as error:
            cw.mk_parser(
                two, config={"port": {"flags": ["-p", "--port"]}}, prog="p"
            ) if False else cw.mk_parser(
                two,
                config={"pool": {"flags": ["--pool"]}, "port": {"flags": ["--pool"]}},
                prog="p",
            )
        assert "cannot add 'port'" in str(error.value)
        assert isinstance(error.value.__cause__, argparse.ArgumentError)

    def test_the_underscore_footgun_names_its_documented_fix(self):
        """A leading-underscore parameter hyphenates into `--` / `---pool`, which argparse
        rejects. cw reproduces that argh bug on purpose (D2), so the message has to carry
        the workaround `cw.HIDE` that the grammar's docstring promises."""

        def serve(host="0.0.0.0", _pool=4): ...

        with pytest.raises(cw.GrammarError) as error:
            cw.mk_parser(serve, prog="p")
        message = str(error.value)
        assert "serve: cannot add '_pool' as --/---pool" in message
        assert "cw.HIDE" in message

    def test_and_hiding_it_really_does_fix_it(self):
        def serve(host="0.0.0.0", _pool=4):
            return f"{host}/{_pool}"

        assert (
            cw.dispatch(
                serve, [], config={"_pool": cw.HIDE}, standalone=False, prog="p"
            )
            == "0.0.0.0/4"
        )


class TestTheBoundKeywordWarning:
    """A `functools.partial`'s pre-bound keyword still showing as a flag.

    It fires on every invocation of a CLI that has one -- `--help` included -- so its text
    is part of the product: it must name the command whose config key closes it, carry no
    `id()` (which would make it differ every run), and be silenceable without changing the
    CLI.
    """

    @staticmethod
    def packages(project=None, *, config_type="setup.cfg"):
        """Packages."""

    @property
    def bound(self):
        return functools.partial(self.packages, config_type="setup.cfg")

    def test_it_names_the_command_and_carries_no_address(self):
        with pytest.warns(cw.BoundKeywordWarning) as caught:
            cw.mk_parser({"packages-from-all": self.bound}, prog="p")
        message = str(caught[0].message)
        assert "config={'packages-from-all': {'config_type': cw.HIDE}}" in message
        assert "0x" not in message
        assert "packages" in message

    def test_a_single_command_needs_no_command_key(self):
        with pytest.warns(cw.BoundKeywordWarning) as caught:
            cw.mk_parser(self.bound, prog="p")
        assert "config={'config_type': cw.HIDE}" in str(caught[0].message)

    def test_it_can_be_silenced_without_changing_the_parser(self, monkeypatch):
        monkeypatch.setenv("CW_QUIET", "1")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            parser = cw.mk_parser({"go": self.bound}, prog="p")
        assert "--config-type" in _sub(parser, "go").format_help()

    def test_filtering_the_category_works_too(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warnings.filterwarnings("ignore", category=cw.BoundKeywordWarning)
            cw.mk_parser({"go": self.bound}, prog="p")

    def test_hiding_the_parameter_still_silences_it(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            parser = cw.mk_parser(
                {"go": self.bound}, config={"go": {"config_type": cw.HIDE}}, prog="p"
            )
        assert "--config-type" not in _sub(parser, "go").format_help()


class TestArgcompleteCompleters:
    """`completer=` is argcomplete's per-argument hook, and not an `add_argument` keyword.

    cw is argparse-based *specifically* so that argcomplete keeps working for the ten fleet
    files marked `# PYTHON_ARGCOMPLETE_OK`; a shim through which those repos migrate must
    be able to express a completer, and it used to raise a raw argparse `TypeError`.
    """

    def test_a_config_leaf_carries_it_to_the_action(self):
        def serve(host="0.0.0.0"): ...

        completer = lambda **kwargs: ["localhost"]  # noqa: E731
        parser = cw.mk_parser(
            serve, config={"host": {"completer": completer}}, prog="p"
        )
        assert parser._actions[-1].completer is completer

    def test_it_is_not_passed_to_add_argument(self):
        """The failure mode: `_StoreAction.__init__() got an unexpected keyword
        argument 'completer'`, with no mention of cw anywhere in it."""
        spec = ArgSpec("host", ["--host"], extra={})
        spec.completer = print
        assert "completer" not in spec.add_argument_kwargs()


def _sub(parser, name):
    """The subparser called ``name``."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise AssertionError(f"no subparser {name!r}")


class TestASeamNamedOnTheWrongCall:
    """`egress=` is a real seam; it is just not a `mk_parser` keyword.

    ADR-0001 says each seam is one keyword argument, and it is -- but not every seam is on
    every entry point, because `egress` runs after the call and `mk_parser` never calls
    anything. Blaming argparse and listing argparse's parameters was true and useless.
    """

    def test_egress_on_mk_parser_names_the_right_call(self):
        with pytest.raises(TypeError) as error:
            cw.mk_parser(echo, egress=lambda *a, **k: 0)
        message = str(error.value)
        assert "cw.run and cw.dispatch" in message
        assert "dataclasses.replace(cw.ARGH, egress=" in message

    def test_ingress_says_there_is_no_such_keyword_anywhere(self):
        with pytest.raises(TypeError) as error:
            cw.mk_parser(echo, ingress=print)
        assert "no `ingress=` keyword" in str(error.value)

    def test_an_ordinary_typo_still_blames_argparse(self):
        with pytest.raises(TypeError, match="argparse.ArgumentParser accepts"):
            cw.mk_parser(echo, prgo="x")
