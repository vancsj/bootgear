---
name: converge
description: Settle the facts behind a set of claims — find, refute and cut each claim with separate agents over a validated append-only ledger, then compute which claims are reported. Use to review an artifact through lenses, to refute an existing numbered slate until a round changes nothing, or when review or debate needs its claims settled before acting.
---

`converge` below is the CLI named in `## Host mechanics`.

## Use, inputs and handback

Use it when a caller (another skill, or the user standalone) needs the facts behind a set of claims settled before acting. Inputs: the mode (step 1), the artifact, and for `full` the lenses and find-angle files, for `refute-only` a numbered slate; optionally a gap-hunt brief and a request for one refuter, which is `init --refuters 1`; in an engine run, the settlement file for `init --settlement`.

Hand back to the caller the render, every claim carrying a `choice`, the follow-up list (each claim labelled `unverified` or `unconverged`) with its count, and exactly one outcome (step 8):

- `converged`: full mode with the reported, appendix and follow-up counts; refute-only mode with the survived, inconclusive, downgraded, killed and retracted counts.
- `unconverged`: in full mode, list the claims reported with reason `unconverged`; in refute-only mode, list the claims whose refute state is `unconverged`.
- `blocked`: name the role agent that was unavailable and the claims it held. No claim is marked survived without its refuter.

Follow-up claims never change the outcome.

In the render nothing verified is dropped: below-cutoff claims go to the appendix; inconclusive claims, blocking unconverged claims (last cut `security`, `data-loss` or `wrong-behavior` at `every-call` or `common` frequency), and claims tagged with a rule listed in `cutoff.report_rules` are always reported and exempt from the per-lens cap; cut-capped claims, rule-tagged or not, are reported but count against the per-lens cap. Follow-up claims are listed in their own section, labelled, and never presented as findings.

## Workflow

- `full`: init → find and coverage (step 3) → gap hunt (step 3; on by default when R2 exists and status `steps.gap_hunt` is true, off with `init --refuters 1` or `steps.gap_hunt: false`) → escalate (step 4) → cut and refute rounds until converged (step 5) → cutoff and render (step 6) → mint memory-ledger facts (step 7) → hand back (step 8).
- `refute-only`: init and file the slate → refute rounds until converged (step 5) → render (step 6) → mint memory-ledger facts (step 7) → hand back (step 8).

## 1. Modes

- `full`: the caller supplies the artifact, the lenses and absolute paths to its find-angle files. Run steps 2–8.
- `refute-only`: the caller supplies the artifact and a numbered slate. Run steps 2, 5–8; there is no find, escalate, cut, cutoff or gate.

Pick a valid slate id and an absolute ledger directory. Provide the mode's
artifact, lenses, angle files, and optional project configuration to the
public `converge` command. Its refusal or status output is authoritative for
the accepted shape, current phase, and next fixed action.

## 2. Roles

One slate is one task. Never use more than `caps.agents` agents on it (default
5, main included); the CLI refuses an allocation that would exceed it. Agents
on another slate or task (a later debate) have their own budget. After the
find and the gap hunt, batches come from the `plan` in the CLI's JSON status.
Allocate these ids:

| role | agent id | covers |
|---|---|---|
| main | `main` | orchestrator: writes `init`, and in refute-only mode the slate's `file` events as `slate` |
| F | `finder` | every find angle of every lens |
| R1 | `r1` | refuter: angles per claim per round from `status --json` `plan` |
| R2 | `r2` | refuter like `r1` (angles per claim per round from `status --json` `plan`), and the gap-hunt finder; omitted when the caller asks for one refuter |
| C | `cutter` | every cut round of every claim (full mode only) |

Refute-only mode uses main, R1 and R2.

Spawn each role by the seat mechanism `init` prints: a `native_subagent` seat as in `## Host mechanics`; for an `advisor` seat, follow the driver step the CLI prints instead of spawning.

- Spawn each role once and reuse it across rounds by continuing that agent; never spawn a new agent for a role that already has one.
- Give a role agent only the artifact, its role brief from the steps below, the claims under test (id, current text, `loc`, `trigger`), its agent id, `<slate>`, `<dir>` and the exact `converge` command it writes.

## 3. Find

Spawn F once with one brief that lists every lens and, per lens, all its find angles (`converge angles --tag find --angles <file>…`; an angle whose `lens=` names another lens belongs only to that lens). Finder brief:

1. For each lens, for each angle whose tell matches the artifact: search, run
   a positive control, then file each claim and record the run through the
   public CLI. Its refusal output owns event shape and dependency checks.
2. For every other angle of the lens, record the CLI's not-applicable event
   with the reason the tell is absent.

After F returns, run the CLI's coverage action.

Gap hunt: after coverage, when the gap hunt is on, continue R2 as the fresh-eyes finder with the caller's gap-hunt brief, else the brief "what did every lens miss". It files with `--as r2 --origin gap-hunt`. Like the find, it is exempt from the batch cap. Its claims go through steps 4 and 5 like any other, with R1 alone refuting them.

## 4. Escalate

Full mode only. For each batch of `plan.escalate`, continue each row's `finder` (F for lens claims, R2 through its driver step for gap-hunt claims). For each claim it asks "can this be more serious than filed?" and records `escalate` through the public CLI: with `--wider` and `--evidence` citing a concrete route to the worse outcome (file:line, caller or command), or without either. A wider text without a route is refused.

## 5. Cut and refute rounds

Full mode cuts each claim before refuting it; refute-only mode runs only the refute batches. Repeat until the CLI reports the cut phase converged (refute-only: the refute phase):

1. Run the CLI's JSON status action and follow its `plan` batches in this order: `plan.rebut`, `plan.cut`, `plan.refute`.
2. `plan.rebut`: continue each row's `finder` with its claim's last refute round. The finder may rebut only with new evidence through the public CLI. A rebut makes the cut stale, so it comes before the re-cut.
3. `plan.cut`: the cut round number for a claim is its status `cut_round` + 1. Cutter brief:
   - Default verdict: cut. Rate a field higher only when evidence justifies it.
   - For each claim set `frequency`, `severity`, `confidence` and `difficulty`,
     each backed by an applicable evaluate angle. Add a choice when the facts
     are agreed but a remedy still needs a decision. A `cosmetic` cut needs a
     one-line `--fix`.
   - Record the cut through the public CLI.

   Continue each row's `finder` with that round's cut values and evidence; it answers with the public CLI's `accept` or `rebut` event. Continue C with each rebuttal for the next round. A claim's cut converges when its latest round is accepted, or when C repeats the same four values after a rebut; it is capped at `caps.cut_rounds`. A claim whose converged cut is `cosmetic` is parked: it leaves the loop, is never refuted, and is listed as follow-up `unverified`; its finder may still challenge the cut with `rebut --stage cut` and new evidence.
4. `plan.refute`: for each row, choose the printed number of the claim's `unused_attack_angles` whose tell applies. With R1 and R2, split a claim's angles between them, ≥1 each when it has ≥2. Declare the round's angles before continuing the refuters, then continue R1 (and R2) with its angles for every claim in the batch; the round number is the row's `round`. Refuter brief:
   - The claim is refuted unless the artifact's code or evidence proves it. Read every source you cite.
   - Outcomes: `killed` (false), `retracted` (its referent does not exist in the artifact), `downgraded` (true only in a narrower form), `survived` (withstood the angle, evidence cited), `inconclusive` (no available source settles it; name what would).
   - For `deliberate` and `guarded-elsewhere`: first resolve the question with the `memory-ledger:ledger` skill and re-run the entry's evidence; record `--source ledger:<slug> --ledger-evidence pass|fail`. If memory-ledger is missing, unconfigured or broken, put its diagnostic in `--evidence` and continue from the code.
   - Write one event per angle through the public CLI, including the cited
     evidence and any narrowed claim.
   - When no attack angle left applies to a claim, record `converge angle-na --phase refute --claim <id> --angle <angle> --reason <why>` for each remaining one; the claim then closes `unconverged`.

## 6. Cutoff and render

- Full mode: run the fixed cutoff action the CLI reports after convergence.
- Refute-only mode: run the fixed render action the CLI reports after
  refutation convergence.

## 7. Memory-ledger

After cutoff (refute-only: after refute converges), mint facts that hold beyond this artifact through the `memory-ledger:ledger` skill, each with a runnable check. These are conventions, root causes, and the deliberate decisions behind appendix or killed claims.

## 8. Outcomes

Hand back the render, every claim carrying a `choice`, and exactly one outcome: `converged`, `unconverged` or `blocked`, with the details listed under `## Use, inputs and handback`.

## Rules

- As main, write only `init` and, in refute-only mode, the slate's `file` events. Never write `refute`, `cut`, `rebut` or `accept`.
- Never give a role agent another role's reasoning.
- Never give a refuter a claim it filed.
- A factual dispute is never a choice; it stays in converge.
- Agent-id distinctness checks stop accidental self-judging, not a lying agent; a caller that needs more must run role agents it trusts.
- When the advisor channel's heartbeat task ends, run its printed `next` at once.

## Fallbacks

- If a role agent cannot be spawned or does not return, stop with outcome `blocked` (step 8). Never write an event for it.
- If an `advisor` seat cannot be driven (the `advisor` skill is missing, it hands back no listener, or the peer goes stale), stop with outcome `blocked` naming the seat; never run that seat as a native subagent.
- If memory-ledger is `missing`, `unconfigured` or `broken`, append `memory-ledger: <status> — <diagnostic>` to the render you hand back and continue.

## Host mechanics

- Spawn each role agent once as a separate fresh native subagent with `spawn_agent`; continue that same subagent for later rounds (for example with `send_input`). Never spawn a replacement for a role that already has one: the slate's agent budget (`caps.agents`, main included) counts every distinct agent.
- Run the CLI as `<plugin-root>/scripts/converge`, where `<plugin-root>` is this engine plugin's root; every `converge` command above means that script. Give role agents the full script path.
- Invoke skills by their public name through the host Skill interface; the ledger skill is `memory-ledger:ledger`.
- Invoke `advisor:advisor` (a separate plugin: `codex plugin add advisor@bootgear`); run an advisor seat's background step in a terminal session left running, with the escalation the `advisor` skill states.
- A role agent is unavailable when its native subagent cannot be created, times out, or, in a headless run, stops on a fresh approval request. Stop with outcome `blocked` (step 8).
