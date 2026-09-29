---
name: converge
description: Settle the facts behind a set of claims — find, refute and cut each claim with separate agents over a validated append-only ledger, then compute which claims are reported. Use to review an artifact through lenses, to refute an existing numbered slate until a round changes nothing, or when review or debate needs its claims settled before acting.
---

Read `reference.md` § `converge — rationale` for rationale. `converge` below is the CLI named in `## Host mechanics`.

## 1. Modes

- `full`: the caller supplies the artifact, the lenses and absolute paths to its find-angle files. Run steps 2–8.
- `refute-only`: the caller supplies the artifact and a numbered slate. Run steps 2, 4, 6–8; there is no find, cut, cutoff or gate.

Pick a valid slate id and an absolute ledger directory. Provide the mode's
artifact, lenses, angle files, and optional project configuration to the
public `converge` command. Its refusal or status output is authoritative for
the accepted shape, current phase, and next fixed action.


## 2. Roles

One slate is one task. Never use more than `caps.agents` agents on it (default
5, main included); the CLI refuses an allocation that would exceed it. Agents
on another slate or task (a later debate) have their own budget. Allocate
these ids:

| role | agent id | covers |
|---|---|---|
| main | `main` | orchestrator: writes `init`, and in refute-only mode the slate's `file` events as `slate` |
| F | `finder` | every find angle of every lens |
| R1 | `r1` | refuter: ≥1 unused attack angle per claim per round; ≥2 when it is the round's only refuter |
| R2 | `r2` | refuter like `r1`, and the gap-hunt finder; omitted when the caller asks for one refuter (review `quick`) |
| C | `cutter` | every cut round of every claim (full mode only) |

Refute-only mode uses main, R1 and R2.

- Spawn each role once and reuse it across rounds by continuing that agent; never spawn a new agent for a role that already has one.
- Give a role agent only the artifact, its role brief from the steps below, the claims under test (id, current text, `loc`, `trigger`), its agent id, `<slate>`, `<dir>` and the exact `converge` command it writes. Never give it another role's reasoning.
- As main, write only `init` and, in refute-only mode, the slate's `file` events. Never write `refute`, `cut`, `rebut` or `accept`.
- If a role agent cannot be spawned or does not return, stop with outcome `blocked` (step 8). Never write an event for it.

## 3. Find

Spawn F once with one brief that lists every lens and, per lens, all its find angles (`converge angles --tag find --angles <file>…`; an angle whose `lens=` names another lens belongs only to that lens). Finder brief:

1. For each lens, for each angle whose tell matches the artifact: search, run
   a positive control, then file each claim and record the run through the
   public CLI. Its refusal output owns event shape and dependency checks.
2. For every other angle of the lens, record the CLI's not-applicable event
   with the reason the tell is absent.

After F returns, run the CLI's coverage action.

## 4. Refute rounds

Repeat until the CLI reports the refute phase converged:

1. Run the CLI's JSON status action. Live claims with `refute: open` are under
   test.
2. For each claim under test, choose ≥2 of its `unused_attack_angles` whose tell applies. With R1 and R2, give each refuter ≥1 of them (more when more apply); with R1 alone, give it ≥2. Never give a refuter a claim it filed. Declare the round's angles before continuing the refuters.
3. Continue R1 (and R2) with its angles for every claim this round; one refuter takes many angles across many claims. The round number for a claim is its status `round` + 1.
4. Refuter brief:
   - The claim is refuted unless the artifact's code or evidence proves it. Read every source you cite.
   - Outcomes: `killed` (false), `retracted` (its referent does not exist in the artifact), `downgraded` (true only in a narrower form), `survived` (withstood the angle, evidence cited), `inconclusive` (no available source settles it; name what would).
   - For `deliberate` and `guarded-elsewhere`: first resolve the question with the `memory-ledger:ledger` skill and re-run the entry's evidence; record `--source ledger:<slug> --ledger-evidence pass|fail`. If memory-ledger is missing, unconfigured or broken, put its diagnostic in `--evidence` and continue from the code.
   - Write one event per angle through the public CLI, including the cited
     evidence and any narrowed claim.
5. Continue each claim's finder with claims that were killed, retracted or
   downgraded this round. The finder may rebut only with new evidence through
   the public CLI.

Gap hunt (only when the caller asks for one and R2 exists): after refute of the lens claims converges, continue R2 as the gap-hunt finder with the caller's gap-hunt brief. It files with `--as r2 --origin gap-hunt`. Run refute rounds on its claims with R1 alone (≥2 unused angles per claim per round). Without R2 there is no gap hunt.

## 5. Cut rounds

Full mode only. Repeat until the CLI reports the cut phase converged:

1. Its round number for a claim is the claim's status `cut_round` + 1.
2. Cutter brief:
   - Default verdict: cut. Rate a field higher only when evidence justifies it.
   - For each claim set `frequency`, `severity`, `confidence` and `difficulty`,
     each backed by an applicable evaluate angle. Add a choice when the facts
     are agreed but a remedy still needs a decision.
   - Record the cut through the public CLI.
3. Continue each claim's finder with that round's cut values and evidence. The
   finder answers with the public CLI's `accept` or `rebut` event.
4. Continue C with each rebuttal for the next round. A claim's cut converges when its latest round is accepted, or when C repeats the same four values after a rebut; it is capped at `caps.cut_rounds`.

## 6. Cutoff and render

- Full mode: run the fixed cutoff action the CLI reports after convergence.
- Refute-only mode: run the fixed render action the CLI reports after
  refutation convergence.

Hand back the render and every claim carrying a `choice`.

## 7. Memory-ledger

After cutoff (refute-only: after refute converges), mint facts that hold beyond this artifact through the `memory-ledger:ledger` skill, each with a runnable check. These are conventions, root causes, and the deliberate decisions behind appendix or killed claims. If memory-ledger is `missing`, `unconfigured` or `broken`, append `memory-ledger: <status> — <diagnostic>` to the render you hand back and continue.

## 8. Outcomes

Hand back exactly one:

- `converged`: full mode with the reported and appendix counts; refute-only mode with the survived, inconclusive, downgraded, killed and retracted counts.
- `unconverged`: list the claims whose refute state is `unconverged`.
- `blocked`: name the role agent that was unavailable and the claims it held. No claim is marked survived without its refuter.

## Host mechanics

- Spawn each role agent once with the Agent tool; continue it with SendMessage for later rounds.
- Run the CLI as bare `converge` in Bash; the plugin's `bin/` is on PATH.
