# Patch re-review checks

After cutoff on the patch-only slate, record a check on the previous slate for each applied `fix-now`.
Act as that slate's main agent.

```text
<gear> --host <host> converge converge fix-check <previous slate> --dir <converge-dir> --as main --claim <id> --outcome pass|fail --evidence "<checks run and their result>" --review-slate <slate>
```

Record `pass` only if the `fix` node's tests and checks passed and this slate has no finding.
Otherwise record `fail` and mark the claim `revert` in the fix list.
Rerun `converge cutoff` on the previous slate.
