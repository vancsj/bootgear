---
name: record
description: Record the user's answer to a question the deputy escalated, as a decision the deputy can cite later. Call after the user answers an escalation.
---

Write one decision for the user's answer.

## Inputs

- The question, as the user saw it.
- The user's answer, in their words.
- The reason the user gave, in one line. If none, use `no reason given`.
- The options and the stakes shown to the user.
- The session ledger file that holds this answer. The answer text must appear in it.

## Procedure

1. Run `python3 <plugin-dir>/scripts/deputy.py record --question "<question>" --claim "<answer>" --because "<reason>" --options "<options>" --stakes "<stakes>" --session-ledger "<session-ledger-file>"`. Pass every free-text value as its own quoted argument.
2. Read the output:
   - `UNCHANGED <slug>`: the same answer is already recorded. Nothing was written.
   - `NEW <slug>`: a decision was written and saved.
   - `REFUSED`: the root has a remote, or the write failed. Report the message and stop.

## Rules

- Record only answers the user gave. The deputy's own answers are not recorded here.
- Never record an assertion. Assertions come only from `deputy.py assert`, after the user confirms.
