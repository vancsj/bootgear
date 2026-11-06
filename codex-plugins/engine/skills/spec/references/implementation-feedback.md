# Implementation feedback

Use this path when tests, runtime evidence, implementation, or code review shows a requirement or design gap.
Keep the gap open before further affected changes. Use the workflow's fixed task folder.
Keep correction scope and mutation limits. A feedback result grants no permission.

## Intake

Record raw observations in a JSON file:

```json
{"observations": [{"id": "O001", "evidence_paths": ["<readable raw evidence file>"]}]}
```

Use unique IDs and nonempty evidence path lists. Resolve relative paths against the caller's working folder.
Do not include author hypotheses or suspect-line lists in the raw inventory.
Call public `spec-feedback settings` for supported inputs and schemas.
Run public intake with the fixed task folder, observations file, and intended destination:

```text
spec-feedback intake --task-folder <folder> --observations <file> --destination spec-review --json
```

Existing requirements route to spec-review. Design remains optional.
First authoring routes to spec only without requirements, design, and prior spec checkpoints.
Recover missing artifacts after a checkpoint in the same folder. Never create a new bootstrap.
Keep `requirements.md`, optional `design.md`, and the author record in the fixed folder.
Reject override handbacks that use another folder on a bound engine path.

## Independent review and resumption

Give the finder raw observations, primary specs, required behaviour, standards, and normal converge evidence.
Keep private author work with the caller. Pass the finder-authored checks file without edits.
Refresh affected tasks, tests, diagrams, verification, and supporting drafts after contract changes.
Preserve deferred claim details, private todos, checkpoint counts, and cumulative visit caps.
Raw observations, edits, retries, and compaction never renew a self-review budget.
Closed checkpoint renewal needs related independent review or confirmed intent evidence.

Run public `spec-feedback gate` before each affected ready exit:

```text
spec-feedback gate --task-folder <folder> --slate <slate> --converge-dir <absolute-dir> --observations <file> --checks <file> --json
```

Use the same slate after a ready-inline correction. Complete independent checks and normal converge work.
Link independent dispositions to private todos afterward. An omitted item never closes a todo.
Require relevant evidence and a disposition about required behaviour before closing a blocking gap.
A passing rerun or an empty claim list alone cannot close it.
Resume ticket-to-pr at impl and authorised change-review at fix.
At a cap, retain pending gaps and use the existing blocked or follow-up outcome.

## Public handback

All commands support prose defaults, `--json`, and `--prose`.
Without an explicit output flag, `BOOTGEAR_OUTPUT` applies. Codex wrappers default to prose.
Paths resolve against `GEAR_CALLER_CWD` when set. Intake and gate never write task artifacts.

Return these fields to the caller:

| Field | Meaning |
|---|---|
| `outcome` | `ready`, `passed`, `refused`, or `unavailable`; only gate returns `passed`. |
| `task_folder`, `requirements_path`, `design_path` | Canonical identity and primary paths; absent design is null. |
| `destination`, `checkpoints` | Intake destination and public spec-stage history. |
| `observations_path`, `checks_path`, `checks` | Sidecar paths and independent coverage entries when applicable. |
| `slate`, `converge_dir`, `converge` | Gate identity and public converge gate result when available. |
| `problems`, `diagnostic`, `next` | Grouped errors, actual capability diagnostic, and caller action. |

`refused` requires corrected input or completed work before retrying.
Map `unavailable` to blocked. Report its actual diagnostic and named mechanism; retain observations and private todos.
Never bypass self-review or converge because a helper is unavailable.
The CLI checks structure and coverage. The caller checks meaning, independence, scope, and permissions.

## Host mechanics

Claude resolves public helpers through PATH. Use the registered Gear spec-feedback command.
Codex checks bundled helpers first, then PATH. Use its registered engine spec-feedback command.
If self-review, converge, or spec-feedback is missing, return blocked with the actual diagnostic.
