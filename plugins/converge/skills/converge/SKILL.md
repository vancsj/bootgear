---
name: converge
description: Verify factual claims through independent finding, attack, and cutting. Use for artifact review or factual disputes.
---

## Inputs and outcomes

Take the artifact, lenses, find-angle paths, principles, standards, and optional config.
In Engine, take the settlement. The caller can select one refuter or supply a gap-hunt brief.

Return the final render to the caller. Include counts for findings, fix-now, fixed, follow-up, and killed.
Keep finding choices and follow-up statuses and choices. Include fix-now patches and recorded fix checks.

| Outcome | Condition or handback |
|---|---|
| `converged` | No reported finding remains disputed. |
| `unconverged` | List disputed findings. |
| `blocked` | Name the unavailable seat or role and pending claims. |

Follow-ups keep their status and do not change the outcome.
The caller routes choices through deputy, resolve, or debate. A handback adds no mutation or delivery authority.

## Procedure

### Prepare the slate and seats

Use Gear's public `converge converge` commands. Read help for syntax.
Create a slate with the supplied lenses, angles, config, and settlement. For an existing slate, read status and resume.
Follow printed steps and role handoffs.

Before launcher approval, use `config resolve` at the review project. Include its task config when present.
Show the effective finder, r1, and r2 counts. For multiple r2 workers, approve an invitation-aware launcher.
Give `{group}`, `{worker}`, and `{invitation}` as separate whole arguments. Use the retry options Gear prints on refusal.

Use the printed seat mechanisms. Start each native role once and reuse it.
For an advisor, call `advisor:advisor` and follow the printed driver.
Honor deferred startup. Reuse the recorded channel until shared work ends. Act on heartbeat `next` when it stops.

For parallel seats, read the worker assignments from main's `work` output.
When main's work shows finder profiles, use the [routed finder handoff](references/finder-routing.md).
Start each ready worker once with its ID, full assignment, and work command.
Keep the same native worker for a reply handoff. Report a refused launch with its assignment and host diagnostic.
For parallel advisors, use the printed reservation and driver for that worker ID.
Use the listener host returned by Gear. Keep one receipt for its active request.
Close the reserved channels when the outer review ends. Keep them open between visits.

Give each role its artifact, brief, rules, saved evidence, and public work. Tell it to read the principles and standards.
Keep author hypotheses and other roles' reasoning out. Allow assigned action files, own slate events, and memory-ledger use.
Preserve source, artifact, and production write limits.

Fill this part yourself for every new or continued role turn.

```text
Tests already ran:
- latest test: <recorded command>; result: <one recorded result line>
```

Use the latest ledger command and one result line, even if narrow. Keep commands separate. Omit exit code and record path.
Use `none recorded` when absent. Tell roles to skip covered runs and probe uncovered behavior when needed.

### Get current work

Run public `work` with actor, slate, directory, and receiving host.
Use inline work or `--out` for editable actions and a compact work package. Save only in the assigned workflow directory.
An orchestrator supplies the role's receiving host. The advisor uses its own host mechanics.
Read relevant claims, saved angles, evidence, conditions, and actions. Fill evidence or judgment.
Submit action file or stdin through `act`. Refresh after a stale refusal. Report waiting or completion to main.

Parallel workers continue ready actions in the same turn. Use `work --wait` for ordinary waiting.
Report completion, an open finder reply, or a blocked assignment to main.

### Apply the role rules

- **Finder:** check each applicable tell. Search and run a positive control before filing.
  Record coverage or why a tell is absent. Use observed output or complete source paths. Classify reproduced, traced, or inferred.
- **Gap hunter:** find what lenses missed. Record the completion action if Gear offers it, even with zero claims.
  Report completion.
- **Claim finder:** check for higher severity and record the check even if the claim stays the same.
  Use a concrete route to support widening.
  Answer refutations and cuts with new evidence or the applicable acceptance action.
- **Refuter:** assume refuted until checked sources establish the claim. Check applicable table angles and record absent tells separately.
  For fresh eyes, choose unused names, including outside the fixed list. Follow printed cap and completion rules.
  Group clean angles for one claim's current batch. Keep refutations singular.
  Read cited sources. Verify memory-ledger evidence first for deliberate or guarded-elsewhere claims.
- **Cutter:** default to cut. Raise ratings only with evidence. Use saved evaluate definitions, lens policy, and effective difficulty basis.
  Give choice options when facts hold but the remedy needs a decision.

Let the CLI compute phases, role work, cutoff, and eligibility. Give evidence and judgment only.

### Finish

Follow main work and status for cutoff, render, gates, and convergence.
Keep survived, disputed, killed, and unverified status separate from cutoff. Keep follow-ups visible.
For an applied fix-now patch, the caller runs checks and an independent patch review. Record its fix check through the CLI.
After a failed fix check, the caller reverts within its permissions.
Refresh cutoff before handback. Record durable verified facts with `memory-ledger:ledger`. Keep run decisions and todos with the task.

## Rules

Keep finder, refuter, cutter, and main separate. Main must not write another role's evidence or judgment.
Never give a refuter its own claim. Use trusted agents if CLI role checks alone provide insufficient identity assurance.
Keep facts in Converge and remedy choices with the caller.
Keep production changes, outward sends, irreversible actions, goal approval, and mutation permissions out of deputy.
An unavailable advisor cannot be replaced with a native role. Keep all other write limits for read-only roles.

## Fallbacks

If a role or advisor is unavailable, return `blocked` with its diagnostic and pending claims. Do not write its events.
If memory ledger is missing, unconfigured, or broken, report its status and diagnostic. Use checked sources when it cannot help.
For missing siblings, report cli:setup for converge. Resume after setup and restart.

## Host mechanics

Get the absolute path from `cli:gear`. Read only the current host's section.

### Claude Code

Use `--host claude` for Claude commands and `--role-host claude` for Claude work.
Use Agent and SendMessage for native roles. Run the printed advisor background step through Bash.
Install missing `cli@bootgear` through the host.

### Codex

Use `--host codex` for Codex commands and `--role-host codex` for Codex work.
Use clean `spawn_agent` roles and host messaging. Keep advisor terminals visible.
Install missing plugins with `codex plugin add cli@bootgear` or `codex plugin add advisor@bootgear`.
A fresh approval in a headless role makes that role unavailable.
