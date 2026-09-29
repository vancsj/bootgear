---
name: recall
description: Re-read the session ledger's settlement and open state from disk, never from model context. Use at the start of every engine iteration and whenever settlement is uncertain.
---

Read the session ledger from disk. Do not reconstruct settlement from context. Read `reference.md` § `recall reference` for rationale.

## When to run it

- Run immediately after compaction.
- The host's lifecycle hook supplies startup, resume, and compaction events;
  compaction follows automatic or manual compaction.
- Run at the start of every `execute` loop iteration.
- The host's stop continuation and fallback direct the next engine iteration
  to `recall` rather than trusting the prior context.
- Run whenever a decision depends on settlement that is not certain word for word.

## Finding the run ID

- Set `<run-id>` to the exact session identity supplied by the host.
- Use the v1 ledger path `<session-dir>/<run-id>.md`.
- Treat `<session-dir>` as the `session-dir` path supplied by the caller.
- Require the caller (`execute`, or whoever else invokes `recall`) to pass `<session-dir>` explicitly on every call.
- Receive `<session-dir>` at the caller's handoff and pass it unchanged on every ledger call.
- Pass `--dir <session-dir>` before reading the ledger.
- Do not attempt to discover `<session-dir>` from `recall`.
- Do not guess `~/.bootgear/session` or any other path when `<session-dir>` is unavailable.
- Do not search for another run.
- Treat a missing file at the specified path as an error.
- Report that no active run exists in this session.

### When `<session-dir>` is lost

- If the caller has no `<session-dir>`, list `~/.bootgear/session/`.
- Match `<run-id>.md` as a default-directory candidate.
- Support both `init` and `init --dir <custom-path>`.
- If the default-directory listing finds nothing, ask the user directly for the absolute `session_dir` path or where `clarify` reported it.
- Use this direct user question as the one documented work-question exception.
- Treat a default-directory filename match as a candidate only.
- Read the found ledger's `session_dir` line in its settlement.
- Require the `session_dir` line to match the directory actually listed.
- Ask the user to confirm that the recovered ledger is the intended run.
- Resume the existing ledger after confirmation.
- Do not start a new `clarify` or `init`.

## What to read

Call the session-ledger script. Do not hand-read its Markdown file with a general file tool.

```text
task session read <run-id> --dir <session-dir> --section settlement
```

- Run this command through the host adapter. Read the settlement, full decisions, open todos, current state, and the last three pitches.
- The full decisions output is required because amendments can appear anywhere in the section.
- Read the run's state machine with `task state show <run-id> --dir <session-dir>`; it prints the machine in force and its version.
- To resume an in-progress `debate`, read the full decisions section once.
- Find the last `[qN]` tag and use it as the current question.
- Do not use `--last N` to identify the current question.
- Do not infer the current question from a party's position.
- Then read the question:

  ```text
  task session read <run-id> --dir <session-dir> --section decisions
  task session read <run-id> --dir <session-dir> --question <qid>
  ```

- Read `task session read <run-id> --dir <session-dir>` with no flags only when auditing the whole run.

Before returning a settlement, run the host adapter's `session validate`
command with the same run and session directory. Return its grouped refusal
unchanged; do not reconstruct or repair a failed validation in the skill.

## Host mechanics

Resolve `task` to `<plugin-root>/scripts/task`; the wrapper derives its
project directory from its own location and honors `PLUGIN_ROOT` when set.
Invoke `session validate` as `task session validate <run-id> --dir
<session-dir>`.

## Current node

```text
task state current <run-id> --dir <session-dir>
```

- Run the command through the host adapter; this step is still required even
  when another output includes the same node.
- Treat its `do` as the current node's instruction, including which skill to call and how.
- On a terminal node of an open ledger, run the `session close` command it prints as `next`.

## Amendments override the settlement

- Every time settlement is read, including outside `execute`'s loop start, read the full decisions section.
- Scan every decisions entry for `AMENDMENT <field>`.
- Do not use `--last N` or `--open-only` to locate an amendment.

```text
task session read <run-id> --dir <session-dir> --section decisions
```

- For each field with one or more `AMENDMENT <field>` entries, apply the most recent new value for the rest of the run.
- Apply amendments for every caller, not only `execute`'s own loop.
- Skip `AMENDMENT state_machine` in this scan: `state amend` already applied it, and `state show` prints the result.
- Require `spec`, `test`, and `review` to check `spec_override`, `test_override`, `review_override`, and `review_fix_mode` before trusting settlement values. See each skill's "Check for an override first".
- Never dispatch from `spec_skill`, `test_skill`, or `review_skill`.
- Dispatch only from the corresponding `_override` field.
- Record `AMENDMENT spec_skill: ...`, `AMENDMENT test_skill: ...`, or `AMENDMENT review_skill: ...` after normal shape validation, but do not use those amendments for runtime dispatch.
- Amend the corresponding `_override` field to change which skill a domain call uses.

Reject an amendment in any of these cases. Keep the last valid value:

- Reject an unknown `<field>` name.
- Reject a new value that fails the settlement shape/value check for that field.
- Reject a new value that breaks a cross-field invariant checked at settlement time.
- Keep the original settlement value or the earlier valid amendment's value after rejection.

- After applying a valid amendment, re-check every cross-field invariant that touches the amended field.
- Check `debate_roster` and `debate_parties` as a pair.
- Record one `AMENDMENT` for each field when extending the pair.
- Record the two amendments in either order.
- When checking either field, scan the full decisions section for an `AMENDMENT` to the other field.
- Re-run the pair check on every read.
- Reject the first amendment until the second exists.
- Apply both amendments together once both exist.
- Treat an incomplete pair as an unfinished amendment, not a broken ledger.
- Keep the original or last fully-valid value when only one half is recorded.
- Pitch an incomplete pair as a gap if it blocks real work.

- Do not amend `session_dir`.
- Require `record-decision` to refuse `AMENDMENT session_dir`.
- Treat any found `AMENDMENT session_dir` as a broken ledger.

## Run manifest after compaction

- Read the run manifest under `--section settlement`.
- Read these manifest fields: `spec_skill`, `test_skill`, `review_skill`, `debate_roster`, `debate_admission`, and `review_fix_mode`.
- Do not use a separate manifest flag.
- Treat the manifest as the authority for skills, agents, and capabilities allowed in the run.
- Do not infer permission from pre-compaction context.
- Treat an unlisted debate party as not permitted.
- Treat an unlisted direct-call admission to `debate` as not permitted.
- Pitch a gap when an unlisted debate party or direct-call admission is needed.
- Treat a valid `AMENDMENT spec_override`, `AMENDMENT test_override`, or `AMENDMENT review_override` as authorization to use that skill.
- Validate the amended override value normally.
- Do not require the amended override value to appear in the manifest's parallel `spec_skill`, `test_skill`, or `review_skill` field.

## What recall is not

- Use `recall` only to re-establish ledger state.
- Do not decide.
- Do not resolve conflicts.
- Do not advance todos.
- Use `execute` to act on the result.
- Use `resolve` or `debate` to handle disagreement.
- Leave the state unchanged when nothing changes.
