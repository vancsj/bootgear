---
name: resolve
description: Resolve disagreements during `execute` from the settlement's per-domain `source_of_truth` order; if no settled source applies, invoke `debate` with the settled source text and `principles`. Use during engine runs when two considerations conflict.
---

Apply the settlement's per-domain `source_of_truth`.

Invoke `debate` with the required settlement data when no settled source applies.

Read `reference.md` § `resolve — design rationale` for design rationale.

## When to run

Run `resolve` when `execute` sends a disagreement in either case:

1. **Before `debate`.** Check `debate_threshold` in the settlement. Run this case when the disagreement is at or above that threshold. Decide below-threshold disagreements `solo` in `execute`; do not send them to `resolve`. Use this case for conflicts between the ticket and existing code, implementations that meet the `goal` differently, or current test behavior that conflicts with the apparent `goal`.

2. **During `debate`.** Run this case when a round makes no progress before `round_cap` and `debate` calls `resolve` again. Apply this procedure to the positions `debate` passes in, not the original decision text.

## How it works

1. If the settlement is not fresh in context, call `recall` first. Pass the same
   `<run-id>`/`<engine-root>`/`<session-dir>` this call has. Do not resolve
   against a remembered settlement that may have compacted.

2. Classify the disagreement's domain. Use the settlement's per-domain `source_of_truth`. Classify the domain as `scope and outcome`, `current behavior`, `implementation approach`, or `correctness`. Classify "is this in scope?" as `scope and outcome`. Classify "should this change existing behavior?" as `current behavior`.

3. Apply that domain's settled source. Read the ticket when `scope and outcome` is settled by the ticket.

4. If no single domain applies, including cases where two domains conflict or no settled source covers the disagreement, follow the caller-specific rule:

   - **Called before `debate`:** Invoke the public `debate` skill in the same turn. Do not leave it pending. Pass only this decision-specific context:
     - the decision in the terms `debate`'s round 1 asks each party to judge
     - the touched domain(s) and the unsatisfied settlement condition for each
     - the full `source_of_truth` for every domain
     - `debate_threshold`, `task_type`, `goal`, and merged user, project, and task principles
     - the same `<run-id>`/`<engine-root>`/`<session-dir>` this call already has

     Require `debate` to read `debate_roster`, `debate_parties`, `debate_round_cap`, `convergence_policy`, `consented_stop_allowed`, and `debate_admission` itself via its own recall. Do not relay those fields as settlement data.

     Do not use `approach` as a principles source.

   - **Called during a stuck round:** Do not invoke `debate` again. Report that no domain settles the disagreement and stop. Let `debate` continue toward `round_cap` itself.

## Recording the outcome

Write one line in the session ledger for every disagreement `resolve` decides:

```text
task session record-decision <run-id> --dir <session-dir> --mode resolve --summary "<what was decided, and which source_of_truth domain settled it>"
```

If `resolve` escalates, do not write a `resolve` entry. Require `debate` to record its outcome with `--mode debate`, `debate-capped`, or `debate-degraded`.

## What resolve is not

Do not invent a `source_of_truth` order.

Apply only what `clarify` settled.

Escalate to `debate` when the settlement is ambiguous or silent on the domain. Do not guess.

## Host mechanics

- Resolve the public session command to `<plugin-root>/scripts/task`.
- Pass `<plugin-root>` as `<engine-root>` in the handoff to this skill.
