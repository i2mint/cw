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
    "resolve_object",
    "resolve_to_function",
    "resource_inputs",
)


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
