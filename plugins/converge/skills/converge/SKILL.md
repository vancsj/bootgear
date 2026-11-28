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

Get Gear through `cli:gear`. Initialize the coordination store once.
Open a slate with Converge `init`. Pass the lenses, angles, config, and settlement that apply.
For an active slate, use `status` and resume it.

Use the returned seats, invitations, and native profiles. Give each invitation only to its participant.
Use native model and effort profiles as guidance. Keep each participant for its reply work.
Use `advisor:advisor` for an advisor seat. Follow status when it shows ready work and a launch command.
Give the requester's approved command the seat invitation. The configured count is the maximum number of advisor seats.
Keep advisor seats while the outer review has more visits. Release them when the review ends.
If a participant disconnects, try to resume it before replacing its stale seat.
Use the new invitation to give the replacement the same seat.

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

Join the assigned seat. Run the same coordination poll as main and the other roles.
Use the assignment's evidence, angles, and action inputs. Fill only evidence and judgment fields.
Keep the seat heartbeat active while you work.
Submit each action through Converge `act`. Poll after a stale action refusal.
Complete the assignment even when the work found zero claims. Poll again for work or results.
Acknowledge each delivery on the next poll. Report blockers through the coordination command.

### Apply the role rules

- **Finder:** check each applicable tell. Search and run a positive control before filing.
  Record coverage or why a tell is absent. Use observed output or complete source paths. Classify reproduced, traced, or inferred.
- **Gap hunter:** find what lenses missed. Complete the assignment even with zero claims.
  Handle finder replies for your own gap-hunt claims.
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

Follow main poll and status for cutoff, render, gates, and convergence.
Keep survived, disputed, killed, and unverified status separate from cutoff. Keep follow-ups visible.
For an applied fix-now patch, the caller runs checks and an independent patch review. Record its fix check through the CLI.
After a failed fix check, the caller reverts within its permissions.
Finish the slate after the gate and handback. Record durable facts with `memory-ledger:ledger`. Keep run decisions and todos with the task.

## Rules

Keep finder, refuter, cutter, and main separate. Main must not write another role's evidence or judgment.
Never give a refuter its own claim. Use trusted agents if CLI role checks alone provide insufficient identity assurance.
Keep facts in Converge and remedy choices with the caller.
Keep production changes, outward sends, irreversible actions, goal approval, and mutation permissions out of deputy.
Keep the settled seat mechanism when you replace a participant. Keep all other write limits for read-only roles.

## Fallbacks

For an optional launch failure, run `fallback` with the affected seat and its diagnostic.
Use the native invitation the command returns. Report the advisor gaps from status.
Pass `--require-advisor` at init if the task requires external coverage.
Report a blocked wait with the seat and assignment. Resume or replace the participant before retrying.
If a required participant is unavailable, return `blocked` with its diagnostic and pending claims.
If memory ledger is missing, unconfigured, or broken, report its status and diagnostic. Use checked sources when it cannot help.
For missing siblings, report cli:setup for converge. Resume after setup and restart.

## Host mechanics

Get the absolute path from `cli:gear`. Read only the current host's section.
Run one Gear command per Bash tool call. A literal `cd` path can precede Gear.

### Claude Code

Use `--host claude` for Claude commands.
Use Agent and SendMessage for native roles. Run waits and heartbeats through Bash.
Run main waits as background Bash tasks. Use the task completion notification.
Install missing `cli@bootgear` through the host.

### Codex

Use `--host codex` for Codex commands.
Use clean `spawn_agent` roles and host messaging. Keep advisor terminals visible.
Run main waits and advisor polls as background tool calls. Collect their output and notify main.
Install missing plugins with `codex plugin add cli@bootgear` or `codex plugin add advisor@bootgear`.
A fresh approval in a headless role makes that role unavailable.
