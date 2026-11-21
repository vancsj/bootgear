---
name: resolve
description: Settle a disagreement with the run's source of truth. Use before debate or when a debate stalls.
---

## Inputs and outcomes

Take the disagreement, caller, `<engine-root>`, and `<session-dir>`. Return one result to `execute` or `debate`.

- **Decided** — the decision and its `source_of_truth` domain, or the user's applicable deputy assertion.
- **Escalated** — return `debate`'s handback unchanged. It can be a recorded closed question, a factual refusal, or `inconclusive`.
  Send factual disputes to `converge`. A refusal or inconclusive result records no outcome.
- **Not settled** — no domain settled a stuck round. Let `debate` continue toward `round_cap`.

Use before debate for disagreements at or above `debate_threshold`. In threshold mode, `execute` decides lower claims solo.
In a stalled debate, use the positions supplied by `debate` before it reaches the cap.

## Procedure

1. If settlement is stale, call `recall` with the same run paths.
2. Classify the domain: `scope and outcome`, `current behavior`, `implementation approach`, or `correctness`.
   Use scope for whether work belongs. Use current behavior for whether to change it.
3. Read and apply that domain's settled source. Read the ticket if it controls scope.
4. If the source settles it, record the decision.

   ```text
   <gear> --host <host> engine task session record-decision --mode resolve --summary "<decision and source_of_truth domain>"
   ```

   For a stuck round, omit `--question` and state that the decision broke the stall.
5. If no single source settles it, follow the route for this caller.
   - For a stuck round, return **Not settled**. Do not start another debate.
   - Before debate, call `deputy:ask`. Use an applicable `assertion` as the decision.
     Record it as `solo` with its slug and return.
   - On escalation, retain only cited slugs present in the candidates. If deputy is absent, record `no-deputy:not-installed`.
     Call `debate` in the same turn. Pass the fields below.

| Pass to debate | Content |
|---|---|
| Decision | Plain question, touched domains, and each unsatisfied condition. |
| Sources | Full `source_of_truth`, `debate_threshold`, `task_type`, `goal`, and merged user, project, and task principles. |
| Run | Same `<engine-root>` and `<session-dir>`. |
| Deputy | Applicable `deputy_slugs` as past user decisions. Omit them if deputy is absent. |

## Rules

Apply only settled authorities. Keep `approach` out of the principles.
Leave production changes, outward sends, irreversible actions, goal sign-off, and mutation permissions with the user.
Require `debate` to recall its roster, parties, cap, policies, and admission. Keep those fields out of the handoff.
On escalation, leave recording to `debate` with `debate`, `debate-capped`, or `debate-degraded`.
Pass each free-text value as one quoted argument. Never interpolate it into a shell command string.

## Fallbacks

If a sibling skill is missing, stop and report `cli:setup` for `engine`. Resume after it verifies dependencies.

## Host mechanics

Get the absolute path from `cli:gear`. Run `<gear> --host <host> engine task <command>`.
Gear reads the run ID from the environment. Add `--dir <session-dir>` only for a custom directory.
Pass the installed Engine root, `<plugin-dir>` on Claude Code or `<plugin-root>` on Codex, as `<engine-root>`.

| Host | `<host>` | Install missing CLI |
|---|---|---|
| Claude Code | `claude` | `/plugin install cli@bootgear` |
| Codex | `codex` | `codex plugin add cli@bootgear` |
