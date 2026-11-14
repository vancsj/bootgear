---
name: self-review
description: Read and fix authored artifacts, check sentence limits, and record bounded author results before independent review.
---

## When to invoke, inputs and handback

Use before independent review of an artifact you authored or changed.
Accept the fixed task folder, project root, stage `spec` or `code`, artifacts, request and applicable standards.
Accept a caller candidate inventory and explicit user selections. Accept related renewal evidence when needed.
For a writing check alone, accept selected Markdown files and kind `procedure` or `description`.

Return checkpoint handbacks to the authoring caller with `check_kind: author-record`:

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

Return writing results to the author with `check_kind: mechanical-writing`:

| Field | Meaning |
|---|---|
| `outcome` | `passed`, `needs-reading`, `refused` or `unavailable`. |
| `kind`, `checked_files` | Selected text kind and checked paths. |
| `findings` | Entries with `path`, `line`, `words`, `limit` and `text`. |
| `diagnostics` | File failures with `path` and `message`. |
| `checks`, `counting_policy`, `limitations` | Supported checks, Markdown word rules and remaining author checks. |
| `next` | The author's next action. |

Treat `passed` as no mechanical findings. Treat `needs-reading` as findings for author review.
Correct `refused` calls. Resolve `unavailable` file failures and retain any reported findings.
A writing result never establishes completed author reading or full ASD-STE100 compliance.

## Procedure

For a writing check alone, read [references/writing-check.md](references/writing-check.md), run `check` and return its result.
For an author pass, follow the reading workflow below within the current checkpoint budget.

### Read and fix

Check public `status` before another checkpointed pass. Follow its next action and retain a closed checkpoint's bound.

1. Read the request, applicable rules and actual artifacts. Do not rely on a summary or earlier verdict.
2. For specs, read requirements, design when present, tasks and relevant settlement text.
3. For code, read the complete current change, related prose and relevant tests.
4. Compare behaviour, decisions, tables, diagrams, tasks and acceptance checks. Check wording, consistency, omissions, easy facts and basic rules.
5. Run `settings`. Read [references/source-selections.md](references/source-selections.md) before building candidates or applying confirmed source modes.
6. Apply each confirmed source mode. Follow invoked workflows and their public handbacks.
7. Read [references/writing-check.md](references/writing-check.md) before checking relevant prose with `check`.
8. Read again for meaning, simple words, active voice, consistent terms and ASD-STE100 rules outside the mechanical check.
9. Fix clear issues within authorised scope. Remove avoidable descriptive counts and repeated detail. Preserve behaviour-defining numbers, identifiers and citations.

### Record the author result

1. Read [references/checkpoints.md](references/checkpoints.md) before opening, configuring, renewing or completing a checkpoint.
2. Use public `status` to reuse the current checkpoint. Keep separate spec and code budgets.
3. Record the author's result after reading and fixes. Use `found` when issues remain. Keep only still-open references.
4. Follow the command's next action. Stop early when clean. Keep deeper questions open with the caller.

## Judgment rules and safety boundaries

Judge quick-check effort by the check, not only the issue's severity.
Keep the default two-pass bound. Edits, retries, compaction and configuration changes never reset it.
Source skills add no mutation permission. The helper records choices; it cannot prove reading, fixes or confirmation truth.
Keep mechanical findings separate from author records. A writing check creates no checkpoint and consumes no author pass.
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

Call `cli:gear`. Replace `<gear>` with its literal absolute path in each tool call.
Run Claude commands as `<gear> --host claude review self-review <command> [arguments]`.
Run Codex commands as `<gear> --host codex engine self-review <command> [arguments]`.
If `cli:gear` is missing, install `cli@bootgear` with `codex plugin add cli@bootgear`.
The commands support `settings`, `check`, `status`, `open`, `configure` and `pass`.
Use scalar routing flags. For checkpoint input, use one JSON file or stdin. Add `--json` for structured handbacks.
Resolve relative caller paths through `GEAR_CALLER_CWD` when supplied.
