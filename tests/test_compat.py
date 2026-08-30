"""`cw.compat` -- the transitional argh shim, and the four repairs it must not un-repair.

The tests that matter here are the ones asserting cw.compat is NOT a literal transcription
of argh's signatures: a migrated console script must keep exiting 2 on a usage error, must
be capturable, and must accept the keyword argh renamed without an alias.
"""

import argparse
import inspect
import io
import subprocess
import sys
import warnings

import pytest

import cw
from cw import compat


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """Most tests are not about the deprecation warning; the ones that are opt back in."""
    monkeypatch.setenv(compat.QUIET_ENV, "1")


def hello(name, *, loudly=False):
    """Greet someone."""
    return f"HELLO {name}" if loudly else f"hello {name}"


def add(a: int, b: int):
    """Add two numbers."""
    return a + b


# =======================================================================================
# The design gauge: every shim is thin
# =======================================================================================


class TestTheShimsAreThin:
    """Spec section 10's gauge: if a shim needed real work, the real API would be wrong."""

    #: The eleven names, plus the two the module docstring counts separately.
    SHIMS = (
        "add_commands",
        "arg",
        "confirm",
        "dispatch",
        "dispatch_command",
        "dispatch_commands",
        "set_default_command",
    )

    @pytest.mark.parametrize("name", SHIMS)
    def test_each_shim_is_three_statements_or_fewer(self, name):
        import ast
        import textwrap

        func = getattr(compat, name)
        func = getattr(func, "__wrapped__", func)  # past @_deprecated
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        body = tree.body[0].body
        statements = [
            node for node in body if not isinstance(node, (ast.Expr, ast.FunctionDef))
        ] + [n for n in body if isinstance(n, ast.FunctionDef)]
        assert len(statements) <= 3, f"{name} has {len(statements)} statements"

    def test_every_measured_argh_name_is_present(self):
        """The fleet's whole measured surface, by name."""
        for name in (
            "dispatch_commands",
            "dispatch_command",
            "ArghParser",
            "dispatch",
            "arg",
            "add_commands",
            "NameMappingPolicy",
            "CommandError",
            "completion",
            "confirm",
            "set_default_command",
        ):
            assert hasattr(compat, name), name


# =======================================================================================
# Repair 1: the shims must not swallow argparse's exit code
# =======================================================================================


class TestExitCodes:
    """A migrated console script must not start exiting 0 on a bad command line."""

    def test_a_usage_error_exits_2(self):
        with pytest.raises(SystemExit) as caught:
            compat.dispatch_commands([add], ["nope"], output_file=io.StringIO())
        assert caught.value.code == 2

    def test_a_usage_error_through_dispatch_command_exits_2(self):
        with pytest.raises(SystemExit) as caught:
            compat.dispatch_command(add, ["nope", "--bad"], output_file=io.StringIO())
        assert caught.value.code == 2

    def test_success_returns_None_like_argh(self):
        assert (
            compat.dispatch_commands(
                [add], ["add", "1", "2"], output_file=io.StringIO()
            )
            is None
        )

    def test_a_command_error_keeps_its_own_code(self):
        def boom():
            """Fail on purpose."""
            raise compat.CommandError("no", code=7)

        with pytest.raises(SystemExit) as caught:
            compat.dispatch_commands(
                [boom], ["boom"], output_file=io.StringIO(), errors_file=io.StringIO()
            )
        assert caught.value.code == 7

    def test_the_recorded_argh_golden_agrees_that_a_usage_error_is_2(self):
        """Not an opinion: the committed argh recording says so."""
        import json
        import os

        from cw import testing

        path = os.path.join(testing.DFLT_GOLDENS_DIR, "priv.json")
        golden = json.load(open(path, encoding="utf-8"))
        nope = next(c for c in golden["cases"] if c["argv"] == ["nope"])
        assert nope["returncode"] == 2

    def test_as_a_real_console_script(self):
        """End to end, because `$?` is what CI actually checks."""
        script = (
            "from cw import compat as argh\n"
            "def add(a: int, b: int):\n"
            "    'Add.'\n"
            "    return a + b\n"
            "argh.dispatch_commands([add])\n"
        )
        for argv, expected in ((["add", "2", "3"], 0), (["nope"], 2)):
            done = subprocess.run(
                [sys.executable, "-c", script, *argv], capture_output=True, text=True
            )
            assert done.returncode == expected, (argv, done.stdout, done.stderr)


# =======================================================================================
# Repairs 2 and 3: streams resolve at call time, and dispatch keywords are split out
# =======================================================================================


class TestStreams:
    """argh's worst defect, not reintroduced into the shim 19 call sites will use."""

    @pytest.mark.parametrize("name", ["output_file", "errors_file"])
    def test_no_stream_is_bound_in_a_signature_default(self, name):
        """`inspect.signature(...).parameters[name].default is not sys.stdout`."""
        for func in (
            compat.dispatch,
            compat.dispatch_commands,
            compat.dispatch_command,
        ):
            parameters = inspect.signature(func).parameters
            if name in parameters:
                assert parameters[name].default is not getattr(
                    sys, name[:-5] or "stdout"
                )

    def test_output_file_None_returns_the_string(self):
        assert (
            compat.dispatch_commands([add], ["add", "2", "3"], output_file=None)
            == "5\n"
        )

    def test_output_file_is_honoured_when_given(self):
        buffer = io.StringIO()
        compat.dispatch_commands([add], ["add", "2", "3"], output_file=buffer)
        assert buffer.getvalue() == "5\n"

    def test_errors_file_is_honoured_when_given(self):
        def boom():
            """Fail on purpose."""
            raise compat.CommandError("nope")

        errors = io.StringIO()
        with pytest.raises(SystemExit):
            compat.dispatch_commands(
                [boom], ["boom"], output_file=io.StringIO(), errors_file=errors
            )
        assert errors.getvalue() == "CommandError: nope\n"

    def test_an_argh_dispatch_keyword_does_not_reach_ArgumentParser(self):
        """Repair 3: `output_file=` must not become a TypeError from ArgumentParser."""
        assert (
            compat.dispatch_commands([add], ["add", "1", "1"], output_file=None)
            == "2\n"
        )

    def test_a_parser_keyword_still_reaches_ArgumentParser(self):
        out = compat.dispatch_commands([add], ["--help"], prog="calc", output_file=None)
        assert out.startswith("usage: calc")

    def test_the_unused_argh_keywords_are_accepted_rather_than_crashing(self):
        """Zero fleet sites pass one, but argh's signature accepts them all."""
        out = compat.dispatch_commands(
            [add],
            ["add", "1", "1"],
            output_file=None,
            raw_output=False,
            always_flush=False,
            skip_unknown_args=False,
            add_help_command=False,
        )
        assert out == "2\n"

    def test_dispatch_rejects_a_build_time_keyword_with_a_message_that_helps(self):
        parser = compat.ArghParser(prog="x")
        with pytest.raises(TypeError, match="cw.mk_parser"):
            compat.dispatch(parser, [], prog="other")


# =======================================================================================
# Repair 4: both spellings of the group keyword
# =======================================================================================


class TestBothGroupSpellings:
    """argh 0.30 renamed `namespace=` to `group_name=` with no alias. Four dead call sites."""

    def _usage(self, **kwargs):
        parser = argparse.ArgumentParser(prog="priv")
        compat.add_commands(parser, [hello], **kwargs)
        return parser.format_usage()

    def test_group_name_and_namespace_are_equivalent(self):
        assert self._usage(group_name="git_ops") == self._usage(namespace="git_ops")

    def test_the_group_really_appears(self):
        assert "{git_ops}" in self._usage(namespace="git_ops")

    def test_group_kwargs_and_namespace_kwargs_are_equivalent(self):
        title = {"title": "Git operations"}
        assert self._usage(group_name="g", group_kwargs=title) == self._usage(
            namespace="g", namespace_kwargs=title
        )


# =======================================================================================
# arg, NameMappingPolicy, ArghParser, completion, confirm
# =======================================================================================


class TestArg:
    """`@arg` writes the function-attribute tier, and is thin because that tier exists."""

    def test_it_writes_the_documented_attribute(self):
        @compat.arg("-i", "--ignore", nargs="*")
        def quickstart(project_dir, *, ignore=None):
            """Start a project."""

        assert quickstart._cw == {
            "params": {"ignore": {"nargs": "*", "flags": ["-i", "--ignore"]}}
        }

    def test_decorator_order_matches_arghs(self):
        """argh's outermost decorator inserts before the innermost."""

        @compat.arg("--alpha")
        @compat.arg("--beta")
        def f(*, alpha=None, beta=None):
            """Two options."""

        assert list(f._cw["params"]) == ["alpha", "beta"]

    def test_the_declaration_reaches_the_parser(self):
        @compat.arg("--ignore", nargs="*")
        def quickstart(project_dir, *, ignore=None):
            """Start a project."""

        # The `nargs='*'` really took: a bare `--ignore` parses to `[]`, epythet's
        # CI-critical case, and argparse renders the inferred short first.
        parser = cw.mk_parser(quickstart, prog="epythet")
        assert "[-i [IGNORE ...]]" in parser.format_usage()
        assert parser.parse_args(["x", "--ignore"]).ignore == []

    def test_a_lone_short_flag_names_the_parameter_the_way_argh_does(self):
        """argh's `naive_guess_func_arg_name`: one flag IS the name, dashes stripped."""

        @compat.arg("-i")
        def f(*, i=None):
            """One option."""

        assert list(f._cw["params"]) == ["i"]

    def test_two_shorts_and_no_long_flag_says_what_argh_needs(self):
        with pytest.raises(ValueError, match="long flag"):
            compat.arg("-i", "-x")(lambda: None)


class TestNameMappingPolicy:
    """Exported, which argh's own is not."""

    def test_it_is_exported(self):
        assert hasattr(compat, "NameMappingPolicy")

    def test_its_values_are_cws_naming_strings(self):
        assert (
            compat.NameMappingPolicy.BY_NAME_IF_HAS_DEFAULT == cw.BY_NAME_IF_HAS_DEFAULT
        )
        assert compat.NameMappingPolicy.BY_NAME_IF_KWONLY == cw.BY_NAME_IF_KWONLY

    def test_it_actually_changes_the_grammar(self):
        def f(alpha, beta=1):
            """Two parameters."""

        by_default = compat.dispatch_command(f, ["--help"], output_file=None)
        by_kwonly = compat.dispatch_command(
            f,
            ["--help"],
            output_file=None,
            name_mapping_policy=compat.NameMappingPolicy.BY_NAME_IF_KWONLY,
        )
        assert "[-b BETA]" in by_default
        assert "[beta]" in by_kwonly

    def test_add_commands_takes_it_too(self):
        parser = argparse.ArgumentParser(prog="x")
        compat.add_commands(
            parser,
            [hello],
            name_mapping_policy=compat.NameMappingPolicy.BY_NAME_IF_KWONLY,
        )
        assert "{hello}" in parser.format_usage()


class TestArghParser:
    """The 27 call sites that hold a parser object."""

    def test_the_three_methods_work_together(self):
        parser = compat.ArghParser(prog="demo", description="A demo.")
        parser.add_commands([hello, add])
        assert parser.dispatch(["hello", "world"], output_file=None) == "hello world\n"
        assert parser.dispatch(["add", "2", "3"], output_file=None) == "5\n"

    def test_set_default_command_makes_a_single_command_cli(self):
        parser = compat.ArghParser(prog="greet")
        parser.set_default_command(hello)
        assert (
            parser.dispatch(["world", "--loudly"], output_file=None) == "HELLO world\n"
        )

    def test_it_is_an_argparse_parser(self):
        assert isinstance(compat.ArghParser(), argparse.ArgumentParser)

    def test_but_mk_parser_still_returns_a_PLAIN_one(self):
        """The property argcomplete depends on is not weakened by the shim's existence."""
        assert type(cw.mk_parser(hello)) is argparse.ArgumentParser


class TestCompletionAndConfirm:
    def test_completion_autocomplete_is_reachable_as_a_submodule_would_be(self):
        parser = cw.mk_parser(hello, prog="x")
        assert compat.completion.autocomplete(parser) in (True, False)

    def test_confirm_forwards_to_cw(self):
        assert compat.confirm("Go", skip=True) is None

    def test_confirm_reads_an_answer(self):
        assert compat.confirm("Go", in_=io.StringIO("y\n"), out=io.StringIO()) is True


# =======================================================================================
# The three names that are deliberately absent
# =======================================================================================


class TestNotShipped:
    """A shim that quietly does the wrong thing is worse than the AttributeError."""

    @pytest.mark.parametrize("name", ["named", "aliases", "add_subcommands"])
    def test_it_raises_and_explains(self, name):
        with pytest.raises(AttributeError) as caught:
            getattr(compat, name)
        message = str(caught.value)
        assert "does not ship" in message and "zero uses" in message
        assert len(message) > 100, "an informative message, not a bare one"

    def test_an_ordinary_missing_name_gets_an_ordinary_message(self):
        with pytest.raises(AttributeError, match="has no attribute 'wibble'"):
            compat.wibble

    def test_named_would_have_been_a_silent_no_op(self):
        """Why it is absent: nothing reads `func._cw['name']`, including cw.commands."""

        def do_load():
            """Load."""

        do_load._cw = {"name": "load"}
        assert "do-load" in cw.mk_parser([do_load], prog="x").format_usage()


# =======================================================================================
# Deprecation, and the monkeypatch coact depends on
# =======================================================================================


class TestDeprecation:
    def test_each_name_warns_once(self, monkeypatch):
        monkeypatch.delenv(compat.QUIET_ENV, raising=False)
        monkeypatch.setattr(compat, "_WARNED", set())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compat.dispatch_commands([add], ["add", "1", "1"], output_file=None)
            compat.dispatch_commands([add], ["add", "1", "1"], output_file=None)
        assert len(caught) == 1
        assert issubclass(caught[0].category, DeprecationWarning)
        assert "transitional argh shim" in str(caught[0].message)

    def test_the_env_var_silences_it(self, monkeypatch):
        monkeypatch.setenv(compat.QUIET_ENV, "1")
        monkeypatch.setattr(compat, "_WARNED", set())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compat.dispatch_commands([add], ["add", "1", "1"], output_file=None)
        assert caught == []


class TestTheOneLineMigration:
    """`from cw import compat as argh` -- what the diff actually has to survive."""

    def test_monkeypatching_cli_argh_dispatch_commands_still_lands(self, monkeypatch):
        """coact/tests/test_cli.py:162 depends on this, and Wave 0 must not break it."""
        import types

        module = types.ModuleType("fake_cli")
        module.argh = compat
        calls = []
        monkeypatch.setattr(
            module.argh, "dispatch_commands", lambda *a, **k: calls.append(a)
        )
        module.argh.dispatch_commands([add], ["add"])
        assert calls == [([add], ["add"])]

    def test_the_module_answers_to_arghs_name(self):
        from cw import compat as argh

        assert argh.CommandError is cw.CommandError
        assert callable(argh.dispatch_commands)
        assert callable(argh.arg)


class TestFuncKwargs:
    """argh's `func_kwargs` is accepted, and refused out loud rather than mis-translated.

    It is a mapping of *ArgumentParser* keywords applied to every subcommand, not
    add_argument keywords, so it is not a cw `config`. Zero fleet call sites pass it. It
    stays in the signature so a call site naming it does not die on a TypeError at
    import-swap time, and says what it does not do if anyone actually uses it.
    """

    def test_it_is_in_the_signature(self):
        assert "func_kwargs" in inspect.signature(compat.add_commands).parameters

    def test_passing_None_or_nothing_is_fine(self):
        parser = compat.ArghParser(prog="x")
        compat.add_commands(parser, [hello], func_kwargs=None)
        assert "{hello}" in parser.format_usage()

    def test_actually_using_it_says_plainly_that_it_is_not_implemented(self):
        parser = compat.ArghParser(prog="x")
        with pytest.raises(NotImplementedError, match="no fleet call site passes it"):
            compat.add_commands(parser, [hello], func_kwargs={"help": "hi"})
