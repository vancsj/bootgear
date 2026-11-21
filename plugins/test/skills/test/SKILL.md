---
name: test
description: Write and run test cases, or classify test failures. Use for direct testing or a test stage in Engine.
---

## Inputs and outcomes

Take the change, requirement, or failure output. In Engine, also take `<engine-root>`, `<session-dir>`, and the sub-task label.
Report each sub-task to `execute` in Engine or to the user in standalone use.

- **Cases written:** path and coverage.
- **Run performed:** exact command and actual pass or fail output. State when a run did not occur.
- **Triage:** one classification per failure, with its error text or stack trace and whether it blocks the task.

Engine uses the report for todos and goal checks. Leave the broader completion decision to Engine.

## Procedure

### Select a test skill first

1. In Engine, read `<gear> --host <host> engine task session read --section settlement`.
   Read `test_override` and the full decisions. Use the latest valid `AMENDMENT test_override`.
   - Use a bare skill name for every sub-task.
   - For a mapping, use the exact label from `execute`.
   - If no override or label matches, use the default here. End the search.
2. In standalone use, check for a project test skill for the sub-task. Use it if present.
3. Otherwise, use the default.

Pass active run paths to the override. Require the same report format. Keep an invalid override report visible.

### Write, run, or triage

Use only the requested sub-tasks.

1. **Write cases.** Cover the requested behavior and edge cases. Use the project's framework and conventions.
   If none apply, choose a simple approach and report it.
   If `.bootgear/config/test-standard.md` exists, cite its applicable rule ID for each case.
2. **Run tests.** Run the affected suite. Record the exact command and actual output.
3. **Triage failures.** Use the real output. Classify each as a regression, a flaky or environmental failure, or an incorrect test.
   Cite the error text or stack trace for each classification.
   - If a regression cites a test standard rule, compare its severity with `cutoff`.
   - At or above `cutoff`, mark it blocking. Below `cutoff`, report it as non-blocking.
   - If there is no cited rule or test standard, mark the regression blocking.

## Rules

Scale coverage to risk. For a small change, write a few cases and run the affected tests.
For a large or high-risk change, expand coverage. Run unit tests plus integration or end-to-end tests.
Triage each failure with evidence.

For delegated writing or triage, name the host user-principles file, project principles, and each project standard when present.
Add the settlement's `principles` in Engine. Tell the role to read these rules first.
For a read-only role, name the target and each permitted workflow record.
Allow memory-ledger lookup and writes. Keep role independence and other write limits.

## Fallbacks

If a required sibling skill is missing, stop. Report `cli:setup` for target `test` and resume after it verifies dependencies.

## Host mechanics

Get the absolute path from `cli:gear`. Choose the current host below.
In Engine, keep the caller's `<engine-root>` and `<session-dir>`. Gear reads the run ID from the environment.
Omit `--dir` for `~/.bootgear/session`. Pass `--dir <session-dir>` for a custom directory.

| Host | `<host>` | Install missing CLI |
|---|---|---|
| Claude Code | `claude` | `/plugin install cli@bootgear` |
| Codex | `codex` | `codex plugin add cli@bootgear` |
