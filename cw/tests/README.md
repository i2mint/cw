# The parity corpus

```
python -m cw.testing parity
```

> **v1 is done when that prints `8 shapes / 137 cases: identical` and exits 0.**

`fixtures.py` holds eight self-contained shapes; `goldens/*.json` holds what **real argh
0.31.3** did with each of their argv vectors, recorded once and committed. `parity` replays
them through cw with every seam on its default (`convention=cw.ARGH`, `decode=cw.argh_decode`,
`egress=cw.argh_egress`) and asserts four things per case: **exit code, stdout, stderr, and
the normalised `usage:` line.**

| shape | models | cases |
|---|---|---|
| `theremin` | `t/theremin` | 19 |
| `priv` | `t/priv` | 21 |
| `epythet` | `i/epythet` | 14 |
| `coact` | `t/coact` | 19 |
| `xa` | `t/xa` | 17 |
| `wads_pack` | `i/wads` | 17 |
| `lacing` | `t/lacing` | 13 |
| `contract` | the D2 contract's egress and error rows | 17 |
| **total** | | **137** |

That total is **counted**, not asserted:
`tests/test_corpus_coverage.py::test_the_case_count_is_counted_rather_than_asserted`
recomputes it from `fixtures.SHAPES`. The canonical spec's "7 repos / 214 cases" was an
invented number with no file behind it; this one has 137 argv vectors in a file, each with a
comment saying which argh rule it pins.

## Why shapes and not the seven repos

As the spec first wrote it, parity "rebuilds each of the seven hard-case repos' command sets
through cw". It cannot run in cw's CI that way, for reasons that are structural:
`theremin/script_utils.py:12`, `coact/__main__.py:26` and `epythet/cli.py:15` are module-scope
`import argh`; `t/theremin` **depends on cw**, which is circular; and installing seven fleet
packages to test a package whose selling point is zero dependencies defeats the exercise.

So the corpus reproduces the seven repos' *shapes*. The seven real repos are gated separately,
by `cw.testing.replay` in each repo's own CI at migration time — which is what D4 actually asks
for.

## Contract-row coverage

`tests/test_corpus_coverage.py` maps each of the 20 rows of the argh compatibility contract
(canonical spec §9) to what covers it, and fails if a row is covered by nothing.

**17 of the 20 rows are asserted by `parity`.** The other three — 14 (`help` defaults to
`%(default)s`), 15 (help renders `repr(default)`, `None` → `-`) and 20 (a group's listing row
reads `group_kwargs['title']`, never `['help']`) — are observable **only** in a `--help` body,
and the golden format keeps help bodies at tier 3: recorded, diffed advisorily by `diff_help`,
never asserted. That is not laziness; `--help` wraps to `COLUMNS` and Python 3.13 reformatted
argparse's option column, so asserting it would produce false failures on a matrix cw has to
be green on.

Those three are covered instead by `tests/argh_parity/`, which builds the same parser with argh
and with cw **in one process at one Python** and asserts the rendered help is byte-identical —
a comparison a committed golden cannot make. It needs `pip install -e '.[dev]'`; without argh
it skips itself.

## Windows — ADR: option A, "normalise"

Issue #14 asked whether parity means anything on the Windows runner (`test_on_windows = true`).
**Decision: A. Normalise, and run everywhere.** Recorded in `cw/testing.py`'s module docstring.

Four things make it real rather than hopeful:

1. **Newlines are normalised on both sides.** Goldens store LF and carry `"newlines": "lf"`;
   every comparison runs both sides through `normalise_text`, so `\r\n` from a Windows
   `print` asserts clean. Tested by `test_a_crlf_golden_asserts_clean_against_lf_output`.
2. **`parity` spawns no subprocess.** It runs in-process against these fixtures, so the
   `.exe` console-script shim and console code pages never enter the picture. Only
   `characterize`/`replay` spawn, and those pin `PYTHONUTF8`/`PYTHONIOENCODING`.
3. **`read_cases` parses a JSON list as well as a `shlex` line**, so a Windows user writing a
   corpus never reaches POSIX-only `shlex`.
4. **Every golden is pure ASCII**, asserted by a test, so the code page cannot matter even in
   principle.

## Re-recording

`argh` is **not** a dependency of cw — not at runtime and not in the `test` extra CI installs.
Recording is a one-time developer act:

```bash
pip install -e '.[dev]'          # this, and only this, brings argh 0.31.3
python misc/record_goldens.py    # all shapes, or name the ones you want
git diff cw/tests/goldens/       # review every line: this is the thing being asserted
```

Re-recording an unchanged fixture produces a byte-identical file (sorted keys, pinned env,
scrubbed heap addresses), so a non-empty `git diff` here always means a real behaviour change.
