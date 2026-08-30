# ADR-0005: cw's release, pinning and rollback policy for the fleet

- **Status:** accepted
- **Date:** 2026-08-30
- **Deciders:** Thor Whalen
- **Issue:** [#12](https://github.com/i2mint/cw/issues/12)

## Context

cw is not an ordinary package on this fleet. 62 repos carry `argh` lines, ~34 will end up
declaring `cw`, and 47 console scripts sit across the repos being migrated. And on this
fleet **a merge to the default branch is a PyPI upload the same day**: cw is wads-managed
(`i2mint/wads/.github/workflows/uv-ci.yml@master`, `[tool.wads.ci.publish] enabled = true`),
so merge → automatic version bump → upload, with no human step between.

That combination means a grammar bug in cw 0.1.1 is a **fleet-wide incident** — 34 repos
whose CLIs change shape at their next `pip install` — and until this ADR there was no
stated containment for it. This is the one gap in the whole cw programme that costs a
fleet-day rather than a repo-hour.

The special hazard is D2. cw's value proposition is "your `--help` does not move". A
package whose grammar can drift between patch releases has no value proposition at all,
because "the fleet's tests still pass" would stop meaning anything.

## Decision

### 1. The dependency spelling every repo uses

```toml
dependencies = ["cw>=0.1,<0.2"]
```

Verbatim, in every migrating repo's `pyproject.toml`. It is the copy-paste line in the
README's migration section.

Rationale: `>=0.1` because the migration needs the v1 API; `<0.2` because cw is a 0.x
package and, by the rule below, a `0.2` is where a grammar change would live. `cw~=0.1` is
the same constraint spelled less obviously; a bare `cw` is what makes a bad release a fleet
incident instead of a repo incident.

Repos that install cw as an optional CLI extra (`t/ocracy`, `t/scribed`) use the same
specifier inside their `[cli]` extra.

### 2. `cw.ARGH` is frozen once published

**A change to the grammar under `cw.ARGH` is not a patch, not a minor version, and not
allowed. It is a new named `Convention` value.**

This is the load-bearing rule of the whole policy. `ARGH` means "argh 0.31.3's grammar". If
`ARGH` can drift, D2 buys nothing and the committed goldens stop being a contract. So:

- A *bug* in cw's reproduction of argh — where cw and argh 0.31.3 genuinely differ — is a
  fix, ships as a patch, and shows up as a golden diff that has to be reviewed line by line.
- A *change* to what the grammar ought to be — better `Optional[X]` handling, hyphenated
  groups, docstring-derived help — never touches `ARGH`. It goes into `MODERN`, or into a
  new named value beside it.
- Consequently, **a non-empty `git diff cw/tests/goldens/` in a PR is a review gate.** Those
  bytes are the contract. Re-recording an unchanged fixture is byte-identical, so any diff
  at all is a real behaviour change.

### 3. The grammar-freeze test — cw's CI is the release gate

`python -m cw.testing parity` replays 8 shapes / 133 cases against goldens recorded from
live argh 0.31.3 and committed to the repo. It runs in cw's own CI on every push, on
3.10 and 3.12, on Linux, macOS and Windows. **An `ARGH` drift therefore fails cw's CI
before the publish step runs**, because wads' publish job is gated on the test job.

It is falsifiable, not decorative: nine plausible reimplementation mistakes were each
introduced deliberately and each turned the gate red (36, 17, 15, 3, 2, 2, 2, 3 and 34
differing cases respectively). A change that passes the whole suite *and* survives swapping
`store_false` for `store_true` means a corpus case is missing, not that the change is safe.
The battery was re-run on 3.10 and on 3.12 and produced the **same nine counts** on both,
which is the evidence for the paragraph below.

**A golden is recorded on one interpreter and asserted on the whole matrix, so the gate
must not assert the recording machine's CPython version.** It did, and that made a correct
cw red on 3.10: `argparse` quoted the choices in its `invalid choice` message up to 3.11
and stopped in 3.12, and it rewrapped the `usage:` block's trailing `...` in 3.13. Neither
is cw's output — argh and cw print the same bytes as each other on any one interpreter —
so `cw.testing.canonical_argparse_text` canonicalises exactly those two renderings, on
both sides of every comparison, and nothing else. Two rules, each naming the CPython change
it answers; adding a third is a change to the gate's meaning and needs the mutation battery
re-run to show it still bites. With it the gate is `identical` on 3.10, 3.11, 3.12 and 3.13.

### 4. Yank policy

A released version is yanked when — and only when — it would have failed the parity gate,
i.e. an `ARGH` grammar regression escaped. Thor executes it (`twine`/PyPI web UI); it is not
delegated, because a yank is a permanent, public statement about a version number.

Two things a yank does **not** do, which is why it is the *second* action and never the
first:

- It does not touch an environment where the bad version is already installed. Only the
  pin-back does.
- It does not free the version number. A PyPI version is burned permanently once used; the
  fix ships as the next number.

### 5. The rollback drill — executed, not merely written

**The drill.** A consumer pinned `cw>=0.1,<0.2` resolves to the newest matching release. cw
0.1.1 is published carrying a grammar regression (short-flag collision suppression dropped
— argh's rule that if two parameters share a first letter, *neither* gets a short flag).
Rolling back is one `pip install` with `==` and the last-good version.

The transcript below is real. Two wheels were built from this tree — `cw 0.1.0` unmodified,
`cw 0.1.1` with `_flag_spellings`'s collision check removed — a throwaway consumer `demo`
declaring `cw>=0.1,<0.2` was installed into a fresh venv, and both halves were run.

```
$ pip install --no-index --find-links ./wheels demo    # cw>=0.1,<0.2 resolves to the newest
cw      0.1.1
demo    0.1.0

$ demo --help
  ...
  File ".../cw/cli.py", line 184, in set_default_command
    parser.add_argument(*args, **kwargs)
argparse.ArgumentError: argument -p/--pool: conflicting option string: -p
  ...
cw.grammar.GrammarError: serve: cannot add 'pool' as -p/--pool: argument -p/--pool:
conflicting option string: -p

$ python -m cw.testing parity
[theremin] $ --help
returncode:
  - 0
  + 1
stderr:
  + GrammarError: theremin_cli: cannot add 'log_knobs' as -l/--log-knobs: argument
    -l/--log-knobs: conflicting option string: -l
  ...
8 shapes / 133 cases: 36 DIFFER
exit=1
```

**The rollback, one command:**

```
$ pip install --no-index --find-links ./wheels "cw==0.1.0"
cw      0.1.0
demo    0.1.0

$ demo --help
usage: demo [-h] [--host HOST] [--port PORT] [--pool POOL]

Serve something.

options:
  -h, --help   show this help message and exit
  --host HOST  '0.0.0.0'
  --port PORT  8080
  --pool POOL  -

$ python -m cw.testing parity
8 shapes / 133 cases: identical
exit=0
```

Three things the drill established that a written procedure would not have:

1. **The failure is loud, at startup, in every affected repo simultaneously** — a
   `GrammarError` from `parser.add_argument`, before any command runs. It is not a silent
   change of behaviour. That is a considerable comfort and it is a property of *this*
   regression, not a guarantee about every possible one.
2. **`python -m cw.testing parity` diagnoses it from the installed package**, in a venv
   containing cw and nothing else — no argh, no source checkout. It is the first command to
   run when a fleet repo's CLI misbehaves after an upgrade, and it names the shape and the
   case.
3. **The rollback needs no coordination.** `pip install "cw==<last-good>"` in the affected
   environment; the consumer's own pin is untouched.

**The escalation ladder, in order:**

| step | action | scope |
|---|---|---|
| 1 | `pip install "cw==<last-good>"` in the broken environment | one env, seconds |
| 2 | `python -m cw.testing parity` to confirm the diagnosis | one env |
| 3 | Pin the *consumer* — `cw>=0.1,<0.2,!=<bad>` — if the repo redeploys before the fix | one repo |
| 4 | Yank the bad version on PyPI (Thor) | fleet |
| 5 | Fix in cw, with a corpus case that goes red without the fix, and release the next patch | fleet |
| 6 | Unpin step 3 | one repo |

Step 3 is a **consumer-side `!=`**, not a fleet-wide re-pin: a scripted fleet action that
edits 34 `pyproject.toml` files is a bigger, less reversible event than the incident it
responds to. Only a repo that actually redeploys during the window needs it.

### 6. Pre-release channel: waves, not release candidates

Repos do **not** migrate against an rc tag. The pre-release channel is the migration wave
order itself:

- **Wave 0** is the repos whose CLI behaviour is covered by their own tests and whose
  maintainer is the person releasing cw. They migrate first, and their CI is cw's real
  pre-release signal.
- **Wave 1 and later** migrate only after Wave 0 has been green through at least one cw
  release.

A repo that needs to test an unreleased cw pins the git ref for the duration
(`cw @ git+https://github.com/i2mint/cw@<sha>`) and returns to `cw>=0.1,<0.2` before its own
merge. A merge that must not publish carries `[skip ci]` in the merge commit — which
suppresses the whole workflow, tests included, so it is for documentation-only merges, not
for holding back a code change.

Rejecting rc tags is a judgement about this fleet, not about rc's in general: with
"whatever lands" as the release cadence and one person releasing, an rc adds a step whose
only signal — "does the fleet still work" — is exactly what Wave 0's CI already reports,
and it burns a version number to get it.

## Consequences

- `cw>=0.1,<0.2` in ~34 repos means a `0.2` is a deliberate, coordinated fleet event. That
  is the intended cost: a grammar change should be hard.
- The committed goldens are now a release contract, and reviewing a golden diff is part of
  reviewing a cw PR. `cw/tests/README.md` states the per-shape counts and a test asserts the
  README matches, so a silently added or removed case is caught too.
- cw's CI must stay green on all three OSes for the publish step to run. That is already the
  configuration (`test_on_windows = true`).
- The drill's throwaway artefacts are not committed. Re-running it takes about two minutes:
  build two wheels from this tree with the collision check removed from
  `cw/grammar.py:_flag_spellings` in one of them, and follow the transcript.
- The `ARGH`-is-frozen rule constrains future work in a way worth stating plainly: a
  genuinely better default cannot be shipped by improving `ARGH`. It ships as `MODERN`, and
  a repo opts in. That is the deal D2 made and this ADR is where it becomes binding on
  releases rather than only on code.

## Alternatives considered

- **Bare `cw` in consumers.** Simplest, and turns every cw release into an unbounded fleet
  experiment. Rejected.
- **Exact pins (`cw==0.1.3`) fleet-wide.** Maximum containment, and it makes every cw patch
  a 34-repo pull request. Rejected: the cure costs more than the disease, every time.
- **`ARGH` may be fixed in patch releases when it diverges from argh.** Kept, deliberately —
  that is rule 2's first bullet, and it is the only kind of `ARGH` change allowed. What is
  rejected is *improving* `ARGH`.
- **Publish release candidates before each minor.** Rejected for this fleet; see rule 6.
- **A scripted fleet re-pin as the standard incident response.** Rejected as step 3; it is
  a larger, slower and less reversible action than the per-environment rollback that
  actually fixes the outage.
