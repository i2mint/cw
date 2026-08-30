"""Skip the live-argh differential when argh is not installed.

`argh` is a **dev** extra, never a test one: cw's CI installs `cw[test]`, which has no argh
in it, precisely so that `python -m cw.testing parity` proves it needs nothing but cw. This
directory is the other half of the story -- it builds the same parser with argh and with cw
and diffs them, which of course needs argh -- so it removes itself rather than erroring at
collection time.

Run it with `pip install -e '.[dev]'`. Without that, `pytest` is still green; it just is not
asserting the thing this directory asserts, and the skip line says so.
"""

import importlib.util

#: Everything here needs argh at import time, so the skip has to happen at collection.
collect_ignore_glob = [] if importlib.util.find_spec("argh") else ["*.py"]
