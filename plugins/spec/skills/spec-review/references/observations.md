# Independent observation checks

Take optional `observations_path`. Return it with finder-authored `checks_path` and `checks`.

```json
{"observations": [{"id": "O001", "evidence_paths": ["<readable raw evidence file>"]}]}
```

Check each observation against required behavior, primary specs and Open questions, standards, and raw evidence.
Keep hypotheses, private lists, and suspect lines out of independent briefs.
Write checks from independent investigation and final claims. The caller passes the file unchanged.
Keep findings in normal Converge, including attacks, replies, verdicts, and withdrawals.

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

Write one check per observation. Use only current-slate claim IDs. Use `unassessed` while incomplete.
For `checked`, supply nonempty evidence references and a required-behavior disposition.
An empty claim list is valid after independent investigation. It cannot close a gap alone. Neither can a passing rerun.
Never reuse checks from another slate.

Use public Spec feedback settings for schemas. Before the affected ready exit, run its gate with both files and the slate.
Use explicit empty arrays for initial reviews on the two bound Engine paths. Omit them for other initial reviews.
After ready-inline correction, keep the same slate and checks.
The gate checks scope, shape, IDs, readability, coverage, known claims, and Converge completion.
The caller verifies truth, independent authorship, meaning, and permission.

Return independent dispositions. Let the caller link private todos. Keep missing or unassessed checks open.
If a public helper is missing, return blocked with its actual diagnostic and mechanism.
On recovery, keep observations, checks, folder, checkpoints, and cumulative caps.
