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
- `NEW <slug>`: a different answer was written as a new entry, beside any recorded answer to the question.
- `REFUSED`: the root has a remote, the session ledger does not contain the answer, `memory-ledger` is not found (`REFUSED memory-ledger not found; install the memory-ledger plugin`), a Codex call has no `--session-id`, or the write failed. Report the message and stop.

## Procedure

1. Run `python3 "$DEPUTY_SCRIPT" record --question "<question>" --claim "<answer>" --because "<reason>" --options "<options>" --stakes "<stakes>" --session-ledger "<session-ledger-file>"`, with the host options from `## Host mechanics`. Pass every free-text value as its own quoted argument.
2. Report the outcome line to the caller.

## Rules

- Record only answers the user gave. The deputy's own answers are not recorded here.
- Never record an assertion. Assertions come only from `deputy.py assert`, after the user confirms.

## Host mechanics

Set `DEPUTY_SCRIPT` to `scripts/deputy.py` in this plugin:

- Claude Code: `DEPUTY_SCRIPT="${CLAUDE_PLUGIN_ROOT}/scripts/deputy.py"`. Add no host options.
- Codex CLI: `DEPUTY_SCRIPT="<directory holding this SKILL.md>/../../scripts/deputy.py"`, as an absolute path. Add `--host codex --session-id <session_id>` to the `record` command, with the `session_id` the host gives you in your context; the shell has no environment variable for it.
