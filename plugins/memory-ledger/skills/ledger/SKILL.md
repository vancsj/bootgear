---
name: ledger
description: Append-only ledger of settled questions, rival answers, and the evidence check behind each — signed per AI session so consensus accumulates across runs, split across a shared team ledger and a machine-local one. Use when looking up whether something was already settled, recording a durable finding about the codebase or business, or verifying and contesting an existing entry. Not general note-taking.
---

## When to use, inputs and handback

Use this skill when a question may already be settled, when recording a durable
finding, or when verifying or contesting an existing entry.

Inputs: a question or claim, an entry to verify or contest, or a capability-status
or hook-event request.

Hand back to the caller:

- settled answer used → its slug, answer id `aN`, claim, `conf`, and this
  session's verdict (`pass`, `fail` with the output it printed, or `not-run`);
- no settled answer → say so, with the minted slug if you wrote a new entry;
- answer contested → the slug and the rival's answer id;
- capability status → one status token (see "Capability status");
- hook event → the host envelope only (see "Capability status").

## Workflow

resolve → same-question hit: `show`, run every `Evidence:` line plus one
zoom-out check → `sign`, `sign --fail --output`, or `refute`; a claim narrower
than its checks → `rival` → no hit or a different question: read both ledgers'
`rules`, choose a ledger → `new` (with `--alt-terms`) → `save` → hand back.

1. Read `references/mechanics.md` before the first command or whenever a flag,
   path, or output shape needs checking.
2. Resolve the question before reading or writing an entry.
3. Read the selected answer and run every listed evidence check before using it.
4. Read each ledger's rules (`rules`), then choose shared or local storage from
   the question's lasting scope; read both ledgers before writing to one.
5. Add a rival instead of editing an answer, evidence line, or signature bytes.
6. Sign the verified result with the current AI session.
7. `save` in the same working stretch, then hand back.

Read `references/judgement.md` when choosing a ledger, interpreting a match,
writing a check, verifying a signature, or resolving disagreement.

### Capability status

For capability status, run `doctor --json` and return its compact `status`:
`configured`, `unconfigured`, or `broken`. A host skill or hook that is absent
or untrusted is `missing`; do not report `cooldown` or `ledger-used` as missing.
For a hook event, return only the host envelope: a reminder for `nudged`, a
status message for `unconfigured` or `broken`, and no output for `cooldown` or
`ledger-used`.

## Rules

- Append-only: correct an answer with a rival, never an edit.
- The signatory is the AI session, never the human.
- Ask the human before `assert`.
- Never put secrets or erasable data in a ledger.
- Not general note-taking: an entry is a settled question with re-runnable checks.

## Fallbacks

- Anything off → `doctor` first.
- Roots missing or unset → tell the user to run the memory-ledger setup skill.
- Codex session identity missing, malformed or conflicting → the write is
  refused; pass the exact identity (see "Host mechanics").

## Host mechanics

Claude command entrypoint: `${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py`. `sign`
takes the signatory from `CLAUDE_CODE_SESSION_ID`.

Codex command entrypoint: `${PLUGIN_ROOT}/scripts/ledger`. Pass the exact
host session identity with `--host codex --session-id <session_id>` and the
matching `--as codex:<session_id>` on writes.
