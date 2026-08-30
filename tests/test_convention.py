"""`cw.convention`: two values, nine fields, and no field that does nothing.

`Convention` is the third seam, and the rule it lives by is that a field which changes
nothing does not ship. So every field gets a test that flips it and watches the parser
change -- a negative control, not a description.
"""

import dataclasses
import io
import pathlib

import pytest

import cw


def echo(word, *, loud=False):
    """Echo."""
    return word


def helper_command(retries=3, region="eu"):
    """Two parameters, one shared first letter is not among them."""
    return retries


class TestTheTwoValues:
    def test_argh_is_the_bare_default(self):
        assert cw.ARGH == cw.Convention()

    def test_both_are_frozen_and_hashable(self):
        assert hash(cw.ARGH) == hash(cw.Convention())
        assert {cw.ARGH, cw.MODERN}
        with pytest.raises(dataclasses.FrozenInstanceError):
            cw.ARGH.short_flags = False

    def test_replace_round_trips(self):
        half = dataclasses.replace(cw.ARGH, resolve_hints=True)
        assert half.resolve_hints is True and half.naming == cw.ARGH.naming
        assert dataclasses.replace(half, resolve_hints=False) == cw.ARGH

    def test_argh_carries_arghs_seams_and_modern_carries_moderns(self):
        assert (cw.ARGH.decode, cw.ARGH.egress) == (cw.argh_decode, cw.argh_egress)
        assert (cw.MODERN.decode, cw.MODERN.egress) == (
            cw.modern_decode,
            cw.iterable_egress,
        )

    def test_modern_keeps_the_default_in_the_help_column(self):
        """ADR-0004 rule 4: with no docstring-derived help in v1, turning this off would
        leave an undocumented flag with an empty help column -- worse than argh, in the
        value the fleet is being told to adopt."""
        assert cw.MODERN.default_in_help is True
        assert "3" in cw.mk_parser(helper_command, convention=cw.MODERN).format_help()

    def test_formatter_class_is_not_a_field(self):
        """It is already an `ArgumentParser` keyword; two homes would need a precedence."""
        assert "formatter_class" not in {
            f.name for f in dataclasses.fields(cw.Convention)
        }


class TestEveryFieldChangesSomething:
    """One negative control per field. A field that survives its own flip is dead code."""

    def test_naming(self):
        def f(path="."): ...

        by_kwonly = dataclasses.replace(cw.ARGH, naming=cw.BY_NAME_IF_KWONLY)
        assert cw.mk_parser(f, prog="x").format_usage() == "usage: x [-h] [-p PATH]\n"
        assert (
            cw.mk_parser(f, prog="x", convention=by_kwonly).format_usage()
            == "usage: x [-h] [path]\n"
        )

    def test_short_flags(self):
        off = dataclasses.replace(cw.ARGH, short_flags=False)
        assert "-l, --loud" in cw.mk_parser(echo).format_help()
        assert "-l, --loud" not in cw.mk_parser(echo, convention=off).format_help()

    def test_hyphenate_commands(self):
        def two_words(): ...

        assert "two-words" in cw.mk_parser([two_words]).format_help()
        off = dataclasses.replace(cw.ARGH, hyphenate_commands=False)
        assert "two_words" in cw.mk_parser([two_words], convention=off).format_help()

    def test_hyphenate_groups(self):
        assert "git_ops" in cw.mk_parser({"git_ops": [echo]}).format_help()
        on = dataclasses.replace(cw.ARGH, hyphenate_groups=True)
        assert (
            "git-ops" in cw.mk_parser({"git_ops": [echo]}, convention=on).format_help()
        )

    def test_default_in_help(self):
        assert "3" in cw.mk_parser(helper_command).format_help()
        off = dataclasses.replace(cw.ARGH, default_in_help=False)
        assert "3" not in cw.mk_parser(helper_command, convention=off).format_help()

    def test_hints_when_declared(self):
        """argh switches hint inference off for the *whole function* on one override."""

        def add(*, a: int = None, b: int = None):
            return a + b

        config = {"a": {"help": "the first"}}
        assert (
            cw.dispatch(add, ["-a", "2", "-b", "3"], config=config, standalone=False)
            == "23"
        )  # both stayed strings
        assert (
            cw.dispatch(
                add,
                ["-a", "2", "-b", "3"],
                config=config,
                convention=cw.MODERN,
                standalone=False,
            )
            == 5
        )

    def test_resolve_hints(self):
        """PEP 563 blindness is argh's, and it is a named switch rather than a bug fix."""

        def migrate(*, to_version: "int" = None):
            return to_version

        assert cw.dispatch(migrate, ["--to-version", "4"], standalone=False) == "4"
        assert (
            cw.dispatch(
                migrate, ["--to-version", "4"], convention=cw.MODERN, standalone=False
            )
            == 4
        )

    def test_decode(self):
        def load(*, path: pathlib.Path = None):
            return path

        assert cw.dispatch(load, ["--path", "/tmp"], standalone=False) == "/tmp"
        assert cw.dispatch(
            load, ["--path", "/tmp"], convention=cw.MODERN, standalone=False
        ) == pathlib.Path("/tmp")

    def test_egress(self):
        def counted():
            return map(str, range(2))

        out = io.StringIO()
        cw.dispatch(counted, [], out=out)
        assert out.getvalue().startswith("<map object")
        out = io.StringIO()
        cw.dispatch(counted, [], convention=cw.MODERN, out=out)
        assert out.getvalue() == "0\n1\n"


def test_convention_imports_no_argparse():
    """It has no formatter reference to place, which is what makes the guard honest."""
    source = pathlib.Path(cw.convention.__file__).read_text()
    assert "import argparse" not in source
