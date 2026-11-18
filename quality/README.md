# Quality checks

Run the locked quality gate from the repository root:

```text
uv run --project quality --locked python quality/check.py
```

It runs the content check, Ruff, BasedPyright, and every plugin's test tree.
The Engine, Converge, spec, and review suites each run with
`BOOTGEAR_TEST_HOST=claude` and `BOOTGEAR_TEST_HOST=codex`.
Native adapter cases retain their distinct host contracts.

The content check (`check_content.py`) rejects home-directory and scratchpad
paths, `docs/` pointers from code or skills, development-diary phrases, and
any term listed in the optional local denylist. The denylist lives outside the repo, at
`~/.bootgear/content-denylist.txt` or the path in
`BOOTGEAR_CONTENT_DENYLIST`, one term per line, so private terms are never
committed.

Ruff and BasedPyright failures are reported as `BASELINE` only when their
normalized output matches `baseline.json` and its lock/config identity. New
failures, missing tools, malformed baselines, and stale identities return a
non-zero status.
