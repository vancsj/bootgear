---
name: recall
description: Re-read the session ledger's settlement and open state from disk, never from model context. Use at the start of every engine iteration and whenever settlement is uncertain.
---

Use after compaction, after a stop continuation reminder, at each `execute` iteration start, and whenever a decision needs fresh settlement.
Get the absolute `<session-dir>` from the caller. Gear reads the run id from the environment.
Keep that directory in context and use it for every call. Omit `--dir` for the default directory.
Run this procedure each iteration even when a hook does not remind you about a custom directory.

Hand back to `execute`, `resolve`, `debate`, or the turn that received the reminder:

- **State restored** — effective settlement and manifest permissions, open todos, decisions, recent pitches, and current node reminder. Include the open question ID and latest position per party when applicable. Report an incomplete roster amendment as a gap and keep the last fully valid pair.
- **Validation refusal** — the grouped `session validate` refusal, unchanged.
- **No active run** — the ledger at the supplied path is missing.
- **Recovered ledger** — the user-confirmed existing ledger and its restored state.
- **Terminal node** — the terminal state and its printed close action on an open ledger. Run it after the required pre-close work. A closed run needs no action.

## Read the run

Read the ledger from disk through Gear's public session interface on every call.

```text
<gear> --host <host> engine task session recall
<gear> --host <host> engine task session validate
```

Use recall's settlement, full decisions, open todos, state, current node reminder, and recent pitches. Return a validation refusal before relying on any settlement. Leave repairs to the caller. Use `state show` when the caller needs the effective machine and its version. Use the current node's `do` for the caller's next work. At an open terminal node, follow the printed `session close` command after `execute`'s required closing work.

### Interpret open debates

Use the full decisions from recall. Find the latest genuine `[qN]` debate tag. Check whether that question closed. A `scope-settled` entry closes round 0 only. Never infer the open question from a party's position, an incidental tag in prose, or a truncated history. Take each party's latest recorded real position for the open question. Preserve absence markers for retry and round recovery. Use `session read --question <qid>` when a filtered view helps.

### Apply effective amendments

For every caller, scan all recalled decisions for `AMENDMENT <field>`. Apply the latest valid value per field. Keep the last valid value after an unknown field, invalid shape or value, or broken cross-field invariant. Recheck applicable invariants after each change.

- Use `state show` for machine amendments. Treat an `AMENDMENT session_dir` as a broken ledger. `record-decision` must refuse it.
- Check `debate_roster` and `debate_parties` together on each read. An extension takes one entry per field, in either order. Apply both when valid together. Until then keep the last fully valid pair. Pitch the unfinished pair if it blocks work.
- Check the effective `spec_override`, `test_override`, `review_override`, and `review_fix_mode` before domain dispatch. Manifest `spec_skill`, `spec_review_skill`, `test_skill`, and `review_skill` amendments are records after shape validation. Use the corresponding override for dispatch.

### Read permissions

Read the run manifest from the settlement, including the domain skill fields, `debate_roster`, `debate_admission`, and `review_fix_mode`. The default `spec_review_skill` is `spec-review`. Use the recalled manifest as the authority for permitted capabilities, including after compaction. Treat unlisted debate parties and direct callers as disallowed. Pitch a gap if one is needed. A valid amended domain override authorizes its skill without a parallel manifest change.

Keep recall read-only except for the printed terminal close after required closing work. Leave decisions and todos to `execute`; send disagreements to `resolve` or `debate`.

## Recover the run

- **Known directory, missing ledger:** report no active run at that path.
- **Directory lost:** list the default session directory and look only for the environment's run id. Treat the matching file as a candidate. Read its settlement through Gear and require the stored `session_dir` to match the directory.
- **No local candidate:** ask the user for the absolute custom directory or the location reported by `clarify`. This is the run-identity work-question exception.
- Ask the user to confirm the recovered ledger. Resume it after confirmation. Never substitute another run or reinitialize it.

If a required sibling skill is missing, stop and report `cli:setup` with target `engine`. Resume after setup verifies the required plugins.

## Host mechanics

Use the absolute path from `cli:gear`. Run `<gear> --host <host> engine task <command>`.
Gear reads `CLAUDE_CODE_SESSION_ID` on Claude Code (`claude`) and `CODEX_SESSION_ID` on Codex (`codex`).
If `cli:gear` is missing, install `cli@bootgear` through the host.
