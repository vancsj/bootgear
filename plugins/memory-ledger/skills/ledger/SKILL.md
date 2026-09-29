---
name: ledger
description: Append-only ledger of settled questions, rival answers, and the evidence check behind each — signed per AI session so consensus accumulates across runs, split across a shared team ledger and a machine-local one. Use when looking up whether something was already settled, recording a durable finding about the codebase or business, or verifying and contesting an existing entry. Not general note-taking.
---

Use this skill when a question may already be settled, when recording a durable
finding, or when verifying or contesting an existing entry.

1. Read `references/mechanics.md` before the first command or whenever a flag,
   path, or output shape needs checking.
2. Resolve the question before reading or writing an entry.
3. Read the selected answer and run every listed evidence check before using it.
4. Choose shared or local storage from the question's lasting scope; read both
   ledgers before writing to one.
5. Add a rival instead of editing an answer, evidence line, or signature bytes.
6. Sign the verified result with the current AI session.

Claude command entrypoint: `${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py`.

Codex command entrypoint: `${PLUGIN_ROOT}/scripts/ledger`. Pass the exact
host session identity with `--host codex --session-id <session_id>` and the
matching `--as codex:<session_id>` on writes.

Read `references/judgement.md` when choosing a ledger, interpreting a match,
writing a check, verifying a signature, or resolving disagreement.

For capability status, run `doctor --json` and return its compact `status`:
`configured`, `unconfigured`, or `broken`. A host skill or hook that is absent
or untrusted is `missing`; do not report `cooldown` or `ledger-used` as missing.
For a hook event, return only the host envelope: a reminder for `nudged`, a
status message for `unconfigured` or `broken`, and no output for `cooldown` or
`ledger-used`.
