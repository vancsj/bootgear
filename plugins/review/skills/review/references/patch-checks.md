# Patch re-review checks

After cutoff on the active patch-only slate, main records each check on the previous slate.

```text
<gear> --host <host> converge converge fix-check <previous-slate> --claim <id> --outcome pass|fail --evidence "<checks and their result>"
```

Record `pass` only if the `fix` node's tests and checks passed and this slate has no finding.
Otherwise record `fail` and mark the claim `revert` in the fix list.
Run `converge cutoff <previous-slate>` to refresh the previous result.
