"""`cw.compat` renders `--help` exactly as argh does, on every parser-building path.

The grammar differential next door builds parsers through `cw.mk_parser`, which defaults
`formatter_class`. The 25 fleet files that hold a parser object do not: they write
`ArghParser()` or `argparse.ArgumentParser()` and then `add_commands` / `set_default_command`
on it. That path had no formatter default, so the one-line migration this shim exists for
changed `--help` for every one of them -- a `None` default printing `None` where argh
printed `-`, a string default losing its quotes, and a multi-paragraph docstring reflowed
into one -- and 805 green tests plus a green parity gate saw none of it, because no test
here had ever rendered help.

This file is that test. It compares the **rendered** help of every `cw.compat` entry point
against live argh's, byte for byte, root parser and subparsers alike.
"""

import argparse
import io
from contextlib import redirect_stdout

import pytest

argh = pytest.importorskip("argh")

from argh.assembling import NameMappingPolicy  # noqa: E402

import cw  # noqa: E402
from cw import compat  # noqa: E402

POLICY = NameMappingPolicy.BY_NAME_IF_HAS_DEFAULT


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setenv(compat.QUIET_ENV, "1")
    monkeypatch.setenv("COLUMNS", "90")


def serve(host=None, port=8080, tag=", "):
    """Serve it.

    Second paragraph, deliberately separate. It is here because argh's formatter is a
    RawDescriptionHelpFormatter and argparse's stock one is not.
    """


def leaf(k=1):
    """A leaf command."""


def render(parser):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        parser.print_help()
    return buffer.getvalue()


def subparser(parser, name):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise AssertionError(f"no subparser {name!r}")


def test_the_case_this_file_exists_for_is_visible_at_all():
    """A guard on the guard: stock argparse really does render these three things
    differently, so a green test below means the default is right and not that the
    difference is unobservable."""
    stock = argparse.ArgumentParser(prog="demo")
    compat.set_default_command(stock, serve)
    stock.formatter_class = argparse.HelpFormatter
    assert "None" in render(stock) and "-\n" not in render(stock)


class TestArghParser:
    """The 27-call-site path: `ArghParser()` and then bind."""

    def test_it_defaults_the_formatter(self):
        assert compat.ArghParser(prog="x").formatter_class is cw.ArghHelpFormatter

    def test_set_default_command_help_is_identical(self):
        theirs = argh.ArghParser(prog="demo")
        argh.set_default_command(theirs, serve, name_mapping_policy=POLICY)
        mine = compat.ArghParser(prog="demo")
        compat.set_default_command(mine, serve)
        assert render(mine) == render(theirs)

    def test_add_commands_help_is_identical_root_and_leaf(self):
        theirs = argh.ArghParser(prog="demo")
        argh.add_commands(theirs, [serve, leaf], name_mapping_policy=POLICY)
        mine = compat.ArghParser(prog="demo")
        compat.add_commands(mine, [serve, leaf])
        assert render(mine) == render(theirs)
        assert render(subparser(mine, "serve")) == render(subparser(theirs, "serve"))

    def test_a_group_is_identical_too(self):
        theirs = argh.ArghParser(prog="demo")
        argh.add_commands(
            theirs,
            [leaf],
            group_name="archive",
            group_kwargs={"title": "Archive ops"},
            name_mapping_policy=POLICY,
        )
        mine = compat.ArghParser(prog="demo")
        compat.add_commands(
            mine, [leaf], group_name="archive", group_kwargs={"title": "Archive ops"}
        )
        assert render(mine) == render(theirs)
        assert render(subparser(mine, "archive")) == render(
            subparser(theirs, "archive")
        )

    def test_an_explicit_formatter_is_never_overridden(self):
        parser = compat.ArghParser(
            prog="x", formatter_class=argparse.RawTextHelpFormatter
        )
        assert parser.formatter_class is argparse.RawTextHelpFormatter


class TestAParserSomebodyElseBuilt:
    """The other documented path: a plain `argparse.ArgumentParser`.

    argh applies its own formatter to every subparser it creates even under a stock root
    parser, so cw promotes a stock formatter rather than propagating it.
    """

    def test_set_default_command_leaves_the_root_alone_because_argh_does(self):
        """The one place the obvious fix would have been WRONG.

        `set_default_command` on a plain parser looks like it should get cw's formatter --
        but argh leaves the root's `formatter_class` untouched there, so promoting it would
        have introduced a divergence while removing another. Verified against argh 0.31.3:
        `argh.set_default_command(argparse.ArgumentParser(), f).formatter_class` is
        `argparse.HelpFormatter`.
        """
        theirs = argparse.ArgumentParser(prog="demo")
        argh.set_default_command(theirs, serve, name_mapping_policy=POLICY)
        mine = argparse.ArgumentParser(prog="demo")
        cw.set_default_command(mine, serve)
        assert mine.formatter_class is argparse.HelpFormatter
        assert render(mine) == render(theirs)

    def test_add_commands_promotes_the_subparsers(self):
        theirs = argparse.ArgumentParser(prog="demo")
        argh.add_commands(theirs, [serve, leaf], name_mapping_policy=POLICY)
        mine = argparse.ArgumentParser(prog="demo")
        cw.add_commands(mine, [serve, leaf])
        assert mine.formatter_class is argparse.HelpFormatter  # root untouched, as argh
        assert subparser(mine, "serve").formatter_class is cw.ArghHelpFormatter
        assert render(mine) == render(theirs)
        assert render(subparser(mine, "serve")) == render(subparser(theirs, "serve"))

    def test_an_explicit_root_formatter_still_reaches_the_subparsers(self):
        """cw promotes only the stock formatter. argh overrides unconditionally, which
        would throw away an explicit `formatter_class=`; no fleet call site passes one to a
        parser it then hands to `add_commands`, and "explicit wins" is the rule cw states
        everywhere else."""
        mine = argparse.ArgumentParser(
            prog="demo", formatter_class=argparse.RawTextHelpFormatter
        )
        cw.add_commands(mine, [leaf])
        assert subparser(mine, "leaf").formatter_class is argparse.RawTextHelpFormatter


class TestArgDeclarations:
    """`cw.compat.arg` against `argh.arg`, for the two keywords that are not
    `add_argument` keywords."""

    def test_completer_reaches_the_action(self):
        def theirs(alpha=1): ...

        def mine(alpha=1): ...

        completer = lambda **kwargs: ["x"]  # noqa: E731
        theirs = argh.arg("--alpha", completer=completer)(theirs)
        mine = compat.arg("--alpha", completer=completer)(mine)
        their_parser = argparse.ArgumentParser(
            prog="p", formatter_class=argh.PARSER_FORMATTER
        )
        argh.set_default_command(their_parser, theirs, name_mapping_policy=POLICY)
        my_parser = cw.mk_parser(mine, prog="p")
        assert getattr(their_parser._actions[-1], "completer") is completer
        assert getattr(my_parser._actions[-1], "completer") is completer
        assert render(my_parser) == render(their_parser)

    def test_dest_names_the_parameter(self):
        def theirs(alpha=1, beta=2): ...

        def mine(alpha=1, beta=2): ...

        theirs = argh.arg("--al", dest="alpha", help="aliased")(theirs)
        mine = compat.arg("--al", dest="alpha", help="aliased")(mine)
        their_parser = argparse.ArgumentParser(
            prog="p", formatter_class=argh.PARSER_FORMATTER
        )
        argh.set_default_command(their_parser, theirs, name_mapping_policy=POLICY)
        assert render(cw.mk_parser(mine, prog="p")) == render(their_parser)


def test_two_commands_with_one_name_are_refused_by_both():
    """argh raises `conflicting subparser`; cw used to keep the last one silently."""

    def first():
        """First."""

    def second():
        """Second."""

    second.__name__ = "first"
    their_parser = argparse.ArgumentParser(prog="p")
    with pytest.raises(Exception) as their_error:
        argh.add_commands(their_parser, [first, second], name_mapping_policy=POLICY)
    assert "conflicting" in str(their_error.value)
    with pytest.raises(cw.CommandTreeError):
        cw.mk_parser([first, second], prog="p")
