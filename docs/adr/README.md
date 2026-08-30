# Architecture decision records

Six decisions, written while cw v1 was built, in the Nygard format used across the fleet
(`docs/adr/NNNN-slug.md`, immutable once accepted; change one by writing a new ADR that
supersedes it, never by editing an accepted **Decision** section in place).

| ADR | Decides | Issue |
|---|---|---|
| [0001](0001-the-v1-seam-table.md) | The v1 seam table: three seams, their defaults, and the `NOT seams:` line | [#8](https://github.com/i2mint/cw/issues/8) |
| [0002](0002-the-ingress-stash.md) | How a **plain** `ArgumentParser` carries convention, config and ingress into `run` | [#9](https://github.com/i2mint/cw/issues/9) |
| [0003](0003-the-merge-ladder.md) | The four-tier merge ladder is argh's field-specific merge, not `dict.update` | [#10](https://github.com/i2mint/cw/issues/10) |
| [0004](0004-grammar-errata.md) | Grammar errata: `group_kwargs`, Mapping-key naming, MODERN's help column | [#11](https://github.com/i2mint/cw/issues/11) |
| [0005](0005-release-and-rollback-policy.md) | Release, pinning and rollback policy for the ~34 repos that will depend on cw | [#12](https://github.com/i2mint/cw/issues/12) |
| [0006](0006-the-v1-cut-list.md) | The v1 cut list: what cw deliberately does **not** ship, and where each comes back | [#13](https://github.com/i2mint/cw/issues/13) |

Read them in order. 0001 is the one that must outlive the session: it is the budget every
later addition is spent against.
