# cw.resolution

Function resolution utilities for CLI parameterization.

This module provides utilities to resolve function specifications from various formats
(JSON, AST expressions, dot paths) into callable functions with optional parameter binding.

Key functions:

- resolve_to_function: Main resolution function supporting multiple spec formats
- resolve_func_from_dot_path: Import and resolve functions from dot notation paths
- parse_json_spec: Parse JSON-formatted function specifications
- parse_ast_spec: Parse AST-formatted function call specifications

Example usage:

The main function is `resolve_to_function`, which can be used to resolve a function
from a string specification or directly from a callable.

```pycon
>>> def func(apple, banana, carrot):
...     return f"{apple=}, {banana=}, {carrot=}"
>>>
>>> from cw.resolution import parse_ast_spec
>>> function_store = {'a': lambda: 1, 'b': lambda: 2}
>>>
>>> wrapped_func = resource_inputs(
...     func,
...     resource=dict(
...         apple=None,  # Use default resolve_to_function
...         carrot=dict(
...             func_key_and_kwargs=parse_ast_spec,
...             get_func=function_store.get
...         )
...     )
... )
>>>
```

Now apple will be resolved via resolve_to_function
carrot will be resolved via resolve_to_function with custom params
banana remains unchanged (passed through as-is)

```pycon
>>> # apple='builtins.len' -> resolve_to_function('builtins.len') -> len function
>>> # banana='test' -> unchanged (no resource specified)
>>> # carrot='a()' -> parsed as AST, resolved via function_store
>>> result = wrapped_func('builtins.len', 'test', 'a()')
>>> 'apple=<built-in function len>' in result
True
>>> "banana='test'" in result
True
>>> 'carrot=<function' in result and 'lambda' in result
True
```

An example of using the resolve_to_function function directly:

```pycon
>>> import json
>>> # JSON format
>>> json_spec = '{"func": "len", "params": {}}'
>>> func = resolve_to_function(json_spec, parse_json_spec)
>>> func([1, 2, 3])
3
```

```pycon
>>> # Dot path format
>>> func = resolve_to_function("builtins.len")
>>> func([1, 2, 3])
3
```

### Functions

| [`parse_ast_spec`](#cw.resolution.parse_ast_spec)(func_spec)                  | Parse AST-formatted function call specification.                                                                                |
|---------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| [`parse_json_spec`](#cw.resolution.parse_json_spec)(func_spec)                 | Parse JSON-formatted function specification.                                                                                    |
| [`parse_spec_with_dot_path`](#cw.resolution.parse_spec_with_dot_path)(func_spec)        | Default parser for simple dot-path function specifications.                                                                     |
| [`resolve_func_from_dot_path`](#cw.resolution.resolve_func_from_dot_path)(dot_path)       | Resolve a function from a dot-separated import path.                                                                            |
| [`resolve_object`](#cw.resolution.resolve_object)(obj, \*, object_map[, ...]) | Resolves an object by either returning it directly if it's of the correct type, or looking it up in a mapping if it's a string. |
| [`resolve_to_function`](#cw.resolution.resolve_to_function)(func_spec[, ...])      | Resolve various function specifications into callable functions.                                                                |
| [`resource_inputs`](#cw.resolution.resource_inputs)(func, resource, \*[, ...]) | Wrap a function to source specified inputs through configurable resolvers.                                                      |

### cw.resolution.parse_ast_spec(func_spec)

Parse AST-formatted function call specification.

Expected format: ‘function_name(arg1=value1, arg2=value2)’

* **Parameters:**
  **func_spec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – String representing a function call with keyword arguments
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  Tuple of (function_name, parameters_dict)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If the expression is malformed or unsafe

### Examples

```pycon
>>> parse_ast_spec('len()')
('len', {})
```

```pycon
>>> parse_ast_spec('str.replace(old="a", new="b")')
('str.replace', {'old': 'a', 'new': 'b'})
```

```pycon
>>> parse_ast_spec('range(start=0, stop=10)')
('range', {'start': 0, 'stop': 10})
```

### cw.resolution.parse_json_spec(func_spec)

Parse JSON-formatted function specification.

Expected format: ‘{“func”: “function_name”, “params”: {“key”: “value”}}’

* **Parameters:**
  **func_spec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – JSON string with func and params keys
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  Tuple of (function_name, parameters_dict)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If JSON is malformed or missing required keys

### Examples

```pycon
>>> parse_json_spec('{"func": "len", "params": {}}')
('len', {})
```

```pycon
>>> parse_json_spec('{"func": "str.replace", "params": {"old": "a", "new": "b"}}')
('str.replace', {'old': 'a', 'new': 'b'})
```

### cw.resolution.parse_spec_with_dot_path(func_spec)

Default parser for simple dot-path function specifications.

Validates that func_spec is a dot path (`'pkg.mod.name'`) or a colon reference
(`'pkg.mod:name'`) – word characters and dots, with at most one colon – then
returns it as-is with empty kwargs.

* **Parameters:**
  **func_spec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Function specification string
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  Tuple of (function_key, kwargs_dict)
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If func_spec contains invalid characters

### Examples

```pycon
>>> parse_spec_with_dot_path('os.path.join')
('os.path.join', {})
```

```pycon
>>> parse_spec_with_dot_path('len')
('len', {})
```

```pycon
>>> parse_spec_with_dot_path('os.path:join')
('os.path:join', {})
```

### cw.resolution.resolve_func_from_dot_path(dot_path)

Resolve a function from a dot-separated import path.

Both spellings of a reference are accepted: the dot path this function is named
after, and the `'pkg.mod:name'` colon form the rest of cw documents (see
[`cw.commands.import_object()`](cw.commands.html.md#cw.commands.import_object)). The colon form is the unambiguous one – it
says where the module ends and the attribute path begins.

* **Parameters:**
  **dot_path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – String like ‘os.path.join’, ‘builtins.len’, ‘str.upper’, or the
  colon form ‘os.path:join’ / ‘json:JSONDecoder.decode’
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)
* **Returns:**
  The resolved callable function
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If the path cannot be resolved to a callable

### Examples

```pycon
>>> import os.path
>>> join_func = resolve_func_from_dot_path('os.path.join')
>>> join_func('a', 'b') == os.path.join('a', 'b')   # a separator, whichever OS
True
```

```pycon
>>> len_func = resolve_func_from_dot_path('builtins.len')
>>> len_func([1, 2, 3])
3
```

```pycon
>>> upper_func = resolve_func_from_dot_path('str.upper')
>>> upper_func('hello')
'HELLO'
```

The colon form resolves to the very same object:

```pycon
>>> resolve_func_from_dot_path('os.path:join') is os.path.join
True
>>> resolve_func_from_dot_path('json:JSONDecoder.decode')
<function JSONDecoder.decode at ...>
```

### cw.resolution.resolve_object(obj, , object_map, expected_type=None, error_message=None)

Resolves an object by either returning it directly if it’s of the correct type,
or looking it up in a mapping if it’s a string.

* **Parameters:**
  * **obj** (`Union`[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`)]) – The object to resolve. Can be a string (to be looked up in object_map)
    or the object itself (if it’s already of type T).
  * **object_map** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`)]) – A dictionary mapping strings to objects of type T.
  * **expected_type** ([`type`](https://docs.python.org/3/builtins/functions.html#type)) – (Optional) The expected type of the resolved object.
    If provided, raises a TypeError if the resolved object
    is not of this type.
  * **error_message** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – (Optional) A custom error message to use if a ValueError
    or TypeError is raised. If None, a default message is used.
* **Return type:**
  [`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`)
* **Returns:**
  The resolved object of type T.
* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If obj is not a string or of the expected type, or if the
        resolved object from the map is not of the expected type
        (when expected_type is provided).
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If obj is a string but is not found in object_map.

### cw.resolution.resolve_to_function(func_spec, func_key_and_kwargs=<function parse_ast_spec>, get_func=<function resolve_func_from_dot_path>)

Resolve various function specifications into callable functions.

This is the main entry point for function resolution. It handles:

- Direct callable objects (returned as-is)
- String specifications parsed via func_key_and_kwargs
- Function lookup via get_func
- Parameter binding via functools.partial

* **Parameters:**
  * **func_spec** (`Union`[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable), [`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncSpec`)]) – Function specification (callable, string, etc.)
  * **func_key_and_kwargs** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncSpec`)], [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncKey`, bound= [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]) – Parser function to extract key and params from spec.
    By default, will parse dot-path function names and call expressions.
  * **get_func** ([`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncKey`, bound= [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)), [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)] | [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`FuncKey`, bound= [`str`](https://docs.python.org/3/builtins/stdtypes.html#str))], [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)]) – Function or mapping to resolve function keys to callables
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)
* **Returns:**
  Resolved callable function, potentially with bound parameters
* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If func_spec type is unsupported or resolved function not callable
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If function resolution fails

### Examples

```pycon
>>> # Direct callable
>>> resolve_to_function(len)
<built-in function len>
```

```pycon
>>> # Simple string (dot path)
>>> length_func = resolve_to_function('builtins.len')
>>> length_func([1, 2, 3])
3
```

```pycon
>>> # JSON format
>>> json_func = resolve_to_function(
...     '{"func": "builtins.len", "params": {}}',
...     parse_json_spec
... )
>>> json_func([1, 2, 3])
3
```

```pycon
>>> # AST format
>>> ast_func = resolve_to_function('str.upper()', parse_ast_spec)
>>> ast_func('hello')
'HELLO'
```

```pycon
>>> # Colon reference -- the spelling the rest of cw documents
>>> import os.path
>>> resolve_to_function('os.path:join') is os.path.join
True
```

### cw.resolution.resource_inputs(func, resource, \*, default_ingress=<function resolve_to_function>)

Wrap a function to source specified inputs through configurable resolvers.

This decorator transforms specified function arguments using resolver functions,
making it particularly useful for CLI contexts where string inputs need to be
resolved to actual objects/functions.

* **Parameters:**
  * **func** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)) – The function to wrap
  * **resource** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`None`](https://docs.python.org/3/builtins/constants.html#None) | [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable) | [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – 

    Dict mapping parameter names to resource specifications:
    - None: use default_ingress (resolve_to_function by default)
    - Callable: use the callable directly as resolver
    - Dict: use as kwargs for partial(default_ingress, \*\*dict)
  * **default_ingress** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)) – Default resolver function (default: resolve_to_function)
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)
* **Returns:**
  Wrapped function with resource resolution applied to specified parameters

### Examples

```pycon
>>> def func(apple, banana, carrot):
...     return f"{apple=}, {banana=}, {carrot=}"
>>>
>>> from cw.resolution import parse_ast_spec
>>> function_store = {'a': lambda: 1, 'b': lambda: 2}
>>>
>>> wrapped_func = resource_inputs(
...     func,
...     resource=dict(
...         apple=None,  # Use default resolve_to_function
...         carrot=dict(
...             func_key_and_kwargs=parse_ast_spec,
...             get_func=function_store.get
...         )
...     )
... )
>>>
```

Now apple will be resolved via resolve_to_function
carrot will be resolved via resolve_to_function with custom params
banana remains unchanged (passed through as-is)

```pycon
>>> # apple='builtins.len' -> resolve_to_function('builtins.len') -> len function
>>> # banana='test' -> unchanged (no resource specified)
>>> # carrot='a()' -> parsed as AST, resolved via function_store
>>> result = wrapped_func('builtins.len', 'test', 'a()')
>>> 'apple=<built-in function len>' in result
True
>>> "banana='test'" in result
True
>>> 'carrot=<function' in result and 'lambda' in result
True
```
