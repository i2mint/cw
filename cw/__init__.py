"""Tools to wire a string-only environment to a Python function call.

``cw`` is a codec layer between a string-only environment -- the command line -- and a
Python function call, with somewhere to put the ``str -> object`` conversion on the way in
and the ``result -> stdout`` conversion on the way out::

    argv (strings)
      |
      |  ARGPARSE -- lexing, --help, usage:, subparsers, and the type= site
      v
    Namespace  {dest: str | list[str] | bool | None}
      |
      |  INGRESS -- Namespace -> (args, kwargs), honouring /, *args, * and **kwargs
      v
    (args, kwargs) --> f --> result
                              |
                              |  EGRESS -- result -> lines -> exit code
                              v
                         stdout + exit code

Two properties are load-bearing rather than incidental:

* **cw produces a plain** :class:`argparse.ArgumentParser`, never a subclass, so tools that
  are argparse-typed at their signature (``argcomplete.autocomplete``) keep working.
* **Importing ``cw`` costs stdlib only.** The one third-party dependency, ``i2``, is
  imported inside :func:`cw.resource_inputs` and nowhere else, and is an optional extra
  (``pip install 'cw[resource]'``). ``tests/test_import_is_cheap.py`` asserts this in a
  fresh subprocess, which is the only place the claim can honestly be checked.

>>> import cw, io
>>> def greet(name, *, loudly=False):
...     '''Say hello to someone.'''
...     return f'HELLO {name}' if loudly else f'hello {name}'
>>> out = io.StringIO()
>>> cw.dispatch(greet, ['world', '--loudly'], out=out)
0
>>> out.getvalue()
'HELLO world\\n'

The same command as a function, for a test that does not want a CLI at all:

>>> cw.dispatch(greet, ['world'], standalone=False)
'hello world'

>>> cw.resolve_to_function('builtins.len') is len
True
"""

from cw.base import (
    ArghHelpFormatter,
    Codec,
    CommandError,
    Decode,
    Egress,
    HIDE,
    MISSING,
)
from cw.cli import (
    BoundKeywordWarning,
    add_commands,
    dispatch,
    enable_completion,
    mk_parser,
    run,
    set_default_command,
)
from cw.commands import CommandTreeError, commands_from
from cw.convention import (
    ARGH,
    BY_NAME_IF_HAS_DEFAULT,
    BY_NAME_IF_KWONLY,
    MODERN,
    Convention,
)
from cw.egress import (
    argh_egress,
    confirm,
    iterable_egress,
    json_egress,
    write_lines,
)
from cw.grammar import (
    GrammarError,
    argh_decode,
    cli_name,
    command_name,
    modern_decode,
)
from cw.ingress import IngressError
from cw.resolution import (
    parse_ast_spec,
    parse_json_spec,
    parse_spec_with_dot_path,
    resolve_func_from_dot_path,
    resolve_to_function,
    resource_inputs,
)

__all__ = [
    # -- base: the shared vocabulary ---------------------------------------------------
    "ArghHelpFormatter",
    "Codec",
    "CommandError",
    "Decode",
    "Egress",
    "HIDE",
    "MISSING",
    # -- cli: building a parser, and running one ----------------------------------------
    "BoundKeywordWarning",
    "add_commands",
    "dispatch",
    "enable_completion",
    "mk_parser",
    "run",
    "set_default_command",
    # -- commands: an object becomes a {name: callable} tree -----------------------------
    "CommandTreeError",
    "commands_from",
    # -- grammar: a signature becomes command-line arguments ----------------------------
    "GrammarError",
    "IngressError",
    "argh_decode",
    "cli_name",
    "command_name",
    "modern_decode",
    # -- egress: a return value becomes lines and an exit code ---------------------------
    "argh_egress",
    "confirm",
    "iterable_egress",
    "json_egress",
    "write_lines",
    # -- convention: what the defaults ARE ----------------------------------------------
    "ARGH",
    "BY_NAME_IF_HAS_DEFAULT",
    "BY_NAME_IF_KWONLY",
    "MODERN",
    "Convention",
    # -- resolution: string specification -> callable -----------------------------------
    "parse_ast_spec",
    "parse_json_spec",
    "parse_spec_with_dot_path",
    "resolve_func_from_dot_path",
    "resolve_to_function",
    "resource_inputs",
]
