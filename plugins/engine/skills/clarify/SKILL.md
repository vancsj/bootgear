---
name: clarify
description: Settle task type, approach, source-of-truth order, debate threshold, and autonomy scope; draft a goal for confirmation. Use at the start of any engine run, before execute. Use checkpoint mode for required model confirmation or source-skill choices during an existing task.
---

In an active Engine run, keep `session_dir` in context. Omit `--dir` for the default `~/.bootgear/session`; pass `--dir <session-dir>` only for a custom directory.

Start with the user's original request, directly or through `start`. The run id comes from the environment.

- **Confirmed** — write the settlement once and hand `execute` the confirmed goal, machine, permissions, `<engine-root>` and absolute `<session-dir>`.
- **Edited or declined** — stay in clarify and redraft for confirmation.
- **Existing ledger, invalid machine or refused settlement** — follow Recovery. An invalid new settlement writes no ledger.

## Checkpoint mode

For `mode: checkpoint`, dispatch before initial assessment, advisor startup, goal sign-off or session initialization.
Inputs: checkpoint kind (`models` or `source-selection`), task folder, pending payload, scope and existing confirmation references.
Active callers also supply engine root and session directory.
For this mode, read [references/confirmation-checkpoints.md](references/confirmation-checkpoints.md).
Return to the requesting caller:

- `checkpoint-confirmed`: kind, confirmed values, scope and typed user confirmation references.
- `needs-confirmation`: kind, pending payload, unresolved question and next caller action.
- `unavailable`: actual diagnostic, missing interaction mechanism and next caller action.

This mode never initializes a run, restarts advisors, or grants mutation permission.

## Workflow

Read applicable rules, assess the request, settle items 1–10, and validate the resolved machine. Show the goal, diagram, node reminders, gate commands, advisor roles, seats, startup choice, launcher and existing pairings. Get explicit confirmation before initialization and handoff.

## What to settle

Ask items in the order that fits the conversation. Use answers already implied by the conversation. Do not force a questionnaire.

Before item 1, read the host user-principles file and `principles.md`, `review-standard.md`, and `test-standard.md` under the project's `.bootgear/config/`, when present. Apply them to the settlement and goal.

For work questions in items 1–5 and 8–10, give `deputy:ask` the question, options and stakes. On `answered`, use the answer and retain its slugs. On `escalate`, ask the user. If deputy is missing, record `no-deputy:not-installed` and ask the user. Keep production changes, outward sends, irreversible actions, goal sign-off and permitted mutations with the user.

1. **Request assessment** — investigate the request before settling task type or anything else; do not accept the first framing uncritically. Inspect the ticket/request text, the relevant implementation path, and existing tests or validation for related behavior. Record as settlement field `request_assessment`:
   - observed scope and affected surfaces
   - a coarse size estimate (`small`/`medium`/`large`)
   - the basis/evidence for that estimate (files read, commands run)
   - open unknowns, if any

   Scale investigation depth to the request: a shallow pass is enough for trivial, bounded work, but state explicitly why deeper investigation wasn't needed rather than skipping the field.

   Store the assessment as a nonempty string, separate from `state_machine`. Later nodes record reassessment only for newly discovered scope.

2. **Task type** — record exactly one of the six values:
   - `ticket-writing` — an issue body, with no design.
   - `ticket-to-pr` — implement a ticket.
   - `triage` — one reported problem.
   - `change-review` — correctness review of a change already made.
   - `design-doc` — requirements and design, with no task list.
   - `artefact-review` — assess the quality of supplied output, including drafts, against a configurable rubric.

   Show node reminders before choosing. Use the exact value whose description and reminders match. Ask the user when two fit. If none fits, tell the user, choose the closest and record the mismatch.

   If `task_type` is `triage`, settle `triage_cutoff`: `one-user` only when the request says the target is a single user, a single-user install or a single customer; otherwise `product`.

   If `task_type` is `design-doc`, settle `work_dir`. For a design-doc run, `work_dir` is required. It is an absolute path or a path that starts with `~`.

   For `ticket-to-pr`, `change-review` or `artefact-review`, settle one fixed `task_folder` for task records.
   Supply an absolute or home path. `init` validates, creates and canonicalises it before storing the run identity.
   Reuse the stored folder through overrides, retries and compaction. Never amend it or supply it through leave arguments.

   For `artefact-review`, record `artefact_review` with the raw request and nonempty local `inputs` paths.
   Use absolute or home paths. Save supplied messages or remote extracts locally with provenance when needed.
   Include an optional task `config` path when the workflow needs custom rubric criteria or finding angles.
   Use `<gear> --host <host> engine task artefact settings` to resolve defaults, host user configuration, project configuration and the task file.
   Show the effective criteria, disabled items, evidence limits and configured source paths before goal confirmation.
   Establish audience, purpose, reader task and delivery mode from evidence; keep unknown or inferred context explicit.
   The default machine reviews supplied inputs without changing or publishing them.

3. **State machine** — resolve the run's `state_machine` settlement field before drafting `goal`. Follow these override tiers exactly:
   1. Resolve the built-in machine for `<task_type>` and tier 2 (`.bootgear/config/state-machine-<task_type>.yaml`, if present — wholly replaces tier 1 for this task type).
   2. Apply any per-run adjustment for this run (tier 3), such as removing a node the task doesn't need. For `change-review` of a change the user did not author, remove `fix`, `spec`, `spec-review` and `spec-debate`. The user authored the change when its git author matches the user's git identity. The git author is the author of the branch commits or the diff. For a PR, it is the PR author. A mismatch or a missing author means the user did not author the change. Remove every incident next edge, reminder branch and exit check. Keep this authoring subgraph when the user requests fixes. Preserve the clarified correction scope and permitted mutations.
   3. Run `<gear> --host <host> engine task state validate <path>` on the resolved machine. Do not proceed on a validation failure; fix the machine or fall back to the unmodified tier 1/2 result.
   4. Run `<gear> --host <host> engine task state diagram <path>` on the same resolved machine.
   5. Show the user the rendered diagram and node reminders together with the `goal` draft, in the confirmation step below.
      For every node with `reminder.leave_check` or `reminder.exit_checks`, list each argv verbatim, its tier, and the exit it gates. Show its resolved command prefix. `transition` resolves registered Gear commands through `gear.toml`; it resolves other commands through `command -v`. Flag a command when Gear and `command -v` cannot resolve it. These commands run at `transition`; the user's confirmation approves them.
   6. Record the complete resolved machine (not a tier-1/2 diff) as settlement field `state_machine`, a block scalar, once, with the rest of settlement. Do not write settlement without a validated `state_machine`.

4. **Approach and principles are distinct:**
   - **approach** — record concrete workflow steps as a nonempty string.
   - **principles** — record constraints across the run as a nonempty string. Merge them with project and user principles before execution.

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
   - Resolve `debate_party_config` with `<gear> --host <host> engine task config resolve --name debate-parties --project-root <project-root> [--task-config-file <task-config-file>] --report models --json`. Follow its `next`. Show `model_report` to the user; never copy `effective` into settlement.
   - Set `convergence_policy` to `unanimous` by default.
   - Set `consented_stop_allowed` to `true` by default. Use `unanimous_convergence`, `consented_stop`, and `round_cap` as the debate outcomes. Set `consented_stop_allowed` to `false` to remove `consented_stop`. End debate only in `unanimous_convergence` or `round_cap` when `consented_stop_allowed` is `false`.

7. **Autonomy has two parts:**
   - Set `no_further_questions: true` after `goal` confirmation. Do not ask routine work questions during the run. Required model or source-selection checkpoints use checkpoint mode. Recovery may also ask for an unclear run identity after compaction.
   - **Permitted mutations** — ask which actions `execute` may take without asking again, including commit, push, open a PR, edit the ticket, post review comments, merge, and force-push. Require a specific list. Do not accept "go ahead autonomously" as the list.

8. **Domain-skill overrides** — map task types to domain skills as follows:
   - `design-doc` uses `spec`.
   - `ticket-writing` drafts without a skill and reviews with `spec-review`.
   - `ticket-to-pr` and `triage` use `test`.
   - `change-review` uses `review`.
   - `artefact-review` uses its machine stages and public `converge`, `resolve` and `debate` capabilities.

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
   - `spec_skill`/`test_skill`/`review_skill` — record the skill each domain call uses in the same shape as item 8's override; optionally record `spec_review_skill` and `spec_review_override` for the independent spec-review stage. Record only the fields whose node the machine has: `spec_skill` for `spec`, `test_skill` for `test-code`, `e2e-test` or `triage`, `review_skill` for `review`. A `change-review` run records `spec_skill` too when its authorized authoring subgraph remains. A `design-doc` run records `spec_skill`. A `ticket-writing` run records `spec_review_skill`.
     - **Bare `<skill-name>`** when the override or its absence names one skill. Use the override, or the general default (`spec`, `test`, `review`) when absent.
     - **`{sub-task-label: <skill-name>}` mapping** when the override is a mapping. Mirror it exactly.

     At call time, select the matching entry through the domain skill's public override contract.
   - `debate_roster` — record every stable party ID that `debate` may invoke. Include built-ins (`main-agent`, `independent-reviewer`, `adversarial-reviewer`) and custom IDs. Do not add duplicates. Always include `main-agent`.
   - `debate_party_config` — record the resolved party configuration snapshot. `debate` uses this field and does not re-read configuration layers.
   - `debate_admission` — record whether skills other than `execute`/`resolve` may call `debate` directly, and record which ones. Record absent or empty for no direct calls. Allow only `resolve`'s escalation path to reach `debate` when direct calls are absent.
   - `review_fix_mode` — default to `accepted_only` for externally accepted feedback. Use `auto_within_permitted_mutations` to authorize automatic `fix-now` patches within item 7's permissions.

   Record what this run may call. Do not record a prediction of what it will call.

10. **Advisor roles, seats, and startup** — settle the advisor's roles and channel startup timing.
   - Check the required CLI and `advisor` skill availability without starting or pairing a listener.
     Check the host's listener requirements below and report actual availability errors.
   - Resolve `converge-seats` without a task file: `<gear> --host <host> engine task config resolve --name converge-seats --project-root <project-root> --json`.
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
   - After `init`, record channels that already exist with `<gear> --host <host> engine task session record-decision` in `solo` mode.
     Use summary `advisor channels: r2=<n>, debate=<m>`, naming only existing channels.
     For deferred startup, record each new pairing when it happens. Preserve the other use's channel when updating the decision.
   - While a channel exists, run its heartbeat task's printed `next` at once when that task ends.
     Keep the 720-second restart grace.

## Draft and confirm the goal

State the task and constraints in one or two sentences. Give a concrete success condition. State the task-specific failure that leaves no path to completion. Treat a stall as open work. Allow edits and require explicit confirmation. Store `goal` as a mapping with text values `succeeded` and `failed`.

## Write the settlement

After confirmation, write items 1–10 and the goal into the settlement input. Include every task-specific field the selected type requires. Keep `state_machine` as the validated block scalar and let Gear set `session_dir`.

```text
<gear> --host <host> engine task session init --settlement-file <file>
```

On refusal, use Recovery. On success, use the directory of the printed `INIT <ledger-file>` as `<session-dir>`. Pass it and `<engine-root>` to `execute`. Preserve the directory on every active-run handoff, including `recall`, `resolve`, `debate`, `spec`, `test`, and `review`.

## Rules

- Ask routine work questions only during initial clarify. Record settled answers and reuse them. Use checkpoint mode only for model or source-selection confirmation.
- After `init`, record each deputy answer in the run as a `solo` decision citing its slugs. Only the user's own confirmed standing decisions go to `deputy:record`.
- Record any mid-run user amendment as an explicit session decision. Keep the original settlement intact.

## Recovery

- **Run identity unclear after compaction** — recover `<session-dir>` and resume the existing ledger; do not start a new run.
- **Ledger already exists** — treat `init`'s refusal as a mid-session `clarify` rerun. Tell the user. Do not run `init` again and do not append a suffix. Resume the existing ledger through `recall`.
- **`<gear> --host <host> engine task state validate` fails on the resolved machine** — fall back to the unmodified tier 1/2 result (item 3, step 3). If that also fails, tell the user the validation error and stop without writing the settlement.
- **Settlement fails validation** — `init` prints the problems and writes no ledger. Fix every listed problem in the settlement file, then run `init` again. Do not add `--force`. When a listed problem is in a value the user confirmed, ask the user for a valid value.

## Host mechanics

Call `cli:gear` for the absolute Gear path. Run `<gear> --host <host> engine task <command>`.
Both hosts support `native_subagent` and `advisor`. The handoff's `<engine-root>` is the installed Engine plugin root.

- **Claude Code (`claude`)** — Gear reads `CLAUDE_CODE_SESSION_ID`. If needed, install `cli@bootgear` through the plugin interface. Only refuter and gap hunter use a listener. Debate uses direct `codex exec` when `command -v codex` succeeds.
- **Codex (`codex`)** — Gear reads `CODEX_SESSION_ID`. If needed, install with `codex plugin add cli@bootgear`. Refuter or gap hunter shares one listener use. Debate needs a separate listener. If the `advisor` skill is missing, tell the user and record no advisor role.

If a required sibling skill is missing, stop and report `cli:setup` with target `engine`. Resume after setup verifies the required plugins.
