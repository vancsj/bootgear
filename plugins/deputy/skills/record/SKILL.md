---
name: record
description: Save an explicitly confirmed standing decision. Use when a decision can apply to future cases.
---

## Inputs and outcomes

Take the decision and its scope. Return one outcome to the caller.

- `run-only` for a one-off.
- `ASSERTED <slug> <answer-id>` after a successful save.
- `REFUSED` with the CLI diagnostic.
- Defer if the scope or target is unclear, or confirmation is unavailable.

## Procedure

1. For a one-off, write a solo decision in the active Engine run, if present. Return `run-only`.
2. Get Gear from `cli:gear`. Read saved questions with `<gear> --host <host> deputy deputy index`.
   Compare scope and meaning. Open matches with `candidates "<slug>" --limit 1`.
3. Draft one scoped question and one decision. Reuse matching wording.
   Check [the QA standards](../../references/qa-standards.md) before the preview.
4. Show the question, decision, and fixed sentence `The user confirmed this canonical decision.`
   Confirm that the rule applies to future cases.
   For a replacement, show the current answer and request approval.
5. Ask with the host question tool when the caller permits it.
   On correction, check scope and preview the new wording.
6. Save once after explicit confirmation.

   `<gear> --host <host> deputy deputy record --question "<question>" --claim "<decision>" --confirmed-by-user`

   Reuse a question with `--entry "<slug>"`.
   For a confirmed replacement, add `--replace "<answer-id>" --previous-claim "<current-answer>"`.

## Rules

Keep the raw reply, reason, options, and stakes out of the record.

## Fallbacks

If the lookup fails, report the diagnostic and defer.
If the question tool is missing, ask in conversation when the caller permits it.
If the write succeeds but the commit fails, report the diagnostic and retry the same confirmed command.
If `cli:gear` is missing, install `cli@bootgear` through the host.

## Host mechanics

Use the absolute path from `cli:gear` and host `claude` or `codex`.
