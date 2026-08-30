# ADR-0008: No fourth channel for a group's `group_kwargs`

- **Status:** accepted
- **Date:** 2026-08-30
- **Deciders:** Thor Whalen
- **Issue:** [#31](https://github.com/i2mint/cw/issues/31)

## Context

`cw.dispatch({'archive': {'ls': ls}})` builds the group. It has nowhere to say
`title='Postmortem archive'`, so the group's row in the parent's `--help` is bare where argh
printed a title. `cw.add_commands(parser, obj, group_name=..., group_kwargs=...)` **does**
have that channel and is byte-identical to argh at both levels — but reaching it means
splitting one `dispatch` call into `mk_parser` + `add_commands` + `run`.

Issue #31 weighed three ways to close the gap in the mapping form itself:

1. a mapping **value** that is a `(funcs, kwargs)` pair — `{'archive': (ARCHIVE, {'title': ...})}`;
2. a **`group_config=`** mapping on `mk_parser` / `dispatch`, keyed by group name;
3. a **reserved key** inside the existing `config` tree — `config['archive']['__group__']`.

The issue recorded that none was obviously right, which is why it was cut from v1.

**Then the live case shipped.** `t/xa` is the one fleet repo that passes `group_kwargs`, and
its migration off argh landed while this was still open ([xa#14](https://github.com/thorwhalen/xa/pull/14)).
It used the two-call form. The migrator's report is the evidence this ADR turns on, and it
is worth quoting rather than paraphrasing:

> Real but small, and the workaround is good — the gap is documentation, not capability.
> […] Once found, `cw.mk_parser(TOP, prog='xa')` + one `add_commands` reads as the same
> two-call shape argh had, seeds the formatter correctly (avoiding the reflow trap by
> construction), and forced a pure `mk_parser()` — which turned out to be the best thing in
> the xa PR, because it made 14 grammar tests possible. **I would choose it again over a
> hypothetical `dispatch(MAPPING, group_config=...)`.**

Three findings from that migration, all verifiable in the repo today:

- The two-call form is not a downgrade. Splitting the build from the run produced a pure
  `mk_parser()` that a test can inspect without running anything. `t/xa` had **no** CLI-shape
  test before the migration — nothing asserted that `gen-secret` was spelled that way, or
  that `archive list` did not shadow the top-level `list`, though thirteen `__name__`
  mutations depended on it. It has fourteen now, and they exist because `mk_parser` became a
  function that returns a parser.
- The formatter trap is avoided **by construction** on this route. Seeding with
  `cw.mk_parser(...)` rather than a bare `argparse.ArgumentParser()` means `formatter_class`
  is already `cw.ArghHelpFormatter`, so `add_commands`' `_child_formatter` propagates it and
  `--help` does not reflow. A `group_config=` keyword would have kept callers on `dispatch`,
  where that is not a hazard either — but it would also have kept them away from the parser
  object, which is where the tests live.
- The thing `t/xa` actually passed was `group_kwargs={'help': ...}`, which is **inert**. The
  parent's listing row comes from `title`; `help` reaches `add_subparsers()`, where argparse
  accepts it and renders it nowhere. That string had never been shown to anyone
  ([xa#13](https://github.com/thorwhalen/xa/issues/13)). So the motivating case for a new
  channel was, on inspection, a case that needed a **better error message**, not a new
  keyword.

## Decision

**cw grows no fourth channel. The mapping form stays as it is, `add_commands` remains the
one place a group's `add_subparsers` keywords are passed, and the two-call form is promoted
from a footnote to the documented answer.**

Each rejected option, and why:

| option | rejected because |
|---|---|
| `(funcs, kwargs)` pair as a mapping value | It adds a **seventh** form of `obj` and breaks the rule the whole module is built on: *the meaning of a value is decided by the value's kind*. A tuple is already an iterable, i.e. already a group; making a two-member tuple mean something else makes `{'grp': (f, g)}` and `{'grp': ([f], {})}` differ in kind, which nobody can read. |
| `group_config=` on `mk_parser` / `dispatch` | It is a fourth behaviour-carrying keyword, so ADR-0001's seam table needs an amendment for something that is **not a seam** — no default to name, no replacement to point at. It is also a second way to do what `add_commands` already does, and the live case reports preferring the existing way. |
| a reserved key in `config` | `config` is *per-parameter* particulars, keyed `{command: {param: add_argument_kwargs}}`. A group's `add_subparsers` keywords are particulars of no parameter. The reserved key would have to be a sentinel to avoid colliding with a command called `__group__`, which means a new public name in the facade for a keyword one repo passes. |

**What cw owes a caller instead: every rejected spelling must name the accepted one.** All
three were already errors; none of them said what works. That is the actual defect, and it
is what this ADR's implementation fixes:

- `mk_parser(..., group_kwargs=...)` / `dispatch(..., group_kwargs=...)` — and `group_name`,
  plus argh's pre-0.30 `namespace` / `namespace_kwargs` spellings — join
  `cw.cli.SEAMS_ELSEWHERE`, which already exists for exactly this ("a real cw keyword, but
  not on *this* call"). They previously reported that `argparse.ArgumentParser` has no such
  keyword and listed argparse's parameters: true, and useless.
- `{'archive': (ARCHIVE, {'title': ...})}` raises `CommandTreeError` naming the pair by
  name. It previously died inside `command_name` complaining that a `dict` has no
  `__name__`, which names neither what was tried nor what works.
- `config={'archive': {'title': ...}}` already raised `config key 'title' matches no
  command`, which is a true answer to a question the caller did not ask. It now appends the
  recipe when **every** unknown key names an `add_subparsers` keyword — so an ordinary
  misspelt command still gets the short, relevant error.

All three point at one string, `cw.cli.TWO_CALL_GROUP_RECIPE`, so there is no second copy of
the advice to drift. The recipe names the two things that bite people on this route, both
learned from real migrations rather than guessed:

1. `group_kwargs['title']`, never `['help']` — the xa#13 trap above; and
2. `raise SystemExit(cw.run(parser))`, because `cw.run` **returns** an exit code where
   argh's `parser.dispatch()` raised it. Splitting a `dispatch` call in two is precisely
   when that gets dropped, and a console script that starts exiting `0` on a usage error
   breaks every CI step that checks `$?`. Two independent migration waves reported this as
   the highest-risk step in a modern-API migration, and nothing catches it: unit tests pass,
   and a `--help` diff shows nothing.

## Consequences

- **Nothing a user sees moves.** No grammar change, no new keyword, no `--help` difference.
  The parity gate stays at `8 shapes / 137 cases: identical`, which it does.
- `t/xa` needs no change. Its `mk_parser()` is now the documented shape rather than a
  workaround, and the comment in `xa/cli.py` explaining why it is two calls can stay as it
  is — it is correct.
- The README's `add_commands` section now shows the **mapping** form with `group_kwargs`.
  The pilot had to read `cw/cli.py:522-579` to confirm a mapping was accepted there at all;
  the docstring said so and the README only ever showed a list.
- **If this decision is wrong, the symptom will be specific and countable**: repos that end
  up on `mk_parser` + `add_commands` *only* for a group title, and would otherwise have been
  one `dispatch` line. There is one such repo today. Revisit at three, and if it is
  revisited, `group_config=` is the option to revisit — it is the only one of the three that
  does not damage a rule cw relies on elsewhere.
- ADR-0001's seam table is **unamended**, which is the point. The `NOT seams:` block gains
  nothing because nothing was added.

## Also settled here

Two loose ends from the same review, recorded so they are not rediscovered:

- **`cw/util.py`** — flagged by the foundation phase as an empty module (docstring only,
  zero importers). It was already deleted in the v1 land (commit `54369a0`); nothing to do,
  and this line exists so the next reader does not go looking for it.
- **`group_kwargs['help']` stays inert.** Making cw raise or warn on it would be a
  divergence from argh in the one direction cw does not go, and it would fire on every
  invocation of an already-migrated repo. It is documented in the README and named in the
  error message instead. `cw.MODERN` is where a future ADR could make it loud, since MODERN
  is allowed to differ; it does not do so in this one.
