"""`cw.ingress`: every parameter kind, and the two rules that are not about kinds.

The claim under test is that a page of `inspect` does the job `i2.Sig.mk_args_and_kwargs`
was going to do. The way to falsify it is to call the ingress and then call the function
with what it produced, which is what `calls_like` does -- so a wrong split shows up as the
wrong arguments arriving, not as a mismatched tuple.
"""

import inspect

import pytest

import cw
from cw.ingress import IngressError, mk_ingress


def split(func, values):
    """The `(args, kwargs)` the ingress makes of `values` -- the thing under test."""
    return mk_ingress(func)(values)


def calls_like(func, values):
    """What `func` actually receives: the ingress output, applied.

    Asserting on the call rather than only on the split is what catches a split that is
    tuple-shaped but wrong -- `*args` re-packed instead of extended, say.
    """
    args, kwargs = split(func, values)
    return func(*args, **kwargs)


def record(*args, **kwargs):
    """A stand-in command that reports exactly what it was handed."""
    return args, kwargs


class TestParameterKinds:
    def test_positional_only(self):
        def f(a, b, /): ...

        assert split(f, {"a": 1, "b": 2}) == ((1, 2), {})

    def test_positional_or_keyword_is_passed_positionally(self):
        """Kind decides how it is called; `cw.grammar` decides, separately, how it is
        spelt. A defaulted parameter is an `--option` under ARGH and still arrives by
        position."""

        def f(a, b=2): ...

        assert split(f, {"a": 1, "b": 9}) == ((1, 9), {})

    def test_keyword_only(self):
        def f(*, a, b=2): ...

        assert split(f, {"a": 1, "b": 9}) == ((), {"a": 1, "b": 9})

    def test_var_positional_extends_rather_than_nesting(self):
        def f(*agents):
            return record(*agents)

        assert calls_like(f, {"agents": ["a", "b"]}) == (("a", "b"), {})

    def test_var_positional_absent_is_empty(self):
        def f(*agents):
            return record(*agents)

        assert calls_like(f, {}) == ((), {})
        assert calls_like(f, {"agents": None}) == ((), {})

    def test_var_positional_is_not_re_packed(self):
        """The split extends the positionals; it does not pass one tuple argument."""
        assert split(lambda *agents: None, {"agents": ["a", "b"]}) == (("a", "b"), {})

    def test_var_keyword_collects_leftovers(self):
        def f(a, **rest):
            return record(a, **rest)

        assert calls_like(f, {"a": 1, "x": 2}) == ((1,), {"x": 2})

    def test_leftovers_are_dropped_without_var_keyword(self):
        """Row 11: argh contributes no CLI argument for `**kwargs`, and drops the rest."""

        def f(a): ...

        assert split(f, {"a": 1, "x": 2}) == ((1,), {})

    def test_private_keys_never_reach_var_keyword(self):
        """cw's own namespace key must not land in someone's `**kwargs`."""

        def f(**rest): ...

        assert split(f, {"_cw": object(), "x": 1}) == ((), {"x": 1})

    def test_all_kinds_at_once(self):
        def f(po, /, pk=2, *args, ko=3, **rest):
            return record(po, pk, *args, ko=ko, **rest)

        assert calls_like(
            f, {"po": "P", "pk": "K", "args": ["A", "B"], "ko": 7, "extra": "E"}
        ) == (("P", "K", "A", "B"), {"ko": 7, "extra": "E"})

    def test_zero_parameters(self):
        assert split(lambda: None, {}) == ((), {})


class TestDefaultsAndHiding:
    def test_a_missing_value_falls_back_to_the_signature_default(self):
        """What makes `cw.HIDE` work: the flag is gone and the function still gets it."""

        def packages(project=None, *, config_type="setup.cfg"):
            return record(project, config_type=config_type)

        assert calls_like(packages, {"project": "p"}) == (
            ("p",),
            {"config_type": "setup.cfg"},
        )

    def test_hide_removes_the_flag_and_keeps_the_value(self):
        """End to end, on the shape `t/priv`'s one `functools.partial` actually has."""
        seen = {}

        def packages_from_all_projects(project=None, *, config_type="setup.cfg"):
            seen.update(project=project, config_type=config_type)

        parser = cw.mk_parser(
            packages_from_all_projects, config={"config_type": cw.HIDE}, prog="priv"
        )
        assert "--config-type" not in parser.format_help()
        cw.run(parser, ["--project", "p"], standalone=False)
        assert seen == {"project": "p", "config_type": "setup.cfg"}

    def test_a_missing_value_with_no_default_is_an_informative_error(self):
        def f(pool):
            return pool

        with pytest.raises(IngressError, match="cw.HIDE"):
            mk_ingress(f)({})


class TestCodecs:
    """The ingress site: a post-parse, per-parameter, opt-in decoder."""

    def test_applies_to_the_named_parameter_only(self):
        def f(a, b):
            return record(a, b)

        args, _ = mk_ingress(f, codecs={"a": str.upper})({"a": "x", "b": "y"})
        assert args == ("X", "y")

    def test_a_codec_from_config_reaches_the_ingress(self):
        seen = {}

        def load(pipeline="theremin"):
            seen["pipeline"] = pipeline

        pipelines = {"bass": "BASS-OBJECT"}
        cw.dispatch(
            load,
            ["--pipeline", "bass"],
            config={"pipeline": {"codec": pipelines.__getitem__}},
            standalone=False,
        )
        assert seen == {"pipeline": "BASS-OBJECT"}

    def test_passthrough_lets_a_sentinel_survive(self):
        """Exactly `t/theremin`'s shape: `nargs='?' const='list'` plus a resolver."""
        seen = {}

        def play(pipeline="theremin"):
            seen["pipeline"] = pipeline

        codec = cw.Codec(decode=str.upper, passthrough={"list"})
        config = {"pipeline": {"nargs": "?", "const": "list", "codec": codec}}
        for argv, expected in (
            ([], "THEREMIN"),
            (["--pipeline"], "list"),
            (["--pipeline", "bass"], "BASS"),
        ):
            cw.dispatch(play, argv, config=config, standalone=False)
            assert seen["pipeline"] == expected, argv


def test_the_call_contract_is_i2s():
    """`{name: value} -> (args, kwargs)`, so an `i2.wrapper.Ingress` is a drop-in.

    Asserted structurally rather than by importing i2, which is the whole point: the
    contract is honoured and the 32ms import is not paid.
    """
    ingress = mk_ingress(lambda a, *, b=1: None)
    assert len(inspect.signature(ingress).parameters) == 1
    result = ingress({"a": 1})
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], tuple) and isinstance(result[1], dict)
