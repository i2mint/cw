"""`cw.grammar` on its own terms: the rules, the errors, and the named acceptance cases.

The differential against live argh lives in `tests/argh_parity/`. This module tests the
things a differential cannot: that the errors are informative, that `cw.MODERN`'s
improvements exist and default OFF, and that the two acceptance cases issue #16 names by
hand come out right.
"""

import dataclasses
import enum
import functools
import inspect
import pathlib
import typing

import pytest

from cw.base import HIDE, MISSING, Codec
from cw.convention import ARGH, MODERN, Convention
from cw.grammar import (
    ArgSpec,
    GrammarError,
    argh_decode,
    cli_name,
    command_name,
    modern_decode,
    specs_for_function,
)


def flags_of(func, **kwargs):
    return [spec.flags for spec in specs_for_function(func, **kwargs)]


def kwargs_of(func, **kwargs):
    return {
        spec.param_name: spec.add_argument_kwargs()
        for spec in specs_for_function(func, **kwargs)
    }


# --------------------------------------------------------------------------------------
# The two acceptance cases issue #16 names


def test_theremin_shape_renders_long_flag_first():
    """`--synth [SYNTH], -s [SYNTH]`, and `--scale` with no short flag at all.

    Both fall out of two rules meeting -- the collision rule suppresses every short flag
    on a signature whose parameters all start with `s`, and the append-merge rule then
    puts the explicitly declared `-s` AFTER the inferred `--synth`. Neither rule mentions
    the other, and no code anywhere asks for this ordering.
    """

    def theremin(synth="sine", scale=None, seconds=3): ...

    config = {
        "synth": {"flags": ["--synth", "-s"], "nargs": "?", "const": "list"},
        "scale": {"flags": ["--scale"], "nargs": "?", "const": "list"},
    }
    assert flags_of(theremin, config=config) == [
        ["--synth", "-s"],
        ["--scale"],
        ["--seconds"],
    ]


def test_collision_suppression_at_scale():
    """34 parameters, the `wads pack populate_pkg_dir` shape: most short flags vanish.

    The property that matters is not which flags survive but that survival is a fact
    about the whole signature: adding one parameter can silently take another's short
    flag away, which is why cw writes the rule as data rather than as a heuristic.
    """
    from tests.argh_parity.corpus import many_parameters

    specs = specs_for_function(many_parameters)
    with_short = [s.param_name for s in specs if len(s.flags) == 2]
    assert len(specs) == 34
    assert with_short == [
        "url",
        "keywords",
        "overwrite",
        "manifest",
        "gitignore",
        "workflow",
        "branch",
        "token",
        "quiet",
    ]


# --------------------------------------------------------------------------------------
# The grammar rules, one test each


def test_bool_true_gives_store_false():
    def f(*, verbose=True, quiet=False): ...

    assert kwargs_of(f)["verbose"]["action"] == "store_false"
    assert kwargs_of(f)["quiet"]["action"] == "store_true"


def test_h_is_always_lost_to_help():
    def f(*, host="localhost"): ...

    assert flags_of(f) == [["--host"]]
    # ...unless the parser does not add --help itself; the flag is only taken away
    # because something else already owns it.
    assert flags_of(f, parser_adds_help=False) == [["-h", "--host"]]


def test_var_keyword_is_silently_dropped():
    def f(alpha, *, beta=1, **configs): ...

    assert [s.param_name for s in specs_for_function(f)] == ["alpha", "beta"]


def test_var_positional_is_a_trailing_nargs_star_positional():
    def f(*agents): ...

    (spec,) = specs_for_function(f)
    assert spec.flags == ["agents"]
    assert spec.add_argument_kwargs()["nargs"] == "*"


def test_bare_list_annotation_yields_nargs_star():
    """The load-bearing one: `epythet quickstart . --ignore` with zero values."""

    def f(project_dir=".", ignore: list = None): ...

    assert kwargs_of(f)["ignore"]["nargs"] == "*"


def test_choices_supply_the_type():
    def f(*, level=None): ...

    assert (
        kwargs_of(f, config={"level": {"choices": [1, 2, 3]}})["level"]["type"] is int
    )


def test_hide_removes_the_argument_but_not_the_parameter():
    def f(host="0.0.0.0", pool=None): ...

    assert flags_of(f, config={"pool": HIDE}) == [["--host"]]


def test_one_override_disables_hints_for_the_whole_function():
    """argh's `can_use_hints = not declared_args`, extended to `config` by ADR-0003.

    `m` is annotated `float` but defaults to the int `4`, so the two inference paths
    disagree about it and the test can see which one ran.
    """

    def f(*, n: float = 3, m: float = 4): ...

    assert kwargs_of(f)["m"]["type"] is float
    with_override = kwargs_of(f, config={"n": {"help": "count"}})
    assert with_override["m"]["type"] is int  # the default-value guesser, alone
    assert with_override["m"]["default"] == 4
    # ...and MODERN keeps hints on, which is the whole point of the switch.
    modern = kwargs_of(f, convention=MODERN, config={"n": {"help": "count"}})
    assert modern["m"]["type"] is float


def test_declared_nargs_loses_to_a_list_default():
    """An argh quirk, reproduced knowingly: the default-value guess runs last."""

    def f(*, xs=[]): ...

    assert kwargs_of(f, config={"xs": {"nargs": "+"}})["xs"]["nargs"] == "*"


def test_falsy_nargs_in_an_override_is_ignored():
    """argh's `if other.nargs:` -- there is no spelling that unsets an inferred nargs.

    Both places an inferred `nargs` can live are covered: the `extra` dict (guessed from
    a list default) and the `nargs` field itself (`*args`, and an optional positional
    under `BY_NAME_IF_KWONLY`). A `dict.update` merge would silently drop the second.
    """

    def from_default(*, xs=[]): ...

    def from_var_positional(*agents): ...

    def from_optional_positional(x=1): ...

    assert kwargs_of(from_default, config={"xs": {"nargs": None}})["xs"]["nargs"] == "*"
    override = {"agents": {"nargs": None}}
    assert kwargs_of(from_var_positional, config=override)["agents"]["nargs"] == "*"
    kwonly = dataclasses.replace(ARGH, naming="by_name_if_kwonly")
    shape = kwargs_of(
        from_optional_positional, convention=kwonly, config={"x": {"nargs": ""}}
    )
    assert shape["x"]["nargs"] == "?"


def test_flags_append_they_do_not_replace():
    def f(*, ignore=None): ...

    assert flags_of(f, config={"ignore": {"flags": ["--skip"]}}) == [
        ["-i", "--ignore", "--skip"]
    ]


def test_function_attribute_is_read_never_written():
    """Tier 3 is a plain attribute so a repo can declare CLI details without importing cw."""

    def f(*, level=None): ...

    f._cw = {"params": {"level": {"choices": [1, 2, 3]}}}
    before = dict(f._cw["params"]["level"])
    assert kwargs_of(f)["level"]["choices"] == [1, 2, 3]
    assert f._cw["params"]["level"] == before


# --------------------------------------------------------------------------------------
# Errors: informative, eager, and never silent


def test_a_config_key_naming_no_parameter_is_an_error():
    def serve(host="0.0.0.0", port=8080): ...

    with pytest.raises(GrammarError) as caught:
        specs_for_function(serve, config={"prot": {"help": "typo"}})
    assert "matches no parameter" in str(caught.value)
    assert "host, port" in str(caught.value)


def test_a_config_key_is_accepted_when_the_function_takes_kwargs():
    def serve(host="0.0.0.0", **extra): ...

    assert flags_of(serve, config={"anything": {"help": "h"}}) == [
        ["--host"],
        ["--anything"],
    ]


def test_turning_a_positional_into_an_option_is_an_error():
    def f(path): ...

    with pytest.raises(GrammarError) as caught:
        specs_for_function(f, config={"path": {"flags": ["--path"]}})
    assert "positional in the signature" in str(caught.value)


def test_a_non_mapping_override_says_so():
    def f(path): ...

    with pytest.raises(GrammarError) as caught:
        specs_for_function(f, config={"path": "help text"})
    assert "must be a mapping" in str(caught.value)


def test_command_name_without_a_name_says_what_to_do_instead():
    def pack_go(): ...

    assert command_name(pack_go) == "pack-go"
    assert command_name(pack_go, hyphenate=False) == "pack_go"
    with pytest.raises(TypeError) as caught:
        command_name(functools.partial(pack_go))
    assert 'cw.dispatch({"my-command": obj})' in str(caught.value)


def test_a_decode_returning_nonsense_says_so():
    def f(*, n: int = 1): ...

    convention = dataclasses.replace(ARGH, decode=lambda param, hint: 42)
    with pytest.raises(GrammarError) as caught:
        specs_for_function(f, convention=convention)
    assert "None, a callable or a mapping" in str(caught.value)


def test_a_decode_may_return_a_bare_callable():
    def f(*, n: "whatever" = 1): ...

    convention = dataclasses.replace(ARGH, decode=lambda param, hint: float)
    assert kwargs_of(f, convention=convention)["n"]["type"] is float


# --------------------------------------------------------------------------------------
# Seam 1: the two decode functions


PARAM = inspect.Parameter("x", inspect.Parameter.KEYWORD_ONLY)


@pytest.mark.parametrize(
    "hint,expected",
    [
        (str, {"type": str}),
        (int, {"type": int}),
        (float, {"type": float}),
        (bool, {"type": bool}),
        (list, {"nargs": "*"}),
        (list[str], {"nargs": "*", "type": str}),
        (typing.List[int], {"nargs": "*", "type": int}),
        (typing.Literal["a", "b"], {"choices": ("a", "b"), "type": str}),
        (typing.Optional[int], {"type": int, "required": False}),
        (typing.Optional[list[int]], {"nargs": "*", "type": int, "required": False}),
        (dict, {}),
        ("int | None", {}),
        (pathlib.Path, {}),
    ],
)
def test_argh_decode_covers_exactly_arghs_if_chain(hint, expected):
    assert argh_decode(PARAM, hint) == expected


class Colour(enum.Enum):
    RED = "r"
    BLUE = "b"


def test_modern_decode_unwraps_optional():
    assert modern_decode(PARAM, typing.Optional[int]) == {"type": int}
    assert modern_decode(PARAM, typing.Optional[list[str]]) == {
        "nargs": "*",
        "type": str,
    }


def test_modern_decode_reads_an_enum_by_name_then_value():
    decoded = modern_decode(PARAM, Colour)
    assert decoded["choices"] == (Colour.RED, Colour.BLUE)
    assert decoded["type"]("RED") is Colour.RED
    assert decoded["type"]("b") is Colour.BLUE
    with pytest.raises(ValueError):
        decoded["type"]("green")


def test_modern_decode_maps_pure_paths_to_path():
    assert modern_decode(PARAM, pathlib.Path) == {"type": pathlib.Path}
    assert modern_decode(PARAM, pathlib.PurePosixPath) == {"type": pathlib.Path}


def test_modern_decode_falls_through_to_argh_decode():
    assert modern_decode(PARAM, int) == argh_decode(PARAM, int)


def test_moderns_improvements_default_off():
    """D2: every improvement ships as a named `Convention` value, and defaults OFF."""

    def f(
        *, colour: Colour = Colour.RED, root: pathlib.Path = None, n: int | None = 1
    ): ...

    assert ARGH.decode is argh_decode
    under_argh = kwargs_of(f)
    assert "choices" not in under_argh["colour"]
    assert "type" not in under_argh["root"]
    assert under_argh["n"]["type"] is int and under_argh["n"]["required"] is False
    under_modern = kwargs_of(f, convention=MODERN)
    assert under_modern["colour"]["choices"] == (Colour.RED, Colour.BLUE)
    assert under_modern["root"]["type"] is pathlib.Path
    assert "required" not in under_modern["n"]


# --------------------------------------------------------------------------------------
# The negative control: no dead switches


def _pep563_twin(func):
    """`func` with its annotations left as strings, the way PEP 563 leaves them."""

    def wrapper(*args, **kwargs):  # pragma: no cover - never called
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    wrapper.__signature__ = inspect.signature(func)
    wrapper.__annotations__ = {
        name: hint if isinstance(hint, str) else hint.__name__
        for name, hint in func.__annotations__.items()
    }
    return wrapper


def _switch_cases():
    """One representative function per `Convention` field, chosen to make it bite.

    Each function is picked so that the two inference paths *disagree* about it -- a
    `float` annotation on a parameter defaulting to an int, an `Optional[int]` that only
    `modern_decode` unwraps -- because a case where they agree cannot tell you which one
    ran, and a negative control that cannot fail is not a control.
    """

    def naming(alpha, beta=1, *, gamma=2): ...

    def short_flags(*, verbose=False): ...

    def default_in_help(*, n=1): ...

    def disagreeing_hint(*, n: float = 1): ...

    def optional_hint(*, n: typing.Optional[int] = 1): ...

    return [
        ("naming", "by_name_if_kwonly", naming, None),
        ("short_flags", False, short_flags, None),
        ("default_in_help", False, default_in_help, None),
        ("hints_when_declared", True, disagreeing_hint, {"n": {"help": "count"}}),
        ("resolve_hints", True, _pep563_twin(disagreeing_hint), None),
        ("decode", modern_decode, optional_hint, None),
    ]


def _shape(func, **kwargs):
    """Everything a switch could change: the flag spellings and the add_argument kwargs."""
    return [
        (spec.flags, spec.add_argument_kwargs())
        for spec in specs_for_function(func, **kwargs)
    ]


@pytest.mark.parametrize(
    "field,value,func,config", _switch_cases(), ids=[row[0] for row in _switch_cases()]
)
def test_every_convention_switch_changes_something(field, value, func, config):
    """A field that changes nothing is speculative generality and does not ship."""
    baseline = _shape(func, config=config)
    flipped = _shape(
        func, convention=dataclasses.replace(ARGH, **{field: value}), config=config
    )
    assert baseline != flipped, f"Convention.{field} changed nothing"


def test_hyphenate_switches_live_on_the_name_function():
    """`hyphenate_commands` / `hyphenate_groups` are read by `cli_name`, not by specs."""
    assert cli_name("git_ops") == "git-ops"
    assert cli_name("git_ops", hyphenate=False) == "git_ops"
    assert ARGH.hyphenate_commands is True and ARGH.hyphenate_groups is False
    assert MODERN.hyphenate_commands is True and MODERN.hyphenate_groups is True


def test_convention_is_frozen_and_hashable():
    assert Convention() == ARGH
    assert hash(Convention()) == hash(ARGH)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ARGH.short_flags = False


# --------------------------------------------------------------------------------------
# ArgSpec itself


def test_add_argument_args_repairs_a_hyphenated_positional():
    assert ArgSpec("project_dir", ["project-dir"]).add_argument_args() == (
        ("project_dir",),
        {"metavar": "project-dir"},
    )
    assert ArgSpec("path", ["path"]).add_argument_args() == (("path",), {})


def test_add_argument_args_leaves_an_explicit_metavar_alone():
    spec = ArgSpec("project_dir", ["project-dir"], extra={"metavar": "DIR"})
    assert spec.add_argument_args() == (("project_dir",), {"metavar": "DIR"})


def test_missing_fields_are_simply_not_passed():
    assert ArgSpec("x", ["-x"]).add_argument_kwargs() == {}
    assert ArgSpec("x", ["-x"], default=None).add_argument_kwargs() == {"default": None}
    assert ArgSpec("x", ["-x"], default=MISSING).add_argument_kwargs() == {}


# --------------------------------------------------------------------------------------
# The remaining merge rules and edge cases


def test_required_and_codec_come_through_the_merge():
    """`required` merges by its own rule, and `codec` rides along to the ingress site."""

    def f(*, token=None): ...

    (spec,) = specs_for_function(
        f, config={"token": {"required": True, "codec": str.upper}}
    )
    assert spec.add_argument_kwargs()["required"] is True
    assert isinstance(spec.codec, Codec)
    assert spec.codec("abc") == "ABC"
    # A Codec passed whole is kept as it is, passthrough and all.
    (spec,) = specs_for_function(
        f, config={"token": {"codec": Codec(decode=str.upper, passthrough={"list"})}}
    )
    assert spec.codec("list") == "list"


def test_two_tiers_merge_in_order_and_hide_wins_from_either():
    """Tier 4 (`config`) lands on top of tier 3 (`func._cw`), field by field."""

    def f(*, token=None, other=None): ...

    f._cw = {"params": {"token": {"help": "from _cw"}, "other": {"help": "kept"}}}
    specs = {s.param_name: s for s in specs_for_function(f, config={"token": HIDE})}
    assert set(specs) == {"other"}
    assert specs["other"].add_argument_kwargs()["help"] == "kept"


def test_hiding_a_parameter_that_does_not_exist_is_an_error():
    def f(*, token=None): ...

    with pytest.raises(GrammarError) as caught:
        specs_for_function(f, config={"nope": HIDE})
    assert "matches no parameter" in str(caught.value)


def test_a_union_whose_first_member_is_a_bare_list():
    assert argh_decode(PARAM, typing.Union[list, None]) == {
        "nargs": "*",
        "required": False,
    }


def test_a_decode_returning_none_means_no_inference():
    def f(*, n: int = 1): ...

    convention = dataclasses.replace(ARGH, decode=lambda param, hint: None)
    # The signature's own default still speaks; only the hint is silenced.
    assert kwargs_of(f, convention=convention)["n"] == {
        "default": 1,
        "type": int,
        "help": "%(default)s",
    }


def test_an_unresolvable_annotation_falls_back_to_reading_it_raw():
    """`resolve_hints=True` must not turn a bad forward reference into a dead CLI."""

    def f(*, thing: "NoSuchTypeAnywhere" = "x"): ...

    assert kwargs_of(f, convention=MODERN)["thing"]["type"] is str
