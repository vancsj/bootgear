# Implementation feedback

Use when tests, runtime evidence, implementation, or review exposes a requirement or design gap.
Keep the gap open before further affected changes. Keep the fixed folder, correction scope, and mutation limits.

## Intake

Record raw evidence without author hypotheses or suspect lines.

```json
{"observations": [{"id": "O001", "evidence_paths": ["<readable raw evidence file>"]}]}
```

Use unique IDs and nonempty evidence paths. Resolve relative paths from the caller's working folder.
Use `spec-feedback settings` for supported inputs and schemas. Run public intake.

```text
<gear> --host <host> <spec-plugin> spec-feedback intake --task-folder <folder> --observations <file> --destination spec-review --json
```

With requirements, route to spec-review. Design is optional.
Route first authoring to spec only without requirements, design, and earlier spec checkpoints.
Recover missing artifacts in the existing folder after a checkpoint. Never bootstrap again.
Keep `requirements.md`, optional `design.md`, and author record in the fixed folder.
On bound Engine paths, reject override output in another folder.

## Review and resumption

Give the finder raw observations, primary specs, required behavior, standards, and normal Converge evidence.
Keep private author work with the caller. Pass independent checks without edits.
Refresh affected tasks, tests, diagrams, checks, and drafts. Keep deferred details, private todos, pass counts, and visit caps.
Raw observations, edits, retries, and compaction keep the budget. Renewal needs related independent review or confirmed intent.

Use the public gate before every affected ready exit.

```text
<gear> --host <host> <spec-plugin> spec-feedback gate --task-folder <folder> --slate <slate> --converge-dir <absolute-dir> --observations <file> --checks <file> --json
```

Use the same slate after ready-inline fixes. Complete independent checks and Converge.
Link independent dispositions to private todos afterward. Require relevant evidence and a disposition before closing a blocking gap.
An omission, passing rerun, or empty claim list cannot close it alone.
Resume ticket-to-PR at `impl` and authorized change-review at `fix`. At a cap, retain gaps as blocked or follow-up.

## Handback

Use `--json` or `--prose`. Default to prose unless `BOOTGEAR_OUTPUT=json`.
Resolve paths from `GEAR_CALLER_CWD` when set. Intake and gate do not write task artifacts.

| Field | Meaning |
|---|---|
| `outcome` | `ready`, `passed`, `refused`, or `unavailable`. Only gate returns `passed`. |
| `task_folder`, `requirements_path`, `design_path` | Canonical task and paths. Absent design is null. |
| `destination`, `checkpoints` | Intake target and public spec-stage history. |
| `observations_path`, `checks_path`, `checks` | Sidecars and independent coverage when applicable. |
| `slate`, `converge_dir`, `converge` | Gate identity and public result when available. |
| `problems`, `diagnostic`, `next` | Grouped errors, diagnostic, and caller action. |

Correct refused input or complete missing work before retrying. Map `unavailable` to blocked and report the diagnostic and mechanism.
Keep observations and private todos. Do not bypass self-review or Converge.
The caller checks meaning, independence, scope, and permission. The CLI checks structure and coverage.

## Host mechanics

Use the absolute path from `cli:gear`.
For Claude Code, use `claude` for `<host>` and `spec` for `<spec-plugin>`.
For Codex CLI, use `codex` for `<host>` and `spec` for `<spec-plugin>`.
Install missing `cli:gear` with `/plugin install cli@bootgear` or `codex plugin add cli@bootgear`, respectively.
If required self-review, Converge, or spec-feedback is missing, return blocked with the real error.
