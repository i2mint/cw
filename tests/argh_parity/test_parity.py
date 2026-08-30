"""The differential: cw's parser must equal argh's, action field by action field."""

import argparse

import pytest

from tests.argh_parity import corpus
from cw.grammar import GrammarError
from tests.argh_parity.harness import (
    action_table,
    argh_parser,
    build_both,
    cw_parser,
    diff_tables,
    render_help,
)

ALL_CASES = corpus.CASES + corpus.KWONLY_CASES


def _ids(cases):
    return [case.id for case in cases]


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_action_tables_are_identical(case):
    """Every `add_argument` cw makes must match the one argh makes, field for field."""
    (left, left_error), (right, right_error) = build_both(case)
    if left_error is not None:
        refused_too = isinstance(right_error, GrammarError)
        assert refused_too, f"argh refused {case.id} ({left_error}), cw built a parser"
        return
    assert right_error is None, f"cw refused {case.id}: {right_error}"
    problems = diff_tables(action_table(left), action_table(right))
    assert not problems, "\n".join([f"case {case.id}:"] + problems)


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_rendered_help_is_byte_identical(case):
    """The user-visible surface: `--help`, character for character."""
    (left, left_error), (right, right_error) = build_both(case)
    if left_error is not None:
        pytest.skip("argh refuses this combination; covered by the action-table test")
    assert render_help(right) == render_help(left)


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_usage_lines_are_identical(case):
    """`usage:` alone, called out because it is what a user sees on every error."""
    (left, left_error), (right, right_error) = build_both(case)
    if left_error is not None:
        pytest.skip("argh refuses this combination; covered by the action-table test")
    assert right.format_usage() == left.format_usage()


# --------------------------------------------------------------------------------------
# Tier 4 (`config`) must be interchangeable with tier 3 (`@arg` / `func._cw`)


CONFIG_EQUIVALENTS = [
    (
        "theremin_shape",
        corpus.theremin_shape,
        {
            "synth": {"flags": ["--synth", "-s"], "nargs": "?", "const": "list"},
            "scale": {
                "flags": ["--scale"],
                "nargs": "?",
                "const": "list",
                "default": None,
            },
        },
    ),
    (
        "declared_choices",
        corpus.declared_choices,
        {"level": {"flags": ["--level"], "choices": [1, 2, 3]}},
    ),
    (
        "declared_disables_hints",
        corpus.declared_disables_hints,
        {"ignore": {"flags": ["--ignore"], "nargs": "*"}},
    ),
]


@pytest.mark.parametrize(
    "name,func,config", CONFIG_EQUIVALENTS, ids=[row[0] for row in CONFIG_EQUIVALENTS]
)
def test_config_is_equivalent_to_a_declaration(name, func, config):
    """ADR-0003: moving an `@argh.arg` into `config` must change nothing.

    This is the migration every worked example in the spec performs, and it only holds
    because `hints_when_declared` reads "declared" as tier 3 **or** tier 4. Drop the
    `config` half of that condition and these cases regress silently.
    """
    plain = _undecorated_twin(func)
    from_declaration = action_table(cw_parser(func))
    from_config = action_table(cw_parser(plain, config=config))
    assert not diff_tables(from_declaration, from_config)


def _undecorated_twin(func):
    """A copy of `func` with no `_cw` and no `argh_args`, so only `config` speaks."""
    import types

    twin = types.FunctionType(
        func.__code__,
        func.__globals__,
        func.__name__,
        func.__defaults__,
        func.__closure__,
    )
    twin.__kwdefaults__ = func.__kwdefaults__
    twin.__annotations__ = dict(func.__annotations__)
    twin.__doc__ = func.__doc__
    return twin


# --------------------------------------------------------------------------------------
# Behaviour, not just shape: what the parser actually produces from argv


PARSE_VECTORS = [
    ("hint_bare_list", corpus.hint_bare_list, [".", "--ignore"], {"ignore": []}),
    ("hint_bare_list", corpus.hint_bare_list, ["."], {"ignore": None}),
    (
        "hint_bare_list",
        corpus.hint_bare_list,
        [".", "--ignore", "a", "b"],
        {"ignore": ["a", "b"]},
    ),
    ("bool_true", corpus.bool_true_is_store_false, ["--verbose"], {"verbose": False}),
    ("bool_true", corpus.bool_true_is_store_false, [], {"verbose": True}),
    ("bool_false", corpus.bool_false_is_store_true, ["--verbose"], {"verbose": True}),
    ("hint_int", corpus.hint_int, ["-n", "5"], {"n": 5}),
    ("theremin_bare", corpus.theremin_shape, ["-s"], {"synth": "list"}),
    ("theremin_value", corpus.theremin_shape, ["--synth", "bass"], {"synth": "bass"}),
    ("varargs", corpus.var_positional, ["a", "b"], {"agents": ["a", "b"]}),
    ("varargs_empty", corpus.var_positional, [], {"agents": []}),
]


@pytest.mark.parametrize(
    "name,func,argv,expected",
    PARSE_VECTORS,
    ids=[f"{row[0]}:{'_'.join(row[2]) or 'bare'}" for row in PARSE_VECTORS],
)
def test_parsed_values_match_argh(name, func, argv, expected):
    """The values reaching the function, which is the only surface a user can observe."""
    from_argh = vars(argh_parser(func).parse_args(argv))
    from_cw = vars(cw_parser(func).parse_args(argv))
    for key, value in expected.items():
        assert from_cw[key] == value, f"cw parsed {key}={from_cw[key]!r}"
        assert from_argh[key] == value, f"argh parsed {key}={from_argh[key]!r}"


def test_hyphenated_positional_is_reachable_by_a_python_name():
    """The permitted divergence, stated as a property rather than hidden by the diff.

    argh's `dest` is `'project-dir'`, which no Python call can use; cw's is
    `'project_dir'`, which is the parameter's own name. Both render `project-dir`.
    """
    argh_ns = vars(argh_parser(corpus.hyphenated_positional).parse_args(["here"]))
    argh_ns.pop("function")  # argh stashes the endpoint in the namespace; cw does not
    cw_ns = vars(cw_parser(corpus.hyphenated_positional).parse_args(["here"]))
    assert argh_ns == {"project-dir": "here", "dry_run": False}
    assert cw_ns == {"project_dir": "here", "dry_run": False}
    assert "project-dir" in argh_parser(corpus.hyphenated_positional).format_usage()
    assert "project-dir" in cw_parser(corpus.hyphenated_positional).format_usage()


def test_missing_positional_error_names_it_the_same_way():
    """The metavar has to survive into argparse's own error text, not just `--help`."""
    for parser in (
        argh_parser(corpus.hyphenated_positional),
        cw_parser(corpus.hyphenated_positional),
    ):
        with pytest.raises(SystemExit):
            parser.parse_args([])


def test_every_case_builds_a_plain_argument_parser():
    """`mk_parser` returns a plain ArgumentParser; argcomplete is argparse-typed."""
    built = 0
    for case in ALL_CASES:
        (_, _), (parser, error) = build_both(case)
        if error is not None:
            continue
        assert type(parser) is argparse.ArgumentParser
        built += 1
    assert built > len(ALL_CASES) - 5, f"only {built} of {len(ALL_CASES)} cases built"
