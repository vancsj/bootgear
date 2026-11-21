---
name: ledger
description: Look up, record, and verify durable questions and answers. Use for reusable findings, disputed answers, and capability checks.
---

## Inputs and outcomes

Take a question, claim, entry, or capability or hook-event request. Return one result to the caller.

- Settled answer used — slug, answer ID, claim, confidence, and this session's verdict.
- Verdict — `pass`, `fail` with command output, or `not-run`.
- No settled answer — say so. Include the minted slug if you wrote an entry.
- Contested answer — slug and rival answer ID.
- Capability check — one status token. Hook event — only the host envelope.

## Procedure

Get the absolute Gear path from `cli:gear`. Use these commands under `<gear> --host <host> memory-ledger ledger`.

1. Run `resolve "<question or claim>"` before reading or writing. Search all open ledgers by default.
   If a match is unclear, read [judgement.md](references/judgement.md#judge-the-match).
2. For a match, run `show <slug>`. Run every `Evidence:` line and one check that can disprove the full claim.
   Sign the result in the current session. Use `sign --fail --output` for failure.
   Use `refute` to contest a signature. Write a rival when the claim proves narrower than its checks.
   If evidence or signatures disagree, read [judgement.md](references/judgement.md#judge-confidence-and-conflicts).
3. Before writing, confirm that a later session can reuse the answer and rerun its checks. Leave task-only facts with the task.
   Read the open ledgers' rules. Use shared for portable facts, local for machine facts, and deputy for standing decisions.
   If scope or placement is unclear, read [judgement.md](references/judgement.md#choose-a-ledger).
4. Reuse the entry if the question matches. Otherwise use the suggested slug with `new` and `--alt-terms`.
   For a new claim or check, read [judgement.md](references/judgement.md#write-the-claim) and its evidence rules.
5. Sign each verified result and run `save` in the same work session. Use `--no-push` when publication is outside scope.

Use `list --filter "<term>"` for filtered lists, `resolve-roots --json` for roots, and `doctor --json` for status.
Use command help for syntax. For selectors, structured output, or special write cases, read [mechanics.md](references/mechanics.md).
Skip reference sections unrelated to the current operation.

### Capability and hook requests

Return `configured`, `unconfigured`, or `broken` from `doctor --json`.
Return `missing` for a missing or untrusted host hook or skill.
For a hook event, emit a reminder for `nudged` or a status message for `unconfigured` or `broken`.
Emit nothing for `cooldown`.

## Rules

Keep existing answers, checks, and signatures. Use a rival for a corrected answer.
Ask the user before `assert`. Keep secrets and erasable data out.
Read-only roles can use the ledger within their other write limits.

## Fallbacks

Run `doctor` on command failure. For missing roots, direct the user to the memory-ledger setup skill.
If session identity is missing, malformed, or conflicting, report the write refusal and stop.

## Host mechanics

Use `claude` or `codex` for `<host>`. Gear reads session identity from the environment.
To override it, put `--session-id` before the subcommand. A Codex signer is `codex:<full-session-id>`.
If supplied, `--as` must match the signer.
Install a missing `cli:gear` with `/plugin install cli@bootgear` on Claude Code or `codex plugin add cli@bootgear` on Codex.
