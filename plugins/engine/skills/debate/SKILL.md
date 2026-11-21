---
name: debate
description: Settle an unresolved Engine choice with several parties. Use when the choice passes the debate threshold.
---

## Inputs and outcomes

Take the decision, settled sources, principles, and any caller Converge render.
Require an unsettled `resolve` result or an admitted direct call. Use Engine's debate.

Return one result to `resolve` or the admitted caller.

| Result | Handback |
|---|---|
| **Refused** | Factual dispute or failed admission check. Record nothing. Route to `converge` or `resolve`, respectively. |
| `inconclusive` | No source can settle a fact. Record nothing. |
| **Deputy assertion** | Answer and cited slugs on an admitted direct call. Dispatch no parties. |
| **Closed question** | Question ID, closing outcome, answer, dissent, and absence data. |

For `consented_stop` or `round_cap`, return main's decision. Include any answer from `resolve` after a stall.
`scope_settled` ends only round 0.

## Procedure

### Admit and brief

Before recording, classify the dispute. Send facts with a possible check to `converge`. Return `inconclusive` for an uncheckable fact.
For a direct choice, require all four conditions.

- `debate_admission` names the caller.
- The caller supplies a plain decision and at least two conflicting live options.
- The caller checked the settled sources and principles without a decision.
- The choice passes `debate_threshold` for reversibility and impact.

Name the failed check on refusal. Require an admitted caller to assemble the full brief.

Use `recall` for full decisions and effective settlement. Read `session_dir` there.
Use the settled `debate_party_config`, roster, custom parties, cap, consent and convergence policy, and admission.

Give each party these items at round 0 and each later round.

- The decision, all `source_of_truth` domains, `debate_threshold`, and the reason it applies.
- `task_type`, `goal`, and merged user, project, and task principles. Omit `approach`.
- Existing project standard paths in `.bootgear/config/`. Tell each party to read them first.
- The caller's Converge render, when present. Treat `survived` and killed claims as settled. Keep disputed findings and unverified follow-ups open.

Include `deputy_slugs` from `resolve` as past user decisions. Ask each party if each still applies.
Record the reason for each departure. Do not ask deputy again.
For an admitted direct call, ask `deputy:ask` before dispatch. Use cited slugs in the same brief.
Return any `assertion` without dispatch. If deputy is absent, record `no-deputy:not-installed` and omit slugs.

### Parties

Dispatch only enabled stable IDs in `debate_roster`. Use 2–5 parties, including `main-agent`. Exclude external review and Converge roles from that count.
Use configured labels in prose only. Record the stable ID.
Apply `label`, `prompt`, `mechanism`, and `enabled` from `debate_party_config.parties.<id>`.
Append `advisor_roles.brief` for an advisor. Reject invalid configuration before dispatch.
Custom parties use `{id, label, prompt, mechanism}`. Use a host-supported mechanism.

### Round 0: scoping

Resume the open question from `recall`. Otherwise run `session next-question-id` and use its printed round-0 submission.
If it refuses for an open question, resume that question.

Each enabled party gives its own topic, scope, principles, and cutoff. Record a real position or marker for each.
Discuss once. Each party agrees, refines, or refutes named points. Main records the scope and unresolved caveats.
Allow dissent. For an all-marker round, use the `debate-degraded` path. Otherwise submit `scope_settled` and use the printed round-1 submission.

### Rounds

Record one position per party as it arrives. Preserve earlier entries and omit unchanged restatements.
Require independent round-1 positions. From round 2, require each party to answer each other's latest position.
Use agreement, refinement, or refutation of named points.

At each round start, run `recall` and brief from that effective state. Finish the round under that state.
Apply roster, party, and cap amendments at the next start. Preserve recorded rounds.
Keep remaining parties. Drop removed parties after any retry owed. Brief added parties for an independent first position.

If the cap holds at the next start, close with `debate-capped` after any owed retry.
If a round stalls or compaction interrupts it, read only the relevant section of [round-recovery.md](references/round-recovery.md).
If dispatch fails or a reply is unusable, read [unavailable-party.md](references/unavailable-party.md) for the marker and retry rules.
Keep absence episodes separate.

### Recording

Use Gear's opening templates. For later positions use `session record-decision` with `--mode debate`, the question ID, and this form.

```text
round N, party '<role>': <position>
```

Use one line. For closure, omit `round N`. Include the question ID and required positions, dissent, or absences.

| Mode | Summary prefix |
|---|---|
| `debate` | `unanimous_convergence:` |
| `debate-capped` | `consented_stop:` or `round_cap:` |
| `debate-degraded` | `degraded_convergence:` |
| `scope-settled` | `scope_settled:` with topic, scope, principles, cutoff, and dissent. Requires a real round-0 position. |

Close each question once. Record nothing after closure.

### End a round

- **`unanimous_convergence`:** require agreement on substance and no live objection that changes the outcome.
  Run the angle round below. Require the result to meet the effective `goal`. Only `AMENDMENT goal` can narrow it.
- **`consented_stop`:** require `consented_stop_allowed: true` and an explicit `CUT` from every party in the round.
  Silence, absence, non-response, or `continue` prevents consent. Record final positions and CUT voters.
  Main states its position and strongest unresolved objection. Check consent yourself. Gear checks only summary presence.
- **`round_cap`:** at the cap (default 10), main decides. Record its position and strongest unresolved objection.
- **`degraded_convergence`:** apply only the conditions in [unavailable-party.md](references/unavailable-party.md) after dispatch failure.

For a tie, continue toward the cap unless all parties explicitly vote `CUT`.

### Angle round

When every party agrees, run one more round before closing. Get `decide` and `attack` lists from the public `converge` command.
Each party names and applies at least two angles no party has used for this question.
Start with `angles: <ids>`. Check the effective goal with `goal: kept` or `goal: narrowed <what>`.

```text
round N, party '<role>': angles: <id>,<id>; goal: kept; <position or response in one line>
```

A narrowing is a new objection. If any position changes or a new objection appears, continue ordinary rounds.
Otherwise close with `unanimous_convergence`.

## Rules

Keep production changes, outward sends, irreversible actions, goal sign-off, and mutation permissions out of deputy.
Pass each free-text value as one CLI argument. Let Gear report exact syntax and refusals.
Skip recovery references in ordinary rounds.

## Fallbacks

Use the unavailable-party rules for failed dispatch.
For a missing required sibling, stop and report `cli:setup` for `engine`. Resume after verification.

## Host mechanics

Get the absolute path from `cli:gear`. Run `<gear> --host <host> engine task <command>`.
Use `<gear> --host <host> converge converge <command>` for angles. Add `--dir` only for a custom session path.
Both hosts support `native_subagent` and `advisor`. Do not switch mechanism after a failure.
A failed native spawn, failed or timed-out advisor call, or missing advisor skill makes a party unavailable.
Read only the current host's section.

### Claude Code

Use `--host claude`. If Gear is absent, install with `/plugin install cli@bootgear`.
Use a fresh subagent for `independent-reviewer`. Give it the full brief without main's position.
By default, `adversarial-reviewer` uses `advisor`, `--mode asking`, direct communication, and `review`.
Use the same dispatch for all advisor seats. Send the full brief and request counterexamples.
For a native mechanism, use a subagent.

### Codex

Use `--host codex`. If Gear is absent, run `codex plugin add cli@bootgear`.
Use a native subagent for a native seat. Treat a spawn timeout as unavailability.
For an advisor, use a Claude Code listener with `--mode asking`, `channel`, and `review`.
Use the recorded debate channel, never `r2`. A missing live listener makes the party unavailable.
For deferred startup without a pairing, run the settled launcher at the first advisor request.
Pair through Advisor and record the debate channel. Preserve the `r2` channel in the decision.
For early startup, require the existing pairing. Reclaim its live seat before each request through Advisor's scan and claim.
