---
name: execute
description: Run the autonomous task loop after clarify confirms `goal`: dispatch by task type, act, resolve contested decisions, report progress, and end succeeded or failed against `goal`. Use immediately after clarify hands off a confirmed goal.
---

Run the loop after `clarify` confirms `goal`. Do not ask work questions before the run ends `succeeded` or `failed`. Permit only the post-compaction recovery path when the run identity cannot be identified.

Hand back to the user a final pitch and a closed session ledger. Every run ends with exactly one of these outcomes:

- **Succeeded:** `goal`'s succeeded condition is met.
- **Failed, condition met:** `goal`'s failed condition is met because the goal is genuinely undoable.
- **Failed, exhausted:** no unit of work remains and no `goal` condition was literally met.
- **Failed, stopped:** a settlement validation refusal, a missing required dependency, a rejected `session_dir` amendment, a `blocked` spec or spec-review, or a missing permission with no other path. The reason names it.

## Picking up from clarify

Use the `<run-id>` selected after the single settlement initialization. Do not call `init` from `execute`. Accept `<run-id>`, `<engine-root>`, and `<session-dir>` as the absolute directory actually used, whether default or not. Call `recall` first with all three values.

Validate `recall`'s result before doing anything else.

## Workflow

Pick up from `clarify` → `recall` with `<run-id>`, `<engine-root>` and `<session-dir>` → validate the settlement → loop {recall, act on the current node, transition, report, check `goal`} until the run succeeds or fails → prune review slates → final pitch → `close`.

## Settlement validation

After the first recall, run the host adapter's public `session validate`
command before trusting the settlement. The command owns mechanical checks for
the exact v1 `task_type` values, required fields, field shapes, cross-field
invariants, the resolved state machine, and the exact `session_dir`.

On a refusal, follow "Fallbacks" below. Do not reconstruct the checklist or
silently repair the settlement in the skill.

Keep semantic checks in the loop: apply the settled source-of-truth domains,
judge whether the goal is genuinely satisfied or impossible, and preserve the
debate, safety, fallback, and permitted-mutation rules below.

Pass `session_dir` as `--dir <session-dir>` to every session command for
this run, unconditionally.

## Task-type dispatch

`task_type` selects which built-in machine `clarify` resolved into settlement's `state_machine` field. Each node's `reminder.do` states the action and names the skill that does it, and how to call it, if any. Read the current node's `reminder`.

Use `goal`'s succeeded and failed conditions for this run.

For a domain-skill override that is a mapping keyed by sub-task label, pass the label with `<run-id>`, `<engine-root>`, and `<session-dir>`.

## The loop

Recall and goal-check wrap every iteration regardless of which node is current. Act is whatever the current node's `reminder.do` says. Transition fires once that node's work reaches one of its `branches` decisions, which may take several iterations for a large node such as `test-code`. Report happens whenever something worth telling the user happens, independent of node boundaries. Work a debate/resolve node (`spec-debate`, `debate-findings`, ...) like any other node, using `resolve`/`debate` as that node's own `reminder.do` names.

For each iteration, follow these steps:

1. **Recall.** Re-read the settlement and open todos. Run `task state current <run-id> --dir <session-dir>` for this run's node and reminder. Apply the latest valid amendment from the full decisions section. Check for a `[qN]` tag with no closing entry. If one exists, resume it under the public `debate` skill before doing anything else in the iteration. Do not start new work or run goal-check with a debate genuinely open.

2. **Act.** Do the current node's `reminder.do`, calling the skill it names. A node with no `reminder` relies on ordinary prose toward `goal`. Only when that work is about to investigate a domain fact this run does not already have from the ticket, the settlement, or this ledger — current behavior, a convention, a prior decision on the same question, not something already established earlier this run or in an earlier iteration of the same node — invoke `memory-ledger:ledger` with the question first (see "Checking and recording in memory-ledger" below) and use a settled hit instead of re-deriving it. A later iteration of the same multi-iteration node (e.g. `test-code` re-running after a fix) skips this when it has no new fact to investigate. Update todos as work starts and completes:

   ```text
   task session update-todo <run-id> --dir <session-dir> "<text>"
   task session update-todo <run-id> --dir <session-dir> "<text>" --done
   ```

   A debate/resolve node is worked like any other: check the debate threshold, run `resolve`, and run `debate` only if `resolve` escalates. For a reversible, narrow decision below the threshold, first call `deputy:ask` with the decision, its options and its stakes. If `deputy` is not installed, record `no-deputy:not-installed` and continue to the existing path. On `answered`, check that every cited slug is in the candidate list; if so, decide solo with the answer and record it with its cited slugs. On `escalate` or `not-applicable`, use the existing debate threshold path (no question is asked mid-run). Production change, outward send, irreversible action, goal sign-off, or permitted mutations are never sent to `deputy:ask`. Record the decision with its below-threshold basis:

   For `spec-debate`, apply `spec_debate_mode` to the choice claims returned by `spec-review`: `mandatory` resolves every claim, while `threshold` decides below-threshold claims solo and resolves only claims at or above the threshold. Debate always returns through `spec` and `spec-review`.

   ```text
   task session record-decision <run-id> --dir <session-dir> --mode solo --summary "<decision; below-threshold basis>"
   ```

When `resolve`, `debate`, `spec`, or `review` settles a fact that outlives this run (a convention, a root cause, a durable "why," not this run's own todo or PR state), judge whether it belongs in memory-ledger and record the `record-decision` entry with a `ledger:<slug>` citation or an explicit `no-ledger:`/`ledger-worthy-unrecorded:` marker per "Checking and recording in memory-ledger" below. Make this judgment every time, whether or not the plugin is installed.

3. **Transition on an ordinary decision.** Once the current node's work reaches a decision, other than reaching `goal`'s succeeded condition (step 5 handles that one), find the matching destination in its `reminder.branches` and call `transition`:

   ```text
   task state transition <run-id> --dir <session-dir> --to <node> --reason "<why>" [--confirm-leave]
   ```

   Pass `--confirm-leave` when the current node's `reminder.leave` is set, only once the named condition is actually true, never to get past the gate; omit it otherwise. `--to failed` needs no `--confirm-leave`, from any node. Read+merge principles per "Reading and merging principles" below, and state the merged result in the same turn as the `transition` call. Read the printed reminder for the new node before continuing; it is this run's instruction for the next iteration's Act step, not merely a log line.

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

Before using `spec`, `spec-review`, `test`, or `review`:

- Check that the skill is available. If the task type requires a missing dependency, such as `test` for ticket-to-PR, follow "Fallbacks" below.
- Invoke the dependency by its public name.
- Read the skill's actual output. Do not assume it met the request.
- On a `review` outcome of `handoff`, stay at `review` and check the returned claim ids first. Before building a fix that adds a mechanism the signed-off spec does not name (a command, flag, check, guard, node or file), run `resolve` in the `scope and outcome` domain, with the spec as the scope source, or else the ticket or PR. On a settled rejection, the fix is out of scope: do not build it. On an undecided `resolve`, go to `review-debate`. Then transition to the current node's `fix` branch and apply the remaining claim ids there; with none remaining, take the branch that matches the review without them.
- In the `fix` node under `review_fix_mode: auto_within_permitted_mutations`, apply each `fix-now` claim marked `apply` by its patch (`converge render --json` `fix_now`) within `permitted_mutations`, and run the tests and checks; revert the patch of each claim marked `revert` after its failed `fix-check`. Then return to `review`: its next pass, `--since` the previous one, is the patch-only re-review that records each `fix-check`.
- On `comment_only`, report the claims and take the branch that matches the reported outcome.
- Pass `<run-id>`, `<engine-root>`, and `<session-dir>` so the domain skill can perform its override check.
- On a `spec` return of `blocked` (a task step that cannot be derived), transition to `failed` with the missing statement as the reason.
- For `spec-review`, pass the original request/ticket, artifact paths, base commit, project root, and the spec-review visit number `<n>` (the slate id, and from `<n>` >= 3 spec-review's `--pass <n>`). On `blocked`, transition to `failed` with the missing role/coverage or claim IDs and evidence in the reason. Otherwise, when `choices` is non-empty, pass claim IDs, render path, slate, converge directory, and the `revise`, `inline`, `deferred` and `follow-up` lists to `spec-debate`; else, when `revise` is non-empty, pass the same fields to `spec`; else (`ready`), when `inline` is non-empty, pass the `inline` list to `spec`, which applies the patches with no re-review and then takes the implementation/ticket branch; else use the implementation/ticket branch. When leaving, pass `--leave-arg slate=<slate> --leave-arg converge_dir=<converge-dir>`.
- After `review` or `spec-review` returns, and before the run closes, record each returned follow-up claim with `task session update-todo <run-id> --dir <session-dir> "follow-up [<stage>]: <claim text>"`, where `<stage>` is `review` or `spec-review`. The same claim text from a later pass matches the todo already there and adds no second one; a refusal because that todo is marked done means it was settled: skip it. Then mark done (`--done`) each open `follow-up [<stage>]` todo of that stage that the new return no longer lists. Record each returned `deferred` claim the same way as `"deferred [spec-review]: <claim text>"`; mark a `deferred` todo done only after `review` has received it, never because a later return no longer lists it.
- When invoking `review`, append the open `deferred [spec-review]:` todos to the linked-ticket input as a "Deferred spec-review findings" section.
- Under `review_fix_mode: accepted_only`, record each returned `fix-now` claim the same way as `"fix-now [<stage>]: <claim text>"`, never as `follow-up`, and mark done each open `fix-now [<stage>]` todo the new return no longer lists.

## Checking and recording in memory-ledger

`memory-ledger` is a declared dependency; it may still be unconfigured or missing. Reach it through its public name `memory-ledger:ledger`, never its implementation script directly. Preserve its compact capability status: `configured`, `unconfigured`, `broken`, `cooldown`, or `missing`. A missing skill or untrusted host adapter is `missing`, not a configured no-op; record the marker and continue because memory-ledger never gates `goal`.

**Before investigating** a domain fact this run doesn't already have from the ticket, the settlement, or a prior step: ask `memory-ledger:ledger` to look up `<question>`. On a hit, ask `memory-ledger:ledger` to verify it before you act on it — a lookup is never used unverified — then use it instead of re-deriving the fact. Treat no match, or a hit that fails verification, as "not yet settled" and investigate normally. When one iteration's Act step surfaces several distinct facts to look up, ask about all of them in one invocation rather than one round-trip per fact.

**After settling** something that would still be true on a later, unrelated run — a convention, a root cause, a durable "why," not this run's own todo or PR state — judge whether it belongs in memory-ledger:

- **Matching entry exists:** cite its slug instead of restating the rationale. Mark the decision `ledger:<slug>`.
- **No match, skill installed, worth recording now:** ask `memory-ledger:ledger` to record it (it decides shared vs. local, folder, phrasing), then cite the new slug. Mark the decision `ledger:<new-slug>`.
- **No match, skill installed, not worth recording yet** — a fact that's real but too thin, too local to this run, or not yet clearly durable to write as its own entry: keep the rationale inline, as today. Mark the decision `ledger-worthy-unrecorded:<why not yet>`.
- **Skill not installed:** keep the rationale inline, as today. Mark the decision `no-ledger:not-installed`.

In every case, carry the marker into the `record-decision` entry itself (see "Act" above). Decisions only, never pitches — a pitch is a progress report, not the point a fact gets settled.

Never record this run's own decisions, todos, or pitches in memory-ledger — those stay in the session ledger via `record-decision`.

Do not add a versioning scheme to `ledger:<slug>` citations.

## Applying a mid-run amendment

Do not rewrite the settlement. Record a user-requested change as its own decision:

```text
task session record-decision <run-id> --dir <session-dir> --mode solo --summary "AMENDMENT <field>: <old value> -> <new value>, per user request"
```

Prefix the summary with `AMENDMENT <field>`. Name the exact settlement field being changed, such as `permitted_mutations`, `goal`, or `debate_threshold`.

Write structured old and new values in full, using the same shape a human would read back:

```text
AMENDMENT debate_roster: [main-agent, independent-reviewer] -> [main-agent, independent-reviewer, security-reviewer]
AMENDMENT source_of_truth: {scope: ticket} -> {scope: ticket, correctness: tests plus manual QA}
```

Do not write a diff, a field name alone, or prose without the complete value.

To change `state_machine`:

```text
task state show <run-id> --dir <session-dir>
task state amend <run-id> --dir <session-dir> --machine-file <file> --reason "<why>, per user request"
```

Save the YAML that `show` prints below its `MACHINE` line to `<file>`, edit it, then run `amend`. On a refusal, fix every listed problem and rerun `amend`.

Reject an amendment to `session_dir` and end the run as `failed` (see "Fallbacks" below). Report that the ledger location cannot change without a fresh `clarify`/`init`.

Treat an `AMENDMENT <field>` decision as authoritative for that field from the next `recall` onward. Apply the latest valid amendment from a full decisions scan rather than `--last N`.

## Reading and merging principles

Read principles from 3 levels wherever this section is referenced (every `transition` call, the session-start hook, and every delegated decision):

- **task** — the settlement's `principles` field.
- **project** — `.bootgear/config/principles.md`, if present.
- **user** — the host's user-principles file, if present. Do not treat the host's general instruction file as a principles source.

Concatenate all present sources, each labeled `[user]`/`[project]`/`[task]`, in that order, keeping each source's principles in their written order. Do not parse or match by topic. A missing level contributes nothing; it is not an error.

Reconcile any real conflict yourself. Across levels, task overrides project overrides user. Within one level, an earlier principle overrides a later one. Every principle that isn't contradicted applies, from every level. Treat two principles as conflicting only when they impose incompatible requirements on the same concrete decision or action, so satisfying the higher-precedence one necessarily violates the other — not differing emphasis, duplication, compatible additions, or ordinary ambiguity.

When that narrow test finds a real conflict and you resolve it, record it:

```text
task session record-decision <run-id> --dir <session-dir> --mode solo --summary "principles reconciliation: <source> says <X>, <source> says <Y>, cannot both hold; took <winner> per precedence"
```

`<source>` is the level, plus the principle's position when both come from the same level (e.g. `[project] #2`).

Do not use a dedicated mode or marker for this — it is an ordinary `solo` decision.

Do not use `approach` as a principles source.

## Ending the run

Before `close`, succeeded or failed, delete this run's review snapshots, naming each slate of a `review slate <slate> ...` decision once; skip it when there is none:

```text
converge prune <slate> [<slate>...] --project-root <repo root>
```

Call `close` exactly once when the run ends, as the `session close` command that `transition` prints as `next`. For `failed`, set `--reason` to one of:

- the `goal` failed condition, when it was actually met;
- the exhausted-stall gap (step 5's fourth bullet), when every unit of work ran out with no condition literally met;
- the stop reason (Fallbacks), for a validation refusal, a missing required dependency, a rejected `session_dir` amendment, a `blocked` spec or spec-review, or a missing permission with no other path.

Send a final pitch before `close`, naming every open `follow-up [<stage>]` and `fix-now [<stage>]` todo:

- **Succeeded:** State what was done and name the ledger file `close` will write.
- **Failed, condition met:** State what was attempted, the genuinely undoable condition, and the change required to make it reachable.
- **Failed, exhausted:** State what was attempted, the stuck point, and that `goal`'s failed condition does not cover it. Record this as a gap in `goal` to fix before the next run.
- **Failed, stopped:** State what was attempted, the stop reason, and what must change before a new run.

Call `close` for every run. Treat a run without `close` as invalid.

## Calling the session CLI safely

Pass every free-text argument (`--summary`, todo text, pitch text, or `--reason`) as its own quoted argument in every `session.py` call `execute` makes. Never interpolate free text into one shell string.

Pass `--dir <session-dir>` to every `session.py` call for this run, including every command example.

Do not perform a `goal` done-condition mutation absent from `permitted_mutations`. Report the goal requirement and missing permission. Fail the run if no other path can complete it.

## Fallbacks

End each of these as `failed`: call `transition --to failed`, then `close ... failed` with the stated reason (see "Ending the run").

- **Validation refusal:** report the refusal's grouped field-level problems; that refusal is the reason.
- **Missing required dependency:** if the task type requires a missing dependency, such as `test` for ticket-to-PR, report it once and name the dependency as the reason. Do not retry.
- **`session_dir` amendment:** the rejected amendment is the reason.
- **Missing override skill:** if the named override skill is not installed, it is a missing required dependency; report it and name it as the reason. Do not use the general default.

If `memory-ledger` is missing or unconfigured, record its status marker and continue.

If `close` refuses because a question is still open, resume and close the named public `debate` question first, then retry `close`. Never close the ledger with a debate left open.

## Host mechanics

- Resolve `task` to `<plugin-dir>/bin/task`; the wrapper derives its project
  directory from its own location.
- Run `task session validate <run-id> --dir <session-dir>` with the exact run
  and session directory.
- Supply `<plugin-dir>` as `<engine-root>` in the handoff to downstream skills.

When delegating, invoke the domain skills by their plugin-qualified names `spec:spec`, `spec:spec-review`, `test:test` and `review:review`. Do not read skill fields yourself and call that skill instead. Pass `<run-id>`, `<engine-root>`, and `<session-dir>` explicitly.
