---
name: record
description: Record a confirmed canonical decision after the deputy escalates a question.
---

Record one confirmed canonical decision from a deputy escalation.

## Inputs and outcomes

Inputs:

- The question that the user saw.
- The user's reply in this conversation. Use it only to derive canonical wording.
- The options, stakes, and context. Use them only to derive the decision.
- The active Engine session directory.

Outcomes, reported to the caller:

- `VOTED <slug> n=<count>`: a similar question already has this decision. One vote was added.
- `UNCHANGED <slug>`: this session already supports this decision. Nothing changed.
- `RIVAL <slug>`: a different decision was added as a rival. Its votes start at zero.
- `NEW <slug>`: no entry exists for this question. A new entry was written.
- `REFUSED`: no confirmation, remote Deputy root, no Engine summary, no memory-ledger, no session id, failed QA, or failed write.
  Report the CLI message and stop.

## Procedure

1. Call `cli:gear`. Read the current Engine phase with `engine task state current --dir "<engine-session-dir>"`.
2. Derive one clear, general question and one decision from the escalation and context. Do not guess.
3. Build this summary: `Canonical question: <question> | Canonical decision: <decision>`.
4. Build the fixed Because sentence: `The user confirmed this canonical decision.`
5. Show the question, decision, and Because sentence to the user before either write.
6. Arm the one-use Engine marker for the current phase. Use `clarify` only when that is the current phase; otherwise use `execute`.
   The marker stores only its kind and phase.

   `<gear> --host <host> engine task session arm-canonical-record --dir "<engine-session-dir>" --phase <clarify|execute>`

7. Ask one question with header `Record` and prompt `Confirm the canonical record shown above?`.
   On Claude, use `AskUserQuestion`. On Codex, use `request_user_input`.
   Use options `Confirm (Recommended)` and `Correct`.
8. If the user rejects or corrects the preview, write nothing. Derive corrected wording. Arm the one-use marker again for the current phase. Preview it before asking again.
9. If the user confirms, record the same summary in Engine:

   `<gear> --host <host> engine task session record-decision --mode solo --summary "<summary>" --dir "<engine-session-dir>"`

   Then run:

   `<gear> --host <host> deputy deputy record --question "<question>" --claim "<decision>" --session-ledger "<engine-session-file>" --confirmed-by-user`

   Pass each free-text value as its own quoted argument. Report Deputy's outcome line.
10. If Deputy fails after Engine succeeds, retry only Deputy. Do not append the Engine summary again.

## Rules

- The main agent reads the user's confirmation in this conversation.
- The CLI does not capture or validate the user's reply.
- Do not store the user's raw reply, reason, options, or stakes.
- The CLI writes the fixed Because sentence and checks the full Engine summary.
- If one decision is unclear, write nothing and return to the existing resolution path.
- Never record an assertion. Assertions use `deputy.py assert` after user confirmation.

## Host mechanics

Call `cli:gear`. Replace `<gear>` with its absolute path and `<host>` with `claude` or `codex`.
The command reads the session id from the host environment.
The standards file is `references/qa-standards.md` in this plugin.
If `cli:gear` is missing on Claude Code, run `/plugin install cli@bootgear`.
On Codex, run `codex plugin add cli@bootgear`.
