"""Tests for ``cw.resolution``'s public surface and its lazy ``i2`` import.

``cw.resolution`` is pre-existing, working code with a live dependent, so these tests pin
the two things the v1 work could plausibly have broken: the names other packages import,
and ``resource_inputs``, whose ``i2`` import moved from module scope into the function body.
"""

import builtins
import sys

import pytest

import cw
from cw.resolution import parse_ast_spec, resource_inputs


#: What other packages import from cw today, plus the rest of the module's stated API.
PUBLIC_RESOLUTION_NAMES = (
    "parse_ast_spec",
    "parse_json_spec",
    "parse_spec_with_dot_path",
    "resolve_func_from_dot_path",
    "resolve_to_function",
    "resource_inputs",
)


def test_resolve_object_is_not_promoted_to_the_package_root():
    """It has zero call sites in cw and zero across the fleet, its body is uncovered, and
    `cw/resolution.py:67` carries a TODO saying it should be merged away.
    `architecture-first`'s pre-commit check 5 says an unreachable name is code written for
    iteration 2. It stays where it has always been -- `cw.resolution` shipped it in 0.0.15
    -- but v1 does not commit to it at the facade, where nothing has ever asked for it.
    """
    from cw import resolution

    assert callable(resolution.resolve_object)
    assert not hasattr(cw, "resolve_object")
    assert "resolve_object" not in cw.__all__


@pytest.mark.parametrize("name", PUBLIC_RESOLUTION_NAMES)
def test_resolution_names_are_reachable_from_the_package_root(name):
    """`t/theremin` does ``from cw import resolve_to_function``. Keep that true."""
    assert callable(getattr(cw, name))
    assert name in cw.__all__


def test_resolve_to_function_still_resolves_a_dot_path():
    assert cw.resolve_to_function("builtins.len") is len


def test_resource_inputs_resolves_the_parameters_it_is_given():
    def func(apple, banana, carrot):
        return apple, banana, carrot

    function_store = {"a": lambda: 1}
    wrapped = resource_inputs(
        func,
        resource=dict(
            apple=None,
            carrot=dict(
                func_key_and_kwargs=parse_ast_spec, get_func=function_store.get
            ),
        ),
    )
    apple, banana, carrot = wrapped("builtins.len", "test", "a()")
    assert apple is len
    assert banana == "test"  # no resource declared -> passed through untouched
    assert callable(carrot)


def test_resource_inputs_says_which_extra_to_install_when_i2_is_missing(monkeypatch):
    """The import moved into the body, so its failure must name the fix."""
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "i2" or name.startswith("i2."):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    for name in [name for name in sys.modules if name.split(".")[0] == "i2"]:
        monkeypatch.delitem(sys.modules, name)

    def func(apple):
        return apple  # pragma: no cover

    with pytest.raises(ImportError, match=r"cw\[resource\]"):
        resource_inputs(func, resource=dict(apple=None))


# =======================================================================================
# The uncovered third (cw#32 item 3)
#
# `cw/resolution.py` is pre-existing code with a live dependent (`t/theremin`), and the
# issue is explicit that it should be TESTED, not refactored blind. So these tests are
# characterization: they say what the module does today, error messages included, so that
# the merge the module's own TODOs ask for has a net under it before anyone starts.
#
# Almost every uncovered line was an error path. That is the shape of the risk: a resolver
# whose happy path is exercised by one dependent and whose refusals are exercised by
# nobody is a module where a rewrite can silently start accepting garbage.
# =======================================================================================

from cw.resolution import (  # noqa: E402
    _extract_func_name,
    _resolve_resource_spec,
    parse_json_spec,
    parse_spec_with_dot_path,
    resolve_func_from_dot_path,
    resolve_object,
    resolve_to_function,
)


class TestResolveFuncFromDotPath:
    """Four ways a dot path fails to name a callable, and what each one says."""

    def test_a_bare_name_that_is_not_a_builtin(self):
        with pytest.raises(ValueError, match="as a built-in function"):
            resolve_func_from_dot_path("no_such_builtin_anywhere")

    def test_a_builtin_type_attribute_that_does_not_exist(self):
        with pytest.raises(ValueError, match=r"'str' has no attribute 'nope'"):
            resolve_func_from_dot_path("str.nope")

    def test_a_builtin_type_attribute_that_is_not_callable(self):
        with pytest.raises(ValueError, match="is not callable"):
            resolve_func_from_dot_path("str.__doc__")

    def test_a_builtin_type_method_resolves(self):
        """The happy path of the builtin-type branch. It is asserted by a doctest too, but
        a doctest is not a test of this function's coverage under `pytest tests/`."""
        assert resolve_func_from_dot_path("str.upper")("hi") == "HI"

    def test_a_module_attribute_that_is_not_callable(self):
        with pytest.raises(ValueError, match=r"'os.sep' is not callable"):
            resolve_func_from_dot_path("os.sep")

    def test_a_module_that_does_not_import(self):
        with pytest.raises(ValueError, match="Cannot resolve"):
            resolve_func_from_dot_path("no_such_module_at_all.thing")

    def test_a_module_attribute_that_does_not_exist(self):
        with pytest.raises(ValueError, match="Cannot resolve"):
            resolve_func_from_dot_path("os.no_such_attribute")


class TestParseSpecWithDotPath:
    def test_a_non_string_is_a_type_error(self):
        with pytest.raises(TypeError, match="must be a string"):
            parse_spec_with_dot_path(123)

    def test_anything_but_word_characters_and_dots_is_refused(self):
        """This is the whole of its validation, and it is what keeps `rm -rf` out."""
        with pytest.raises(ValueError, match="word characters and dots"):
            parse_spec_with_dot_path("os.system('rm -rf /')")


class TestParseJsonSpec:
    """Five refusals, one per malformed shape."""

    @pytest.mark.parametrize(
        "spec,match",
        [
            ("{not json", "Invalid JSON"),
            ("[1, 2]", "must be a dictionary"),
            ('{"params": {}}', "must contain 'func' key"),
            ('{"func": 3}', "'func' value must be a string"),
            ('{"func": "len", "params": 3}', "'params' value must be a dictionary"),
        ],
    )
    def test_it_says_which_part_is_wrong(self, spec, match):
        with pytest.raises(ValueError, match=match):
            parse_json_spec(spec)

    def test_params_defaults_to_empty_when_absent(self):
        assert parse_json_spec('{"func": "len"}') == ("len", {})


class TestParseAstSpec:
    """The safety story: only a call, only keywords, only literals."""

    def test_a_non_string_is_a_type_error(self):
        with pytest.raises(TypeError, match="must be a string"):
            parse_ast_spec(123)

    def test_no_parentheses_falls_back_to_the_dot_path_parser(self):
        assert parse_ast_spec("os.path.join") == ("os.path.join", {})

    def test_a_syntax_error_is_reported_as_one(self):
        """Note the spec must contain BOTH parentheses to get this far: the `(`/`)`
        pre-check routes `'len((('` to the dot-path parser instead, which refuses it for a
        different reason. Characterized rather than changed -- both spellings are refused,
        and the pre-check is what makes a bare dot path work at all."""
        with pytest.raises(ValueError, match="Invalid syntax"):
            parse_ast_spec("f(x=)")
        with pytest.raises(ValueError, match="word characters and dots"):
            parse_ast_spec("len(((")

    def test_an_expression_that_is_not_a_call_is_refused(self):
        with pytest.raises(ValueError, match="must be a function call expression"):
            parse_ast_spec("(1 + 2)")

    def test_positional_arguments_are_refused(self):
        """Deliberate: a positional has no name to bind to, so only keywords are allowed."""
        with pytest.raises(ValueError, match="Only keyword arguments"):
            parse_ast_spec("len([1, 2])")

    def test_double_star_kwargs_are_refused(self):
        with pytest.raises(ValueError, match=r"\*\*kwargs syntax not supported"):
            parse_ast_spec("f(**d)")

    def test_a_non_literal_argument_value_is_refused(self):
        """`ast.literal_eval` is the safety boundary; a name is not a literal."""
        with pytest.raises(ValueError, match="Unsafe or invalid argument value"):
            parse_ast_spec("f(x=some_name)")

    def test_a_dotted_function_name_is_rebuilt_from_the_attribute_chain(self):
        assert parse_ast_spec("a.b.c(x=1)") == ("a.b.c", {"x": 1})

    def test_a_function_name_that_is_neither_a_name_nor_an_attribute(self):
        import ast as ast_module

        node = ast_module.parse("f()", mode="eval").body.func
        assert _extract_func_name(node) == "f"
        with pytest.raises(ValueError, match="Unsupported function name format"):
            _extract_func_name(ast_module.parse("[f][0]()", mode="eval").body.func)


class TestResolveToFunction:
    """The entry point: what it accepts, what it binds, and how it refuses."""

    def test_a_callable_spec_is_returned_untouched(self):
        assert resolve_to_function(len) is len

    def test_a_mapping_get_func_is_used_as_a_lookup(self):
        """A Mapping is accepted directly, not only its `.get` -- and this branch had no
        test, so nothing said whether a dict was allowed at all."""
        assert resolve_to_function("a", parse_ast_spec, {"a": len}) is len

    def test_a_lookup_that_raises_is_reported_with_both_the_key_and_the_spec(self):
        def exploding_get(key):
            raise KeyError(key)

        with pytest.raises(ValueError, match="could not resolve 'a'"):
            resolve_to_function("a()", parse_ast_spec, exploding_get)

    def test_a_lookup_that_returns_a_non_callable_is_a_type_error(self):
        with pytest.raises(TypeError, match="returned non-callable object"):
            resolve_to_function("a", parse_ast_spec, {"a": 3})

    def test_kwargs_are_bound_with_partial(self):
        resolved = resolve_to_function(
            "join(b='B')", parse_ast_spec, {"join": lambda a, b: a + b}
        )
        assert resolved("A") == "AB"

    def test_a_parser_that_returns_non_dict_kwargs_is_a_type_error(self):
        def bad_parser(spec):
            return spec, [("a", 1)]  # a list of pairs, not a dict

        with pytest.raises(TypeError, match="kwargs must be a dictionary"):
            resolve_to_function("len", bad_parser, {"len": len})

    def test_anything_that_is_neither_callable_nor_a_string_is_refused(self):
        with pytest.raises(TypeError, match="must be either a callable or a string"):
            resolve_to_function(42)


class TestResolveResourceSpec:
    """The three accepted spec shapes, and the refusal of a fourth."""

    def test_none_means_the_default_ingress(self):
        assert _resolve_resource_spec(None, resolve_to_function) is resolve_to_function

    def test_a_callable_is_used_as_is(self):
        def resolver(x):
            return x  # pragma: no cover

        assert _resolve_resource_spec(resolver, resolve_to_function) is resolver

    def test_a_dict_becomes_partial_keywords_on_the_default(self):
        resolved = _resolve_resource_spec({"get_func": {"a": len}}, resolve_to_function)
        assert resolved("a") is len

    def test_anything_else_says_what_the_three_shapes_are(self):
        with pytest.raises(TypeError, match="must be None, callable, or dict"):
            _resolve_resource_spec(42, resolve_to_function)


class TestResolveObject:
    """`resolve_object` is deliberately NOT at the package facade (ADR-0007), and it had no
    test at all. It stays where it is; these tests are what make the merge its own TODO
    asks for reviewable rather than a rewrite from scratch.
    """

    MAP = {"a": 1, "b": "two"}

    def test_a_string_is_looked_up(self):
        assert resolve_object("a", object_map=self.MAP) == 1

    def test_a_string_that_is_not_in_the_map_is_a_value_error(self):
        with pytest.raises(ValueError, match="Unknown object identifier: zz"):
            resolve_object("zz", object_map=self.MAP)

    def test_a_custom_error_message_replaces_the_default(self):
        with pytest.raises(ValueError, match="pick one of a, b"):
            resolve_object("zz", object_map=self.MAP, error_message="pick one of a, b")

    def test_a_non_string_passes_through_when_no_type_is_expected(self):
        sentinel = object()
        assert resolve_object(sentinel, object_map=self.MAP) is sentinel

    def test_a_non_string_of_the_expected_type_passes_through(self):
        assert resolve_object(7, object_map=self.MAP, expected_type=int) == 7

    def test_a_non_string_of_the_wrong_type_is_a_type_error(self):
        with pytest.raises(TypeError, match="Expected type"):
            resolve_object(7.5, object_map=self.MAP, expected_type=int)

    def test_a_looked_up_value_of_the_wrong_type_is_also_a_type_error(self):
        """The second type check, on the *resolved* value, is the one a reader misses: a
        map entry may be the wrong type even when the key was fine."""
        with pytest.raises(TypeError, match="Resolved object should be of type"):
            resolve_object("b", object_map=self.MAP, expected_type=int)

    def test_the_custom_message_covers_both_type_errors(self):
        with pytest.raises(TypeError, match="nope"):
            resolve_object(
                7.5, object_map=self.MAP, expected_type=int, error_message="nope"
            )
        with pytest.raises(TypeError, match="nope"):
            resolve_object(
                "b", object_map=self.MAP, expected_type=int, error_message="nope"
            )


class TestTheColonRefSpelling:
    """``'pkg.mod:name'`` is the house spelling (``cw.commands.import_object``,
    ``cw.cli.mk_parser``'s ``obj:`` doc, ``python -m cw``), so the package's most
    generically named resolver must accept it too -- i2mint/cw#40.
    """

    def test_resolve_to_function_accepts_a_colon_ref(self):
        import os.path

        assert cw.resolve_to_function("os.path:join") is os.path.join

    def test_a_colon_ref_may_walk_attributes_after_the_colon(self):
        decode = cw.resolve_to_function("json:JSONDecoder.decode")
        assert decode.__qualname__ == "JSONDecoder.decode"

    def test_the_dot_path_spelling_still_resolves_identically(self):
        assert cw.resolve_to_function("builtins.len") is builtins.len
        assert cw.resolve_to_function("os.path.join") is __import__("os.path").path.join

    def test_a_second_colon_is_still_rejected(self):
        with pytest.raises(ValueError):
            cw.resolve_to_function("a:b:c")

    def test_an_unimportable_colon_ref_still_raises_value_error(self):
        """The failure *shape* is what dependents catch, so widening the grammar must not
        change the exception type of a bad reference."""
        with pytest.raises(ValueError):
            cw.resolve_to_function("cw:no_such_attribute")

    def test_a_non_callable_colon_ref_is_a_value_error(self):
        with pytest.raises(ValueError, match="not callable"):
            cw.resolve_to_function("cw.commands:REF_SEPARATOR")

    def test_the_dot_path_resolver_takes_the_colon_form_too(self):
        from cw.resolution import resolve_func_from_dot_path

        assert resolve_func_from_dot_path("json:JSONDecoder.decode").__qualname__ == (
            "JSONDecoder.decode"
        )

    def test_the_default_parser_passes_a_colon_ref_through_unchanged(self):
        from cw.resolution import parse_spec_with_dot_path

        assert parse_spec_with_dot_path("os.path:join") == ("os.path:join", {})
        assert parse_ast_spec("os.path:join") == ("os.path:join", {})
