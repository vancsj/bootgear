# Independent observation checks

Read this reference when the caller supplies observations.
Accept an optional raw inventory path as `observations_path`.
Hand `observations_path`, finder-authored `checks_path`, and `checks` back to the caller with the normal result.

The raw file has this envelope:

```json
{"observations": [{"id": "O001", "evidence_paths": ["<readable raw evidence file>"]}]}
```

Investigate every observation against required behaviour, primary specs, standards, and raw evidence.
Read primary Open questions. Keep author hypotheses, private unresolved lists, and suspect-line lists outside independent role briefs.
Write checks from independent investigation and final claim outcomes. The caller passes your file without edits.
Keep every actual finding in normal converge treatment, including attacks, finder replies, verdicts, and withdrawals.

Write this report envelope:

```json
{
  "slate": "<current-slate>",
  "checks": [{
    "id": "O001",
    "state": "checked",
    "evidence_refs": ["<independent investigation evidence>"],
    "disposition": "<result about required behaviour>",
    "claim_ids": ["F001"]
  }]
}
```

Each observation needs exactly one check. Use only current-slate claim IDs.
Use `unassessed` while investigation remains incomplete. Never present it as closure.
A checked result needs nonempty investigation evidence references and a disposition about required behaviour.
An empty `claim_ids` list is valid when independent investigation found no defect.
A passing rerun or an empty claim list alone cannot close a blocking behavioural gap.
Do not claim coverage from a report copied from another slate.

Use public `spec-feedback settings` for complete schemas.
Use public `spec-feedback gate` with both sidecar paths and the current slate before an affected ready exit.
Explicit empty arrays serve initial reviews on the two bound engine paths. Other reviews need no empty files.
A ready-inline correction uses the same slate and checks, with no added review slate.
The gate checks report scope, fields, IDs, raw file readability, coverage, known claims, and normal converge completion.
It does not prove evidence truth, independent authorship, meaning, or permissions.

Return the independent dispositions to the caller. The caller links them to private todos afterward.
Keep unresolved observations visible. Missing checks and unassessed results leave their corresponding gaps open.
If a public helper is unavailable, return blocked with its diagnostic and named mechanism.
Keep the same observations, checks, task folder, checkpoint history, and cumulative caps during recovery.
