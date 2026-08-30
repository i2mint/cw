"""`cw.commands`: the six shapes an `obj` can be, and the one naming rule.

The rule this module exists to protect is small and load-bearing: **a name from a mapping
key or an `__all__` entry wins over the callable's own `__name__`**, and is then hyphenated
like any other name. It is what gives `t/priv`'s one `functools.partial` the right command
word, and it is the reason `t/xa` can have two different commands both called `list`.
"""

import functools
import io
import types

import pytest

import cw
from cw.commands import CommandTreeError, commands_from, import_object, is_command


def ls(path="."):
    """List."""


def rm_tree(path):
    """Remove."""


class Runner:
    """A callable instance -- one of the two shapes that crash argh outright."""

    def __call__(self, x=1):
        return x


class TestTheSixForms:
    def test_a_callable_is_one_command(self):
        assert commands_from(ls) == {"ls": ls}

    def test_an_iterable_names_each_member(self):
        assert commands_from([ls, rm_tree]) == {"ls": ls, "rm-tree": rm_tree}

    def test_a_mapping_names_by_key(self):
        assert commands_from({"listing": ls}) == {"listing": ls}

    def test_a_mapping_value_that_is_a_mapping_is_a_group(self):
        tree = commands_from({"archive": {"list": ls}})
        assert tree == {"archive": {"list": ls}}

    def test_a_mapping_value_that_is_a_list_is_a_group(self):
        assert commands_from({"archive": [ls]}) == {"archive": {"ls": ls}}

    def test_a_module_uses_its_public_callables(self):
        module = types.ModuleType("demo")
        module.ls = ls
        module._hidden = rm_tree
        module.NotACommand = Runner
        ls.__module__ = "demo"
        try:
            assert commands_from(module) == {"ls": ls}
        finally:
            ls.__module__ = __name__

    def test_a_module_with_dunder_all_uses_it_as_the_name_list(self):
        module = types.ModuleType("demo")
        module.__all__ = ["ls", "rm_tree"]
        module.ls, module.rm_tree = ls, rm_tree
        assert commands_from(module) == {"ls": ls, "rm-tree": rm_tree}

    def test_a_module_without_dunder_all_skips_imported_names(self):
        """Otherwise every `from x import y` at the top of a module becomes a command."""
        module = types.ModuleType("demo")
        module.helper = functools.reduce  # imported from elsewhere
        assert commands_from(module) == {}

    def test_an_instance_uses_its_public_methods(self):
        class Tool:
            def go(self):
                """Go."""

            def _private(self): ...

        assert list(commands_from(Tool())) == ["go"]

    def test_a_string_is_always_exactly_one_command(self):
        assert commands_from("json:dumps") == {"dumps": __import__("json").dumps}

    def test_a_string_as_a_mapping_value_is_resolved_and_named_by_the_key(self):
        assert commands_from({"render": "json:dumps"}) == {
            "render": __import__("json").dumps
        }


class TestNaming:
    def test_a_key_wins_over_dunder_name_and_is_still_hyphenated(self):
        """One rule satisfies all three of `t/xa`'s and `t/priv`'s real names."""
        tree = commands_from({"gen-secret": ls, "list": rm_tree, "parse_pth_paths": ls})
        assert set(tree) == {"gen-secret", "list", "parse-pth-paths"}

    def test_a_partial_gets_the_right_name_from_its_key(self):
        """`i2.name_of_obj` returns the base function's name here -- the wrong command."""
        partial = functools.partial(ls, path="/tmp")
        assert list(commands_from({"packages_from_all_setup_cfgs": partial})) == [
            "packages-from-all-setup-cfgs"
        ]

    def test_a_partial_in_a_list_is_an_informative_error(self):
        with pytest.raises(TypeError, match="mapping form"):
            commands_from([functools.partial(ls)])

    def test_a_callable_instance_is_a_command(self):
        """argh crashes on this shape; for cw it is just a value that is callable."""
        runner = Runner()
        assert commands_from({"run": runner}) == {"run": runner}

    def test_group_names_are_verbatim_under_argh_and_hyphenated_under_modern(self):
        assert list(commands_from({"git_ops": [ls]})) == ["git_ops"]
        assert list(commands_from({"git_ops": [ls]}, convention=cw.MODERN)) == [
            "git-ops"
        ]

    def test_commands_are_not_hyphenated_when_the_convention_says_not_to(self):
        import dataclasses

        plain = dataclasses.replace(cw.ARGH, hyphenate_commands=False)
        assert list(commands_from([rm_tree], convention=plain)) == ["rm_tree"]

    def test_two_commands_named_list_coexist_in_different_groups(self):
        """The `t/xa` shape, and the reason a Mapping is the right form for it."""

        def top_list(): ...

        def archive_list(): ...

        tree = commands_from({"list": top_list, "archive": {"list": archive_list}})
        assert tree["list"] is top_list
        assert tree["archive"]["list"] is archive_list


class TestRefusals:
    def test_a_list_of_strings_names_both_working_spellings(self):
        """`priv.__all__` is 47 strings; guessing what they mean would ship a wrong CLI."""
        with pytest.raises(CommandTreeError) as caught:
            commands_from(["ls", "rm"])
        message = str(caught.value)
        assert "__all__" in message and "getattr" in message

    def test_nesting_deeper_than_one_level_is_refused(self):
        with pytest.raises(CommandTreeError, match="one level"):
            commands_from({"a": {"b": {"c": ls}}})

    def test_a_factory_is_not_called_for_you(self):
        """A factory left uncalled is a *command*, not a group -- and it says so.

        `t/priv`'s three group sources are zero-argument factories returning lists, and
        there is no way to tell one from a command that happens to take no arguments. So
        cw does not guess: an uncalled factory is a callable value and becomes a command
        (hyphenated, since it is a command name), and calling it gives the group. Python
        has parentheses, and `priv/__main__.py` already writes them.
        """

        def dispatch_funcs():
            return [ls]

        assert commands_from({"git_ops": dispatch_funcs}) == {"git-ops": dispatch_funcs}
        assert commands_from({"git_ops": dispatch_funcs()}) == {"git_ops": {"ls": ls}}

    def test_something_with_no_commands_in_it_is_refused(self):
        with pytest.raises(CommandTreeError, match="cannot derive commands"):
            commands_from(3)


class TestImportObject:
    def test_resolves_a_dotted_attribute_path(self):
        import json

        assert import_object("json:JSONDecoder.decode") is json.JSONDecoder.decode

    def test_a_missing_colon_is_an_informative_error(self):
        with pytest.raises(ValueError, match="colon"):
            import_object("json.dumps")


def test_the_discriminator_is_the_value():
    assert is_command(ls) and is_command(functools.partial(ls)) and is_command(Runner())
    assert not is_command([ls]) and not is_command({"a": ls}) and not is_command("ls")


# =======================================================================================
# Two commands may not share a derived name
# =======================================================================================


class TestNameCollisionsAreRefused:
    """argh raises `ArgumentError: conflicting subparser`. cw used to keep the last one.

    Silently losing a command is worse than the crash it replaces: `dispatch([run_a,
    run_b])` where the two share a `__name__` returned 0 and ran the wrong function, with
    no warning and no row in `--help`.
    """

    @staticmethod
    def _two_functions_called_first():
        def first():
            """First."""
            return "FIRST"

        def second():
            """Second."""
            return "SECOND"

        second.__name__ = "first"
        return first, second

    def test_an_iterable_refuses_it(self):
        first, second = self._two_functions_called_first()
        with pytest.raises(CommandTreeError) as error:
            commands_from([first, second])
        message = str(error.value)
        assert "'first'" in message
        assert message.count("first") >= 2 and "second" in message

    def test_a_mapping_refuses_it_after_hyphenation(self):
        """`git_ops` and `git-ops` derive the same command name under ARGH."""

        def one():
            """One."""

        def two():
            """Two."""

        with pytest.raises(CommandTreeError):
            commands_from({"git_ops": one, "git-ops": two})

    def test_a_module_whose_names_collide_after_hyphenation_refuses_it(self):
        """`__all__ = ['git_ops', 'git-ops']` derives one command name from two
        attributes. (A name listed twice is not a collision: it is the same object.)"""
        module = types.ModuleType("toy")
        module.__all__ = ["do_it", "do-it"]
        module.do_it = lambda: None
        setattr(module, "do-it", lambda: None)
        with pytest.raises(CommandTreeError):
            commands_from(module)

    def test_dispatch_refuses_it_rather_than_running_the_last_one(self):
        first, second = self._two_functions_called_first()
        with pytest.raises(CommandTreeError):
            cw.dispatch([first, second], ["first"], out=io.StringIO(), prog="p")

    def test_two_groups_may_still_hold_the_same_command_name(self):
        """The point of grouping: `xa list` and `xa archive list` both exist."""

        def ls():
            """List."""

        tree = commands_from({"list": ls, "archive": {"list": ls}})
        assert sorted(tree) == ["archive", "list"]
