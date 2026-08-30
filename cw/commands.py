"""Turning an object into the ``{name: callable}`` tree a parser is built from.

A function, a list, a mapping, a module, an instance, or a ``'pkg.mod:name'`` reference --
each has one meaning, and the meaning is decided by **the value, not by a string DSL**:

======================================  ===================================================
``obj``                                 becomes
======================================  ===================================================
any callable                            **one command**, with no command word at all
``[f, g]`` -- any iterable              commands named from each ``__name__``
``{'name': f}`` -- a mapping            commands named **by the key**
``{'grp': <any of the above>}``         a **group**: a mapping or iterable *value* is a
                                        group, a callable value is a command
a module, or any other object           its public callable attributes; ``__all__``, if
                                        present, is the name list
``'pkg.mod:name'`` -- a string          **always exactly one command**, imported lazily
======================================  ===================================================

Grouping is exactly one level deep -- argh's limit, and the fleet's only two group users
(``t/xa`` and ``t/priv``) need exactly one.

>>> def ls(path='.'): ...
>>> def rm(path): ...
>>> commands_from([ls, rm])
{'ls': <function ls at ...>, 'rm': <function rm at ...>}

**The rule that makes ``t/priv`` work: a name from a mapping key or an ``__all__`` entry
wins over the function's own ``__name__``**, and then has ``hyphenate_commands`` applied to
it like any other derived name. It is hardcoded and not configurable, because making it a
switch reintroduces exactly the ambiguity that produces the wrong name today:

>>> import functools
>>> def packages_from_all_projects(project=None, *, config_type='setup.cfg'): ...
>>> partial = functools.partial(packages_from_all_projects, config_type='setup.cfg')
>>> list(commands_from({'packages_from_all_setup_cfgs': partial}))
['packages-from-all-setup-cfgs']

That is the correct name, and it was in the package's ``__all__`` the whole time. Deriving
it from the ``functools.partial`` instead gives ``packages-from-all-projects`` -- a command
that describes a different function -- which is what the live CLI registers today and what
``i2.name_of_obj`` also returns.
"""

import importlib
import inspect
from collections.abc import Iterable, Mapping
from typing import Any, Callable, Dict, Optional, Union

from cw.grammar import cli_name, command_name

__all__ = ["commands_from", "import_object", "CommandTreeError"]

#: The separator in a lazy object reference: ``'pkg.mod:name'``.
REF_SEPARATOR = ":"

#: How deep a command tree may nest. argh's limit, and the fleet's need.
MAX_GROUP_DEPTH = 1

#: A tree value: a command, or (one level down) a group of them.
CommandTree = Dict[str, Union[Callable, dict]]


class CommandTreeError(TypeError):
    """``obj`` does not describe a command tree, and guessing would ship a wrong CLI."""


def import_object(ref: str) -> Any:
    """``'pkg.mod:name'`` -> the object, imported now.

    The house spelling -- ``py2mcp.mk_mcp_from_refs(['pkg.tools:verb'])`` uses the same
    one. The colon is required: it is what separates the module path from the attribute
    path without guessing where one ends.

    >>> import_object('collections:OrderedDict')
    <class 'collections.OrderedDict'>
    >>> import_object('json:JSONDecoder.decode')                # doctest: +ELLIPSIS
    <function JSONDecoder.decode at ...>
    >>> import_object('collections.OrderedDict')
    Traceback (most recent call last):
      ...
    ValueError: bad object reference 'collections.OrderedDict': expected 'pkg.mod:name',
    with a colon between the module and the attribute.
    """
    if REF_SEPARATOR not in ref:
        raise ValueError(
            f"bad object reference {ref!r}: expected 'pkg.mod:name', with a colon "
            "between the module and the attribute."
        )
    module_name, _, attribute_path = ref.partition(REF_SEPARATOR)
    obj = importlib.import_module(module_name)
    for attribute in attribute_path.split("."):
        obj = getattr(obj, attribute)
    return obj


def is_command(value: Any) -> bool:
    """Is this tree value a command (rather than a group)?

    The discriminator, in one place: a callable value is a command, and a mapping or other
    iterable value is a group. It is structural, so a ``functools.partial`` and a callable
    instance -- both of which crash argh -- are simply commands.

    >>> is_command(print), is_command([print]), is_command({'a': print})
    (True, False, False)
    """
    return callable(value) and not isinstance(value, (Mapping, Iterable))


def _public_callables(obj: Any) -> Dict[str, Callable]:
    """A module's or an instance's public callable attributes, ``__all__`` first.

    Two filters, both there to stop a CLI from sprouting commands nobody wrote. Classes
    are excluded, and -- for a module with no ``__all__`` -- so is anything defined
    elsewhere, or every ``from x import y`` at the top of the module would become a
    command.
    """
    declared = getattr(obj, "__all__", None)
    names = (
        list(declared)
        if declared is not None
        else [name for name in dir(obj) if not name.startswith("_")]
    )
    home = getattr(obj, "__name__", None) if inspect.ismodule(obj) else None
    found = {}
    for name in names:
        value = getattr(obj, name, None)
        if not callable(value) or inspect.isclass(value):
            continue
        if declared is None and home is not None:
            if getattr(value, "__module__", home) != home:
                continue
        found[name] = value
    return found


def _named(name: str, *, convention, group: bool = False) -> str:
    """One naming function for derived names, mapping keys and group names alike.

    A key does not win *verbatim*: it wins over ``__name__``, and is then hyphenated by the
    same rule as any other name, which is the only reading under which ``'gen-secret'``,
    ``'list'`` and ``'parse_pth_paths'`` all come out right at once.
    """
    hyphenate = convention.hyphenate_groups if group else convention.hyphenate_commands
    return cli_name(name, hyphenate=hyphenate)


def commands_from(obj: Any, /, *, convention=None, _depth: int = 0) -> CommandTree:
    """``obj`` -> ``{name: callable}``, with a nested mapping for each group.

    Args:
        obj: Any of the six forms in this module's docstring.
        convention: Supplies ``hyphenate_commands`` and ``hyphenate_groups``. Defaults to
            :data:`cw.ARGH`.

    Returns:
        A mapping of command-line name to callable, whose values may themselves be such a
        mapping -- one level deep, no further.

    A mapping value that is itself a mapping or a list is a group, which is how ``t/xa``
    gets two different commands both called ``list``:

    >>> def list_cmd(): ...
    >>> def archive_list_cmd(): ...
    >>> tree = commands_from({'list': list_cmd,
    ...                       'archive': {'list': archive_list_cmd}})
    >>> {name: sorted(value) if isinstance(value, dict) else value.__name__
    ...  for name, value in tree.items()}
    {'list': 'list_cmd', 'archive': ['list']}

    Group names are **verbatim** under :data:`cw.ARGH` -- ``priv git_ops`` is a string in
    priv's own README -- and hyphenated under :data:`cw.MODERN`:

    >>> import cw
    >>> def g(): ...
    >>> list(commands_from({'git_ops': [g]}))
    ['git_ops']
    >>> list(commands_from({'git_ops': [g]}, convention=cw.MODERN))
    ['git-ops']

    A zero-argument factory that *returns* commands is not called for you, because there is
    no way to tell one from a command that happens to take no arguments -- and Python
    already has parentheses:

    >>> def dispatch_funcs():
    ...     return [g]
    >>> list(commands_from({'git_ops': dispatch_funcs()}))
    ['git_ops']

    A list of attribute *names* -- ``priv.__all__`` is 47 strings -- is refused, with the
    two spellings that do work:

    >>> commands_from(['ls', 'rm'])
    Traceback (most recent call last):
      ...
    cw.commands.CommandTreeError: 'ls' is a string, and a list of strings is ambiguous: it
    could be attribute names or object references. Pass the module itself (its __all__ is
    used), or spell the mapping: {name: getattr(module, name) for name in module.__all__}.
    """
    convention = convention if convention is not None else _default_convention()

    if isinstance(obj, str):
        obj = import_object(obj)
    if is_command(obj):
        return {command_name(obj, hyphenate=convention.hyphenate_commands): obj}
    if isinstance(obj, Mapping):
        return _from_mapping(obj, convention=convention, _depth=_depth)
    if isinstance(obj, Iterable):
        return _from_iterable(obj, convention=convention)
    if inspect.ismodule(obj) or hasattr(obj, "__dict__"):
        return {
            _named(name, convention=convention): func
            for name, func in _public_callables(obj).items()
        }
    raise CommandTreeError(
        f"cannot derive commands from {obj!r}: it is not a callable, a mapping, an "
        "iterable of callables, a module, or a 'pkg.mod:name' reference."
    )


def _from_mapping(obj: Mapping, *, convention, _depth: int) -> CommandTree:
    """Each key names its value: a command if the value is callable, a group otherwise."""
    tree: CommandTree = {}
    for key, value in obj.items():
        if isinstance(value, str):
            value = import_object(value)
        if is_command(value):
            tree[_named(key, convention=convention)] = value
        elif _depth >= MAX_GROUP_DEPTH:
            raise CommandTreeError(
                f"group {key!r} is nested more than {MAX_GROUP_DEPTH} level deep. argh "
                "supports one level of grouping and so does cw; flatten the inner group, "
                "or give its commands longer names."
            )
        else:
            tree[_named(key, convention=convention, group=True)] = commands_from(
                value, convention=convention, _depth=_depth + 1
            )
    return tree


def _from_iterable(obj: Iterable, *, convention) -> CommandTree:
    """Each member names itself. A string member is refused rather than guessed at."""
    tree: CommandTree = {}
    for value in obj:
        if isinstance(value, str):
            raise CommandTreeError(
                f"{value!r} is a string, and a list of strings is ambiguous: it could be "
                "attribute names or object references. Pass the module itself (its "
                "__all__ is used), or spell the mapping: "
                "{name: getattr(module, name) for name in module.__all__}."
            )
        tree[command_name(value, hyphenate=convention.hyphenate_commands)] = value
    return tree


def _default_convention():
    """:data:`cw.ARGH`, imported late so that ``convention`` may import this module."""
    from cw.convention import ARGH

    return ARGH
