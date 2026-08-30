# ADR-0003: The four-tier merge ladder is argh's field-specific merge, not `dict.update`

- **Status:** accepted
- **Date:** 2026-08-30
- **Deciders:** Thor Whalen
- **Issue:** [#10](https://github.com/i2mint/cw/issues/10)

## Context

cw's whole `config` story rests on one sentence: *"leaf values **are** `add_argument`
kwargs, and `config` is merged **over** the inferred spec, later wins."* Read as a flat
`dict.update`, that sentence is wrong twice, and under D2 (bit-for-bit argh) it is an
unclosed hole in the thing everything else sits on.

**argh's real merge**, read at source (`argh/dto.py:33-50`):

```python
def update(self, other):
    for name in other.cli_arg_names:
        if name not in self.cli_arg_names:
            self.cli_arg_names.append(name)  # APPEND if absent
    if other.is_required != NotDefined:
        self.is_required = other.is_required  # only if defined
    if other.default_value != NotDefined:
        self.default_value = other.default_value  # only if defined
    if other.nargs:
        self.nargs = other.nargs  # only if TRUTHY
    if other.completer:
        self.completer = other.completer
    self.other_add_parser_kwargs.update(other.other_add_parser_kwargs)
```

and `make_from_kwargs` (`dto.py:66-88`) **pops** `required` / `nargs` / `default` out of the
kwargs dict before any of that happens. A flat `dict.update` diverges on a falsy `nargs`, on
`required=False`, and on any override that wants to unset.

**The second, worse hole: which tier suppresses type-hint inference.** argh's
`assembling.py:419` is `can_use_hints = not declared_args`, keyed off `@arg` — tier 3. The
spec said tier 2 is skipped when *tier 3* is non-empty and said nothing at all about tier 4
(`config`). But **every worked migration in the spec moves declarations from tier 3 into
tier 4** (`theremin`'s `CLI_CONFIG`, `coact`'s `CONFIG`), so those migrations would silently
re-enable hint inference that argh had switched off. theremin and coact happen to survive
because `str` is idempotent through `type=`. That is luck, not a rule — ~32 fleet files
carry annotations argh currently ignores.

## Decision

### 1. The merge is field-specific, reimplemented per `dto.py:33-50`

`cw.grammar.ArgSpec.update` is four rules, none of which is `dict.update`:

```python
for flag in other.flags:  # APPEND, never replace
    if flag not in self.flags:
        self.flags.append(flag)
if other.required is not MISSING:  # only when the override HAS one
    self.required = other.required
if other.default is not MISSING:
    self.default = other.default
if other.nargs:  # only when TRUTHY
    self.nargs = other.nargs
if other.codec is not None:
    self.codec = other.codec
self.extra.update(other.extra)  # everything else
```

`cw.MISSING` plays argh's `NotDefined` role, which is why `required=False` and
`default=None` are distinguishable from "not mentioned" — `None` cannot carry that
distinction because `None` is an ordinary default.

The **flag append** rule is the one with visible consequences. `t/theremin`'s three
parameters `synth`, `scale` and `seconds` all begin with `s`, so argh's collision rule
gives none of them a short flag; `@arg('--synth', '-s')` then *appends* after the inferred
`--synth`, and `--help` reads `--synth [SYNTH], -s [SYNTH]` — long first. cw reproduces
that with **no special case anywhere**; it falls out of append-not-replace.

### 2. Tier 4 (`config`) suppresses hints exactly as tier 3 (`@arg`) does — under `ARGH`

`convention.hints_when_declared` reads "declared" as tier 3 **or** tier 4:

```python
use_hints = convention.hints_when_declared or not (declared or config)
```

`ARGH.hints_when_declared` is `False`; `MODERN.hints_when_declared` is `True`.

This is what makes moving an `@argh.arg` into a `config` entry **behaviour-preserving**,
which is the entire purpose of D2. Verified:

```
>>> import cw
>>> from cw import compat
>>> def h(*, n: int = None):
...     return repr(n)
>>> cw.dispatch(h, ['-n', '5'])                                   # hints ON  -> int
5
0
>>> cw.dispatch(h, ['-n', '5'], config={'n': {'help': 'count'}})  # hints OFF -> str
'5'
0
>>> @compat.arg('-n', '--n', help='count')
... def h2(*, n: int = None):
...     return repr(n)
>>> cw.dispatch(h2, ['-n', '5'])                                  # hints OFF -> str
'5'
0
>>> cw.dispatch(h, ['-n', '5'], config={'n': {'help': 'count'}},
...             convention=cw.MODERN)                             # MODERN keeps hints
5
0
```

(The trailing `0` on each is `dispatch`'s exit code; the line above it is what the command
printed.)

`config` and `@arg` now give identical behaviour under `ARGH`, which the spec claimed and
a `dict.update` reading would have made false.

**This is a footgun and we are keeping it**, because it is argh's: under `ARGH`, adding a
`help` string to *one* parameter changes the *type coercion* of *every other parameter* of
that function. It is documented in `specs_for_function`'s docstring and in the README.
`convention=cw.MODERN` is the way out.

### 3. There is no spelling that unsets a value, and that is recorded rather than invented

argh has none. cw reproduces `if other.nargs:` exactly, so a falsy `nargs` in an override is
ignored:

```
>>> from cw.grammar import specs_for_function
>>> def g(*agents): ...
>>> [(s.flags, s.nargs) for s in specs_for_function(g)]
[(['agents'], '*')]
>>> [(s.flags, s.nargs) for s in specs_for_function(g, config={'agents': {'nargs': None}})]
[(['agents'], '*')]
```

We considered making `cw.MISSING` mean "unset" as an override value and **did not**: no
fleet call site wants it, argh has no equivalent, and inventing a spelling under D2 means
`ARGH` would no longer mean "argh's grammar". If a repo ever needs it, `MISSING`-as-unset is
the spelling to add, and it is an addition to `ArgSpec.update` — a boundary that already
exists.

### 4. The ladder is one function, and it lives in `cw.grammar`

`cw.grammar.specs_for_function` is the only implementation of the four tiers:

```
1. signature inference     kind, default, name, flag spellings
2. hint inference          decode(param, hint)                       <- skipped per rule 2
3. function attribute      func._cw['params'][param]                 (cw.compat.arg writes it)
4. config                  config[param]                             (this call's particulars)
```

Issue #10's acceptance criterion asked for it in `cw/convention.py`. It is in
`cw/grammar.py` instead, because `grammar` is the only module that knows what an `ArgSpec`
is: putting the ladder in `convention` would have made `convention` import `grammar`'s
internals and `grammar` import `convention`'s, a cycle for no gain. `cw/convention.py`
*documents* the ladder and this ADR is cited in both docstrings.

## Consequences

- Nine parity-corpus cases exist for the merge specifically: falsy `nargs`
  (`declared_falsy_nargs`), `required=False`, `@arg`-vs-`config` equivalence,
  `def h(*, n: int = None)`, and the theremin flag-append shape. A mutation that replaces
  the field-specific merge with `dict.update` turns **15** parity cases red; one that makes
  falsy `nargs` merge unconditionally turns **2** red. Both were run.
- Under `ARGH`, `config` is not a "local" override: touching one parameter changes the whole
  function's type inference. Anyone surprised by a `str` where they expected an `int` should
  look for a `config` entry or an `@arg` elsewhere in the same function first.
- There is a documented hole — no unset — and it is a hole argh has too. It is not a defect
  to be fixed quietly in a patch release; see ADR-0005 on why `ARGH` is frozen.
- One argh defect this ladder faithfully reproduces, found while building it and in no spec
  section: argh's **default-value guesser runs after the merge and overwrites a declared
  `nargs`**. `@arg('--xs', nargs='+')` on `def f(*, xs=[])` yields `nargs='*'`, not `'+'`,
  because `get_all_kwargs` returns `dict(field_kwargs, **other_add_parser_kwargs)`. Pinned
  by `declared_nargs_loses_to_default`. If a migrated CLI looks wrong, check this first.

## Alternatives considered

- **Flat `dict.update`**, as the spec's prose implied. Rejected: it diverges observably on
  falsy `nargs` and on `required=False`, and it *replaces* flags rather than appending them,
  which changes theremin's `--help` line. Under D2 that is a bug, not a simplification.
- **Tier 4 does not suppress hints** (the literal reading of `can_use_hints =
  not declared_args`). Rejected: it makes every "move your `@arg`s into `config`" migration
  a silent behaviour change, and the spec instructs exactly that migration seven times.
- **Nothing suppresses hints** (always resolve annotations). That is `MODERN`, and it ships
  — as an opt-in, per D2.
- **Invent `cw.MISSING` as an unset spelling.** Deferred, not rejected: no consumer.
