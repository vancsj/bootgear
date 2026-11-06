---
name: self-review
description: Run bounded author checks with confirmed source skill selections before independent spec or code review.
---

## When to invoke, inputs and handback

Use before independent review of an artifact you authored or changed.
Accept the fixed task folder, project root, stage `spec` or `code`, artifacts, request and applicable standards.
Accept a caller candidate inventory and explicit user selections. Accept related renewal evidence when needed.

Return the public command handback to the authoring caller:

| Field | Meaning |
|---|---|
| `outcome` | `ready`, `clean`, `limit-reached`, `needs-candidates`, `needs-selection`, `refused` or `unavailable`. |
| `task_folder`, `record_path` | Fixed task identity and opaque author record reference. |
| `record_exists` | Whether author storage exists. |
| `stage`, `visit`, `passes`, `limit` | Current checkpoint and budget, when present. |
| `checkpoints` | Public checkpoint history, settings and completed pass snapshots. |
| `candidates`, `selections`, `pass_history` | Current sources, confirmed modes and completed pass evidence, when present. |
| `pending`, `diagnostic` | Missing inputs or the actual failure. |
| `unresolved_refs` | References to still-open author work, retained by the caller. |
| `next` | The receiver and its next action. |

Only `clean` and `limit-reached` permit independent-review handoff. A cap does not establish a clean artifact.
Return `needs-candidates` or `needs-selection` to the caller for confirmation. Do not infer choices.
Return `refused` for correction. Map `unavailable` to the caller's `blocked` result and preserve pending work.

## Procedure

1. Run `settings` to learn defaults and supported inputs.
2. Read [references/checkpoints.md](references/checkpoints.md) before opening, configuring, renewing or completing a checkpoint.
3. Read [references/source-selections.md](references/source-selections.md) when building candidates or applying selected source modes.
4. Use public `status` to reuse the current checkpoint. Keep separate spec and code budgets.
5. Apply each confirmed source mode. Follow invoked workflows and their public handbacks.
6. Check clear terms, short sentences, obvious rule breaks, factual sources and conflicting sections.
7. Compare the request, decisions, tables, diagrams, tasks and outcome checks. Fix easy issues within authorised scope.
8. Record the artifact's state after fixes. Use `found` when issues remain, and keep only still-open references.
9. Follow the command's next action. Stop early when clean. Keep deeper work open with the caller.

## Judgment rules and safety boundaries

Judge quick-check effort by the check, not only the issue's severity.
Keep the default two-pass bound. Edits, retries, compaction and configuration changes never reset it.
Source skills add no mutation permission. The helper records choices; it cannot prove reading, fixes or confirmation truth.
The caller checks candidate completeness and semantic coverage. A matching stage label does not prove coverage.

Keep author hypotheses, suspect lines and private unresolved lists with the caller.
Give independent roles artifacts, the full review diff when applicable, request, standards and normal converge evidence.
Keep genuine contract questions in primary spec Open questions. Preserve normal converge claims and deferred evidence.
Keep author items open until independent investigation or normal converge treatment establishes their disposition.
Do not close them because a later handback omits them.

## Fallbacks

If a required source skill is missing, return `unavailable` with its name and actual diagnostic to the caller.
Accept confirmed ledger references when available on either host. Check the actual capability before using it.
If the helper or local advisory locking fails, return `unavailable` with the actual diagnostic and named mechanism.
Never run unlocked, skip author review or request new mutation permission as a fallback.
Do not require an engine run for standalone authoring. The direct caller obtains required confirmation and re-enters.

## Host mechanics

Claude: use the registered `BOOTGEAR_HOST=claude gear.py review self-review` command.
Codex: use the registered `BOOTGEAR_HOST=codex gear.py engine self-review` command.
Set the host on each command when tool shells do not retain the host context.
Both commands support `settings`, `status`, `open`, `configure` and `pass`.
Use scalar routing flags and one JSON file or stdin for structured input. Add `--json` for structured handbacks.
Resolve relative caller paths through `GEAR_CALLER_CWD` when supplied.
