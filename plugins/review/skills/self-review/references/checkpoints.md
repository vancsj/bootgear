# Checkpoints

Use the fixed task folder and public `status` only. Treat `record_path` as opaque.
Run `status --task-folder TASK --stage spec --json` before opening or reusing a checkpoint.
Absent storage returns `record_exists: false` and empty `checkpoints`. It creates no storage.

For `open`, `configure`, and `pass`, supply `--task-folder TASK --project-root PROJECT --stage spec|code`.
Use `--input FILE` or `--input -` with JSON on stdin. Follow `next`.

Open with explicit `candidates` and `selections` lists, including empty lists when applicable.
The helper assigns the same-stage visit. Omit a free visit ID.
Default `limit` is two. A different new limit needs `limit_confirmation` with typed user evidence.
Keep the limit fixed while open.

Configure only while open. Resupply the full candidate inventory and confirmed selections.
Keep project candidates, original scope, and current coverage. Preserve pass count and completed snapshots.

Record the pass after reading and authorized fixes.

```json
{"expected_pass": 1, "result": "found", "unresolved_refs": ["caller:open-item"]}
```

For a spec pass, read the full spec and check issues within reasonable effort.
For a clean spec pass, supply this exact `attestation`.

```json
{"expected_pass": 1, "result": "clean", "unresolved_refs": [], "attestation": "I have read the full spec and gone through the issues not requiring high effort to settle"}
```

Use the next number. A duplicate refuses and returns current state without another pass.
Use `clean` when no issues remain from the author check. Use `found` when issues remain.
Record only open references. `author-record` records the author's result and does not certify a fix.
`clean` closes even at the cap. `found` at the cap closes as `limit-reached`.
Keep closed checkpoints immutable. Only these two outcomes permit independent review.

Open a successor only after the prior same-stage checkpoint closes and qualifying evidence exists.
Use `renewal` with `kind: independent-revision` and independent `ref`.
For confirmed intent, use `kind: confirmed-intent-change`, supporting `ref`, and typed `confirmation`.
Edits, raw observations, retries, and compaction do not qualify.
Reuse the folder and caller-owned open work.
