# Checkpoints

Use the workflow's fixed task folder throughout the task. Treat `record_path` as opaque; read public `status` only.
Run `status --task-folder TASK --stage spec --json` before opening or reusing a checkpoint.
Absent storage returns `record_exists: false` and an empty `checkpoints` list without creating storage.

Route `open`, `configure` and `pass` with `--task-folder TASK --project-root PROJECT --stage spec|code`.
Pass structured input with `--input FILE`, or `--input -` and JSON on stdin.
Read the command's `next` field after each action.

Open with explicit `candidates` and `selections` lists, including explicit-empty lists when applicable.
The helper assigns each same-stage visit. Never supply a free visit identifier.
The default `limit` is two. A different new-checkpoint limit needs `limit_confirmation` with typed user evidence.
Never change an active checkpoint's limit.

Use `configure` only on an open checkpoint. Supply the full applicable candidate inventory and confirmed selections again.
Keep project candidates. Preserve original scope and provide a current coverage declaration.
Configuration changes preserve the count and every completed pass snapshot.

Record a pass with this shape:

```json
{"expected_pass": 1, "result": "found", "unresolved_refs": ["caller:open-item"]}
```

Use the expected next number. A duplicate call refuses and returns current state without another pass.
Use `clean` when the quick check is clean after authorised fixes. Use `found` when issues remain.
Record only still-open references. A record never certifies that an open issue was resolved.
`clean` closes the checkpoint, including at the cap. `found` at the cap closes it as `limit-reached`.
Closed checkpoints remain immutable. Only `clean` and `limit-reached` permit independent-review handoff.

Open a successor only after the prior same-stage checkpoint closes and actual qualifying evidence exists.
Add `renewal` with `kind: independent-revision` and a supporting independent review `ref`.
For confirmed intent changes, use `kind: confirmed-intent-change`, a supporting `ref`, and typed `confirmation`.
An ordinary edit, raw observation, retry or compaction never qualifies as renewal.
Retain the same task folder and caller-owned open work across successors.
