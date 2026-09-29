---
name: execute
description: Run the autonomous task loop after clarify confirms `goal`: dispatch by task type, act, resolve contested decisions, report progress, and end succeeded or failed against `goal`. Use immediately after clarify hands off a confirmed goal.
---

Run the loop after `clarify` confirms `goal`. Do not ask work questions before the run ends `succeeded` or `failed`. Permit only the post-compaction recovery path when the run identity cannot be identified.

Read `reference.md` § `Required settlement fields` for design rationale.

## Picking up from clarify

Use the `<run-id>` selected after the single settlement initialization. Do not call `init` from `execute`. Accept `<run-id>`, `<engine-root>`, and `<session-dir>` as the absolute directory actually used, whether default or not. Call `recall` first with all three values.

Validate `recall`'s result before doing anything else.

## Settlement validation

After the first recall, run the host adapter's public `session validate`
command before trusting the settlement. The command owns mechanical checks for
the exact v1 `task_type` values, required fields, field shapes, cross-field
invariants, the resolved state machine, and the exact `session_dir`.

Treat a validation refusal as a failed first iteration and report its grouped
field-level problems. Do not reconstruct the checklist or silently repair the
settlement in the skill.

Keep semantic checks in the loop: apply the settled source-of-truth domains,
judge whether the goal is genuinely satisfied or impossible, and preserve the
debate, safety, fallback, and permitted-mutation rules below.

Pass `session_dir` as `--dir <session-dir>` to every session command for
this run, unconditionally.

## Host mechanics

- Resolve `task` to `<plugin-dir>/bin/task`; the wrapper derives its project
  directory from its own location.
- Run `task session validate <run-id> --dir <session-dir>` with the exact run
  and session directory.
- Supply `<plugin-dir>` as `<engine-root>` in the handoff to downstream skills.

When delegating, invoke `spec`, `test`, or `review` by public name. Do not read `spec_skill`, `test_skill`, or `review_skill` yourself and call that skill instead. Pass `<run-id>`, `<engine-root>`, and `<session-dir>` explicitly.

## Reading and merging principles

Read principles from 3 levels wherever this section is referenced (every `transition` call, `session_start_recall.py`, and every delegated decision):

- **task** — the settlement's `principles` field.
- **project** — `.bootgear/config/principles.md`, if present.
- **user** — the host's user-principles file, if present. Do not treat the host's general instruction file as a principles source.

Concatenate all present sources, each labeled `[user]`/`[project]`/`[task]`, in that order. Do not parse or match by topic. A missing level contributes nothing; it is not an error.

Reconcile any real conflict yourself: task overrides project overrides user. Every principle that isn't contradicted applies, from every level. Treat two levels as conflicting only when they impose incompatible requirements on the same concrete decision or action, so satisfying the higher-precedence one necessarily violates the other — not differing emphasis, duplication, compatible additions, or ordinary ambiguity.

When that narrow test finds a real conflict and you resolve it, record it:

```text
task session record-decision <run-id> --dir <session-dir> --mode solo --summary "principles reconciliation: <level> says <X>, <level> says <Y>, cannot both hold; took <winning level> per precedence"
```

Do not use a dedicated mode or marker for this — it is an ordinary `solo` decision.

Do not use `approach` as a principles source.

## Applying a mid-run amendment

Do not rewrite the settlement. Record a user-requested change as its own decision:

```text
task session record-decision <run-id> --dir <session-dir> --mode solo --summary "AMENDMENT <field>: <old value> -> <new value>, per user request"
```

Prefix the summary with `AMENDMENT <field>`. Name the exact settlement field being changed, such as `permitted_mutations`, `goal`, or `debate_threshold`.

Split the old and new values on the first ` -> `. Require neither value to contain ` -> `. Use `becomes` or `changes to` when the real value contains that substring.

Write structured old and new values in full, using the same shape a human would read back:

```text
AMENDMENT debate_roster: [main-agent, independent-reviewer] -> [main-agent, independent-reviewer, security-reviewer]
AMENDMENT source_of_truth: {scope: ticket} -> {scope: ticket, correctness: tests plus manual QA}
```

Do not write a diff, a field name alone, or prose without the complete value.

Change `state_machine` only with `state amend`, never `record-decision`:

```text
task state show <run-id> --dir <session-dir>
task state amend <run-id> --dir <session-dir> --machine-file <file> --reason "<why>, per user request"
```

Save the YAML that `show` prints below its `MACHINE` line to `<file>`, edit it, then run `amend`. On a refusal, fix every listed problem and rerun `amend`.

Reject an amendment to `session_dir` and end the run. Report that the ledger location cannot change without a fresh `clarify`/`init`.

Treat an `AMENDMENT <field>` decision as authoritative for that field from the next `recall` onward. Apply the latest valid amendment from a full decisions scan rather than `--last N`.

## Calling session.py safely

Pass every free-text argument (`--summary`, todo text, pitch text, or `--reason`) as its own quoted argument in every `session.py` call here and in `clarify`, `recall`, `resolve`, and `debate`. Never interpolate free text into one shell string. Read `reference.md` § `Separate session.py arguments`.

Pass `--dir <session-dir>` to every `session.py` call for this run, including every command example.

## Task-type dispatch

`task_type` selects which built-in machine `clarify` resolved into settlement's `state_machine` field. The machine's nodes, not a per-task-type bullet list here, say what the work is: each node's `reminder.do` states the action and names the skill that does it, and how to call it, if any. `execute` does not carry its own separate description of what `ticket-writing`, `bug-triage`, `ticket-to-pr`, or `pr-review` involve; read the current node's `reminder` instead.

`state_machine` is a required settlement field (see "Picking up from clarify"). `clarify` resolves the built-in machine for the exact v1 `task_type`, then applies any project or per-run override before writing the complete machine into settlement.

Use `goal`'s succeeded and failed conditions for this run.

Do not perform a `goal` done-condition mutation absent from `permitted_mutations`. Report the goal requirement and missing permission. Fail the run if no other path can complete it.

For a domain-skill override that is a mapping keyed by sub-task label, pass the label with `<run-id>`, `<engine-root>`, and `<session-dir>`.

If the named override skill is not installed, report the missing skill. Do not use the general default.

## The loop

Recall and goal-check wrap every iteration regardless of which node is current. Act is whatever the current node's `reminder.do` says. Transition fires once that node's work reaches one of its `branches` decisions, which may take several iterations for a large node such as `test-code`. Report happens whenever something worth telling the user happens, independent of node boundaries. There is no separate universal "handle disagreement" step: a debate/resolve node (`spec-debate`, `debate-findings`, ...) is worked the same way any other node is, using `resolve`/`debate` as that node's own `reminder.do` names.

For each iteration, follow these steps:

1. **Recall.** Re-read the settlement and open todos. Run `task state current <run-id> --dir <session-dir>` for this run's node and reminder. Apply the latest valid amendment from the full decisions section. Check for a `[qN]` tag with no closing entry. If one exists, resume it under the public `debate` skill before doing anything else in the iteration. Do not start new work or run goal-check with a debate genuinely open.

2. **Act.** Do the current node's `reminder.do`, calling the skill it names. A node with no `reminder` (`clarify` in `ticket-to-pr.yaml`) relies on ordinary prose toward `goal`. Only when that work is about to investigate a domain fact this run does not already have from the ticket, the settlement, or this ledger — current behavior, a convention, a prior decision on the same question, not something already established earlier this run or in an earlier iteration of the same node — invoke `memory-ledger:ledger` with the question first (see "Checking and recording in memory-ledger" below) and use a settled hit instead of re-deriving it. A later iteration of the same multi-iteration node (e.g. `test-code` re-running after a fix) skips this when it has no new fact to investigate. Update todos as work starts and completes:

   ```text
   task session update-todo <run-id> --dir <session-dir> "<text>"
   task session update-todo <run-id> --dir <session-dir> "<text>" --done
   ```

   A debate/resolve node is worked like any other: check the debate threshold, run `resolve`, and run `debate` only if `resolve` escalates. For a reversible, narrow decision below the threshold, decide solo instead and record it with its below-threshold basis:

   ```text
   task session record-decision <run-id> --dir <session-dir> --mode solo --summary "<decision; below-threshold basis>"
   ```

When `resolve`, `debate`, `spec`, or `review` settles a fact that outlives this run (a convention, a root cause, a durable "why," not this run's own todo or PR state), judge whether it belongs in memory-ledger and record the `record-decision` entry with a `ledger:<slug>` citation or an explicit `no-ledger:`/`ledger-worthy-unrecorded:` marker per "Checking and recording in memory-ledger" below — the judgment happens every time; only the citation depends on the plugin being installed.

3. **Transition on an ordinary decision.** Once the current node's work reaches a decision, other than reaching `goal`'s succeeded condition (step 5 handles that one), find the matching destination in its `reminder.branches` and call `transition`:

   ```text
   task state transition <run-id> --dir <session-dir> --to <node> --reason "<why>" [--confirm-leave]
   ```

   Pass `--confirm-leave` when the current node's `reminder.leave` is set; omit it otherwise, since `transition` refuses the move without it. Only pass `--confirm-leave` once the named condition is actually true, never to get past the gate. Read+merge principles per "Reading and merging principles" below, and state the merged result in the same turn as the `transition` call. Read the printed reminder for the new node before continuing; it is this run's instruction for the next iteration's Act step, not merely a log line.

   Do not transition mid-node. A node whose work spans several iterations (writing tests, running them, fixing a failure, running again) transitions once, when a `branches` destination is actually reached, not once per iteration.

4. **Report periodically.** Report meaningful milestones, blockers, and direction changes directly to the user and record each one:

   ```text
   task session record-pitch <run-id> --dir <session-dir> "<what changed>"
   ```

   Use pitches to report progress. Do not use a pitch to ask a question.

5. **Check `goal`, then transition on the outcome.** End successfully when the succeeded condition is met. End unsuccessfully when the failed condition is met because the goal is genuinely undoable rather than merely unresolved. Continue otherwise.

   If the same next unit of work fails in consecutive iterations with no new information from a pitch, resolve, or debate, re-read the failed condition against that stuck point instead of trying it a third time.

   - When the succeeded condition is met, call `transition --to succeeded` before calling `close succeeded`. `transition` does not itself verify the condition; this check is what makes the call honest.
   - End unsuccessfully with the failed condition as the reason if the stuck point matches it. Call `transition --to failed` before `close failed`.
   - Treat a non-matching stuck point as a gap in `goal`'s failed condition. Report the gap and keep working the next unit toward `goal` if one exists.
   - Call `transition --to failed` then `close ... failed` if no other unit of work remains, even when no `goal` condition was literally met. Give the exhausted-stall gap as the reason: name the stuck point, state that `goal`'s failed condition does not cover it, and record it as a gap in `goal`, not as a genuine match.

## Delegating to `spec`, `test`, and `review`

Before using `spec`, `test`, or `review`:

- Check that the skill is available. If the task type requires a missing dependency, such as `test` for ticket-to-PR, report it once and fail with the dependency named as the reason. Do not retry.
- Invoke the dependency by its public name.
- Read the skill's actual output. Do not assume it met the request.
- On a `review` outcome of `handoff`, stay at `review` and check the returned claim ids first. Before building a fix that adds a mechanism the signed-off spec does not name (a command, flag, check, guard, node or file), run `resolve` in the `scope and outcome` domain, with the spec as the scope source, or else the ticket or PR. On a settled rejection, the fix is out of scope: do not build it. On an undecided `resolve`, go to `review-debate`. Then transition to the current node's `fix` branch and apply the remaining claim ids there; with none remaining, take the branch that matches the review without them.
- On `comment_only`, report the claims and take the branch that matches the reported outcome.
- Pass `<run-id>`, `<engine-root>`, and `<session-dir>` so the domain skill can perform its override check.

## Checking and recording in memory-ledger

`memory-ledger` is a declared dependency; it may still be unconfigured or missing. Reach it through its public name `memory-ledger:ledger`, never its implementation script directly, so `execute` stays ignorant of that skill's own CLI shape. Preserve its compact capability status: `configured`, `unconfigured`, `broken`, `cooldown`, or `missing`. A missing skill or untrusted host adapter is `missing`, not a configured no-op; record the marker and continue because memory-ledger never gates `goal`.

**Before investigating** a domain fact this run doesn't already have from the ticket, the settlement, or a prior step: ask `memory-ledger:ledger` to look up `<question>`. On a hit, verify it per that skill's own "Verifying, on every retrieve you act on" — a lookup is never used unverified — then use it instead of re-deriving the fact. Treat no match, or a hit that fails verification, as "not yet settled" and investigate normally. When one iteration's Act step surfaces several distinct facts to look up, ask about all of them in one invocation rather than one round-trip per fact.

**After settling** something that would still be true on a later, unrelated run — a convention, a root cause, a durable "why," not this run's own todo or PR state — judge whether it belongs in memory-ledger:

- **Matching entry exists:** cite its slug instead of restating the rationale. Mark the decision `ledger:<slug>`.
- **No match, skill installed, worth recording now:** ask `memory-ledger:ledger` to record it (it decides shared vs. local, folder, phrasing), then cite the new slug. Mark the decision `ledger:<new-slug>`.
- **No match, skill installed, not worth recording yet** — a fact that's real but too thin, too local to this run, or not yet clearly durable to write as its own entry: keep the rationale inline, as today. Mark the decision `ledger-worthy-unrecorded:<why not yet>`.
- **Skill not installed:** keep the rationale inline, as today. Mark the decision `no-ledger:not-installed`.

In every case, carry the marker into the `record-decision` entry itself (see "Act" above). Decisions only, never pitches — a pitch is a progress report, not the point a fact gets settled.

Never record this run's own decisions, todos, or pitches in memory-ledger — those stay in the session ledger via `record-decision`.

A `ledger:<slug>` citation names an entry, not the specific answer relied on at citation time; if a later run adds a rival to that entry, the citation itself doesn't say which answer this run actually used. This is a known gap, not something to solve per-run — do not invent a versioning scheme here.

## Ending the run

Before `close`, succeeded or failed, delete this run's review snapshots, naming each slate of a `review slate <slate> ...` decision once; skip it when there is none:

```text
converge prune <slate> [<slate>...] --project-root <repo root>
```

Call `close` exactly once when `goal` resolves:

```text
task session close <run-id> --dir <session-dir> succeeded
task session close <run-id> --dir <session-dir> failed --reason "<the undoable condition that was met>"
task session close <run-id> --dir <session-dir> failed --reason "<the exhausted-stall gap, per step 5's third bullet>"
```

Use one of these two `failed` paths:

- Use the `goal` failed condition when it was actually met.
- Use the exhausted-stall gap when every unit of work ran out with no condition literally met.

Send a final pitch after `close`:

- **Succeeded:** State what was done and name the closed ledger file.
- **Failed, condition met:** State what was attempted, the genuinely undoable condition, and the change required to make it reachable.
- **Failed, exhausted:** State what was attempted, the stuck point, and that `goal`'s failed condition does not cover it. Record this as a gap in `goal` to fix before the next run.

Call `close` for every run. Treat a run without `close` as invalid.

If `close` refuses because a question is still open, resume and close the named public `debate` question first, then retry `close`. Never close the ledger with a debate left open.
