---
name: record
description: Record the user's answer to a question the deputy escalated, as a decision the deputy can cite later. Call after the user answers an escalation.
---

Write one decision for the user's answer.

## Inputs and outcomes

Inputs:

- The question, as the user saw it.
- The user's answer, in their words.
- The reason the user gave, in one line. If none, use `no reason given`.
- The options and the stakes shown to the user.
- The session ledger file that holds this answer. The answer text must appear in it.

Outcomes, reported to the caller:

- `VOTED <slug> n=<count>`: a similar question already has this answer. One vote was added to it; `n` is the vote count.
- `UNCHANGED <slug>`: this same session ledger's check is already on that answer. Nothing was written.
- `RIVAL <slug>`: a different answer to a recorded question was added to that entry as a rival. Its votes start at zero.
- `NEW <slug>`: no entry exists for this question. A new entry was written.
- `REFUSED`: the root has a remote, the session ledger does not contain the answer, `memory-ledger` is not found (`REFUSED memory-ledger not found; install the memory-ledger plugin`), a Codex call has no session id from `--session-id` or the environment, the entry breaks the Q&A standards in `references/qa-standards.md` (the message names each problem), or the write failed. Report the message and stop.
- `REFUSED`: the root has a remote, the session ledger does not contain the answer, `memory-ledger` is not found (`REFUSED memory-ledger not found; install the memory-ledger plugin`), a Codex call has no session id from `--session-id` or the environment, or the write failed. Report the message and stop.

## Procedure

1. Call `cli:gear`, then run `<gear> --host <host> deputy deputy record --question "<question>" --claim "<answer>" --because "<reason>" --options "<options>" --stakes "<stakes>" --session-ledger "<session-ledger-file>"`. Pass every free-text value as its own quoted argument.
2. Report the outcome line to the caller.

## Rules

- Record only answers the user gave. The deputy's own answers are not recorded here.
- Never record an assertion. Assertions come only from `deputy.py assert`, after the user confirms.

## Host mechanics

Call `cli:gear`. Replace `<gear>` with its literal absolute path in each tool call.
Replace `<host>` with `claude` or `codex`, based on the current host.
The standards file is `references/qa-standards.md` in this plugin.
If `cli:gear` is missing on Claude Code, run `/plugin install cli@bootgear`. On Codex, run `codex plugin add cli@bootgear`.
For Codex without hook context, add `--session-id <session_id>` with the full host session ID.
If `--session-id` is omitted, the command uses `BOOTGEAR_SESSION_ID`, then `CLAUDE_CODE_SESSION_ID`.
Host hooks supply shared host and session context.
Without hook context, pass explicit host and session options to `record`.
