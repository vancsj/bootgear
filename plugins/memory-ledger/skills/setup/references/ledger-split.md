# Ledger split

Two ledgers, and which is which is not interchangeable:

| | holds | git remote |
|---|---|---|
| **shared** | facts anyone on the team can re-check: the codebase, the product, the business, third-party contracts | yes, eventually — that is the point of it |
| **local** | facts true of this machine only: shell profile, tool config, personal scratch paths, locally-bound services | never |

An existing ledger with entries in it is treated as **the shared one** — do not
repurpose it as the local ledger, and do not move it. `resolve-roots` shows where
it actually is; leave it there and record that path in the config rather than
relocating it to match a default.
