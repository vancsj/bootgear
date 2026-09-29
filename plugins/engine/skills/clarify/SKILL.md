---
name: clarify
description: Settle task type, approach, source-of-truth order, debate threshold, and autonomy scope; draft a goal for confirmation. Use at the start of any engine run, before execute. The only stage that asks the user work questions; recall's lost-session_dir recovery is a documented exception, not work.
---

Ask the user work questions only in this stage. Record settled items in the session ledger. Do not ask again after recording a settled item. Set `no_further_questions: true` after `goal` confirmation. Hand off to `execute` after confirmation. When compaction leaves the run identity unclear, recover `<session-dir>` and resume the existing ledger; do not start a new run.

Read `reference.md` § `Why clarify owns work questions` for rationale before changing this skill.

## What to settle

Ask items in the order that fits the conversation. Use answers already implied by the conversation. Do not force a questionnaire.

1. **Request assessment** — investigate the request before settling task type or anything else; do not accept the first framing uncritically. Inspect the ticket/request text, the relevant implementation path, and existing tests or validation for related behavior. Record as settlement field `request_assessment`:
   - observed scope and affected surfaces
   - a coarse size estimate (`small`/`medium`/`large`)
   - the basis/evidence for that estimate (files read, commands run)
   - open unknowns, if any

   Scale investigation depth to the request: a shallow pass is enough for trivial, bounded work, but state explicitly why deeper investigation wasn't needed rather than skipping the field. This gates on shape — non-empty, cites real artifacts — not on independently-verified truth; settlement validation checks the same way it checks other required fields.

   This is separate from state-machine resolution (item 3): sizing the request and shaping the workflow graph are different judgments with different procedures. Do not conflate the two fields or skip one because the other was done.

   `execute`'s Act step reassesses scope only for newly discovered node-level work, recorded as a decision/amendment; do not repeat the full assessment at every node.

2. **Task type** — record exactly one of the four v1 values:
   - `ticket-writing` — requirement spike
   - `bug-triage`
   - `ticket-to-pr`
   - `pr-review`

   Compare `task_type` literally. Do not match it by description. Do not record another spelling or a paraphrase.

   If none fits, tell the user, choose the closest value, and record the mismatch.

3. **State machine** — resolve the run's `state_machine` settlement field before drafting `goal`. Follow these override tiers exactly:
   1. Resolve the built-in machine for `<task_type>` and tier 2 (`.bootgear/config/state-machine-<task_type>.yaml`, if present — wholly replaces tier 1 for this task type).
   2. Apply any per-run adjustment for this run (tier 3), such as removing a node the task doesn't need. For `pr-review` of a PR the user did not author, remove the `fix` node and every `next:` entry and `reminder.branches` key naming it, unless the user asks to push fixes to that PR.
   3. Run `task state validate <path>` on the resolved machine. Do not proceed on a validation failure; fix the machine or fall back to the unmodified tier 1/2 result.
   4. Run `task state diagram <path>` on the same resolved machine.
   5. Show the user the rendered diagram and node reminders together with the `goal` draft, in the confirmation step below.
      For every node with `reminder.leave_check`, also list its argv verbatim, the tier it came from (built-in, project override, or per-run), and the output of `command -v <argv[0]>`. Flag it when `argv[0]` contains `/` or `command -v` finds no program provided by an installed plugin. These commands run at `transition`; the user's confirmation approves them.
   6. Record the complete resolved machine (not a tier-1/2 diff) as settlement field `state_machine`, a block scalar, once, with the rest of settlement.

   Each v1 task type has a built-in machine. A project override wholly replaces
   that machine for the task type, and a per-run adjustment replaces it for
   that run; do not write settlement without a validated `state_machine`.

4. **Approach and principles are distinct:**
   - **approach** — record concrete workflow steps such as read the ticket, implement, and open a PR.
   - **principles** — record high-level constraints across the run, such as no scope creep, prefer simplicity over cleverness, and never touch production data. Merge them with the project and user principles before execution.

5. **Source of truth, per domain — set separate authorities.** Settle at least:
   - scope and outcome — use the ticket, issue, or user's stated intent by default
   - current behavior — use the code and its existing tests by default
   - implementation approach — use this settlement's stated approach by default
   - correctness once implemented — use tests and verification run after the change by default

   Adjust domains to the task type. Omit an implementation-approach domain for bug triage when it is not needed.

6. **Debate threshold** — use reversibility and blast radius by default unless the user gives other axes. Decide reversible, narrow decisions solo. Escalate decisions that are hard to reverse or broad in effect through `resolve`, then `debate` if `resolve` cannot settle them.

   Also settle:
   - Set `debate_round_cap` to `10` by default. Set a different positive value when requested. Give an owed unavailable-party retry one extra round beyond this cap.
   - Use the default three-party roster (`main-agent`, `independent-reviewer`, `adversarial-reviewer`) unless the run needs custom parties. Record a custom party as `{id, label, prompt, mechanism}`; require a distinct ID and a host-supported mechanism.
   - Resolve `debate_party_config` with `task config resolve --name debate-parties --project-root <project-root> [--task-config-file <task-config-file>] --report models --json`. Follow its `next`. Show `model_report` to the user; never copy `effective` or model/profile fields into settlement.
   - Set `convergence_policy` to `unanimous` by default.
   - Set `consented_stop_allowed` to `true` by default. Use `unanimous_convergence`, `consented_stop`, and `round_cap` as the debate outcomes. Set `consented_stop_allowed` to `false` to remove `consented_stop`. End debate only in `unanimous_convergence` or `round_cap` when `consented_stop_allowed` is `false`.

7. **Autonomy has two parts:**
   - Set `no_further_questions: true` after `goal` confirmation. Do not ask for decisions during the run. Ask a work question only when compaction leaves the run identity unclear; recover `<session-dir>` and resume the existing ledger.
   - **Permitted mutations** — ask which actions `execute` may take without asking again, including commit, push, open a PR, edit the ticket, post review comments, merge, and force-push. Require a specific list. Do not accept "go ahead autonomously" as the list.

8. **Domain-skill overrides** — map task types to domain skills as follows:
   - ticket writing uses `spec`
   - ticket-to-PR and bug triage use `test`
   - PR review uses `review`

   Ask whether the project has a specialized skill for every domain the task type calls.

   Record `spec_override`, `test_override`, and/or `review_override` as:
   - a bare `<skill-name>` when one skill covers the whole domain
   - `{sub-task-label: <skill-name>}` when the project splits the domain by concern, such as `test_override: {unit: <skill-a>, e2e: <skill-b>}` or `review_override: {quick: <skill-a>, full: <skill-b>}`

   Use the project's own sub-task labels. Do not invent a fixed vocabulary. Treat an absent override as the general default. Ask about specialized skills once here. At call time, resolve the current override, including any later `AMENDMENT`, select the entry matching the current sub-task, and fall back to the general default when no mapping label matches.

   When the task type calls `spec`, also settle **`spec_debate_mode`** —
   `mandatory` (default: always attempt `resolve` before sign-off, escalating
   only if `resolve` can't decide and the disagreement is at or above
   `debate_threshold`) or `threshold` (attempt `resolve`/escalate only at or
   above `debate_threshold`, otherwise sign off solo). This field is read
   by `spec` itself, not by `execute`; an absent value means `spec` uses
   `mandatory`. `execute` does not validate it.

9. **Run manifest** — record skills, agents, and other capabilities this run may use beyond the three overrides.

   Write:
   - `spec_skill`/`test_skill`/`review_skill` — record the skill each domain call uses in the same shape as item 8's override:
     - **Bare `<skill-name>`** when the override or its absence names one skill. Use the override, or the general default (`spec`, `test`, `review`) when absent.
     - **`{sub-task-label: <skill-name>}` mapping** when the override is a mapping. Mirror it exactly.

     At call time, select the matching entry through the domain skill's public override contract.
   - `debate_roster` — record every stable party ID that `debate` may invoke. Include built-ins (`main-agent`, `independent-reviewer`, `adversarial-reviewer`) and custom IDs. Do not add duplicates. Always include `main-agent`.
   - `debate_party_config` — record the resolved party configuration snapshot. `debate` uses this field and does not re-read configuration layers.
   - `debate_admission` — record whether skills other than `execute`/`resolve` may call `debate` directly, and record which ones. Record absent or empty for no direct calls. Allow only `resolve`'s escalation path to reach `debate` when direct calls are absent.
   - `review_fix_mode` — set to `accepted_only` by default to restrict `review` to externally accepted feedback, or set to `auto_within_permitted_mutations` to allow `review`'s iterate-to-closure loop to apply findings automatically within `permitted_mutations` from item 7.

   Record what this run may call. Do not record a prediction of what it will call.

## Drafting `goal`

After settlement, draft `goal` as a short, high-level prompt. Do not write a spec or task breakdown. State:

- what the task is and its constraints, in one or two sentences
- **succeeded when** — the concrete condition that means done
- **failed when** — the task-specific condition that makes the task undoable; do not use a generic placeholder such as "the platform can't do X" or "the bug can't be reproduced at all"

Classify a stall as not failure. Define failure as having no path to completion remaining.

Show the draft. Get explicit confirmation before handing off to `execute`. Allow edits before confirmation.

## Writing the settlement

After confirmation:

1. Set `run-id` to the exact session identity supplied by the host.

2. Call `init` with this run-id and the settlement body. Pass `--dir` only when this run needs a non-default ledger location. Omit `--dir` for the default:
   ```
   task session init <run-id> --settlement-file <file>
   ```

   Treat a refusal because a ledger already exists at this path as a mid-session `clarify` rerun. Tell the user. Do not append a suffix.

3. Let `init` resolve `--dir` (default `~/.bootgear/session`) to an absolute path and write `session_dir: <that path>` into the settlement as it stores it. Replace any `session_dir:` line already in `<file>` with the resolved path. Use the printed `INIT <path>` line as the same absolute path that was written. Do not compute or pre-populate `session_dir` before this call. Discard whatever `session_dir` value the caller supplied. Do not resolve the path with a separate command.

4. After `init`, read `<session-dir>` back from `recall`, or parse it from `init`'s printed path. Pass `<run-id>`, `<engine-root>`, and `<session-dir>` explicitly when starting `execute`.

Include at least: `task_type`, `request_assessment`, `state_machine`, `approach`, `principles`, per-domain `source_of_truth`, `debate_threshold`, `debate_round_cap`, `convergence_policy`, `consented_stop_allowed`, custom `debate_parties` as `{id, label, prompt, mechanism}`, resolved `debate_party_config`, `spec_override`/`test_override`/`review_override`, the run manifest (`spec_skill`/`test_skill`/`review_skill`, `debate_roster`, `debate_admission`, `review_fix_mode`), `spec_debate_mode` when applicable, `autonomy`, `goal`, and `session_dir`. Let `init` write `session_dir`; do not pre-populate it.

Pass `<session-dir>` in context at every handoff, unconditionally, until the first post-compaction `recall` succeeds. Pass it from `clarify` to `execute`. Require `execute` to pass it on every `recall`/`resolve`/`debate`/`spec`/`test`/`review` call it makes for this run, every time.

Write the settlement only once. Do not revise it in `execute`. When the user amends a settled item mid-run, record the new requirement, changed restriction, or different goal condition as an explicit decision in the ledger's `decisions` section. Do not use a `clarify` update path.

## Host mechanics

- Resolve the public `task` command to `<plugin-dir>/bin/task`.
- Supply `<plugin-dir>` as `<engine-root>` in the handoff to `execute`.
- Supply the host's exact session identity as `<run-id>`.
- A host-supported debate party mechanism is `native_subagent` or `advisor`.
  Leave `adversarial-reviewer` without a `mechanism` to use its `advisor`
  default.
