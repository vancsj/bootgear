---
name: spec
description: Write requirements, material design choices, and derived tasks. Use when behavior or design needs a spec.
---

## Inputs and outcomes

Take the request or ticket, project root, repo evidence, and fixed task folder.
Take supplied project review context, candidate skills, confirmed selections, and model confirmations.
In Engine, take the Engine root, session directory, and stage label. On re-entry, take the render, claim IDs, and choices.
Optional `stop_after` accepts only `design`.

Return one outcome to `execute` in Engine or the standalone user.

| Outcome | Handback |
|---|---|
| `package` | Requirements, optional design, task paths, open choices, and exact review evidence. |
| `package-design` | Requirements, design, open choices, and evidence. Omit tasks. |
| `blocked` | Missing statement or evidence, actual capability error, or pending confirmation. Keep claim IDs and work. |
| `delegated` | Override artifacts and the same applicable fields. |
| `ready` | On inline-only re-entry, applied claim IDs and the same slate. |

Include `author_review` with `task_folder`, `stage`, `visit`, `record_path`, and `outcome` for authored packages and overrides.
Only `clean` and `limit-reached` permit handoff. Keep `unresolved_refs` with the caller, outside independent briefs.

For required confirmation, return `blocked` with `checkpoint_outcome: needs-confirmation`, `checkpoint_kind`, `pending_payload`, and `missing_confirmation`.
Include existing confirmation references and the next caller action.
For source selection, include the public self-review result and all missing candidate names.
Engine uses clarify checkpoint mode. Standalone uses host interaction. Re-enter after confirmation.

## Procedure

### Select an override

Check before authoring and at each mapped stage. In Engine, read `engine task session read --section settlement`.
Use `spec_override` with its latest valid amendment. A bare skill covers the task.
Use mapping labels `requirements`, `design`, `review`, and `task`. If unmatched, use this default and stop searching.
Standalone, use a clearly named or registered project spec skill that fits.

Pass run paths, task folder, authoring context, and `stop_after`. Require the stage artifact and applicable author handback.
For `stop_after: design`, skip the mapped task stage. Return no tasks.
Return `blocked` for an incompatible override. Obtain any missing author check through its public skill before handoff.

### 1. Investigate and write requirements

Read the request, implementation, analogous tests, and authoritative contracts. Read existing host and project principles and standards.
Use `.bootgear/config/{principles,review-standard,test-standard}.md` and Engine settlement principles where applicable.
Write `investigation.md` with behavior, evidence, checked boundaries, and unresolved facts.

Form both models before design. State user expectations and limits. State concepts, responsibilities, relationships, and boundaries.
If either model is uncertain or changed materially, stop affected drafting and return the checkpoint.
Read [investigation-models.md](references/investigation-models.md) for an uncertain or changed model or a complex evidence trace.
Reuse exact confirmation when it covers the payload and scope. Clear, unchanged models need no new question.

Write concise `requirements.md` with goal, boundaries, required behavior, constraints, and acceptance checks.
Add a compatibility target or feature model only if it defines behavior.
Use relevant arc42 sections. Keep facts, assumptions, constraints, decisions, and Open questions visible.
For material assumptions or status distinctions, use [document-status.md](references/document-status.md).
State each contract once and cite it elsewhere. Keep necessary numbers, identifiers, and evidence. Remove avoidable counts.
Keep run controls in settlement. Keep rationale in `requirements-notes.md`.
If an exclusion blocks the requested result, return that scope choice. Leave unresolved interpretations with the caller.

Return requirements path and content, notes path, Open questions, and evidence. In Engine, the caller handles choices after review.

### 2. Write design

For a real trade-off or `stop_after: design`, write `design.md`. Otherwise a small task can use requirements alone.
State material choices, consequences, boundaries, behavior, and necessary order. Cite the existing pattern.
Keep rejected alternatives with their cost or risk. Use relevant arc42 sections and clear status labels.
Leave local names and implementation inventories open. Put extra rationale in `design-notes.md`.

For changed architecture, data, lifecycle, relations, or security, read only the applicable checks in [views-security.md](references/views-security.md).
Use a C4 or runtime view if it explains the changed mechanism. Skip diagrams without a useful view.
Return design path and content, notes path, and unresolved material trade-offs in primary Open questions.

### 3. Check completeness

Read primary requirements and design when present. For each material change, verify all four conditions.

1. It names the affected boundary or location clearly enough to implement.
2. It states the result.
3. It states the order or says order is independent.
4. It leaves no substantive TBD, competing option, or implementation-time choice.

Allow local naming and equivalent structure when behavior is fixed.
Check the literal goal and all constraints in both directions. Resolve assumptions that can invalidate requirements or architecture.
If a check fails, name the criterion and change. Revise requirements or design before tasks.

### 4. Derive tasks

Skip this stage for `stop_after: design`.
Write ordered `task.md` steps from clear primary statements. Cite each statement. Name work units and acceptance checks.
Reference contracts. Do not invent behavior or design choices. Allow independent order and local names where specified.
If derivation fails, return once to design or completeness with the exact gap.
If it remains, return `blocked` with the missing statement and no task artifact. On re-entry, retain claim IDs and evidence.
Return task path and content, or the refusal.

### 5. Check authored work and return

Call public self-review at `spec` with the fixed folder and authoring context. Give it all primary artifacts and relevant settlement.
Follow its reading and fixes. Keep mechanical results separate from the author record.
Keep the default two passes and stop early when clean. Preserve the open budget across edits, retries, config changes, and compaction.
Renew closed checkpoints only from related independent revision or confirmed intent change. Keep active limits fixed.
Use its public source contract. Never scan installed skills or infer a mode.
On `needs-candidates` or `needs-selection`, retain work and return the required confirmation handback.
On `unavailable`, return `blocked` with the diagnostic and mechanism. Keep author checking and locking required.
Return `package` or `package-design` only on `clean` or `limit-reached`. Keep open references with the caller.

### Re-entry and implementation feedback

For raw implementation feedback, read [implementation-feedback.md](references/implementation-feedback.md).
Use public intake, artifact binding, and gate handback.

Read the render, claim IDs, and choices. Apply authorized inline patches. Address revise claims in primary artifacts.
Propagate changed intent through specs, tasks, tests, views, and drafts. Check changed models before affected drafting.
If findings recur, compare artifacts and evidence. Record the cause and correction with the task before another round.

- For `revise` or settled `choices`, repeat completeness, task derivation when required, and author check. Return the refreshed package.
- For `ready` with only inline patches, return `ready` with applied IDs. Skip stages 3–5 and any new slate.
  Keep the existing checkpoint and required exit gate.

Retain unresolved claims and author references. Skip references for paths you do not use.

## Rules

Make primary artifacts complete without notes. Cite durable rationale in notes. Keep contract questions in primary Open questions.
User confirmation settles intent. Verify current behavior with evidence.
Give independent roles primary artifacts, intent, standards, and normal Converge evidence. Keep author notes and suspect lists private.
Leave independent review, resolve, and debate to the caller. In `threshold`, it decides lower choices and escalates eligible choices.
In `mandatory`, it resolves all choices and debates unresolved choices at or above the threshold.
A finding, author check, or ready result adds no mutation or delivery authority.

## Fallbacks

If needed evidence, self-review, override, or helper is unavailable, return `blocked`.
Give the real diagnostic, mechanism, pending work, and next action. Do not treat unavailable history as empty.
Without confirmation, stop affected drafting or source-dependent author work. Do not request extra mutation permission as a fallback.

## Host mechanics

Read only the current host's section. Keep `session_dir` and the caller's Engine root. Add `--dir` only for a custom directory.
Use `spec` for `<spec-plugin>`. Gear reads the run ID from the environment.

### Claude Code

Invoke through Skill. Get the absolute executable from `cli:gear`.
Run `<gear> --host claude engine task <command>` and `<gear> --host claude spec spec-feedback <command>`.
If needed, run `/plugin install cli@bootgear`.

### Codex

Invoke by public name. Get the absolute executable from `cli:gear`.
Run `<gear> --host codex engine task <command>` and `<gear> --host codex spec spec-feedback <command>`.
If needed, run `codex plugin add cli@bootgear`.
If a required sibling is missing, stop and report `cli:setup` for `spec`. Resume after verification.
