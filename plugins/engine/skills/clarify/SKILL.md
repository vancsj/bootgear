---
name: clarify
description: Settle an Engine run's scope, workflow, authority, and permissions. Use before execution or at a required confirmation checkpoint.
---

## Inputs and outcomes

Take the original request from the user or `start`. Use the run ID from the environment.
Keep `session_dir` in context. Use `--dir <session-dir>` only for a custom directory.

- **Confirmed** — write the settlement once. Pass the goal, machine, permissions, `<engine-root>`, and absolute `<session-dir>` to `execute`.
- **Edited or declined** — revise the draft and ask for confirmation again.
- **Existing ledger, invalid machine, or refused settlement** — follow Fallbacks.

### Checkpoint mode

For `mode: checkpoint`, use this path before any new-run work.
Take kind (`models` or `source-selection`), task folder, pending payload, scope, and existing confirmations.
In a run, also take the Engine root and session directory.
Read [confirmation-checkpoints.md](references/confirmation-checkpoints.md) only for this mode.

Return one outcome to the caller.

- `checkpoint-confirmed` — kind, confirmed values, scope, and typed user confirmation references.
- `needs-confirmation` — kind, pending payload, unresolved question, and next caller action.
- `unavailable` — diagnostic, missing interaction mechanism, and next caller action.

Keep the existing run, advisors, and permissions.

## Procedure

Read the host user-principles file and the project's `.bootgear/config/{principles,review-standard,test-standard}.md` files when present.
Use answers already clear from the conversation. Settle the items below in the order that fits the request.
For work questions in items 1–5 and 8–10, give `deputy:ask` the question, options, and stakes.
On `answered`, use the answer and retain its slugs. On `escalate`, ask the user.
If deputy is missing, record `no-deputy:not-installed` and ask the user.

### 1. Assess the request

Read the request or ticket, the implementation path, and related tests or checks before choosing a task type.
Write a nonempty `request_assessment` string outside `state_machine`.
Include observed scope, affected areas, size (`small`, `medium`, or `large`), evidence, and unknowns.
For shallow checks, state why they suffice. Reassess later only for new scope.

### Task type

Show the node reminders first.

2. **Task type** — choose one exact value:
   - `ticket-writing` — draft an issue body without design.
   - `ticket-to-pr` — implement a ticket.
   - `triage` — investigate one reported problem.
   - `change-review` — review a change already made.
   - `design-doc` — write requirements and design without tasks.
   - `artefact-review` — assess supplied output against a rubric.

If two fit, ask the user. If none fits, tell the user, choose the closest, and record the mismatch.

- For `triage`, set `triage_cutoff: one-user` only for an explicit single user, install, or customer. Otherwise use `product`.
- For `design-doc`, require `work_dir`.
- For `ticket-to-pr`, `change-review`, or `artefact-review`, require one fixed `task_folder`.
  `init` validates, creates, and canonicalizes it. Reuse it for overrides, retries, and compaction.
  Never amend it or supply it as a leave argument.
- For `artefact-review`, record `artefact_review` with the raw request and nonempty local `inputs` paths.
  Save messages or remote extracts locally with provenance if needed. Add an optional task `config` for custom criteria or angles.
  Run `engine task artefact settings` to resolve defaults and host, project, and task settings.
  Before sign-off, show effective criteria, disabled items, evidence limits, and configured source paths.
  State the audience, purpose, reader task, and delivery mode from evidence. Mark unknowns and inferences.
  The default machine reviews the supplied inputs without edits or publication.

Use absolute or home paths for folders and artefact files.

### 3. Resolve the state machine

1. Start from the built-in machine. If `.bootgear/config/state-machine-<task_type>.yaml` exists, use it as a full replacement.
2. Apply run-specific changes last. For `change-review` of another author's change, remove `fix`, `spec`, `spec-review`, and `spec-debate`.
   Remove all edges, reminder branches, and exit checks for these nodes. Keep them if the user requests fixes.
   Compare commit or diff authors, or the PR author, with the user. A missing author counts as a mismatch.
   Preserve the agreed correction scope and mutations.
3. Run `engine task state validate <path>`. Fix errors or use Fallbacks.
4. Run `engine task state diagram <path>` on the validated machine.
5. Show the diagram and reminders at sign-off. For each `reminder.leave_check` or `reminder.exit_checks`, show:
   - Exact argv, tier, and exit it gates.
   - Resolved command prefix. Gear uses `gear.toml` for registered routes and `command -v` for other commands.
   - Any unresolved command.

Sign-off approves these transition checks. Store the full validated machine as the `state_machine` block scalar.

### 4. Record approach and principles

Write nonempty strings for both. Use `approach` for workflow steps and `principles` for constraints.
Merge user and project principles with run principles before execution.

### 5. Set authorities by domain

Set separate `source_of_truth` entries. Default to these sources.

| Domain | Source |
|---|---|
| Scope and outcome | Ticket, issue, or user intent. |
| Current behavior | Code and existing tests. |
| Implementation approach | The settled approach. |
| Correctness after implementation | Checks and tests run after the change. |

Adjust for the task type. Omit the approach domain for triage when it adds no value.

### 6. Set the debate rules

Record `debate_threshold`. Debate an unresolved decision if it meets any condition below.

- Undo needs more than one revert, or the decision changes shared state.
- More than one person or customer is affected.
- The decision affects money, legal matters, security, or data loss.
- Any of these conditions is unknown.

Otherwise decide solo for a one-revert change confined to one component or file. Record each threshold answer with the decision.
A decision from a settled source is solo. Keep the threshold choice out of deputy.

- Default `debate_round_cap` to `10`. Use a requested positive cap. Give an owed unavailable-party retry one extra round.
- Default to `main-agent`, `independent-reviewer`, and `adversarial-reviewer`.
  Custom parties need unique `id`, `label`, `prompt`, and a host-supported `mechanism`.
- Use `convergence_policy: unanimous`. Default `consented_stop_allowed` to `true`.
  This policy allows `unanimous_convergence`, `consented_stop`, and `round_cap`. With `false`, remove `consented_stop`.

### 7. Set autonomy

After sign-off, set `no_further_questions: true`. Leave only required checkpoints and unclear run identity recovery.
Get a specific `permitted_mutations` list, including which Git, PR, ticket, or review actions are allowed.
A general instruction to act autonomously supplies no mutation list.

### 8. Select domain overrides

Ask once about specialized skills for the domains this machine calls.

- `design-doc` uses `spec`.
- `ticket-writing` drafts directly and uses `spec-review` to review.
- `ticket-to-pr` and `triage` use `test`.
- `change-review` uses `review`.
- `artefact-review` uses its stages and public `converge`, `resolve`, and `debate`.

For `spec_override`, `test_override`, and `review_override`, use a bare skill name or a `{sub-task-label: skill-name}` map.
Use project labels. At call time, apply valid amendments and match the current label. Use the general default if absent or unmatched.

Default `debate_mode` to `threshold`. Decide lower choices solo and resolve choices at or above the threshold.
For `mandatory`, resolve every choice. In both modes, debate only unresolved choices at or above the threshold.
`execute` rereads the mode at each debate node. An absent mode means `threshold`.

### 9. Record the run manifest

Record allowed capabilities. Include the matching domain fields for these nodes.

| Node or task | Field |
|---|---|
| `spec`, `design-doc`, or a retained `change-review` authoring path | `spec_skill` |
| `test-code`, `e2e-test`, or `triage` | `test_skill` |
| `review` | `review_skill` |
| `ticket-writing` | `spec_review_skill` |
| Optional independent spec review | `spec_review_skill` and `spec_review_override` |

Mirror each override's shape. With no override, use the general `spec`, `test`, or `review`.
At call time, use the domain skill's public selection contract.

- In `debate_roster`, list all permitted stable party IDs once. Always include `main-agent`.
- Record the resolved `debate_party_config` snapshot from item 10. Debate uses that snapshot.
- In `debate_admission`, list any other skills allowed to call debate directly. Leave it absent or empty for `resolve` only.
- Default `review_fix_mode` to `accepted_only` for external acceptance.
  Use `auto_within_permitted_mutations` to allow automatic `fix-now` patches within the run's permissions.

### 10. Set advisor roles and startup

Check required CLIs and the advisor skill without launching or pairing. Report real errors. Use the host requirements below.
Use Converge `config resolve` at the review project before launcher approval.
Include the approved task `converge.yaml` if the task folder has one. Show effective finder, r1, and r2 counts.
Save an approved task config as `converge.yaml` in the settled task folder for both review stages.
Resolve `converge-seats` without a task config. Offer only available roles among independent reviewer, adversarial reviewer, refuter, and gap hunter.
Recommend adversarial reviewer and gap hunter, or adversarial reviewer alone when `r2` is `native_subagent`.
Take an explicit decline as no advisor for that role. Record `native_subagent` in its place only after that decline.

Choose the advice mode before sign-off. Use a separate seat for debate and each persistent refuter.

| Choice | Action |
|---|---|
| `deferred` | Verify and settle the launcher now. Start the advisor when work first needs its seat. |
| `direct` | Use one-shot advice. Omit the launcher. |

Use `{invitation}` as one whole launcher argument. Use `{seat}` only when the launcher needs the seat name.
Use the requester's launch command to select the model and effort.
Show the exact launcher and planned roles at sign-off. Report any failure with its diagnostic.

Write task configs for both settings. Set selected debate parties to `advisor` and the rest to `native_subagent`.
Name all five Converge seats. Use `advisor` only for `r2` when refuter or gap hunter is selected.
Use the following route. Add `--task-config-file <task-config-file>` for each task config.

```text
<gear> --host <host> engine task config resolve --name <name> --project-root <project-root> --json
```

For `debate-parties`, add `--report models`. Show `model_report`. Follow `next` and store `debate_party_config`, never `effective`.
For `converge-seats`, follow `next` and store `converge_seats`.
Record `advisor_roles: {roles, brief, startup}`, with one line for the brief. Add an approved one-line `launcher` when supplied.
With no roles, omit startup and launcher.

### Confirm and initialize

Show the goal, diagram, reminders, gate commands, advisor roles and seats, advice mode, and launcher.
State concrete success and failure in one or two sentences. Keep a stall open while a path remains.
Allow edits. Require explicit sign-off. Write `goal` with text values `succeeded` and `failed`.

Run `<gear> --host <host> engine task session init --settlement-file <file>` with all settled fields.
Let Gear set `session_dir`. Use the parent of the printed `INIT <ledger-file>` for all active-run handoffs.

After init, record deputy answers as `solo` decisions with their slugs.
Initialize the coordination store for persistent advice. Record the assigned advisor seats for the run.
Use Advisor to start seat heartbeats.
Hand the confirmed run to `execute`.

## Rules

Keep production, outward sends, irreversible actions, goal approval, and mutation permissions with the user.
Use `deputy:record` only for the user's confirmed standing decisions.
Record a mid-run change as a session decision. Keep the original settlement.

## Fallbacks

- For unclear identity, recover `<session-dir>` and resume. Never create a replacement run.
- If the ledger exists, report the rerun and use `recall`. Do not rerun init or append a suffix.
- If the adjusted machine fails validation, try the base or project machine unchanged.
  If that fails, report the error and stop before writing settlement.
- If init rejects settlement, fix every listed field and retry without `--force`.
  Ask the user for a valid value if the refusal concerns a confirmed value.
- For a missing sibling skill, stop and report `cli:setup` for `engine`. Resume after verification.

## Host mechanics

Get the absolute path from `cli:gear`. Run `<gear> --host <host> engine task <command>`.
Use the installed Engine plugin root as `<engine-root>`. Both hosts support `native_subagent` and `advisor`.

- **Claude Code** — use `claude` and `CLAUDE_CODE_SESSION_ID`. Install missing `cli@bootgear` through the host.
  Only refuter and gap hunter need a listener. Debate is direct if `command -v codex` succeeds.
- **Codex** — use `codex` and `CODEX_SESSION_ID`. If needed, run `codex plugin add cli@bootgear`.
  Refuter and gap hunter share one listener use. Debate needs its own. If `advisor` is absent, report it and record no advisor role.
