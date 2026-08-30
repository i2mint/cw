"""The live differential against argh 0.31.3 -- developer-only.

Every module here builds the *same* function's parser twice, once with argh and once
with cw, and asserts the two are identical. It therefore needs argh installed, which
only ``pip install 'cw[dev]'`` provides; ``conftest.py`` skips the whole package when
argh is absent, so ``cw[test]`` (what CI installs) stays green without it.

This is the only place in the repo that imports argh, and nothing under ``cw/`` ever
does -- argh is LGPL-3.0-or-later and cw is MIT.
"""
