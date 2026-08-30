# ADR-0006: The v1 cut list

- **Status:** accepted
- **Date:** 2026-08-30
- **Deciders:** Thor Whalen
- **Issue:** [#13](https://github.com/i2mint/cw/issues/13)
- **Depends on:** [ADR-0001](0001-the-v1-seam-table.md)

## Context

`architecture-first`'s test 1: **evidence, not naming.** A seam or a feature with no caller
is speculative generality, and naming a plausible consumer proves nothing — the consumer has
to exist somewhere you can point at.

The canonical spec contained a number of features whose only stated consumer turned out, on
inspection, not to be a cw consumer at all. This ADR is the audit: what v1 ships, what it
does not, and — for each cut — **the boundary that already exists, where it comes back**.

A cut is cheap only if its re-entry point is named. A cut with no named re-entry is a
decision someone will relitigate from scratch in six months.

## Decision

### A. Cut, with the re-entry boundary named

| cut | why | where it comes back |
|---|---|---|
| **`func_codec`** (spec §5.4) | A convenience constructor — `func_codec(get_func, /, *, parse=parse_ast_spec, passthrough=())` — with zero call sites. Its vocabulary belongs to `cw/resolution.py`, not to any module that shipped. The `Codec` it would have built is spellable in one line by hand. | A function in `cw.resolution`, returning a `Codec`. The `config[param]['codec']` leaf it feeds already exists. |
| **`cw.compat.named`** | Verified zero fleet uses. Worse, as specified it was a **silent no-op**: it writes `func._cw['name']` and nothing reads it, so `@named('load')` on `do_load` would still register `do-load`. A shim that quietly does the wrong thing is worse than the `AttributeError` it prevents. | `cw.compat.__getattr__` raises an informative error naming the cw spelling: a mapping key, `{'load': do_load}` — which also lets two commands share a name in different groups. |
| **`cw.compat.aliases`** | Verified zero fleet uses. cw has no v1 equivalent. | Same `__getattr__`. A mapping can name the same callable twice if a repo needs it. |
| **`cw.compat.add_subcommands`** | Verified zero fleet uses. It is `add_commands(..., group_name=...)` with the arguments reordered. | Same `__getattr__`, which names the working call. |
| **`Convention.formatter_class`** | Duplicated by `**parser_kwargs` — two homes for one setting and no stated precedence. | It is already there: `cw.dispatch(..., formatter_class=argparse.ArgumentDefaultsHelpFormatter)`, where argparse names it. (Consequence: `cw/convention.py` does not import `argparse`, which is what makes §12's mechanical import check honest.) |
| **`Convention.completion`** | A field that does nothing does not ship, and the spec had completion "called automatically by `mk_parser` when `convention.completion` allows" while `Convention` had no such field. | Completion is a plain `completion: bool = True` parameter on `run` and `dispatch`, plus the public `cw.enable_completion(parser)`. Adding a convention field later is one line, if a *context* ever wants to disable completion rather than a *call*. |
| **`mk_ingress` as a facade name** | Its justification was "an i2 `Ingress` is a drop-in substitute", for a package that just spent an ADR refusing to import i2. Nobody asked for it as a public name. | It exists and is documented as `cw.ingress.mk_ingress`, honouring i2's `{name: value} -> (args, kwargs)` contract, and is simply not in `cw.__all__`. Promoting it is one line. |

### B. Not cut, and why the cut list's reasoning did not survive contact

Issue #13 proposed four further cuts. Each was re-examined against the code that now exists,
and each turned out to have a real caller. Recorded here so the question is closed rather
than reopened:

**`json_egress` — kept.** The cut list's objection was "its pointer is `t/py2mcp`, which is
explicitly not a cw consumer". True, and incomplete: `t/xa/xa/cli.py:777` hand-rolls
`print(json.dumps(out, indent=2, default=str))` *inside a command body*, and xa's migration
replaces exactly that line with `egress=cw.json_egress`. That is a cw call site in the
migration plan, which is the evidence test 1 asks for. Twelve statements, fully covered.

**`import_object` / the `'pkg.mod:name'` string form of `obj` — kept.** It has a caller
inside cw itself: `python -m cw specs 'pkg.mod:func'`, which answers *"what flags does this
function get, and why did that one not get a short flag"* without importing anybody's
`__main__`. That command is the most useful thing cw's own CLI does. The spec's unresolved
ambiguity is also resolved rather than inherited: **a string is always exactly one command,
with no command word.** §8.2 says "a bare string is ALWAYS one command" and §8.1's callable
row says "one command; no command word"; a string resolves to a callable, so the two rows
compose. `mk_parser` resolves the string before the single-command check.

**Core `cw.add_commands` — kept.** Two callers, both real. `cw.compat.add_commands`
(15 measured fleet call sites) has to be three statements or fewer, which means the real
implementation lives in the core. And the parity corpus's `xa` shape uses
`mk_parser` + `add_commands(group_kwargs=...)` + `run` — the **only** path that exercises
ADR-0004 rule 1's `add_parser(help=group_kwargs.get('title'))` code path at all. Cutting it
from the core would mean rewriting that shape and losing the coverage.

**The Site-B `Codec` protocol — kept, in part.** The cut list's case was that its only named
consumer (`t/theremin`) does not need it: theremin's four
`partial(resolve_to_function, ...)` are at `script_utils.py:236-241`, *inside* `run_theremin`,
never at the parser boundary — errata E12, and a prototype reproduced theremin 19/19 with no
codec at all. That is correct and it is why `func_codec` is cut above.

What is kept is the mechanism, not the convenience layer: `cw.Codec` (a two-field value:
`decode`, `passthrough`), the `ArgSpec.codec` field, the `config[param]['codec']` leaf, and
`mk_ingress(codecs=...)`. Three reasons:

1. The re-entry point the cut list named — *"`config[param]['codec']`, a new leaf key on a
   dict that already exists"* — **is** this mechanism. Cutting `Codec` and keeping the leaf
   is not a smaller thing; it is the same thing without a name.
2. The grammar already promotes a bare callable in a `config` leaf to a `Codec`. Cutting it
   now is a three-module change, and leaving `ArgSpec.codec` in place while `mk_ingress`
   ignored it would ship a dead field — the exact defect this ADR exists to prevent.
3. It closes a real hole that argparse's `type=` cannot: argparse applies `type=` to a
   string `default` and to a `const` too, so a decoder that resolves names to objects would
   be handed theremin's `'list'` sentinel and its defaults as well as its real arguments.
   `passthrough` is what lets the sentinel survive, and
   `tests/test_fleet_shapes.py::test_the_sentinel_survives_a_codec` demonstrates the case.

### C. Not built at all in v1 — the standing list

Neither cut nor deferred; simply out of scope, with the shape of the eventual addition
recorded so nobody designs it twice.

1. **Docstring-derived per-parameter help.** argh's `help='%(default)s'` wart means an
   undocumented flag's help column reads `False` or `'json'`. The replacement exists —
   `i2.doc_mint.docstring_to_params` (`doc_mint.py:405`) parses numpy/google/rest — and
   `t/an/an/__main__.py:76-106` is the fleet convention it would restore. Not in v1 because
   it is not implemented, and a `Convention` field that does nothing does not ship. When it
   arrives it is `cw[docs]`, imported lazily inside a function: the one place i2 earns its
   way back in. **It is also what unblocks `MODERN.default_in_help=False`** (ADR-0004
   rule 4).
2. **Lazy command loading.** `priv/__init__.py` is a careful PEP-562 lazy design that
   `__main__.py` defeats by `getattr`-ing 47 names. cw does not fix it: argparse must have
   *every* subparser registered to print `--help` and to let argcomplete complete. A pre-scan
   is ~15 lines and makes `priv --help` incomplete — breaking the one feature seven fleet
   repos depend on. If it is ever wanted, the spelling is a lazy group value, and nothing in
   the current rules changes.
3. **A surface-neutral `CommandSpec` / non-CLI adapters.** No consumer. `py2mcp` and `qh`
   consume plain functions by string ref today. See ADR-0001's `Surface for v1:` line.
4. **`**kwargs` collection from the command line.** No agreed spelling (`--set k=v`? bare
   `k=v`? repeated `--opt`?) and the only candidate consumer, `wads.populate_pkg_dir`'s
   `**configs`, is content to have them dropped — which is argh's behaviour and therefore
   cw's. Picking a spelling without a consumer is speculative.
5. **Async.** Zero fleet occurrences. v1 does exactly one thing: `guard_no_coroutine` raises
   an informative `TypeError` naming `asyncio.run`, **at the call site in `run`**, so no
   choice of egress can switch it off. This is a deliberate, documented divergence — argh's
   real behaviour is to print `<coroutine object ...>` and warn, having never run the body,
   and reproducing *that* is not what D2 means by fidelity.
6. **Windows-specific handling.** cw inherits argparse's platform behaviour and adds
   nothing: `'-'`→stdin, EPIPE on a closed pipe, and colour detection are absent, as they
   are in argh. `cw.testing`'s `shlex.split` is POSIX-only; a golden may spell its argv as a
   JSON list instead, which is the documented Windows path.
7. **`cw.bind` / `set_dispatch_defaults` / a `Param` class / a `Codec` registry / a `name_of=`
   seam.** All named in candidate proposals; all replaced by, respectively,
   `functools.partial(cw.dispatch, convention=..., prog=...)`, plain dicts of `add_argument`
   kwargs, fall-through composition, and the `{name: func}` mapping form.

### D. `mk_parser` is pure; completion fires at dispatch time

The spec specified `mk_parser` as pure — *"no parsing, no I/O, no side effects"* — **and** as
firing `argcomplete.autocomplete()`, which reads the environment and can `exit()` the
process, while also selling `mk_parser` as the thing a test inspects. Those cannot all hold.

**Decision: completion fires at dispatch time**, which is where argh fires it.
`cw.enable_completion` does its `import argcomplete` *inside the function* (so `import cw`
stays stdlib-only, enforced by `tests/test_import_is_cheap.py`), and `run` calls it before
parsing. `mk_parser` performs no I/O, imports nothing third-party, and cannot exit the
process; a test asserts it.

## Consequences

- The public API listing in the README is exactly `cw.__all__`, and `cw.__all__` is exactly
  what survived this ADR. A name in one and not the other is a bug in whichever is newer.
- `cw.compat`'s `__getattr__` means a repo that used `argh.named` gets a message naming the
  cw spelling instead of a traceback that names nothing. The three unshipped names are the
  only place cw's compat layer refuses rather than translates.
- Section B closes four questions that three previous phases each flagged as open. They are
  closed *with* their evidence, so reopening one means finding a caller that does not exist
  rather than re-reading the same spec paragraph.
- Section C's items are additions at boundaries that already exist. None of them requires
  a core change, which is the claim ADR-0001 makes and this section is the audit of.
- One cost worth stating: keeping `Codec` means cw ships a mechanism whose only demonstrated
  case is a test fixture. That is the weakest "kept" decision in this ADR, and if a year
  passes with no `config[param]['codec']` in the fleet, it is the first thing to cut.

## Alternatives considered

- **Cut everything issue #13 listed, on principle.** Rejected: four of the seven had callers
  the issue had not seen, and cutting `add_commands` would have removed the only path that
  exercises ADR-0004 rule 1.
- **Keep `named` as specified** (write `func._cw['name']`, read it in `cw.commands`). That
  is a feature, not a shim, and it duplicates the mapping-key rule ADR-0004 rule 2 just
  settled. Two ways to name a command is not compatibility.
- **Ship `func_codec` because `Codec` survived.** Rejected: `Codec` earns its place as the
  mechanism behind a documented leaf key; `func_codec` is a convenience with no call site,
  and it is one line to write by hand when someone needs it.
- **Fire completion in `mk_parser`** (the spec's literal reading). Rejected: it makes the
  build step read the environment and possibly exit, which breaks the thing `mk_parser` is
  for — being inspected by a test.
