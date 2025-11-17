"""Function resolution utilities for CLI parameterization.

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

Now apple will be resolved via resolve_to_function
carrot will be resolved via resolve_to_function with custom params
banana remains unchanged (passed through as-is)

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

An example of using the resolve_to_function function directly:

>>> import json
>>> # JSON format
>>> json_spec = '{"func": "len", "params": {}}'
>>> func = resolve_to_function(json_spec, parse_json_spec)
>>> func([1, 2, 3])
3

>>> # Dot path format
>>> func = resolve_to_function("builtins.len")
>>> func([1, 2, 3])
3


"""

# TODO: Expand and merge the resolve_object function (see at the end of the file)

import ast
import importlib
import json
import re
from functools import partial
from typing import Tuple, TypeVar, Union
from collections.abc import Callable, Mapping

FuncSpec = TypeVar("FuncSpec")
FuncKey = TypeVar("FuncKey", bound=str)


def _get_builtin(name: str):
    """Get a built-in object, handling both dict and module __builtins__."""
    import builtins

    return getattr(builtins, name)


def resolve_func_from_dot_path(dot_path: str) -> Callable:
    """Resolve a function from a dot-separated import path.

    Args:
        dot_path: String like 'os.path.join', 'builtins.len', or 'str.upper'

    Returns:
        The resolved callable function

    Raises:
        ValueError: If the path cannot be resolved to a callable

    Examples:
        >>> import os.path
        >>> join_func = resolve_func_from_dot_path('os.path.join')
        >>> join_func('a', 'b')  # doctest: +ELLIPSIS
        'a/b'

        >>> len_func = resolve_func_from_dot_path('builtins.len')
        >>> len_func([1, 2, 3])
        3

        >>> upper_func = resolve_func_from_dot_path('str.upper')
        >>> upper_func('hello')
        'HELLO'
    """
    if "." not in dot_path:
        # Handle built-ins and single names
        try:
            return _get_builtin(dot_path)
        except AttributeError:
            raise ValueError(f"Cannot resolve '{dot_path}' as a built-in function")

    parts = dot_path.split(".")

    # Special handling for built-in types like str, int, float, etc.
    if len(parts) == 2 and parts[0] in (
        "str",
        "int",
        "float",
        "list",
        "dict",
        "set",
        "tuple",
        "bool",
        "bytes",
    ):
        try:
            base_type = _get_builtin(parts[0])
            func = getattr(base_type, parts[1])
            if not callable(func):
                raise ValueError(f"'{dot_path}' is not callable")
            return func
        except AttributeError:
            raise ValueError(f"'{parts[0]}' has no attribute '{parts[1]}'")

    # Standard module import path
    func_name = parts[-1]
    module_path = ".".join(parts[:-1])

    try:
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        if not callable(func):
            raise ValueError(f"'{dot_path}' is not callable")
        return func
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Cannot resolve '{dot_path}': {e}")


def parse_spec_with_dot_path(func_spec: str) -> tuple[str, dict]:
    """Default parser for simple dot-path function specifications.

    Validates that func_spec contains only word characters and dots,
    then returns it as-is with empty kwargs.

    Args:
        func_spec: Function specification string

    Returns:
        Tuple of (function_key, kwargs_dict)

    Raises:
        ValueError: If func_spec contains invalid characters

    Examples:
        >>> parse_spec_with_dot_path('os.path.join')
        ('os.path.join', {})

        >>> parse_spec_with_dot_path('len')
        ('len', {})
    """
    if not isinstance(func_spec, str):
        raise TypeError(f"func_spec must be a string, got {type(func_spec)}")

    if not re.match(r"^[\w.]+$", func_spec):
        raise ValueError(
            f"func_spec must contain only word characters and dots: '{func_spec}'"
        )

    return func_spec, {}


def parse_json_spec(func_spec: str) -> tuple[str, dict]:
    """Parse JSON-formatted function specification.

    Expected format: '{"func": "function_name", "params": {"key": "value"}}'

    Args:
        func_spec: JSON string with func and params keys

    Returns:
        Tuple of (function_name, parameters_dict)

    Raises:
        ValueError: If JSON is malformed or missing required keys

    Examples:
        >>> parse_json_spec('{"func": "len", "params": {}}')
        ('len', {})

        >>> parse_json_spec('{"func": "str.replace", "params": {"old": "a", "new": "b"}}')
        ('str.replace', {'old': 'a', 'new': 'b'})
    """
    try:
        data = json.loads(func_spec)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in func_spec: {e}")

    if not isinstance(data, dict):
        raise ValueError("JSON func_spec must be a dictionary")

    if "func" not in data:
        raise ValueError("JSON func_spec must contain 'func' key")

    func_name = data["func"]
    params = data.get("params", {})

    if not isinstance(func_name, str):
        raise ValueError("'func' value must be a string")

    if not isinstance(params, dict):
        raise ValueError("'params' value must be a dictionary")

    return func_name, params


def parse_ast_spec(func_spec: str) -> tuple[str, dict]:
    """Parse AST-formatted function call specification.

    Expected format: 'function_name(arg1=value1, arg2=value2)'

    Args:
        func_spec: String representing a function call with keyword arguments

    Returns:
        Tuple of (function_name, parameters_dict)

    Raises:
        ValueError: If the expression is malformed or unsafe

    Examples:
        >>> parse_ast_spec('len()')
        ('len', {})

        >>> parse_ast_spec('str.replace(old="a", new="b")')
        ('str.replace', {'old': 'a', 'new': 'b'})

        >>> parse_ast_spec('range(start=0, stop=10)')
        ('range', {'start': 0, 'stop': 10})
    """
    if not isinstance(func_spec, str):
        raise TypeError(f"func_spec must be a string, got {type(func_spec)}")

    if not "(" in func_spec or not ")" in func_spec:
        return parse_spec_with_dot_path(func_spec)

    try:
        # Parse the expression safely
        tree = ast.parse(func_spec, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid syntax in func_spec: {e}")

    if not isinstance(tree.body, ast.Call):
        raise ValueError("func_spec must be a function call expression")

    call_node = tree.body

    # Extract function name
    func_name = _extract_func_name(call_node.func)

    # TODO: Should we generalize to support other types of arguments?
    # Only allow keyword arguments for safety and clarity
    if call_node.args:
        raise ValueError("Only keyword arguments are supported in AST format")

    # Extract keyword arguments
    kwargs = {}
    for keyword in call_node.keywords:
        if keyword.arg is None:  # **kwargs not allowed
            raise ValueError("**kwargs syntax not supported")

        # Safely evaluate the argument value
        try:
            value = ast.literal_eval(keyword.value)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Unsafe or invalid argument value for '{keyword.arg}': {e}"
            )

        kwargs[keyword.arg] = value

    return func_name, kwargs


def _extract_func_name(node: ast.AST) -> str:
    """Extract function name from an AST node.

    Handles both simple names (Name) and attribute access (Attribute).
    """
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        # Recursively build the dotted name
        base = _extract_func_name(node.value)
        return f"{base}.{node.attr}"
    else:
        raise ValueError("Unsupported function name format")


def resolve_to_function(
    func_spec: Callable | FuncSpec,
    func_key_and_kwargs: Callable[
        [FuncSpec], tuple[FuncKey, dict]
    ] = parse_ast_spec,  # also parse_json_spec and parse_spec_with_dot_path
    get_func: (
        Mapping[FuncKey, Callable] | Callable[[FuncKey], Callable]
    ) = resolve_func_from_dot_path,
) -> Callable:
    """Resolve various function specifications into callable functions.

    This is the main entry point for function resolution. It handles:
    - Direct callable objects (returned as-is)
    - String specifications parsed via func_key_and_kwargs
    - Function lookup via get_func
    - Parameter binding via functools.partial

    Args:
        func_spec: Function specification (callable, string, etc.)
        func_key_and_kwargs: Parser function to extract key and params from spec.
            By default, will parse dot-path function names and call expressions.
        get_func: Function or mapping to resolve function keys to callables

    Returns:
        Resolved callable function, potentially with bound parameters

    Raises:
        TypeError: If func_spec type is unsupported or resolved function not callable
        ValueError: If function resolution fails

    Examples:
        >>> # Direct callable
        >>> resolve_to_function(len)  # doctest: +ELLIPSIS
        <built-in function len>

        >>> # Simple string (dot path)
        >>> length_func = resolve_to_function('builtins.len')
        >>> length_func([1, 2, 3])
        3

        >>> # JSON format
        >>> json_func = resolve_to_function(
        ...     '{"func": "builtins.len", "params": {}}',
        ...     parse_json_spec
        ... )
        >>> json_func([1, 2, 3])
        3

        >>> # AST format
        >>> ast_func = resolve_to_function('str.upper()', parse_ast_spec)
        >>> ast_func('hello')
        'HELLO'
    """
    # Resolve Mapping get_func into a function
    if isinstance(get_func, Mapping):
        func_store = get_func
        get_func = func_store.get

    if callable(func_spec):
        # If func_spec is already a function, just return it
        return func_spec
    elif isinstance(func_spec, str):
        # Get function key and kwargs from the specification
        func_key, kwargs = func_key_and_kwargs(func_spec)

        # Resolve the function key into a function
        try:
            func = get_func(func_key)
        except Exception as e:
            raise ValueError(
                f"get_func could not resolve '{func_key}' into a function "
                f"(func_spec={func_spec!r}): {e}"
            )

        if not callable(func):
            raise TypeError(
                f"get_func({func_key!r}) returned non-callable object "
                f"(func_spec={func_spec!r}): {func!r}"
            )

        if not kwargs:
            # If no kwargs were given, just return the function
            return func
        else:
            # If kwargs were given, bind them to the function
            if not isinstance(kwargs, dict):
                raise TypeError(
                    f"kwargs must be a dictionary, but got {type(kwargs)} "
                    f"(func_spec={func_spec!r})"
                )
            return partial(func, **kwargs)
    else:
        raise TypeError(
            f"func_spec must be either a callable or a string, got {type(func_spec)} "
            f"(func_spec={func_spec!r})"
        )


"""Resource inputs decorator for function argument sourcing.

This module provides a decorator that wraps functions to source specific arguments
through configurable resolution mechanisms, particularly useful for CLI contexts
where string inputs need to be resolved to actual objects/functions.
"""

from functools import partial
from typing import Dict, Any, Optional, Union
from collections.abc import Callable
from cw.resolution import resolve_to_function
from i2.wrapper import Ingress, wrap


def _resolve_resource_spec(resource_spec, default_ingress: Callable) -> Callable:
    """Convert a resource specification into a callable resolver.

    Args:
        resource_spec: Resource specification - can be:
            - None: use default_ingress
            - Callable: use directly
            - Dict: use as kwargs for partial(default_ingress, **resource_spec)
        default_ingress: Default ingress function to use

    Returns:
        Callable that can resolve the input value

    Examples:
        >>> from cw.resolution import resolve_to_function
        >>> resolver = _resolve_resource_spec(None, resolve_to_function)
        >>> # resolver is now resolve_to_function

        >>> resolver = _resolve_resource_spec(lambda x: x.upper(), resolve_to_function)
        >>> # resolver is the lambda function

        >>> resolver = _resolve_resource_spec({'get_func': {'a': 1}.get}, resolve_to_function)
        >>> # resolver is partial(resolve_to_function, get_func={'a': 1}.get)
    """
    if resource_spec is None:
        return default_ingress
    elif callable(resource_spec):
        return resource_spec
    elif isinstance(resource_spec, dict):
        return partial(default_ingress, **resource_spec)
    else:
        raise TypeError(
            f"Resource spec must be None, callable, or dict. Got {type(resource_spec)}"
        )


def _create_resource_kwargs_trans(
    resource_resolvers: dict[str, Callable],
) -> Callable[[dict], dict]:
    """Create a kwargs transformation function for resource resolution.

    Args:
        resource_resolvers: Mapping of parameter names to their resolver functions

    Returns:
        Function that transforms kwargs by applying resolvers to specified parameters
    """

    def _kwargs_trans(outer_kwargs: dict) -> dict:
        """Transform kwargs by resolving specified parameters."""
        transformed = {}

        for param_name, value in outer_kwargs.items():
            if param_name in resource_resolvers:
                resolver = resource_resolvers[param_name]
                transformed[param_name] = resolver(value)
            else:
                # Parameters not in resource keep their original values
                transformed[param_name] = value

        return transformed

    return _kwargs_trans


def resource_inputs(
    func: Callable,
    resource: dict[str, None | Callable | dict[str, Any]],
    *,
    default_ingress: Callable = resolve_to_function,
) -> Callable:
    """Wrap a function to source specified inputs through configurable resolvers.

    This decorator transforms specified function arguments using resolver functions,
    making it particularly useful for CLI contexts where string inputs need to be
    resolved to actual objects/functions.

    Args:
        func: The function to wrap
        resource: Dict mapping parameter names to resource specifications:
            - None: use default_ingress (resolve_to_function by default)
            - Callable: use the callable directly as resolver
            - Dict: use as kwargs for partial(default_ingress, **dict)
        default_ingress: Default resolver function (default: resolve_to_function)

    Returns:
        Wrapped function with resource resolution applied to specified parameters

    Examples:

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

        Now apple will be resolved via resolve_to_function
        carrot will be resolved via resolve_to_function with custom params
        banana remains unchanged (passed through as-is)

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

    """
    # Build resolver functions for each resourced parameter
    resource_resolvers = {
        param_name: _resolve_resource_spec(resource_spec, default_ingress)
        for param_name, resource_spec in resource.items()
    }

    # Create the kwargs transformation function
    kwargs_trans = _create_resource_kwargs_trans(resource_resolvers)

    # Create ingress using the Ingress class
    ingress = Ingress(
        inner_sig=func,
        kwargs_trans=kwargs_trans,
        outer_sig=func,  # Keep same signature  # TODO: Add annotation and default control
        allow_excess=True,
        apply_defaults=True,
    )

    # Wrap the function using the ingress
    return wrap(func, ingress=ingress)


# ------------------------------------------------------------------------------------
# Generic type for object resolution

T = TypeVar("T")


# TODO: Expand and merge with resolve_to_function and resource_inputs
def resolve_object(
    obj: str | T,
    *,
    object_map: dict[str, T],
    expected_type: type = None,
    error_message: str = None,
) -> T:
    """
    Resolves an object by either returning it directly if it's of the correct type,
    or looking it up in a mapping if it's a string.

    Args:
        obj: The object to resolve. Can be a string (to be looked up in object_map)
             or the object itself (if it's already of type T).
        object_map: A dictionary mapping strings to objects of type T.
        expected_type: (Optional) The expected type of the resolved object.
                       If provided, raises a TypeError if the resolved object
                       is not of this type.
        error_message: (Optional) A custom error message to use if a ValueError
                       or TypeError is raised. If None, a default message is used.

    Returns:
        The resolved object of type T.

    Raises:
        TypeError: If obj is not a string or of the expected type, or if the
                   resolved object from the map is not of the expected type
                   (when expected_type is provided).
        ValueError: If obj is a string but is not found in object_map.
    """
    if isinstance(obj, str):
        if obj in object_map:
            resolved_obj = object_map[obj]
        else:
            msg = error_message or f"Unknown object identifier: {obj}"
            raise ValueError(msg)
    elif expected_type is None or isinstance(obj, expected_type):
        resolved_obj = obj
    else:
        msg = error_message or f"Expected type {expected_type}, got {type(obj)}"
        raise TypeError(msg)

    if expected_type and not isinstance(resolved_obj, expected_type):
        msg = (
            error_message
            or f"Resolved object should be of type {expected_type}, got {type(resolved_obj)}"
        )
        raise TypeError(msg)

    return resolved_obj
