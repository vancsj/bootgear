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

## Evaluation fields for design claims

Cutters score `architecture` claims from the design-pattern catalog with these
meanings instead of the correctness ones.

| Field | Correctness | Design |
|---|---|---|
| `frequency` | How often the trigger runs. | How often the area changes: `git log` churn of the files. |
| `severity` | User or data impact. | Cost of reversal once other code builds on it. |
| `confidence` | Reproduced or traced. | Cost scenario shown in this repo, versus argued. |
| `difficulty` | Fix effort. | Fix effort now versus later. |
