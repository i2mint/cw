# CW: Command-line Wrapper Utilities

CW is a Python package that provides utilities for wrapping functions to work seamlessly with command-line interfaces (CLIs). It specializes in resolving string-based function specifications into actual callable functions, making it easy to pass complex objects like functions as command-line parameters.

## Why CW?

When building command-line interfaces with great "dispatch to CLI" tools like 
`argh`, `click`, `docopt`, or `typer`, all parameter values are fundamentally strings. 
This creates a challenge when your Python functions need to accept complex objects like other functions as parameters. 

Consider this example using `argh`:

```python
import argh
from cw.resolution import resource_inputs, parse_ast_spec

def process_data(data, transform_func, multiplier=1):
    """Process data using a transformation function."""
    transformed = transform_func(data)
    return transformed * multiplier

# Without CW: This won't work from CLI because transform_func is a string
@argh.dispatch_command
def cli_process(data, transform_func, multiplier=1):
    return process_data(data, transform_func, multiplier)  # ERROR: transform_func is a string!

# With CW: This works seamlessly
function_store = {
    'double': lambda x: x * 2,
    'square': lambda x: x ** 2,
    'upper': str.upper
}

wrapped_process = resource_inputs(
    process_data,
    resource={
        'transform_func': {
            'func_key_and_kwargs': parse_ast_spec,
            'get_func': function_store.get
        }
    }
)

@argh.dispatch_command  
def cli_process_working(data, transform_func, multiplier=1):
    return wrapped_process(data, transform_func, multiplier)
```

Now you can call from the command line:
```bash
python script.py "hello" "upper()" --multiplier 3
# Results in: "HELLOHELLOHELLO"

python script.py 5 "double()" --multiplier 2  
# Results in: 20 (5 * 2 * 2)
```

## Core Components

### Function Resolution (`cw.resolution`)

The resolution module provides utilities to convert string specifications into callable functions:

- **`resolve_to_function`**: Main resolution function supporting multiple spec formats
- **`resolve_func_from_dot_path`**: Import and resolve functions from dot notation paths  
- **`parse_json_spec`**: Parse JSON-formatted function specifications
- **`parse_ast_spec`**: Parse AST-formatted function call specifications

### Resource Inputs Decorator

The `resource_inputs` decorator wraps functions to automatically resolve specified string parameters into actual objects:

```python
from cw.resolution import resource_inputs, parse_ast_spec

def func(apple, banana, carrot):
    return f"{apple=}, {banana=}, {carrot=}"

function_store = {'a': lambda: 1, 'b': lambda: 2}

wrapped_func = resource_inputs(
    func,
    resource=dict(
        apple=None,  # Use default resolve_to_function
        carrot=dict(
            func_key_and_kwargs=parse_ast_spec,
            get_func=function_store.get
        )
    )
)
```

## Examples

### Basic Function Resolution

```python
>>> from cw.resolution import resolve_to_function, parse_json_spec, parse_ast_spec

# Direct callable (returned as-is)
>>> resolve_to_function(len)  # doctest: +ELLIPSIS
<built-in function len>

# Simple string (dot path)
>>> length_func = resolve_to_function('builtins.len')
>>> length_func([1, 2, 3])
3

# JSON format
>>> json_spec = '{"func": "len", "params": {}}'
>>> func = resolve_to_function(json_spec, parse_json_spec)
>>> func([1, 2, 3])
3

# Dot path format
>>> func = resolve_to_function("builtins.len")
>>> func([1, 2, 3])
3
```

### Advanced Function Resolution with AST

```python
>>> # AST format
>>> ast_func = resolve_to_function('str.upper()', parse_ast_spec)
>>> ast_func('hello')
'HELLO'
```

### Resource Inputs in Action

```python
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

# Now apple will be resolved via resolve_to_function
# carrot will be resolved via resolve_to_function with custom params  
# banana remains unchanged (passed through as-is)

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

## Parser Functions

### Dot Path Parser

```python
>>> from cw.resolution import parse_spec_with_dot_path
>>> parse_spec_with_dot_path('os.path.join')
('os.path.join', {})

>>> parse_spec_with_dot_path('len')  
('len', {})
```

### JSON Parser

```python
>>> from cw.resolution import parse_json_spec
>>> parse_json_spec('{"func": "len", "params": {}}')
('len', {})

>>> parse_json_spec('{"func": "str.replace", "params": {"old": "a", "new": "b"}}')
('str.replace', {'old': 'a', 'new': 'b'})
```

### AST Parser

```python
>>> from cw.resolution import parse_ast_spec
>>> parse_ast_spec('len()')
('len', {})

>>> parse_ast_spec('str.replace(old="a", new="b")')
('str.replace', {'old': 'a', 'new': 'b'})

>>> parse_ast_spec('range(start=0, stop=10)')
('range', {'start': 0, 'stop': 10})
```

## Installation

```bash
pip install cw
```

## Key Features

- **CLI-First Design**: Built specifically for command-line interface needs
- **Multiple Resolution Formats**: Support for dot paths, JSON, and AST expressions
- **Flexible Resource Specifications**: Configure resolvers per parameter
- **Function Store Integration**: Use custom mappings for function resolution
- **Parameter Binding**: Automatic parameter binding with `functools.partial`
- **Type Safety**: Comprehensive validation and clear error messages

## Use Cases

- **CLI Tools**: Convert string parameters to functions in command-line applications
- **Configuration Systems**: Resolve function references from config files
- **Plugin Systems**: Dynamically load and configure functions
- **Data Processing Pipelines**: Specify transformation functions as strings
- **API Endpoints**: Accept function specifications in REST APIs

CW bridges the gap between the string-based world of command-line interfaces and the rich object model of Python, making it easy to build powerful, flexible CLI tools.