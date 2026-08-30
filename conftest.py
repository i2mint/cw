"""Session-wide pytest setup.

One thing only: silence `cw.compat`'s deprecation warnings for the run. `cw/compat.py`'s
doctests exercise the shim, and every one of them correctly fires a `DeprecationWarning` --
which is the module working, not a problem, but sixty-odd of them bury anything that is a
problem. `tests/test_compat.py::TestDeprecation` unsets this and asserts the warnings really
do fire, so silencing them here costs no coverage of the behaviour.
"""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _quiet_compat_deprecations():
    before = os.environ.get("CW_COMPAT_QUIET")
    os.environ["CW_COMPAT_QUIET"] = "1"
    yield
    if before is None:
        os.environ.pop("CW_COMPAT_QUIET", None)
    else:
        os.environ["CW_COMPAT_QUIET"] = before
