"""Every module under ``cw/`` must compile with ``SyntaxWarning`` as an error.

A non-raw docstring containing ``\\ `` (a reST escape) compiles with a ``SyntaxWarning`` on
Python 3.12+, so every consumer's first command in a fresh virtualenv prints it (issue #43).
"""

import pathlib
import warnings

import pytest

import cw

_MODULES = sorted(pathlib.Path(cw.__file__).parent.rglob("*.py"))


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: p.name)
def test_module_compiles_without_syntax_warning(path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
