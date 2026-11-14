---
name: spec
description: Write concise requirements, material design choices and derived tasks before independent review. Use when behaviour or design needs settling.
---

## Inputs and outcomes

Inputs: request or ticket, project root, repository evidence, and one fixed task folder.
Include supplied project review context, candidate skill inventory, confirmed selections, and applicable model confirmations.
In an active run, include engine root, session directory, and stage label. The run id comes from the environment.
On re-entry, include the independent review render, claim IDs, and settled choices.
Optional `stop_after` accepts only `design`.

Hand back to the caller (`execute` in an active run, the user standalone):

- `package`: requirements, optional design, task paths, open choices, and exact evidence for independent review.
- `package-design`: requirements and design paths, open choices, and evidence; no task artifact.
- `blocked`: missing statement, evidence, capability diagnostic, or pending confirmation; retain affected claim IDs and work.
- `delegated`: override artifacts and the same applicable public handback fields.
- `ready`: re-entry only; applied inline claim IDs, with the same slate and no new review.

Packages and delegated authoring handbacks include `author_review`: `task_folder`, `stage`, `visit`, `record_path`, and `outcome`.
Only author-review outcomes `clean` and `limit-reached` permit independent handoff.
Keep `unresolved_refs` with the caller, separate from independent role inputs.
A limit does not resolve those items.
Keep contract questions visible in the primary documents as Open questions.

For required confirmation, return `blocked` with `checkpoint_outcome: needs-confirmation`, `checkpoint_kind`, `pending_payload`, and `missing_confirmation`.
Source selections also retain the public self-review result and all missing candidate names.
Include the next caller action and existing confirmation references.
An active caller uses clarify's public checkpoint mode, then re-enters this skill.
A standalone caller obtains confirmation through host interaction, then re-enters.
Do not require engine for standalone authoring.

When raw implementation feedback applies, read [references/implementation-feedback.md](references/implementation-feedback.md).
Use its public intake, primary artifact binding, and gate handback.

## Procedure

1. Resolve an override before authoring and before each mapped stage.
2. Investigate and form both models before drafting.
3. Write requirements; write design for real trade-offs, or whenever `stop_after` is `design`.
4. Check completeness against the primary artifacts.
5. Derive tasks, except when `stop_after` is `design`.
6. Invoke self-review at stage `spec`, then return the package for independent spec-review.
7. On independent feedback, refresh affected artifacts and use the re-entry rules below.

### Overrides

In an active run, read the settlement through the public session command:

```text
<gear> --host <host> engine task session read --section settlement
```

Use `spec_override`, including its latest valid amendment.
A bare skill name applies to the whole task.
A mapping uses stage labels `requirements`, `design`, `review`, and `task`.
An absent matching entry uses this skill's default stage. Do not search for another override.
Standalone, use a clearly named or registered project spec skill when its description matches the request.

Pass engine root, session directory, task folder, authoring context, and `stop_after` to an override.
Overrides return each stage's artifact and the applicable author-review handback.
When `stop_after` is `design`, invoke no mapped task stage and return no task artifact.
An incompatible override returns `blocked`; obtain the missing author check through its public skill before independent handoff.

### Stage 1: investigation and requirements

Read the request, relevant implementation, analogous tests, and authoritative contracts before choosing a design.
Read `.bootgear/config/principles.md`, `.bootgear/config/review-standard.md`, and `.bootgear/config/test-standard.md` when present.
Read the host user-principles file when present.
In an active run, also read the settlement's principles.

Before drafting, read [references/investigation-models.md](references/investigation-models.md).
Write task-local `investigation.md` with conclusions, evidence, checked boundaries, and unresolved facts.
Form the mental and conceptual models.
If either is uncertain or materially changed, return the pending checkpoint before affected drafting.
Clear, unchanged models need no new confirmation.

Read [references/document-status.md](references/document-status.md) when writing or updating requirements or design.
Write concise `requirements.md` with the goal, boundaries, required behaviour, constraints and acceptance checks.
Include a compatibility target or feature model only when it defines the requested behaviour.
Use relevant arc42 sections. Keep material facts, assumptions, constraints, decisions and open questions clear without empty headings.
State each contract once. Reference that statement elsewhere.
Remove avoidable descriptive counts. Preserve behaviour-defining numbers, identifiers and useful citations.
Keep run controls in the settlement.
Write rationale in task-local `requirements-notes.md`.
Challenge any exclusion that prevents the requested outcome; return the concrete scope choice to the caller.
Do not decide unresolved interpretations through guesswork, resolve, or debate within this stage.

Return the requirements artifact: primary path and content, notes path, open questions, and investigation evidence.
In an active run, the caller handles choices after independent review.
Standalone, the direct caller handles them.

### Stage 2: design

Run this stage for real trade-offs. Always run it when `stop_after` is `design`.
Otherwise, a small task can use requirements alone.

Explain material choices, consequences, affected boundaries, resulting behaviour and necessary order in `design.md`.
Cite the existing pattern being followed.
For real alternatives, state the selected approach and each rejected option's cost or risk.
Keep these alternatives in the primary design for independent review.
Use relevant arc42 sections. Keep material status information clear through sections or concise labels.
Leave routine internal naming and implementation inventories to implementation.
Put additional rationale in task-local `design-notes.md`.
Read [references/views-security.md](references/views-security.md) for affected architecture, data, lifecycle, relations, or security boundaries.
Choose useful C4 or runtime views that explain the changed mechanism. Do not require a diagram without a useful view.

Return the design artifact: primary path and content, notes path, and unresolved material trade-offs.
Retain those trade-offs in primary Open questions.

### Stage 3: completeness

Read primary requirements and design, when present. Do not rely on notes.
Check the design, or requirements when design was skipped:

1. Each material change identifies its affected boundary or location clearly enough for implementation.
2. Each change states the resulting behaviour.
3. Changes have a stated order, or are explicitly order-independent.
4. No substantive choice remains as TBD, an implementation-time decision, or competing options.

A local method name or equivalent code structure can remain open when the contract fixes behaviour.
Do not turn that freedom into a missing requirement.
Check the literal goal and every constraint. Check both directions between the request and proposed work.
Resolve assumptions that can invalidate requirements or architecture before affected implementation can start.
If completeness fails, name the criterion and change, then revise requirements or return to design.
Do not derive tasks from a failing artifact.

### Stage 4: task breakdown

Skip this stage when `stop_after` is `design`.
Derive ordered `task.md` steps from unambiguous primary requirements or design statements.
Each step names its source statement. Do not invent behaviour or a material design choice.
Name work units and acceptance checks. Reference primary contracts instead of repeating design details or implementation inventories.
If a step cannot be derived, make one bounded return to design or completeness with the exact gap.
If the same gap remains, return `blocked`, no task artifact, and the missing statement.
Include related claim IDs and evidence on re-entry.
Ordering already declared independent and local naming are not substantive choices.

Return the task artifact: content and path, or the structural refusal.

### Stage 5: author check and package return

Invoke self-review through its public interface at stage `spec`, using the fixed task folder and authoring context.
Supply the actual requirements, design when present, tasks and relevant settlement text.
Follow its reading-and-fix workflow. Do not replace it with checkpoint helper calls.
Keep mechanical results separate from the author's recorded result. Keep deeper questions open for independent review.
Keep its default two-pass budget. Stop earlier when clean.
Reuse an open checkpoint after edits, retries, configuration changes, or compaction.
Renew a closed checkpoint only with related independent-revision or confirmed-intent-change evidence.
Do not increase an active limit or infer any source-skill mode.
Keep candidate discovery, selections, scope, provenance, and coverage under self-review's public contract.
Never scan installed skills to form candidates.

At `needs-candidates` or `needs-selection`, retain pending work and return the confirmation handback where required.
At `unavailable`, return `blocked` with the actual diagnostic and named mechanism.
Do not bypass checking or run without supported locking.
Only `clean` or `limit-reached` permits the independent package handoff.
Retain all still-open author references with the caller.

Return `package` with all derived primary paths, open choices, evidence, and `author_review`.
When `stop_after` is `design`, return `package-design` without task content or path.
Do not run independent spec-review, resolve, or debate here.

### Re-entry

Read the review render, claim IDs, and settled choices.
Apply authorised inline patches and address revise claims in the primary artifacts.
Propagate changed intent through requirements, design, tasks, tests, views, and supporting drafts.
Recheck materially changed models before affected drafting.
When findings recur, compare the changed artifacts and prior evidence before another round.
Record the supported cause and corrective action in task-local caller tracking.

For `revise` or settled `choices`, rerun completeness, task derivation when applicable, and the author check.
Return the refreshed package, or `package-design` when `stop_after` is `design`.
Do not silently drop unresolved claims or author references.
For `ready` with only inline patches, apply them and return `ready` with their IDs.
Do not rerun stages 3–5 or start a new slate on that inline path.
Preserve the existing checkpoint and the caller's required ready-exit gate.

## Judgment rules and safety

Keep primary artifacts readable without notes.
Write required facts in the primary artifact; notes may explain them but cannot carry them alone.
Cite durable rationale in notes rather than embedding it in the primary artifact.
Keep evidence, assumptions, constraints, decisions, and unresolved questions distinct.
User confirmation settles intent; verify current behaviour with evidence.
Independent roles receive primary artifacts, authoritative intent, standards, and normal converge evidence.
Exclude notes, author hypotheses, private unresolved lists, and suspect-line lists from their briefs.
A factual finding, author check, or ready result grants no mutation or delivery permission.

`debate_mode` belongs to the caller's settlement:

- `threshold`: decide below-threshold choices through the caller; escalate eligible choices through resolve and debate.
- `mandatory`: send every choice to resolve; send unresolved choices at or above the threshold to debate.

## Fallbacks

Return `blocked` when required evidence, self-review, an override, or its public helper is unavailable.
Report the real diagnostic, missing mechanism, pending work, and next caller action.
Without required confirmation, return before affected drafting or a source-dependent author pass.
Do not treat unavailable history as empty history or request new mutation permission as a fallback.

## Host mechanics

Read only the subsection for the current host. Skip the other host subsection.

### Claude Code

Use `spec` for `<spec-plugin>`.

Use `claude` for `<host>`.

- Invoke skills through the Skill tool.
- Call `cli:gear`. Replace `<gear>` with its literal absolute path in each tool call.
- Run engine commands as `<gear> --host claude engine task <command> [arguments]`.
- Run feedback commands as `<gear> --host claude spec spec-feedback <command> [arguments]`.
- If `cli:gear` is missing, run `/plugin install cli@bootgear` first.
- Keep `session_dir` in context. Supply `--dir` only for a custom session directory.

### Codex

Use `spec` for `<spec-plugin>`.

Use `codex` for `<host>`.

- Invoke skills by public name.
- Call `cli:gear`. Replace `<gear>` with its literal absolute path in each tool call.
- Run feedback commands as `<gear> --host codex spec spec-feedback <command> [arguments]`.
- Run engine commands as `<gear> --host codex engine task <command> [arguments]`.
- If `cli:gear` is missing, install `cli@bootgear` with `codex plugin add cli@bootgear`.
- Keep `<engine-root>` from the caller for active-run handoffs.
- Keep `session_dir` in context. Supply `--dir` only for a custom session directory.
- If required self-review or its public command is missing, return `blocked` with the actual diagnostic.

If a required sibling skill is missing, stop and report `cli:setup` with target `spec` as the next step.
Resume after setup verifies the required plugins.
