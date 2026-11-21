---
name: recall
description: Restore an Engine run from its ledger. Use at each iteration, after compaction, or when settlement is uncertain.
---

## Inputs and outcomes

Use this skill for stop continuation reminders and every `execute` iteration, even without a hook reminder.
Take the caller's absolute `<session-dir>`. Return one outcome to `execute`, `resolve`, `debate`, or the turn with the reminder.

- **State restored** — effective settlement and manifest permissions, open todos, decisions, recent pitches, and the node reminder.
  For a debate, include its open question ID and each party's latest real position.
  Report an incomplete roster amendment and keep the last valid pair.
- **Validation refusal** — grouped `session validate` refusal, unchanged.
- **No active run** — missing ledger at the known path.
- **Recovered ledger** — user-confirmed ledger and restored state.
- **Terminal node** — terminal state and printed close action for an open ledger. A closed ledger needs no action.

## Procedure

1. Read the ledger from disk on every call. Run `session recall` and `session validate`.
   Return any validation refusal before using settlement. Leave repair to the caller.
2. Use the full decisions, todos, state, reminder, and recent pitches. Follow the current node's `do`.
   Use `state show` for the effective machine and version.
3. Apply the latest valid `AMENDMENT <field>` per field. Recheck the applicable invariants.
   Retain the last valid value after an unknown field, invalid value or shape, or broken invariant.
   - Use `state show` for machine amendments. Treat `AMENDMENT session_dir` as ledger damage. The CLI must refuse it.
   - Check `debate_roster` and `debate_parties` together. Apply an extension only when both entries form a valid pair.
     Accept either order. Keep the last valid pair until then. Pitch an incomplete pair if it blocks work.
   - Before dispatch, check effective `spec_override`, `test_override`, `review_override`, and `review_fix_mode`.
     Validate amended manifest skill fields as records. Use overrides for dispatch.
4. When a debate is open, use the full decisions to locate the latest genuine `[qN]` tag and check closure.
   `scope-settled` closes round 0 only. Ignore incidental tags. Never infer an open question from positions or partial history.
   Read each party's latest real position. Retain absence markers for retries. Use `session read --question <qid>` if needed.
5. Read permitted capabilities from the effective manifest, including after compaction.
   Check domain skills, `debate_roster`, `debate_admission`, and `review_fix_mode`. Default `spec_review_skill` to `spec-review`.
   Disallow unlisted parties and direct callers. Pitch a needed capability gap.
   A valid domain override permits the selected skill without another manifest amendment.

## Rules

Keep recall read-only except for the printed terminal close. Run it after `execute` completes pre-close work.
Leave decisions and todos to `execute`. Route disagreements to `resolve` or `debate`.

## Fallbacks

- If a known path has no ledger, report no active run there.
- If the directory is lost, search the default directory only for the environment's run ID.
  Read the candidate through Gear. Require its stored `session_dir` to match.
- If no candidate matches, ask for the absolute custom directory or the path reported by `clarify`.
- Ask the user to confirm a recovered ledger. Resume it after confirmation. Never substitute or reinitialize a run.
- If a sibling skill is missing, stop and report `cli:setup` for `engine`. Resume after verification.

## Host mechanics

Get the absolute path from `cli:gear`. Run `<gear> --host <host> engine task <command>`.
Keep the caller's directory on each call. Add `--dir` only for a custom directory.
Gear reads `CLAUDE_CODE_SESSION_ID` for `claude` or `CODEX_SESSION_ID` for `codex`.
If the CLI is missing, install `cli@bootgear` through the host.
