---
name: execute
description: Run the settled Engine workflow. Use after clarify hands off a confirmed goal.
---

## Inputs and outcomes

Take the confirmed `goal`, `<engine-root>`, and absolute `<session-dir>` from `clarify`.
Use `recall` first. Never initialize a run here.
Return a final pitch and closed ledger to the user.

- **Succeeded** — the success condition holds.
- **Failed, condition met** — the failure condition holds and the goal cannot be reached.
- **Failed, exhausted** — no unit of work remains and neither condition holds.
- **Failed, stopped** — name the validation refusal, missing dependency, identity amendment, blocked spec or review, or missing permission.

## Procedure

### Start or resume

Honor settled `advisor_roles.startup` and `launcher`. Pass them unchanged to debate and Converge.
Use recorded early pairings. Let the consumer start a deferred listener at its first advisor task.
Record each pairing with `session record-decision` in `solo` mode, as `advisor channels: r2=<n>, debate=<m>`.
Preserve the other channel. On a stale peer, use the consumer's unavailable outcome. Never start a replacement.
Keep direct dispatch unchanged.

### Run each iteration

1. **Recall.** Use `recall` with both run paths. Resume a genuinely open debate before work or goal checks.
   Use `state current` for the reminder, legal destinations, and exit gates.
2. **Act.** Follow the current `do`, or work toward `goal` if absent.
   Use `session update-todo` when work starts or ends. Check new facts through the memory-ledger rules below.
   Apply `debate_mode` when `do` names it. In `mandatory`, resolve every choice.
   In `threshold`, decide lower choices solo and resolve choices at or above `debate_threshold`.
   Debate only if `resolve` escalates an unresolved choice at or above the threshold.
   Follow printed branches from `spec-debate` through `spec` and `spec-review`.
3. **Report.** Use `session record-pitch` for milestones, blockers, and changes of direction. Keep questions out.
4. **Check the goal.** End only on success, failure, or the stopped path in Fallbacks.
   After two failures of the same step without new pitch, resolve, or debate information, reassess.
   If the failed condition holds, use it. Otherwise report the gap and try another unit.
   If no unit remains, fail as exhausted. Record the stuck point and the gap in `goal`.
5. **Transition.** Verify the branch decision and leave conditions. Use `state current` and `state transition --help`.
   Supply only the selected exit's check inputs and confirm its leave condition.
   Check the goal independently of flags and gates. Merge and state principles in the same turn.
   Read the next reminder. At a terminal node, do the closing work before the printed close command.

For a narrow, reversible choice, give `deputy:ask` the question, options, and stakes.
Use an `answered` result only if every cited slug matches a candidate. Record the slugs and below-threshold basis as `solo`.
On a failed citation check, `escalate`, or `not-applicable`, use the threshold without asking.
If deputy is absent, record `no-deputy:not-installed` and continue.

### Dispatch the current node

Use the machine's `do` to choose the work and skill. Check the required skill and invoke its public name.
Pass `<engine-root>` and `<session-dir>`. For a mapped override, pass the sub-task label. Each skill selects its override.
Read the actual handback. For spec calls, pass any node `stop_after` on every call, including re-entry.

Require the author check before independent review on an authoring path.
Follow the printed reminders. Read only the section for the active handoff.

- For author review or renewal, use [Authoring and independent review](references/handoffs.md#authoring-and-independent-review).
- For spec-review dispatch or a blocked spec, use [Required checkpoints and spec review branches](references/handoffs.md#required-checkpoints-and-spec-review-branches).
- For review claim handback or fixes, use [Review claims and fixes](references/handoffs.md#review-claims-and-fixes).
- For a contract gap or repeated finding, use [Contract gaps and repeated rounds](references/handoffs.md#contract-gaps-and-repeated-rounds).
- For artefact assessment or challenge, use [Artefact review](references/handoffs.md#artefact-review).

### Check durable facts

Use only the public `memory-ledger:ledger` skill. Before new investigation, look up facts absent from the ticket, settlement, and earlier work.
Group one iteration's questions. Verify any hit before using it. On no match or failed verification, investigate.
Retain status `configured`, `unconfigured`, `broken`, `cooldown`, or `missing`. A missing or untrusted adapter is `missing`.
Memory ledger status never gates `goal`.

After resolve, debate, spec, or review settles a fact, decide if it is durable, even when the skill is missing.
Use these markers in `session record-decision`, outside pitches.

| Status | Action |
|---|---|
| Entry exists | Cite `ledger:<slug>` instead of repeating rationale. |
| New durable fact | Ask the skill to place and write it. Cite `ledger:<new-slug>`. |
| Worth keeping inline for now | Record `ledger-worthy-unrecorded:<why not yet>` and the reason. |
| Skill absent | Record `no-ledger:not-installed` and the reason inline. |

Keep run decisions, todos, and pitches in the run ledger. Do not add versions to citations.

### Merge principles and brief roles

At each transition, session start hook, and delegated decision, read the sources below when present.
Concatenate them in written order. Label each level.

| Label | Source |
|---|---|
| `[user]` | Host user-principles file, separate from general instructions. |
| `[project]` | `.bootgear/config/principles.md`. |
| `[task]` | Settlement `principles`. |

Apply every compatible rule. A conflict requires incompatible demands on the same concrete decision or action.
Task wins over project, then user. Within a level, earlier wins. Do not sort or match rules by topic.
For a conflict, record `solo` with `principles reconciliation: <sources>, <conflict>, <winner>`.
Give the level and, for a same-level conflict, each rule's position.
Keep `approach` out of principles.

At the same triggers, read existing `.bootgear/config/review-standard.md` and `.bootgear/config/test-standard.md` in full.
Skip a file already in context. The hook names both. Keep them separate from principles.

For every writing or judging subagent, including `impl`, name these files and add settlement principles.
Tell it to read the files first. Give it only needed context. Keep other roles' conclusions private.

### Close

1. At a terminal node, prune review snapshots with `converge prune` and the project root.
   Name each slate from `review slate <slate> ...` decisions once. Skip if none exist.
2. Send a final pitch with open `follow-up [<stage>]`, `fix-now [<stage>]`, and `deferred [spec-review]` todos.
   - For success, name the work and ledger.
   - For condition met, name attempted work, the failed condition, and what would make the goal reachable.
   - For exhaustion, name attempted work, the stuck point, and the gap in the failed condition.
   - For a stop, name attempted work, reason, and what a new run needs.
3. Run the `session close` action from `state transition` or `state current` once.
   On an open-question refusal, resume and close it through `debate`, then retry.

## Rules

Use the normal CLI next action for transitions. Use `state transition --force --reason` only for an authorized gate bypass.
Preserve run, destination, role, and ledger validation. Report the reason, destination, and bypassed controls.
Keep artifact and delivery permissions in `permitted_mutations`. A forced exit adds none.
If a goal mutation lacks permission, report the goal requirement and missing permission. Fail if no path remains.

Keep production changes, outward sends, irreversible actions, goal sign-off, and mutation permissions with the user.
Pass each free-text value as one quoted argument. Never interpolate it into shell code.

For a user-requested amendment, keep the original settlement. Read only [amendments.md](references/amendments.md).

## Fallbacks

Use the failed terminal path and report the reason for these stops.

- **Validation refusal:** return its grouped field problems.
- **Missing required skill or override:** name it once. Do not retry or use the general default in place of a named override.
- **Identity amendment:** reject a change to `session_dir` or `task_folder`. Report the real diagnostic and preserve both.
- **Blocked work or missing permission:** use the failed path when no authorized path remains. Use the checkpoint handoff when it applies.

Report missing or unconfigured memory-ledger status and continue.

## Host mechanics

Get Gear from `cli:gear`. Use `<gear> --host <host> engine task <command>` and plugin `converge` for Converge.
Use `claude` on Claude Code and `codex` on Codex. Gear reads the run ID from the environment.
Keep `session_dir` in context. Omit `--dir` for `~/.bootgear/session`. Add `--dir <session-dir>` only for a custom directory.
Pass the installed Engine root as `<engine-root>`.

Use `spec:spec`, `spec:spec-review`, `test:test`, and `review:review`.
If `cli:gear` is absent, install `cli@bootgear` through the host.
For missing sibling skills, report `cli:setup` for `engine`. Resume after setup verifies them.
