"""argh's *no-policy* (legacy) mode against ``cw.ARGH_LEGACY`` and ``cw.compat``.

``ArghParser().add_commands(funcs)`` and ``set_default_command(parser, f)`` with no
``name_mapping_policy`` are not ``BY_NAME_IF_HAS_DEFAULT`` (``cw.ARGH``) and not
``BY_NAME_IF_KWONLY`` either: argh decides per function. This is the differential over the
shape matrix that showed it (i2mint/cw#46) and now pins ``cw.ARGH_LEGACY`` to it.

One deliberate difference: argh *raises* ``ArgumentNameMappingError`` for a function with
both a defaulted positional and a keyword-only parameter; cw reads it as
``BY_NAME_IF_HAS_DEFAULT`` (what argh's own message tells you to set) instead of crashing a
CLI that already works under cw.
"""

import argparse
import warnings

import pytest

argh = pytest.importorskip("argh")

from argh.assembling import NameMappingPolicy  # noqa: E402
from argh.assembling import ArgumentNameMappingError  # noqa: E402

import cw  # noqa: E402
from cw import compat  # noqa: E402

from .harness import (
    action_table,
    argh_parser,
    cw_parser,
    diff_tables,
    render_help,
)  # noqa: E402

#: Every combination of parameter kinds a CLI function can have, as a signature string.
SHAPES = [
    "x",
    "x, y",
    "x, y=1",
    "x, y: int = 3",
    "x, y: bool = True",
    "x, y: bool = False",
    "x, y=None",
    "x, y=1, z=2",
    "x, /, y=1",
    "x, y=1, /",
    "*, k",
    "*, k: int",
    "*, d=2",
    "*, k, d=2",
    "x, *, k",
    "x, *, d=2",
    "x, *, k, d=2",
    "x, *, flag: bool = False",
    "x, *args",
    "x, *args, k",
    "x, y=1, *args",
    "x, y=1, *, k",
    "x, y=1, *, d=2",
    "x, y=1, *args, k",
]


def make(signature):
    namespace = {}
    exec(f"def f({signature}):\n    '''Doc.'''\n", namespace)  # noqa: S102 - test input
    return namespace["f"]


def argh_legacy(func):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return argh_parser(func, policy=None)


def mixes_defaulted_positional_and_kwonly(func):
    import inspect

    params = list(inspect.signature(func).parameters.values())
    return any(
        p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        and p.default is not p.empty
        for p in params
    ) and any(p.kind is p.KEYWORD_ONLY for p in params)


@pytest.mark.parametrize("signature", SHAPES)
def test_arghlegacy_matches_argh_no_policy(signature):
    func = make(signature)
    if mixes_defaulted_positional_and_kwonly(func):
        # argh refuses; cw reads it as BY_NAME_IF_HAS_DEFAULT instead
        with pytest.raises(ArgumentNameMappingError):
            argh_legacy(func)
        expected = argh_parser(func, policy=NameMappingPolicy.BY_NAME_IF_HAS_DEFAULT)
    else:
        expected = argh_legacy(func)
    ours = cw_parser(func, convention=cw.ARGH_LEGACY)
    assert diff_tables(action_table(expected), action_table(ours)) == []
    assert render_help(expected) == render_help(ours)


@pytest.mark.parametrize("signature", SHAPES)
def test_compat_add_commands_and_set_default_command_match_argh(signature):
    func = make(signature)
    if mixes_defaulted_positional_and_kwonly(func):
        pytest.skip("argh raises for this shape; covered by the test above")
    mine = compat.ArghParser(prog="prog")
    mine.add_commands([func])
    theirs = argparse.ArgumentParser(prog="prog", formatter_class=argh.PARSER_FORMATTER)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        argh.add_commands(theirs, [func])
    assert render_help(_sub(mine)) == render_help(_sub(theirs))


def _sub(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["f"]
    raise AssertionError("no subparsers")


@pytest.mark.parametrize("signature", ["x, y=1", "*, k", "x, *, k, d=2"])
def test_explicit_policies_are_unchanged(signature):
    func = make(signature)
    for policy in NameMappingPolicy:
        parser = argparse.ArgumentParser(
            prog="prog", formatter_class=argh.PARSER_FORMATTER
        )
        ours = getattr(compat.NameMappingPolicy, policy.name)
        compat.add_commands(parser, [func], name_mapping_policy=ours)
        theirs = argparse.ArgumentParser(
            prog="prog", formatter_class=argh.PARSER_FORMATTER
        )
        argh.add_commands(theirs, [func], name_mapping_policy=policy)
        assert render_help(_sub(parser)) == render_help(_sub(theirs))


@pytest.mark.parametrize("signature", ["x, y=1", "*, k", "x, *, k, d=2"])
def test_argh_own_enum_is_read_by_name(signature):
    """Passing argh's own ``NameMappingPolicy`` (not cw.compat's) gives argh's grammar."""
    func = make(signature)
    for policy in NameMappingPolicy:
        parser = argparse.ArgumentParser(
            prog="prog", formatter_class=argh.PARSER_FORMATTER
        )
        compat.add_commands(parser, [func], name_mapping_policy=policy)
        theirs = argparse.ArgumentParser(
            prog="prog", formatter_class=argh.PARSER_FORMATTER
        )
        argh.add_commands(theirs, [func], name_mapping_policy=policy)
        assert render_help(_sub(parser)) == render_help(_sub(theirs))

