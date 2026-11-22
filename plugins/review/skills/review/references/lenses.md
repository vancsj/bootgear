# Review lenses

Give each finder its selected rows, the diff, and the linked ticket. Record each find angle as checked or inapplicable.

| Lens | Finder brief |
|---|---|
| `correctness` | Find changed behavior that fails for a reachable input or event order. Check edge cases, failure paths, and state. |
| `tests` | Find changed behavior that no test would catch breaking. Find tests that cannot fail. |
| `security` | Check injection, authorization, authentication, and secrets. Find a path to unauthorized data or effects. |
| `architecture` | Check fit with surrounding code. Require a design-pattern tell in the diff and a cost scenario in the repo. |
| `simplicity` | Find abstractions, branches, complexity, or duplicate utilities the change can remove without changing behavior. |
| `contract` | Check callers and consumers of public API, schema, CLI, event, and file formats. Find broken or unstated contracts. |
| `consistency` | Compare names, structure, errors, docs, and tests with peers inside and outside the file. Cite each peer as `file:line`. Use `traced` only with all citations. Otherwise use `inferred`. |

## Changed behavior checks

Trace values from input through writers, copies, timing, readers, and visible output.
Keep fields with different writers or meaning distinct.
Compare validation and application order. Check affected reversals, edits, retries, recovery, and caches.
Check relationship ownership, updates, and deletion across callers. Test assumptions in code, tests, and diagrams against primary evidence.
Use current confirmed intent when a ticket is stale. Check that each test can reject a concrete wrong output.

For changed trust, untrusted input, authentication, authorization, or sensitive data, apply STRIDE.
Trace spoofing, tampering, repudiation, disclosure, denial of service, and privilege escalation through controls and observable tests.
Give short reasons for inapplicable categories. Keep effort proportionate. Use normal Converge treatment.
Give independent roles the full diff, request, standards, and raw evidence. Keep author reasoning and suspect lists private.

## Cut dimensions per lens

After attack, use public evaluate angles for `impact`, `size`, `reach`, and `difficulty`. Rate `rate` when the lens uses it.

| Lens | Rating |
|---|---|
| `correctness` | Use the wrong result for `impact`. Count changed users or records for `size`. Count reaching call sites or production queries for `rate` (`call-site-count`, `prod-traffic`). |
| `tests` | Use the untested behavior for `impact` and `reach`. |
| `security` | Use `reach: crafted` when only attacker input reaches the trigger. |
| `contract` | Use `impact: clarity` when a changed surface leaves a caller contract unstated. |
| `architecture` | Count commits touching the claim's files in 90 days for `rate` (`git log`, `file-churn`). Use the repo cost scenario for `impact`. |
| `simplicity` | Use `clarity` or `cosmetic` unless extra code returns a wrong result. |
| `consistency` | Use `clarity` unless divergence returns a wrong result. |
