"""Tests for ``cw.base``: sentinels, ``CommandError``, ``Codec``, ``ArghHelpFormatter``.

The ``ArghHelpFormatter`` cases are *goldens*: each expected string was recorded from real
help output, not derived from any implementation. If one of them changes, the help column
changed, and that is a grammar break.
"""

import argparse

import pytest

from cw.base import (
    ArghHelpFormatter,
    Codec,
    CommandError,
    DFLT_HELP,
    HIDE,
    MISSING,
)


# --------------------------------------------------------------------------------------
# Sentinels


def test_sentinels_are_distinct_and_are_not_none():
    assert HIDE is not MISSING
    assert HIDE is not None and MISSING is not None
    assert HIDE is not False and MISSING is not False


def test_sentinels_repr_readably():
    assert repr(HIDE) == "cw.HIDE"
    assert repr(MISSING) == "cw.MISSING"


# --------------------------------------------------------------------------------------
# CommandError


def test_command_error_defaults_to_exit_code_one():
    assert CommandError().code == 1
    assert CommandError("boom").code == 1
    assert str(CommandError("boom")) == "boom"


def test_command_error_carries_an_explicit_code():
    assert CommandError("boom", code=7).code == 7


def test_command_error_code_is_keyword_only():
    with pytest.raises(TypeError):
        CommandError("boom", 7)


def test_command_error_is_catchable_as_an_exception():
    with pytest.raises(CommandError) as caught:
        raise CommandError("boom", code=3)
    assert caught.value.code == 3


# --------------------------------------------------------------------------------------
# Codec


@pytest.mark.parametrize(
    "value, expected",
    [
        ("abc", "ABC"),  # a str is decoded
        (3, 3),  # a non-str is not -- argparse's own `type=` rule
        (None, None),
        (True, True),
        (["a", "b"], ["A", "B"]),  # elementwise, for an nargs parameter
        ([], []),
        ([1, "a"], [1, "A"]),
    ],
)
def test_codec_applies_only_to_strings(value, expected):
    assert Codec(decode=str.upper)(value) == expected


def test_codec_never_sees_a_passthrough_value():
    codec = Codec(decode=str.upper, passthrough={"list"})
    assert codec("list") == "list"
    assert codec("bass") == "BASS"
    assert codec(["list", "bass"]) == ["list", "BASS"]


def test_codec_is_frozen():
    with pytest.raises(Exception):
        Codec(decode=str.upper).decode = str.lower


# --------------------------------------------------------------------------------------
# ArghHelpFormatter -- recorded goldens


def _help_of(*add_argument_calls, description=None):
    """Collapsed help text for a parser carrying the given ``add_argument`` calls."""
    parser = argparse.ArgumentParser(
        prog="x",
        add_help=False,
        description=description,
        formatter_class=ArghHelpFormatter,
    )
    for args, kwargs in add_argument_calls:
        parser.add_argument(*args, **kwargs)
    return " ".join(parser.format_help().split())


@pytest.mark.parametrize(
    "default, expected_column",
    [
        (None, "-"),  # None renders as a dash, not as "None"
        (False, "False"),
        (True, "True"),
        ("hi", "'hi'"),  # a str keeps its quotes
        (3, "3"),
        (1.5, "1.5"),
        ([], "[]"),
        ((), "()"),
    ],
)
def test_help_column_renders_repr_of_the_default(default, expected_column):
    help_text = _help_of((("--param",), dict(default=default, help=DFLT_HELP)))
    assert f"--param PARAM {expected_column}" in help_text


def test_help_column_renders_a_callable_default_by_name():
    def helper():
        pass  # pragma: no cover

    help_text = _help_of((("--param",), dict(default=helper, help=DFLT_HELP)))
    assert "--param PARAM 'helper'" in help_text


def test_an_explicit_help_string_keeps_the_appended_default():
    help_text = _help_of((("--param",), dict(default="e", help="an explicit one")))
    assert "--param PARAM an explicit one (default: 'e')" in help_text


def test_help_interpolates_prog_type_and_choices():
    help_text = _help_of(
        (("--p",), dict(default="w", help="prog is %(prog)s")),
        (("--t",), dict(type=int, default=1, help="type is %(type)s")),
        (("--c",), dict(choices=["a", "b"], default="a", help="pick %(choices)s")),
    )
    assert "--p P prog is x" in help_text
    assert "--t T type is int" in help_text
    assert "--c {a,b} pick a, b" in help_text


def test_description_is_not_rewrapped():
    """The ``RawDescriptionHelpFormatter`` half: line breaks in a description survive."""
    parser = argparse.ArgumentParser(
        prog="x",
        add_help=False,
        description="line one\n    line two, indented",
        formatter_class=ArghHelpFormatter,
    )
    assert "line one\n    line two, indented" in parser.format_help()


def test_the_look_is_reparametrizable_by_subclassing():
    """The three class attributes are the open-closed seam; no cw code needs editing."""

    class Loud(ArghHelpFormatter):
        NONE_IN_HELP = "NOTHING"
        CHOICES_SEPARATOR = " | "

    parser = argparse.ArgumentParser(prog="x", add_help=False, formatter_class=Loud)
    parser.add_argument("--param", default=None, help=DFLT_HELP)
    parser.add_argument("--c", choices=["a", "b"], default="a", help="%(choices)s")
    help_text = " ".join(parser.format_help().split())
    assert "--param PARAM NOTHING" in help_text
    assert "--c {a,b} a | b" in help_text
