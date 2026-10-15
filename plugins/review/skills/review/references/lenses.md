# review lenses

Each lens is one topic of the single finder, F. Its brief lists every lens of
the depth with the scope and brief below, plus the diff and, when one is
linked, the ticket. For each lens, F declares the find angles whose tell
matches the diff (`find-angles.yaml`, plus `design-patterns.yaml` for
`architecture`) and records every other angle as not applicable.

| Lens | Depth | Scope | Brief |
|---|---|---|---|
| `correctness` | quick, full | Claimed behavior, edge cases, failure paths, state. | Find where the code does not do what the change claims, for some reachable input or order of events. |
| `tests` | quick, full | Tests added, changed or missing for the changed behavior. | Find behavior the change adds or alters that no test would catch breaking, and tests that cannot fail. |
| `security` | full | Injection, authorization, authentication, sensitive-data exposure, secrets. | Find a path by which an untrusted input or caller gets an effect or data it should not. |
| `architecture` | full | Fit with surrounding structure; the design-pattern catalog. | Find a design choice with a tell in the diff and a cost scenario shown in this repo. |
| `simplicity` | full | Unnecessary abstraction, unreachable branches, excess complexity, reinvented utilities. | Find code the change could drop or shrink with the same behavior. |
| `contract` | full | Public API, schema, CLI, event and file-format surfaces; callers and consumers. | Find a caller or consumer that the changed surface breaks or leaves unstated. |

## Cut dimensions per lens

The cutter rates each claim's `impact`, `size` and `reach`, `rate` when its
lens policy counts it, and `difficulty` after the attack, deciding each value
by the tests `converge angles --tag evaluate` prints. Per lens:

| Lens | Meaning |
|---|---|
| `correctness` | `impact` from the wrong result; `size` counts users or records whose result changes; `rate` counts call sites or production queries that reach the trigger (`call-site-count`, `prod-traffic`). |
| `tests` | `impact` and `reach` of the behavior no test would catch breaking. |
| `security` | `reach: crafted` when only input an attacker supplies reaches the trigger. |
| `contract` | `impact: clarity` when the changed surface leaves a caller's contract unstated. |
| `architecture` | `rate` counts the commits touching the claim's files in the last 90 days (`git log` churn, the `file-churn` angle); `impact` from the cost scenario shown in this repo. |
| `simplicity` | `impact` is `clarity` or `cosmetic` unless the extra code returns a wrong result. |
