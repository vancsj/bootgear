---
name: self-review
description: Check and correct authored work. Use before independent review, or to check prose sentence limits.
---

## Inputs and outcomes

For author review, take the fixed task folder, project root, `spec` or `code` stage, artifacts, request, and standards.
Take any candidate inventory, explicit selections, and renewal evidence.
For a writing check alone, take Markdown paths and `procedure` or `description`.

Return `check_kind: author-record` to the authoring caller.

| Field | Meaning |
|---|---|
| `outcome` | `ready`, `clean`, `limit-reached`, `needs-candidates`, `needs-selection`, `refused`, or `unavailable`. |
| `task_folder`, `record_path`, `record_exists` | Task identity, opaque record reference, and whether storage exists. |
| `stage`, `visit`, `passes`, `limit` | Current checkpoint and budget, if present. |
| `checkpoints` | Public history, settings, and completed pass snapshots. |
| `candidates`, `selections`, `pass_history` | Source inventory, confirmed modes, and prior pass evidence, if present. |
| `pending`, `diagnostic` | Missing input or actual failure. |
| `unresolved_refs` | Open author work for the caller to keep. |
| `next` | Receiver and next action. |

Only `clean` or `limit-reached` permits independent review. A cap does not resolve open work.
Return `needs-candidates` or `needs-selection` for caller confirmation. Return `refused` for correction.
Map `unavailable` to caller `blocked`. Keep pending work.

Return `check_kind: mechanical-writing` to the author.

| Field | Meaning |
|---|---|
| `outcome` | `passed`, `needs-reading`, `refused`, or `unavailable`. |
| `kind`, `checked_files` | Selected kind and checked paths. |
| `findings` | `path`, `line`, `words`, `limit`, and `text` per finding. |
| `diagnostics` | `path` and `message` per file failure. |
| `checks`, `counting_policy`, `limitations` | Supported checks, Markdown counting, and remaining author checks. |
| `next` | Author's next action. |

`passed` means no mechanical findings. On `needs-reading`, review the findings.
Correct a `refused` call. On `unavailable`, fix file errors and keep any findings.

## Procedure

For a writing check alone, run `check --kind procedure|description --files FILE...`. Return its result.
Use `procedure` for instructions and `description` for descriptive text.
If you need counting rules, exit codes, or diagnostics, read [writing-check.md](references/writing-check.md).

For an author pass:

1. Run public `status` before each pass. Follow `next`. Keep spec and code budgets separate.
2. Read the request, rules, and actual artifacts. For specs, read all current spec documents, including unchanged sections.
   Read the relevant settlement. For code, read the complete change, related prose, and tests. Use current evidence.
   For a spec pass, you may ask a sub-agent to read the full spec, request, and standards.
   Ask it to report issues to you. Keep its report private. Decide what to fix and record the verdict yourself.
3. Consider behavior, decisions, tables, diagrams, tasks, and acceptance checks.
   Consider wording, consistency, omissions, easy facts, and basic rules.
   For a spec pass, choose which issues to pursue and how much effort to spend.
4. Run `settings`. For candidates or selected modes, read [source-selections.md](references/source-selections.md).
   Apply confirmed modes only. Follow the public workflow and handback for each invoked source.
5. Run `check` on relevant prose. Read again for meaning, plain words, active voice, stable terms, and remaining ASD-STE100 rules.
6. Fix clear issues within scope. Remove avoidable counts and repeated detail. Keep numbers that define behavior, identifiers, and citations.
7. For opening, configuring, renewing, or recording a checkpoint, read [checkpoints.md](references/checkpoints.md).
   Record after reading and fixes. Give the exact attestation for a clean spec pass.
   Use `found` for remaining issues. Keep only open references.
8. Follow `next`. Stop early when clean. Return deeper questions to the caller.

## Rules

Judge quick-check effort by the check as well as issue severity.
Keep the default two-pass bound across edits, retries, compaction, and configuration changes.
Source skills add no mutation permission. The helper records choices and does not verify reading, fixes, or confirmation.
The caller checks candidate completeness and semantic coverage. A stage label alone supplies no coverage.

Keep writing results separate from author results. A writing check consumes no pass and cannot certify ASD-STE100 compliance.
Keep private hypotheses, suspect lines, and open lists with the caller. Share artifacts, full diff, request, standards, and normal Converge evidence.
Keep real contract questions in primary Open questions. Preserve normal and deferred Converge evidence.
Close author items only with independent disposition. An omitted reference cannot close an item.

## Fallbacks

On a missing required source, helper failure, or locking failure, return `unavailable` with the name and actual diagnostic.
Verify capability before using a confirmed ledger reference. Accept it on either host.
Keep the required author check and locking. Request no new mutation permission as a fallback.
Standalone callers obtain required confirmation and re-enter. They need no Engine run.

## Host mechanics

Get the absolute path from `cli:gear`. Use `<gear> --host <host> review self-review <command>`.
Commands are `settings`, `check`, `status`, `open`, `configure`, and `pass`.
Use scalar routing flags and one JSON file or stdin for checkpoint input. Add `--json` for structured output.
Resolve caller-relative paths through `GEAR_CALLER_CWD` when set.

| Host | `<host>` | Install missing CLI |
|---|---|---|
| Claude Code | `claude` | `/plugin install cli@bootgear` |
| Codex | `codex` | `codex plugin add cli@bootgear` |

If a sibling skill is missing, stop and report `cli:setup` for `review`. Resume after verification.
