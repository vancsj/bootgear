---
name: ledger
description: Look up, record, and verify durable questions and answers. Use for settled facts, reusable findings, rival answers, or capability checks.
---

## Inputs and handback

Take a question, claim, entry to verify or contest, or a capability or hook-event request.
Return one result to the caller.

- Settled answer used — slug, answer id, claim, confidence, and this session's verdict.
- Verdict — `pass`, `fail` with the command output, or `not-run`.
- No settled answer — say so. Include the minted slug if you wrote an entry.
- Contested answer — slug and rival answer id.
- Capability check — one status token. Hook event — the host envelope only.

## Procedure

### Look up and verify

1. Get the absolute Gear path from `cli:gear`. Resolve the question before reading or writing an entry.
2. If the question matches, run `show`. Run every Evidence line and one broader check before relying on the answer.
3. Sign your result. Use `sign --fail --output` for a failing check, or `refute` to contest a signature.
   Use `rival` when the claim is narrower than its checks.

### Write and save

1. Check that a later task can use the answer and rerun its checks. Keep task-only Q&As out of the ledger.
2. Check all open ledgers and read their rules. Choose shared, local, or deputy storage for the lasting scope.
3. Use the existing entry for a matching question. Otherwise use `new` with `--alt-terms`.
4. Sign the verified result with the current AI session. Run `save` in the same working stretch.

Read `references/judgement.md` for ledger choice, matches, evidence, and signature disputes.
Read `references/mechanics.md` before a write or when a flag, path, or output shape needs checking.

### Commands

```text
<gear> --host <host> memory-ledger ledger resolve "<question or claim>"
<gear> --host <host> memory-ledger ledger show <slug>
<gear> --host <host> memory-ledger ledger list --filter "<term>"
<gear> --host <host> memory-ledger ledger doctor --json
<gear> --host <host> memory-ledger ledger resolve-roots --json
```

Use command help when a form is absent or output leaves the syntax unclear.

### Capability status

Return the status from `doctor --json`, namely `configured`, `unconfigured`, or `broken`.
For a missing or untrusted host hook or skill, return `missing`.
For hook events, emit a reminder for `nudged` and a status message for `unconfigured` or `broken`.
Emit nothing during `cooldown`.

## Rules

Use a rival to correct an answer. Keep its existing answer, checks, and signatures intact.
Ask the user before `assert`. Keep secrets and erasable data out.
Read-only roles may look up and record entries within their other write limits.

## Fallbacks

Run `doctor` first when a command fails. If roots are missing, tell the user to run the memory-ledger setup skill.
If missing, malformed, or conflicting session identity blocks a write, report the refusal and stop.
If `cli:gear` is missing, use `/plugin install cli@bootgear` on Claude or `codex plugin add cli@bootgear` on Codex.

## Host mechanics

Use `claude` or `codex` for `<host>`. Gear sets the host and reads session identity from the environment.
The optional `--session-id` before the subcommand overrides it.
A Codex signer is `codex:<full-session-id>`. If supplied, `--as` must match.
