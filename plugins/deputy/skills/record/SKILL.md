---
name: record
description: Save a confirmed standing decision. Use when a decision can apply to future cases.
---

## Inputs and outcomes

Take the decision and its scope. Return one result to the caller.

- `run-only` for a one-off.
- `ASSERTED <slug> <answer-id>` after a save.
- `REFUSED` with the CLI diagnostic.
- Deferral if scope, target, or confirmation is missing.

## Procedure

1. For a one-off, record a solo decision in the active Engine run, if present. Return `run-only`.
2. Get Gear from `cli:gear`. Read `<gear> --host <host> deputy deputy index`.
   Compare scope and meaning. Open matches with `candidates "<slug>" --limit 1`.
3. Draft one scoped question and one decision. Reuse matching wording.
   Read [qa-standards.md](../../references/qa-standards.md) before you preview a standing decision.
4. Show the question, decision, and `The user confirmed this canonical decision.`
   Confirm that the rule applies to future cases. For a replacement, show the current answer and request approval.
5. Use the host question tool when the caller permits it.
   If the user corrects the text, check scope and preview it again.
6. Save once after explicit confirmation.

   `<gear> --host <host> deputy deputy record --question "<question>" --claim "<decision>" --confirmed-by-user`

   To reuse a question, add `--entry "<slug>"`.
   For a confirmed replacement, add `--replace "<answer-id>" --previous-claim "<current-answer>"`.

## Rules

Keep the raw reply, reason, options, and stakes out of the record.

## Fallbacks

If lookup fails, report the diagnostic and defer.
If the question tool is missing, ask in conversation when the caller permits it.
If the write succeeds but the commit fails, report the diagnostic. Retry the same confirmed command.
If `cli:gear` is missing, install `cli@bootgear` through the host.

## Host mechanics

Use the absolute path from `cli:gear`. Use `claude` or `codex` for `<host>`.
