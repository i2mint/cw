"""Self-contained fixtures and committed argh goldens for :func:`cw.testing.parity`.

Shipped **inside** the package on purpose: ``python -m cw.testing parity`` is the definition
of v1, and a gate that only runs from a source checkout is not a gate. Nothing here is
imported by ``cw`` itself -- :func:`cw.testing.parity` imports it lazily, and only when it
runs.
"""
