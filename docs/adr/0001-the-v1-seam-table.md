# ADR-0001: The v1 seam table

- **Status:** accepted
- **Date:** 2026-08-30
- **Deciders:** Thor Whalen
- **Issue:** [#8](https://github.com/i2mint/cw/issues/8)

## Context

cw replaces `argh` (LGPL-3.0-or-later) across a fleet in which ~34 repos will end up
declaring it and 47 console scripts already sit on the thing being replaced. The
`architecture-first` discipline asks for the seam table **before** the first commit,
because the boundaries decided in v1 are the ones every later iteration has to add at.

The forcing constraint is decision **D2**: cw reproduces argh's grammar bit-for-bit by
default, and every improvement ships as a named value that defaults *off*. D2 buys the
migration — a repo swaps its dispatcher and its `--help` does not move — and it is also
what pushes this table past the shape `architecture-first` prefers. That tension is the
substance of this ADR, not a footnote to it.

## Decision

**Three seams. Each is exactly one keyword argument on `cw.dispatch` / `cw.mk_parser`.
Each default is a real, complete implementation — never a stub. Each has a replacement
that exists on disk today.**

| # | Seam (one kwarg) | v1 default — real, not a stub | Replacement you can point at |
|---|---|---|---|
| 1 | **`decode=`** — how a parameter's type is inferred.<br>`(Parameter, hint) -> add_argument kwargs \| callable \| None` | `cw.argh_decode` — argh 0.31.3's two inference paths (the annotation guesser `TypingHintArgSpecGuesser`, `assembling.py:739-793`, and the default-value guesser `guess_extra_parser_add_argument_spec_kwargs`, `:310-364`) unified into one function with one precedence order. | **`cw.modern_decode`, shipping in v1** — `Optional[X]` unwrap, `Enum` by name-then-value, `pathlib.PurePath`. D2 mandates that it ship and that it default off. The *symptom* that motivates the seam is `lacing/cli.py:249-253`, which hand-writes `int()` in a function body under the comment *"argh delivers option values as strings; coerce here."* |
| 2 | **`egress=`** — result to lines to exit code.<br>`(result, *, out, err) -> int` | `cw.argh_egress` — argh's `isinstance(result, (GeneratorType, list, tuple))` whitelist (`dispatching.py:398`): a `dict` prints on one line, `None` prints nothing, `0`/`False`/`''` do print, generators stream lazily and flush per line. | **`cw.iterable_egress` and `cw.json_egress`, shipping in v1.** `t/xa/xa/cli.py:777` already hand-rolls `print(json.dumps(out, indent=2, default=str))` *inside a command body* because argh has no egress hook at all; `i/qh/qh/base.py:37 mk_json_egress` is the house's other egress, already written. |
| 3 | **`convention=`** — a re-binding of what the defaults ARE | `cw.ARGH` — nine fields, every one at argh's real value, every one asserted by the parity corpus. | **`cw.MODERN`, shipping in v1**, which D2 mandates. Precedent: `i/streamlitfront/streamlitfront/base.py:339` is `mk_app(objs, config=None, convention=None)` — the same two words with the same meanings, already shipping in the fleet. |

```
Surface for v1: CLI only. MCP / HTTP / frontend / shipped skills: asked, not built.
                Would any of them need the core to change? NO -- py2mcp.mk_mcp_from_refs
                (py2mcp/main.py:91) and qh.mk_fastapi_app (qh/base.py:103) consume the same
                plain functions by string ref today. cw IS the CLI row of that table, not a
                layer under it. Nothing in cw is shared with them, so nothing in cw has to
                move when one of them changes.

NOT seams:      argparse itself -- it IS the product. argcomplete.autocomplete(argument_parser:
                argparse.ArgumentParser, ...) is argparse-typed at the signature, so 10 fleet
                repos and 10 `# PYTHON_ARGCOMPLETE_OK` markers survive an argh->cw migration
                untouched, which the t/an typer migration could not do (an/__main__.py:21-25
                records that argcomplete had to be dropped). No `parser_backend=`.
              . prog / description / epilog / formatter_class / allow_abbrev / conflict_handler
                -- passed VERBATIM as **parser_kwargs to argparse.ArgumentParser. cw invents no
                vocabulary for anything argparse already names.
              . The config -> convention precedence ladder. Four fixed tiers, one function.
                No pluggable resolver, no ChainMap subclass. (ADR-0003.)
              . Short-flag inference. argh's first-character collision rule with -h suppression,
                written directly as data. `Convention.short_flags: bool` turns it off; there is
                no `short_flag_strategy=` callable.
              . The flag append-merge rule. Load-bearing for byte-identical --help, written
                directly. (ADR-0003.)
              . The obj -> {name: func} discrimination rule. A callable value is a command,
                a Mapping/Iterable value is a group. Structural, written directly.
              . Completion. `try: import argcomplete` inside `enable_completion`, fired at
                dispatch time, written fresh (argh's completion.py is LGPL). shtab is MPL-2.0
                and unadjudicated, so there is nothing to point at -- no `completion_backend=`.
              . The exception -> exit-code policy. CommandError -> one line to err, exit(code);
                everything else keeps its traceback; a SystemExit keeps its exit code. Written
                directly: 4 fleet occurrences in 2 repos, and argh's wrap_errors / raw_output /
                always_flush / skip_unknown_args / EntryPoint / ArghNamespace /
                parse_and_resolve / run_endpoint_function have ZERO fleet uses across all 109
                argh-touching files.
              . The output stream. `out=`/`err=` are plain parameters resolved at CALL time,
                not seams. (This one line is what makes cw CLIs testable with capsys, which
                argh CLIs are not -- argh binds `output_file: IO = sys.stdout` in a signature
                default at dispatching.py:77.)
              . The two-level nesting limit. argh's limit; xa and priv are the only group users.
              . `cw.compat`'s eleven names. Fixed surface, matched to measured fleet usage.
              . A Codec registry / a `Param` class / `cw.bind` / `set_dispatch_defaults`.
                functools.partial(cw.dispatch, convention=..., prog=...) is the house dispatch,
                written directly. Nothing to build.
              . Async. Zero fleet occurrences. Not abstracted -- see ADR-0006.
              . Colour / TTY detection. Absent. argh has none, the fleet uses none.
```

**The argcomplete census, because two documents got it wrong.** The canonical spec says
"7 fleet repos", an earlier draft of this ADR said eight. Both are wrong. Counted directly
over `$PP` (`grep -rl --include='*.py' PYTHON_ARGCOMPLETE_OK`, discarding cw's own two
source files, which only mention the marker in prose): **10 marker files across 10 repos** —
`t/article`, `t/coact`, `t/ek`, `t/ke`, `t/ocracy`, `t/openloops`, `t/paces`, `t/scribed`,
`t/skill`, `tt/reelee` — and every one of the ten is an argh consumer. That is the number
this row is about, and it is larger than either document claimed.

### Three things this table must say honestly, because the review caught them

**1. Seam 1's headline pointer in the canonical spec was wrong.**
`cw/resolution.py:318 resolve_to_function` is `(str) -> callable` — a *value converter*.
`Decode` is a *grammar inferencer*: it answers "what `add_argument` kwargs does this
parameter get". The spec itself proves at length that `resolve_to_function` must **not**
sit at argparse's `type=` site. The replacement to point at is `cw.modern_decode`;
`lacing/cli.py:249-253` is the symptom, not the replacement.

**2. The honest surface count is nine, not three.**
`convention=` is one keyword argument carrying a frozen dataclass of **nine** fields —
`naming`, `short_flags`, `hyphenate_commands`, `hyphenate_groups`, `default_in_help`,
`hints_when_declared`, `resolve_hints`, plus `decode` and `egress`, which *are* seams 1
and 2 given a per-context home. Counted as switches a caller can flip, that is seven
grammar switches plus two seams: **nine**, past `architecture-first`'s stop-and-ask
ceiling of seven.

We stopped, asked, and shipped it anyway. **D2 forced it.** "Every improvement ships as a
named convention value that defaults off" is not satisfiable with fewer switches, because
each switch is a place where argh's behaviour and the better behaviour genuinely differ
and both must be reachable. The alternative — one boolean `modern=True` — was rejected: it
makes every future improvement a breaking change to the meaning of a flag, which is the
opposite of what D2 buys.

(Issue #8 estimated twelve. Nine is the shipped number; `formatter_class` was cut by
ADR-0006 as duplicated by `**parser_kwargs`, and the draft's remaining count was a
double-count of `decode`/`egress` as both fields and seams.)

**3. `architecture-first` test 4 — "v1 ships exactly one implementation per seam" — is
deliberately spent.** cw ships two decoders, three egresses and two conventions:

| seam | implementations shipped in v1 |
|---|---|
| `decode=` | `argh_decode` (default), `modern_decode` |
| `egress=` | `argh_egress` (default), `iterable_egress`, `json_egress` |
| `convention=` | `ARGH` (default), `MODERN` |

This is priced, not overlooked. Test 4 exists to stop "and here's the S3 one too, for
later" — a second implementation with no caller. Here the second implementation *is* the
product: D2's promise is precisely "the improvement exists and is one keyword away", and a
`MODERN` that does not exist makes the promise unverifiable. `json_egress` is the weakest
of the three (ADR-0006 examines it and keeps it, at 12 statements).

Tests 1–3 hold unspent: every seam names a replacement that exists on disk, every seam is
one keyword argument with no base class or registry behind it, and the count stopped at
three.

## Consequences

- **Adding a seam later requires amending this ADR.** The `NOT seams:` list above is
  binding; a fourth keyword argument that switches behaviour is a change to this table,
  written as a new ADR that supersedes it.
- Every default named here is a working implementation, asserted by
  `python -m cw.testing parity` (8 shapes / 133 cases against goldens recorded from live
  argh 0.31.3) and by `tests/argh_parity/` (a live differential when `cw[dev]` is
  installed). A seam whose default became a stub would fail the gate, not merely read
  badly.
- `convention=` being one argument that carries nine fields means "flip cw to modern
  behaviour" stays one act at one call site — which is what makes the nine survivable.
- The `Surface for v1: CLI only` line is a commitment that the *core* owes nothing to a
  future MCP/HTTP surface. If one arrives and needs the core to change, that is evidence
  this line was wrong, and it gets its own ADR.

## Alternatives considered

- **Fold `decode` and `egress` into `convention` only** (two seams, not three). Rejected:
  the one-off case — this call, this function, this egress — is the common one, and
  forcing a caller to construct a `Convention` to change one thing fails progressive
  disclosure.
- **A `parser_backend=` seam** so cw could sit over `click` or `typer` later. Rejected by
  test 1 and by the whole point of the package: argparse *is* the product, because
  `argcomplete.autocomplete` is argparse-typed at its signature and ten fleet
  `# PYTHON_ARGCOMPLETE_OK` markers depend on that.
- **A `name_of=` command-naming hook.** Built and tested in a candidate, then cut: the
  `{name: func}` mapping form covers its only fleet case (`t/xa`), and xa needs that form
  anyway for `gen-secret` and the `archive` group. Two ways to do one thing is not a seam.
- **`out=` as a fourth seam.** It is a parameter *of* the egress seam, not a peer of it.
