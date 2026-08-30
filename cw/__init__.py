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

>>> import cw
>>> cw.CommandError('no such pipeline', code=2).code
2
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
from cw.resolution import (
    parse_ast_spec,
    parse_json_spec,
    parse_spec_with_dot_path,
    resolve_func_from_dot_path,
    resolve_object,
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
    # -- resolution: string specification -> callable -----------------------------------
    "parse_ast_spec",
    "parse_json_spec",
    "parse_spec_with_dot_path",
    "resolve_func_from_dot_path",
    "resolve_object",
    "resolve_to_function",
    "resource_inputs",
]
