---
name: clarify
description: Settle task type, approach, source-of-truth order, debate threshold, and autonomy scope; draft a goal for confirmation. Use at the start of any engine run, before execute. The only stage that asks the user work questions; recall's lost-session_dir recovery is a documented exception, not work.
---

In an active Engine run, keep `session_dir` in context. Omit `--dir` for the default `~/.bootgear/session`; pass `--dir <session-dir>` only for a custom directory.

Run at the start of every engine run, before `execute`. Input: the user's request, directly or through `start`.

Outcomes:

- **Goal confirmed** — the settlement is written through `init` (required fields in `## Writing the settlement`), and the run is handed to `execute` with `<run-id>`, `<engine-root>`, and `<session-dir>`.
- **Goal edited or declined** — stay in `clarify` and redraft until the user confirms.
- **Ledger already exists** — `init` refuses; follow `## Recovery`.
- **`task state validate` fails after the fallback** — follow `## Recovery`.
- **Settlement fails validation** — `init` refuses and writes no ledger; follow `## Recovery`.

## Workflow

Read the project principles and standards → investigate the request → settle items 1–10 (state machine validated and diagrammed) → draft `goal` → show `goal`, the diagram, the `leave_check` and `exit_checks` lists, `advisor_roles`, the seat mapping, startup choice, approved launcher, and existing advisor pairings → on confirmation, `init` the settlement → hand off to `execute` with `<run-id>`, `<engine-root>`, and `<session-dir>`.

## What to settle

Ask items in the order that fits the conversation. Use answers already implied by the conversation. Do not force a questionnaire.

Before item 1, read the host user-principles file, if present, and `.bootgear/config/principles.md`, `.bootgear/config/review-standard.md` and `.bootgear/config/test-standard.md` from the project root, each when present. Use them to draft the goal and to settle the items that follow.

Before each work question in items 1–5, 8, 9 and 10, call the `deputy:ask` skill with the question, its options and its stakes. If `deputy` is not installed, record `no-deputy:not-installed` and ask the user. On `answered`, use the answer and keep its cited slugs for `init`. On `escalate`, ask the user. Item 7 (permitted mutations) and the goal sign-off are never sent to the deputy, and production change, outward send, irreversible action, goal sign-off, or permitted mutations are never sent to it.

1. **Request assessment** — investigate the request before settling task type or anything else; do not accept the first framing uncritically. Inspect the ticket/request text, the relevant implementation path, and existing tests or validation for related behavior. Record as settlement field `request_assessment`:
   - observed scope and affected surfaces
   - a coarse size estimate (`small`/`medium`/`large`)
   - the basis/evidence for that estimate (files read, commands run)
   - open unknowns, if any

   Scale investigation depth to the request: a shallow pass is enough for trivial, bounded work, but state explicitly why deeper investigation wasn't needed rather than skipping the field.

   This is separate from state-machine resolution (item 3). Do not conflate the two fields or skip one because the other was done.

   Later nodes reassess scope only for newly discovered node-level work, recorded as a decision/amendment; do not repeat the full assessment at every node.

2. **Task type** — record exactly one of the five values:
   - `ticket-writing` — an issue body, with no design.
   - `ticket-to-pr` — implement a ticket.
   - `triage` — one reported problem.
   - `change-review` — a change already made.
   - `design-doc` — requirements and design, with no task list.

   Show the node reminders of each machine before the type pick.

   A request to review a draft is not a task type. Refuse it. Point the user to `spec-review`. `design-doc` writes its own requirements and design and does not review drafts.

   Pick `task_type` by matching the request to the machine descriptions and node reminders. Do not record another spelling or a paraphrase.

   If two types fit, ask the user which one. Do not choose silently.

   If none fits, tell the user, choose the closest value, and record the mismatch.

   If `task_type` is `triage`, settle `triage_cutoff`: `one-user` only when the request says the target is a single user, a single-user install or a single customer; otherwise `product`.

   If `task_type` is `design-doc`, settle `work_dir`. For a design-doc run, `work_dir` is required. It is an absolute path or a path that starts with `~`.

3. **State machine** — resolve the run's `state_machine` settlement field before drafting `goal`. Follow these override tiers exactly:
   1. Resolve the built-in machine for `<task_type>` and tier 2 (`.bootgear/config/state-machine-<task_type>.yaml`, if present — wholly replaces tier 1 for this task type).
   2. Apply any per-run adjustment for this run (tier 3), such as removing a node the task doesn't need. For `change-review` of a change the user did not author, remove the `fix` node. The user authored the change when its git author matches the user's git identity. The git author is the author of the branch commits or the diff. For a PR, it is the PR author. A mismatch or a missing author means the user did not author the change. Remove every `next:` entry and `reminder.branches` key that names it. Keep the fix node when the user asks to push fixes to the change.
   3. Run `task state validate <path>` on the resolved machine. Do not proceed on a validation failure; fix the machine or fall back to the unmodified tier 1/2 result.
   4. Run `task state diagram <path>` on the same resolved machine.
   5. Show the user the rendered diagram and node reminders together with the `goal` draft, in the confirmation step below.
      For every node with `reminder.leave_check` or `reminder.exit_checks`, also list each argv verbatim (an `exit_checks` argv with the exit it gates), the tier it came from (built-in, project override, or per-run), and the output of `command -v <argv[0]>`. Flag it when `argv[0]` contains `/` or `command -v` finds no program provided by an installed plugin. These commands run at `transition`; the user's confirmation approves them.
   6. Record the complete resolved machine (not a tier-1/2 diff) as settlement field `state_machine`, a block scalar, once, with the rest of settlement. Do not write settlement without a validated `state_machine`.

4. **Approach and principles are distinct:**
   - **approach** — record concrete workflow steps such as read the ticket, implement, and open a PR.
   - **principles** — record high-level constraints across the run, such as no scope creep, prefer simplicity over cleverness, and never touch production data. Merge them with the project and user principles before execution.

5. **Source of truth, per domain — set separate authorities.** Settle at least:
   - scope and outcome — use the ticket, issue, or user's stated intent by default
   - current behavior — use the code and its existing tests by default
   - implementation approach — use this settlement's stated approach by default
   - correctness once implemented — use tests and verification run after the change by default

   Adjust domains to the task type. Omit an implementation-approach domain for triage when it is not needed.

6. **Debate threshold** — a decision that `resolve` cannot settle goes to `debate` when any of these holds: (a) undoing it takes more than one revert, or it changes shared state; (b) it reaches more than one person or customer; (c) it touches money, legal, security or data-loss; (d) any of (a) to (c) is unknown. Otherwise it is solo: reversible by one revert, confined to one component or file, and none of (a) to (d) applies. Record each answer with the decision. A `resolve` settled by a source of truth is always solo. Never send this item to `deputy:ask`: the deputy has no threshold to judge against.

   Also settle:
   - Set `debate_round_cap` to `10` by default. Set a different positive value when requested. Give an owed unavailable-party retry one extra round beyond this cap.
   - Use the default three-party roster (`main-agent`, `independent-reviewer`, `adversarial-reviewer`) unless the run needs custom parties. Record a custom party as `{id, label, prompt, mechanism}`; require a distinct ID and a host-supported mechanism.
   - Resolve `debate_party_config` with `task config resolve --name debate-parties --project-root <project-root> [--task-config-file <task-config-file>] --report models --json`. Follow its `next`. Show `model_report` to the user; never copy `effective` into settlement.
   - Set `convergence_policy` to `unanimous` by default.
   - Set `consented_stop_allowed` to `true` by default. Use `unanimous_convergence`, `consented_stop`, and `round_cap` as the debate outcomes. Set `consented_stop_allowed` to `false` to remove `consented_stop`. End debate only in `unanimous_convergence` or `round_cap` when `consented_stop_allowed` is `false`.

7. **Autonomy has two parts:**
   - Set `no_further_questions: true` after `goal` confirmation. Do not ask for decisions during the run. Ask a work question only when compaction leaves the run identity unclear; recover `<session-dir>` and resume the existing ledger.
   - **Permitted mutations** — ask which actions `execute` may take without asking again, including commit, push, open a PR, edit the ticket, post review comments, merge, and force-push. Require a specific list. Do not accept "go ahead autonomously" as the list.

8. **Domain-skill overrides** — map task types to domain skills as follows:
   - `design-doc` uses `spec`.
   - `ticket-writing` drafts without a skill and reviews with `spec-review`.
   - `ticket-to-pr` and `triage` use `test`.
   - `change-review` uses `review`.

   Ask whether the project has a specialized skill for every domain the task type calls.

   Record `spec_override`, `test_override`, and/or `review_override` as:
   - a bare `<skill-name>` when one skill covers the whole domain
   - `{sub-task-label: <skill-name>}` when the project splits the domain by concern, such as `test_override: {unit: <skill-a>, e2e: <skill-b>}` or `review_override: {quick: <skill-a>, full: <skill-b>}`

   Use the project's own sub-task labels. Do not invent a fixed vocabulary. Treat an absent override as the general default. Ask about specialized skills once here. At call time, resolve the current override, including any later `AMENDMENT`, select the entry matching the current sub-task, and fall back to the general default when no mapping label matches.

   For every task type, settle **`debate_mode`** —
   `threshold` (default: decide choice claims below `debate_threshold` solo,
   and resolve or escalate those at or above it) or `mandatory` (resolve every
   choice claim, and escalate only those unresolved at or above
   `debate_threshold`). `execute` reads it at each debate node; an absent value
   means `threshold`.

9. **Run manifest** — record skills, agents, and other capabilities this run may use beyond the three overrides.

   Write:
   - `spec_skill`/`test_skill`/`review_skill` — record the skill each domain call uses in the same shape as item 8's override; optionally record `spec_review_skill` and `spec_review_override` for the independent spec-review stage. Record only the fields whose node the machine has: `spec_skill` for `spec`, `test_skill` for `test-code`, `e2e-test` or `triage`, `review_skill` for `review`. A `change-review` run records `review_skill` alone. A `design-doc` run records `spec_skill`. A `ticket-writing` run records `spec_review_skill`.
     - **Bare `<skill-name>`** when the override or its absence names one skill. Use the override, or the general default (`spec`, `test`, `review`) when absent.
     - **`{sub-task-label: <skill-name>}` mapping** when the override is a mapping. Mirror it exactly.

     At call time, select the matching entry through the domain skill's public override contract.
   - `debate_roster` — record every stable party ID that `debate` may invoke. Include built-ins (`main-agent`, `independent-reviewer`, `adversarial-reviewer`) and custom IDs. Do not add duplicates. Always include `main-agent`.
   - `debate_party_config` — record the resolved party configuration snapshot. `debate` uses this field and does not re-read configuration layers.
   - `debate_admission` — record whether skills other than `execute`/`resolve` may call `debate` directly, and record which ones. Record absent or empty for no direct calls. Allow only `resolve`'s escalation path to reach `debate` when direct calls are absent.
   - `review_fix_mode` — set to `accepted_only` by default to restrict `review` to externally accepted feedback, or set to `auto_within_permitted_mutations` to allow `review`'s iterate-to-closure loop to apply findings automatically within `permitted_mutations` from item 7.

   Record what this run may call. Do not record a prediction of what it will call.

10. **Advisor roles, seats, and startup** — settle the advisor's roles and channel startup timing.
   - Check the required CLI and `advisor` skill availability without starting or pairing a listener.
     Use `## Host mechanics` to identify uses that need a listener. Report actual availability errors.
   - Resolve `converge-seats` without a task file: `task config resolve --name converge-seats --project-root <project-root> --json`.
     Recommend `adversarial-reviewer` and `gap-hunter`, or only `adversarial-reviewer` when `r2` is `native_subagent`.
     Ask which roles the advisor takes: `independent-reviewer`, `adversarial-reviewer`, `refuter`, or `gap-hunter`.
     "No" means none. Offer only roles whose required capabilities are available.
   - For selected channel uses, present both startup choices. Reuse a choice already explicit in the conversation.
     Otherwise, ask the user. Do not infer timing from a launcher's presence.
   - **Early startup** (`early`): start and pair each selected channel use before goal confirmation.
     Ask the user to start a listener when no approved launcher is available.
     Show every pairing. Keep each pairing for the run; do not close it after each task.
   - **Deferred startup** (`deferred`): start a listener only when its first advisor task is due.
     Settle the exact approved automatic launcher command or capability. Verify its availability without starting it.
     Obtain permission to run it under item 7. Show the launcher and planned channel uses at goal confirmation.
     Do not require live pairings during clarify. Settle unavailable launchers here; do not defer questions to execute.
   - Direct calls need no listener. For direct-only roles, record `startup: early` without a launcher.
     Keep their direct dispatch unchanged.
   - Pair one listener per selected channel use. Never share the debate and `r2` channels.
     Record a party as `native_subagent` only after the user explicitly declines its advisor use.
     If early pairing fails, show the diagnostic and settle another available choice before writing the settlement.
   - Write task-layer debate-parties and converge-seats files for the chosen roles.
     Set each selected debate party's `mechanism` to `advisor`; set other parties to `native_subagent`.
     Name all five converge seats. Set `r2: advisor` for `refuter` or `gap-hunter`; set all other seats to `native_subagent`.
     Resolve both with `--task-config-file` and follow each `next`.
   - Record `advisor_roles: {roles, brief, startup}` and `converge_seats` together.
     Limit `brief` to the chosen roles in one line. Deferred startup also records the single-line approved `launcher`.
     When no advisor role is selected, omit startup and launcher.
   - After `init`, record channels that already exist with `task session record-decision` in `solo` mode.
     Use summary `advisor channels: r2=<n>, debate=<m>`, naming only existing channels.
     For deferred startup, record each new pairing when it happens. Preserve the other use's channel when updating the decision.
   - While a channel exists, run its heartbeat task's printed `next` at once when that task ends.
     Keep the 720-second restart grace.

## Drafting `goal`

After settlement, draft `goal` as a short, high-level prompt. Do not write a spec or task breakdown. State:

- what the task is and its constraints, in one or two sentences
- **succeeded when** — the concrete condition that means done
- **failed when** — the task-specific condition that makes the task undoable; do not use a generic placeholder such as "the platform can't do X" or "the bug can't be reproduced at all"

Store `goal` in the settlement as a mapping with the keys `succeeded` and `failed`, each a text value. Do not store it as prose.

Classify a stall as not failure. Define failure as having no path to completion remaining.

Show the draft. Get explicit confirmation before handing off to `execute`. Allow edits before confirmation.

## Writing the settlement

After confirmation:

1. Set `run-id` to the exact session identity supplied by the host.

2. Call `init` with this run-id and the settlement body. Pass `--dir` only when this run needs a non-default ledger location. Omit `--dir` for the default:
   ```
   task session init <run-id> --settlement-file <file>
   ```

   When `init` refuses because a ledger already exists at this path, or because the settlement fails validation, follow `## Recovery`.

3. Let `init` resolve `--dir` (default `~/.bootgear/session`) to an absolute path and write `session_dir: <that path>` into the settlement as it stores it. Replace any `session_dir:` line already in `<file>` with the resolved path. `init` prints `INIT <ledger-file>`, the ledger file inside that directory. Do not compute or pre-populate `session_dir` before this call. Discard whatever `session_dir` value the caller supplied. Do not resolve the path with a separate command.

4. After `init`, take `<session-dir>` as the directory containing the `INIT <ledger-file>` path. Pass `<run-id>`, `<engine-root>`, and `<session-dir>` explicitly when starting `execute`.

Include at least: `task_type`, `triage_cutoff` when `task_type` is `triage`, `work_dir` when `task_type` is `design-doc`, `request_assessment`, `state_machine`, `approach`, `principles`, per-domain `source_of_truth`, `debate_threshold`, `debate_round_cap`, `convergence_policy`, `consented_stop_allowed`, custom `debate_parties` as `{id, label, prompt, mechanism}`, resolved `debate_party_config`, `spec_override`/`test_override`/`review_override`, the run manifest (`spec_skill`/`test_skill`/`review_skill`, optional `spec_review_skill`/`spec_review_override`, `debate_roster`, `debate_admission`, `review_fix_mode`), `debate_mode` when applicable, `advisor_roles` and `converge_seats`, `autonomy`, `goal`, and `session_dir`. Let `init` write `session_dir`; do not pre-populate it.

Pass `<session-dir>` in context at every handoff, unconditionally, until the first post-compaction `recall` succeeds. Pass it from `clarify` to `execute`. Require `execute` to pass it on every `recall`/`resolve`/`debate`/`spec`/`test`/`review` call it makes for this run, every time.

## Rules

- Ask the user work questions only in this stage. Record settled items in the session ledger. Do not ask again after recording a settled item. Set `no_further_questions: true` after `goal` confirmation.
- After `init`, record each deputy-answered item in the run ledger as a `solo` decision that names its cited slugs (`task session record-decision … --mode solo`). Do not write it to the deputy ledger. Only the user's own answers go to `deputy:record`.
- Write the settlement only once. Do not revise it in `execute`. When the user amends a settled item mid-run, record the new requirement, changed restriction, or different goal condition as an explicit decision in the ledger's `decisions` section. Do not use a `clarify` update path.

## Recovery

- **Run identity unclear after compaction** — recover `<session-dir>` and resume the existing ledger; do not start a new run.
- **Ledger already exists** — treat `init`'s refusal as a mid-session `clarify` rerun. Tell the user. Do not run `init` again and do not append a suffix. Resume the existing ledger through `recall`.
- **`task state validate` fails on the resolved machine** — fall back to the unmodified tier 1/2 result (item 3, step 3). If that also fails, tell the user the validation error and stop without writing the settlement.
- **Settlement fails validation** — `init` prints the problems and writes no ledger. Fix every listed problem in the settlement file, then run `init` again with the same run-id. Do not add `--force`. When a listed problem is in a value the user confirmed, ask the user for a valid value.

## Host mechanics

- Resolve the public `task` command to `<plugin-dir>/bin/task`.
- Supply `<plugin-dir>` as `<engine-root>` in the handoff to `execute`.
- Supply the host's exact session identity as `<run-id>`: the value of
  `$CLAUDE_CODE_SESSION_ID`.
- A host-supported debate party mechanism is `native_subagent` or `advisor`.
- Item 10: only `refuter` and `gap-hunter` need the paired listener; the debate
  roles use a direct `codex exec`, so they need no listener and are available
  when `command -v codex` succeeds.
