# cw.commands

Turning an object into the `{name: callable}` tree a parser is built from.

A function, a list, a mapping, a module, an instance, or a `'pkg.mod:name'` reference –
each has one meaning, and the meaning is decided by **the value, not by a string DSL**:

| `obj`                         | becomes                                                                                  |
|-------------------------------|------------------------------------------------------------------------------------------|
| any callable                  | **one command**, with no command word at all                                             |
| `[f, g]` – any iterable       | commands named from each `__name__`                                                      |
| `{'name': f}` – a mapping     | commands named **by the key**                                                            |
| `{'grp': <any of the above>}` | a **group**: a mapping or iterable *value* is a<br/>group, a callable value is a command |
| a module, or any other object | its public callable attributes; `__all__`, if<br/>present, is the name list              |
| `'pkg.mod:name'` – a string   | **always exactly one command**, imported lazily                                          |

Grouping is exactly one level deep – argh’s limit, and the fleet’s only two group users
(`t/xa` and `t/priv`) need exactly one.

```pycon
>>> def ls(path='.'): ...
>>> def rm(path): ...
>>> commands_from([ls, rm])
{'ls': <function ls at ...>, 'rm': <function rm at ...>}
```

\*\*The rule that makes `t/priv` work: a name from a mapping key or an `__all__` entry
wins over the function’s own `__name__``**, and then has ``hyphenate_commands` applied to
it like any other derived name. It is hardcoded and not configurable, because making it a
switch reintroduces exactly the ambiguity that produces the wrong name today:

```pycon
>>> import functools
>>> def packages_from_all_projects(project=None, *, config_type='setup.cfg'): ...
>>> partial = functools.partial(packages_from_all_projects, config_type='setup.cfg')
>>> list(commands_from({'packages_from_all_setup_cfgs': partial}))
['packages-from-all-setup-cfgs']
```

That is the correct name, and it was in the package’s `__all__` the whole time. Deriving
it from the `functools.partial` instead gives `packages-from-all-projects` – a command
that describes a different function – which is what the live CLI registers today and what
`i2.name_of_obj` also returns.

### Functions

| [`commands_from`](#cw.commands.commands_from)(obj, /, \*[, convention, \_depth])   | `obj` -> `{name: callable}`, with a nested mapping for each group.   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| [`import_object`](#cw.commands.import_object)(ref)                                 | `'pkg.mod:name'` -> the object, imported now.                        |

### Exceptions

| [`CommandTreeError`](#cw.commands.CommandTreeError)   | `obj` does not describe a command tree, and guessing would ship a wrong CLI.   |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------|

### *exception* cw.commands.CommandTreeError

Bases: [`TypeError`](https://docs.python.org/3/builtins/exceptions.html#TypeError)

`obj` does not describe a command tree, and guessing would ship a wrong CLI.

### cw.commands.commands_from(obj, , , convention=None, \_depth=0)

`obj` -> `{name: callable}`, with a nested mapping for each group.

* **Parameters:**
  * **obj** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Any of the six forms in this module’s docstring.
  * **convention** – Supplies `hyphenate_commands` and `hyphenate_groups`. Defaults to
    `cw.ARGH`.
* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), `Union`[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]
* **Returns:**
  A mapping of command-line name to callable, whose values may themselves be such a
  mapping – one level deep, no further.

A mapping value that is itself a mapping or a list is a group, which is how `t/xa`
gets two different commands both called `list`:

```pycon
>>> def list_cmd(): ...
>>> def archive_list_cmd(): ...
>>> tree = commands_from({'list': list_cmd,
...                       'archive': {'list': archive_list_cmd}})
>>> {name: sorted(value) if isinstance(value, dict) else value.__name__
...  for name, value in tree.items()}
{'list': 'list_cmd', 'archive': ['list']}
```

Group names are **verbatim** under `cw.ARGH` – `priv git_ops` is a string in
priv’s own README – and hyphenated under `cw.MODERN`:

```pycon
>>> import cw
>>> def g(): ...
>>> list(commands_from({'git_ops': [g]}))
['git_ops']
>>> list(commands_from({'git_ops': [g]}, convention=cw.MODERN))
['git-ops']
```

A zero-argument factory that *returns* commands is not called for you, because there is
no way to tell one from a command that happens to take no arguments – and Python
already has parentheses:

```pycon
>>> def dispatch_funcs():
...     return [g]
>>> list(commands_from({'git_ops': dispatch_funcs()}))
['git_ops']
```

A list of attribute *names* – `priv.__all__` is 47 strings – is refused, with the
two spellings that do work:

```pycon
>>> commands_from(['ls', 'rm'])
Traceback (most recent call last):
  ...
cw.commands.CommandTreeError: 'ls' is a string, and a list of strings is ambiguous: it
could be attribute names or object references. Pass the module itself (its __all__ is
used), or spell the mapping: {name: getattr(module, name) for name in module.__all__}.
```

### cw.commands.import_object(ref)

`'pkg.mod:name'` -> the object, imported now.

The house spelling – `py2mcp.mk_mcp_from_refs(['pkg.tools:verb'])` uses the same
one. The colon is required: it is what separates the module path from the attribute
path without guessing where one ends.

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

```pycon
>>> import_object('collections:OrderedDict')
<class 'collections.OrderedDict'>
>>> import_object('json:JSONDecoder.decode')
<function JSONDecoder.decode at ...>
>>> import_object('collections.OrderedDict')
Traceback (most recent call last):
  ...
ValueError: bad object reference 'collections.OrderedDict': expected 'pkg.mod:name',
with a colon between the module and the attribute.
```
