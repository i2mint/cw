"""Every ``>>>`` example in README.md and docs/adr/*.md must actually run.

The README is the package's front door and the ADRs are its permanent record, so an
example that has drifted from the code is worse than no example: a reader copies it.
``--doctest-modules`` only reaches Python modules, so these files would otherwise be
the one place in the repo where a claim is never checked.

Two mechanics are worth knowing before adding an example to those files:

- A fence line (```` ``` ````) is blanked before parsing. doctest ends an example's
  expected output at a blank line, so without this the closing fence reads as part of
  the expected output and every block "fails".
- Each file gets a *fresh* namespace pre-loaded with the names its prose defines in
  ```` ```python ```` fences (which doctest cannot execute). Keep that list in step
  with the README, or an example that leans on one will fail here rather than silently
  pass.
"""

import doctest
import pathlib
import re

import pytest

import cw

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

DOC_FILES = [REPO_ROOT / "README.md"] + sorted(
    (REPO_ROOT / "docs" / "adr").glob("*.md")
)

FENCE = re.compile(r"(?m)^```.*$")


def _readme_globals():
    """The names the README's non-doctest ```python fences bring into scope."""

    def greet(name, *, loudly=False):
        """Say hello to someone."""
        return f"HELLO {name}" if loudly else f"hello {name}"

    def add(a: int, b: int):
        """Add two numbers."""
        return a + b

    def ls(path=".", *, long=False):
        """List a directory."""
        return [f"{path}/one", f"{path}/two"]

    return {
        "cw": cw,
        "greet": greet,
        "add": add,
        "ls": ls,
        "COMMANDS": {"add": add, "list": ls, "git-ops": {"add": add}},
    }


@pytest.mark.parametrize(
    "path", DOC_FILES, ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_every_documented_example_runs(path):
    text = FENCE.sub("", path.read_text())
    globs = _readme_globals()
    runner = doctest.DocTestRunner(
        optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS
    )
    name = str(path.relative_to(REPO_ROOT))
    test = doctest.DocTestParser().get_doctest(text, globs, name, name, 0)
    runner.run(test, out=lambda s: None)
    result = runner.summarize(verbose=False)
    assert result.failed == 0, (
        f"{name}: {result.failed} of {result.attempted} examples failed. "
        f"Run `python -m pytest tests/test_docs_examples.py -k {path.stem!r} -v` "
        f"after re-running the block by hand to see the diff."
    )


def test_the_docs_actually_contain_examples():
    """A regex that silently stopped matching would make the test above vacuous."""
    counts = {}
    for path in DOC_FILES:
        text = FENCE.sub("", path.read_text())
        # Keyed by path, not by name: docs/adr/README.md would shadow the package's.
        name = path.relative_to(REPO_ROOT).as_posix()
        parsed = doctest.DocTestParser().get_doctest(text, {}, name, name, 0)
        counts[name] = len(parsed.examples)

    assert counts["README.md"] >= 20, counts
    # The three ADRs that carry transcripts. ADR-0001/0005/0006 are prose and tables.
    for adr in (
        "docs/adr/0002-the-ingress-stash.md",
        "docs/adr/0003-the-merge-ladder.md",
        "docs/adr/0004-grammar-errata.md",
    ):
        assert counts[adr] > 0, f"{adr} lost its examples: {counts}"
