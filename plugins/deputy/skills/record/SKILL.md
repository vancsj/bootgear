---
name: record
description: Save a standing decision when the user confirms it for future cases.
---

## Inputs and outcomes

Inputs: the decision to save and the reason it might apply to future cases.

Return `ASSERTED <slug> <answer>` after a successful save or `REFUSED` with the CLI diagnostic.
If the caller does not allow a confirmation question, defer the save.

## Procedure

1. Call `cli:gear`. Use `<gear> --host <host> deputy deputy index` to read all saved questions.
   If the lookup fails, report the diagnostic and defer the save.
2. Identify the same decision and scope by meaning. Open likely entries with `candidates "<slug>" --limit 1`.
3. Draft one canonical question with its scope and one decision. Use the saved wording when it fits.
4. Show the question, decision, and fixed confirmation sentence.
   Use `The user confirmed this canonical decision.`.
   If replacing an assertion, also show the current answer and ask the user to approve the replacement.
5. Ask for explicit confirmation with the host's normal question tool when the caller permits it.
   If the tool is unavailable, ask for confirmation in the conversation when the caller permits it.
   If the user corrects the preview, show the corrected wording before asking again.
6. Write once after confirmation.

   `<gear> --host <host> deputy deputy record --question "<question>" --claim "<decision>" --confirmed-by-user`

   Add `--entry "<slug>"` when reusing a question.
   For a confirmed replacement, add `--replace "<answer-id>" --previous-claim "<current-answer>"`.
   If the commit fails after the file is written, report the diagnostic. Retry the same confirmed command.

## Rules

- Save only decisions that the user explicitly approves for future cases.
- Do not store the user's raw reply, reason, options, or stakes.
- If scope or the target is unclear, defer the save.
- Read `references/qa-standards.md` for the question and answer rules.

## Host mechanics

Use the absolute path from `cli:gear`. Use `claude` or `codex` as `<host>`.
If `cli:gear` is missing, install `cli@bootgear` through the host.
