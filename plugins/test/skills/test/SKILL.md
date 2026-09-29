---
name: test
description: Write test cases, run them, and read or triage reports. Works standalone and delegates to a project's matching test skill when one exists.
---

Use this skill when a task needs test cases written, tests run, or a failure understood.

## Check for an override first

Before any other action:

1. If running inside an active `engine` run, read the settlement:

   ```text
   task session read <run-id> --section settlement
   ```

   Read `test_override`, then scan the active run's full decisions for an `AMENDMENT test_override`; the latest valid value wins.

   - For a bare `<skill-name>`, use that skill for every sub-task.
   - For a mapping, use the entry matching the exact sub-task label passed by `execute`. Do not infer the label.
   - If the override is absent, or the mapping has no matching label, use this skill's default. Do not search again.

2. If `test` was invoked directly without an active run, check for a project testing skill matching the sub-task. Delegate if one exists.

3. Otherwise, use the default implementation below.

When delegating inside an active run, pass `<run-id>`, `<engine-root>`, and `<session-dir>` using the active run's handoff contract. The override must use the reporting format in "Reporting back". Do not adapt this skill to compensate for an override that does not.

## Default implementation

Use only the sub-tasks required by the request:

1. **Writing test cases.** Given a change or requirement, write cases for the stated behavior and its edge cases. Use the project's existing framework and conventions. If none are evident, choose the simplest reasonable approach and state that choice. If `.bootgear/config/test-standard.md` exists, apply its rule IDs and cite the specific rule for each case.

2. **Running tests.** Run the relevant suite and record the exact command and actual output.

3. **Reading and triaging reports.** Use the actual failure output. Classify each failure as a real regression, a flaky or environmental failure, or an incorrect test. Include the error text or stack trace supporting each classification.

   If a regression cites a `.bootgear/config/test-standard.md` rule, mark it blocking when the rule's severity is at or above `cutoff`, non-blocking (reported but not a blocker) when below. No cited rule, or no `test-standard.md`: treat as blocking.

## Progressive disclosure

For a small change, write a few cases and run the relevant tests.

For a large or high-risk change, expand case coverage, run integration or end-to-end tests as well as unit tests, and triage every failure with its supporting evidence.

## Reporting back

Report each sub-task separately:

- **cases written** — location and coverage.
- **run performed** — exact command and actual pass/fail output. State separately if it was not run.
- **triage** — one classification per failure, with its error text or stack trace, and whether it's blocking (see "Reading and triaging reports"). Never combine failures into one conclusion.

Inside an active `engine` run, this report is input to `execute`'s todo updates and goal check. `test` does not decide whether the broader task is complete.

## Host mechanics

- Resolve the public session command to `<plugin-dir>/bin/task`.
- Pass `<plugin-dir>` as `<engine-root>` in the handoff to this skill.
