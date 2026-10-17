---
name: converge
description: Settle the facts behind a set of claims — find, attack and cut each claim with separate agents over a validated append-only ledger, then compute which claims are findings. Use to review an artifact through lenses, or when review or debate needs its claims settled before acting.
---

`converge` below is the CLI named in `## Host mechanics`.

## Use, inputs and handback

Use it when a caller (another skill, or the user standalone) needs the facts behind a set of claims settled before acting. Inputs: the artifact, the lenses and absolute paths to their find-angle files; optionally a gap-hunt brief, a request for one refuter (`init --refuters 1`), a task config file (`init --config`), and in an engine run the settlement file for `init --settlement`.

Each claim ends with a status and a separate `cut` field (`yes`/`no`):

- `survived`: no attack refuted it, or the refuter agreed with its finder's rebut.
- `disputed`: the refuter disagreed with the rebut and the finder rebutted again.
- `killed`: its finder declined to rebut a refutation.
- `unverified`: cut before the attack, so never attacked.

The cutoff gives each claim one result:

- `finding`: `cut: no`, reported.
- `fix-now`: `cut: no`; a `survived` claim whose accepted after cut carries a cheap patch. The caller applies the patch and records `fix-check` (step 6).
- `fixed`: a `fix-now` claim whose `fix-check` passed.
- `follow-up`: `cut: yes`; listed in its own section with its status, never presented as a finding.
- `killed`: listed with its evidence.

Nothing verified is dropped.

Hand back to the caller the render, every finding carrying a `choice`, the `fix-now` claims with their patches (`converge render --json` `fix_now`), the follow-up list with its count and each follow-up's `choice`, the killed claims, and exactly one outcome (step 8). The caller asks `deputy:ask` for each choice, and production change, outward send, irreversible action, goal sign-off, or permitted mutations are never sent to it; this handback does not change:

- `converged`: no finding is `disputed`; give the finding, fix-now, fixed, follow-up and killed counts.
- `unconverged`: list the `disputed` findings.
- `blocked`: name the role agent or seat that was unavailable and the claims it held. No claim is settled without its refuter.

Follow-up claims never change the outcome.

## Workflow

init (step 1) → find and coverage (step 3) → gap hunt (step 3; on when R2 exists and `steps.gap_hunt` is true) → escalate (step 4; on when `steps.escalate` is true) → cut before, attack, cut after until `converge status` reports `phase: cutoff` (step 5) → cutoff, render, gate and `converged`, then the caller's `fix-check` per `fix-now` claim (step 6) → mint memory-ledger facts (step 7) → hand back (step 8).

`steps.cut` picks the cut passes: `before`, `after`, `both` (default) or `none`.

## 1. Init

Pick a valid slate id and an absolute ledger directory, and run `converge init` with the lenses, the find-angle files and any configuration the caller gives. Its refusal or status output is authoritative for the accepted shape, the current phase and the next fixed action.

## 2. Roles

One slate is one task. Never use more than `caps.agents` agents on it (default 5, main included); the CLI refuses an allocation that would exceed it. Agents on another slate or task (a later debate) have their own budget. After the find and the gap hunt, work comes from the `plan` in the CLI's JSON status; each row names its `agent_role`. Allocate these ids:

| role | agent id | covers |
|---|---|---|
| main | `main` | orchestrator: writes `init` |
| F | `finder` | every find angle of every lens; for its claims, escalates, replies to refutations, and accepts or rebuts cut rounds |
| R1 | `r1` | attacks every table batch, and the fresh-eye batch of claims R2 filed or of every claim when R2 is omitted; gives the verdict on its refutations |
| R2 | `r2` | the gap-hunt finder, acting as F for its claims; attacks the fresh-eye batch of every other claim and gives the verdict on its refutations; omitted when the caller asks for one refuter |
| C | `cutter` | every cut round of every claim |

Spawn each role by the seat mechanism `init` prints: a `native_subagent` seat as in `## Host mechanics`; for an `advisor` seat, follow the driver step the CLI prints instead of spawning.

- Spawn each role once and reuse it across the slate by continuing that agent; never spawn a new agent for a role that already has one.
- Give a role agent only the artifact, its role brief from the steps below, the claims under test with their `id`, `claim`, `loc`, `trigger`, `evidence` and `tier` from `converge status --json`, its agent id, `<slate>`, `<dir>`, the exact `converge` command it writes, the context files that the caller names, and the instruction to read them.

## 3. Find

Spawn F once with one brief that lists every lens and, per lens, all its find angles (`converge angles --tag find --angles <file>…`; an angle whose `lens=` names another lens belongs only to that lens). Finder brief:

1. For each lens, for each angle whose tell matches the artifact: search, run
   a positive control, then file each claim and record the run through the
   public CLI. Its refusal output owns event shape and dependency checks.
   File each claim with `--evidence` (the output or file:line hops it rests
   on) and `--tier`:
   - `reproduced`: you ran a command or test and quote output showing the trigger;
   - `traced`: no run, and you cite file:line for every hop from the entry point to the effect;
   - `inferred`: any other basis.
2. For every other angle of the lens, record the CLI's not-applicable event
   with the reason the tell is absent.

After F returns, run the CLI's coverage action.

Gap hunt: after coverage, when the gap hunt is on, continue R2 as the fresh-eyes finder with the caller's gap-hunt brief, else the brief "what did every lens miss". It files with `--as r2 --origin gap-hunt`. Like the find, it is exempt from the batch cap. Its claims go through steps 4 and 5 like any other, with R1 running every attack batch on them.

## 4. Escalate

For each batch of escalate rows, continue each row's finder (F for lens claims, R2 for gap-hunt claims). For each claim it asks "can this be more serious than filed?" and records `escalate` through the public CLI: with `--wider` and `--evidence` citing a concrete route to the worse outcome (file:line, caller or command), or without either. A wider text without a route is refused.

## 5. Cut and attack

Repeat until `converge status` reports `phase: cutoff`: run the CLI's JSON status action and, for each batch of its `plan`, continue each row's `agent_role` with the row's claims, batch and angles.

1. Cut rows (`cut-before`, `cut-after`). Cutter brief:
   - Default verdict: cut. Rate a value higher only when evidence justifies it.
   - For each claim set `impact`, `size` and `reach`, and `rate` (an integer
     count) when the CLI requires it for the claim's lens; after the attack
     also set `difficulty`. Back each with an applicable evaluate angle and
     decide each value by the `<value>: <test>` lines that
     `converge angles --tag evaluate` prints.
   - After the attack, `trivial` or `local` needs the fix as a unified diff
     that touches only the claim's `loc` file and its tests, passed as
     `--patch "$(cat fix.diff)"`, with `--callers none` and
     `--migration none`; the CLI measures the patch and refuses a class it
     does not earn. Otherwise set `cross-cutting` or `redesign`.
   - Add `--choice` naming the options when the facts are agreed but a remedy
     still needs a decision; the CLI refuses a cut that needs one without it.
   - Record the cut through the public CLI.

   For `accept` rows, continue the claim's finder with that round's cut values and evidence; it answers with `accept`, or `rebut` with new evidence. Continue C with each rebuttal for the next round.
2. Attack rows. Refuter brief:
   - The claim is refuted unless the artifact's code or evidence proves it. Read every source you cite.
   - Table batch: attack the claim with every angle in the row whose tell applies, and record each other angle not applicable with the reason its tell is absent.
   - Fresh-eye batch (`batch` `fresh-eye`): the row has `angles: []`, `used` (the angles already attacked on the claim) and `rule`. Attack with up to `caps.angles_per_claim` angles of your own choosing, none in `used`. A one-line name without edge whitespace is accepted, including a fixed angle recorded not applicable on the claim. Mark the last attack `--last`. An empty `fixed_remaining` in `status` does not mean nothing is left to attack; the fresh-eye batch still runs.
   - For `deliberate` and `guarded-elsewhere`: first resolve the question with the `memory-ledger:ledger` skill and re-run the entry's evidence, citing the entry and its result in the evidence. If memory-ledger is missing, unconfigured or broken, put its diagnostic in the evidence and continue from the code.
   - Write one `attack` event per angle, `clean` or `refuted`, with the cited evidence.
3. Dispute rows. For `reply`, continue the claim's finder with the batch's refuted attack: it rebuts with new evidence, optionally with a clarified claim text, or declines, which kills the claim. For `verdict`, continue the refuter that recorded the refutation with the rebut: it agrees, or disagrees with more evidence. A disagreement returns to the finder for one more `reply`.

## 6. Cutoff, render and gate

Run the cutoff, render and gate actions the CLI prints, then `converge converged`: `CONVERGED` picks outcome `converged`, `OPEN` picks `unconverged` with the disputed findings it lists.

For each `fix-now` claim, the caller that applies its patch runs the tests and checks, starts a one-round re-review slate whose brief asks only for problems the patch introduces, and records `converge fix-check <slate> --as main --claim <id> --outcome pass|fail --evidence "<checks run and their result>" --review-slate <re-review slate>`. `pass` needs passing checks and a re-review slate with a current cutoff and no finding; on `fail` the caller reverts the patch. Then rerun the cutoff: `pass` gives `fixed`, `fail` returns the claim to finding or follow-up.

## 7. Memory-ledger

After cutoff, mint facts that hold beyond this artifact through the `memory-ledger:ledger` skill, each with a runnable check. These are conventions, root causes, and the deliberate decisions behind follow-up or killed claims.

## 8. Outcomes

Hand back the render, every finding carrying a `choice`, and exactly one outcome: `converged`, `unconverged` or `blocked`, with the details listed under `## Use, inputs and handback`.

## Rules

- As main, write only `init`, and `fix-check` for a patch the caller applied. Never write `attack`, `reply`, `verdict`, `cut`, `rebut` or `accept`: refuters write `attack` and `verdict`, finders `escalate`, `reply`, `rebut` and `accept`, the cutter `cut`.
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

- Spawn each role agent once with the Agent tool; continue it with SendMessage for later rounds.
- Run the CLI as bare `converge` in Bash; the plugin's `bin/` is on PATH.
- Invoke `advisor:advisor`; run an advisor seat's background step with the Bash tool's `run_in_background`.
