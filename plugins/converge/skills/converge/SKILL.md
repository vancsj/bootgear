---
name: converge
description: Settle factual claims through independent finding, attack, and cutting over a validated slate. Use for artifact review or disputed facts.
---

## When to invoke, inputs, and handback

Use when a caller needs factual claims checked before acting.
Inputs: the artifact, lenses, find-angle files, applicable principles and standards, and optional task configuration.
An Engine caller also supplies its settlement for slate creation.
The caller can select one refuter or supply a gap-hunt brief.

Return the final render to the calling skill or standalone user.
Include finding, fix-now, fixed, follow-up, and killed counts.
Keep every finding's choice and every follow-up's status and choice.
Include fix-now patches and recorded fix checks.
Return exactly one outcome:

- `converged`: no reported finding remains disputed.
- `unconverged`: list the disputed findings.
- `blocked`: name the unavailable role or seat and its pending claims.

Follow-up claims keep their status. They do not change the outcome.
The caller decides choices through `deputy:ask`, resolve, or debate under its own workflow.
This handback grants no delivery, production, outward-send, or artifact mutation permission.

## Procedure

### Prepare the slate

Call `cli:gear` and use its absolute executable path.
Use registered `converge converge` commands through Gear.
Create a slate with the supplied lenses, angles, configuration, and settlement.
For an existing slate, read public status and continue it.
Use CLI help for arguments and accepted values.
Follow the printed normal steps and role handoffs.

### Allocate roles

Use the seat mechanisms printed by the CLI.
Start each native role once and reuse it for later work.
For an advisor seat, invoke `advisor:advisor` and follow the printed driver.
Honor deferred startup and reuse the recorded channel.
Keep the advisor channel open while tasks sharing its context remain.
Run a heartbeat task's printed next step when that task ends.

Give each role only its artifact, role brief, applicable rules, saved evidence, and current public work.
Tell the role to read the supplied principles and standards.
Keep private author hypotheses and another role's private reasoning out of the brief.
Allow memory-ledger lookup and record, including for read-only roles.
Preserve source, artifact, and production write limits.
Allow task action files and the role's own Converge events.

Before every new or continued role turn, fill this context by hand:

```text
Tests already ran:
- latest test: <recorded command>; result: <one recorded result line>
```

Use the latest test command recorded in the run ledger, even when its scope is narrow.
Include no exit code or record path. Do not combine separate commands.
Use `none recorded` when no result exists.
Tell roles to skip covered runs and probe uncovered behavior when needed.

### Obtain current work

Each role runs public `work` with its actor, slate, directory, and explicit receiving host.
Read inline work, or use optional `--out` to save editable actions and a compact work package.
Save output only in an assigned workflow directory outside the target artifact.
An orchestrator preparing another role's work supplies that receiving role's host.
An advisor listener uses its own host mechanics.
Read the package's relevant claims, saved angle definitions, evidence, conditions, and valid actions.
Choose an action, fill its evidence or judgment, and submit its file or stdin through `act`.
Refresh work after a stale-action refusal.
Report a waiting or completed role to main.

### Apply role judgment

- Finder: test each applicable tell. Search and run a positive control before filing supported claims.
  Record find coverage or an absent-tell reason. Use observed output or complete source hops as evidence.
  Classify evidence as reproduced, traced, or inferred.
- Gap hunter: find what the supplied lenses missed. Report when the search is complete.
- Claim finder: test whether a claim can be more serious. Record the escalation check even without widening.
  Support widening with a concrete route. Answer refutations and cuts with new evidence or the applicable acceptance action.
- Refuter: treat the claim as refuted unless checked sources establish it.
  Check each applicable table angle. Record absent tells separately.
  For fresh-eye work, choose unused names, including names outside the fixed list.
  The fixed list is not a menu. Follow the printed cap and completion conditions.
  Group checked clean angles for one claim's current batch. Keep refutations singular.
  Read every cited source. For deliberate or guarded-elsewhere claims, verify the relevant memory-ledger evidence first.
- Cutter: default to cutting. Raise a rating only when evidence supports it.
  Apply the saved evaluate definitions, lens policy, and effective difficulty basis.
  Name decision options when facts hold but the remedy needs a choice.

Let the CLI compute normal phases, role work, cutoff, and eligibility.
The agent supplies evidence and judgments. It must not assert computed eligibility.

### Finish and hand back

Follow public main work and status for cutoff, render, gates, and convergence.
Keep survived, disputed, killed, and unverified status separate from cutoff results.
Keep follow-up claims visible.
For each applied fix-now patch, the applying caller runs checks and an independent patch review.
It records the resulting fix check through the public CLI.
On a failed fix check, the caller reverts the patch under its own permission.
Refresh cutoff before the final handback.

Record durable, verified facts through `memory-ledger:ledger`.
Keep run decisions and todos in task records.
Return the handback defined above.

## Judgment rules and safety

- Keep finder, refuter, cutter, and orchestrator responsibilities separate.
- Main never records another role's evidence or judgment.
- Never give a refuter a claim it filed.
- A factual dispute stays in Converge. A remedy choice belongs to the caller's decision workflow.
- Never delegate production changes, outward sends, irreversible actions, goal approval, or permitted mutations to the deputy.
- CLI role checks prevent accidental self-judging. Use trusted agents when stronger identity guarantees are needed.
- Never replace an unavailable advisor seat with a native role.
- Read-only roles may write memory-ledger entries. Their other write limits remain.

## Fallbacks

If a required role or advisor mechanism is unavailable, return `blocked` with its diagnostic and pending claims.
Never write that role's events yourself.
If memory-ledger is missing, unconfigured, or broken, include its status and diagnostic in the handback.
Continue from checked sources when memory-ledger cannot supply evidence.
If a required sibling skill is missing, run `cli:setup` for target `converge`, then retry.
Do not call another plugin's private scripts.

## Host mechanics

### Claude Code

Use Gear's `--host claude` for commands executed by Claude Code.
Use `--role-host claude` for work Claude Code receives.
Spawn native roles with the Agent tool. Continue them with SendMessage.
Run an advisor seat's printed background step through the Bash tool.
If `cli:gear` is missing, install `cli@bootgear` through the plugin interface.

### Codex

Use Gear's `--host codex` for commands executed by Codex.
Use `--role-host codex` for work Codex receives.
Spawn clean native roles with `spawn_agent`. Continue them with the host messaging tool.
Leave advisor terminal sessions visible while they run.
If `cli:gear` is missing, run `codex plugin add cli@bootgear`.
If `advisor:advisor` is missing, run `codex plugin add advisor@bootgear`.
Treat a fresh approval requirement in a headless role as an unavailable role.
