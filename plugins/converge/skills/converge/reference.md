# converge — rationale

See SKILL.md § 1–2.

- **Facts, not choices.** converge settles what is true: does the claim hold, how often, how bad, how sure, how hard to fix. A claim whose facts are agreed but whose fix is still a choice leaves with `choice` for `debate`. A factual dispute never goes to debate: arguing does not settle facts, reading and running do.
- **Separate agents per role.** An agent that found a claim is invested in it; one that refuted it is invested in the kill. So the finder never refutes or cuts its own claim, and refuters and cutters of a claim are disjoint. A role gets the artifact and the claim, never another role's reasoning, so it cannot inherit a conclusion.
- **Agent budget.** At most 5 agents per task, main included — token cost grows with every spawned agent, and each fresh agent re-reads the artifact. The budget is per task and one slate is one task: a later debate on the slate's choices has its own budget. `caps.agents` (default 5, at most 5) enforces it per slate; the CLI counts the `init` writer and refuses the id that would exceed the cap. Agents therefore take many angles each rather than one agent per angle: one finder covers every find angle of every lens, two refuters (one at quick depth) cover every angle, and one cutter covers every cut round, each continued across rounds instead of respawned. The reserved ids `slate` (main filing a refute-only slate) and `converge` (the computed cutoff) are not agents and do not count.
- **Why a refuter is reused across angles.** A fresh refuter per angle would keep one angle's reading from steering the next, but it costs one agent per angle per round and cannot fit the agent cap. The unused-angle rule already forces every round onto angles never used on that claim, which is what makes a quiet round a convergence signal; a refuter reused across rounds still has to attack from a new direction.
- **Accept or rebut ends a cut round.** With one cutter reused across rounds, two identical rounds from the same agent would only show it agrees with itself. So the claim's finder — the party with the opposite stake — answers each round: `accept` converges it; a `rebut` with new evidence forces another round, and if the cutter repeats the same values after reading the rebuttal, the cut is converged as held. `caps.cut_rounds` still ends a dispute as `cut-capped`.
- **Trust boundary.** Agent ids are declared by the orchestrator; the CLI cannot see which agent is really calling. The distinctness checks stop accidental self-judging (one agent reusing its id for the next role), not a lying agent. A caller that needs more must run role agents it trusts.
- **Default verdicts.** Refute defaults to refuted and cut defaults to cut, so a claim reaches the report only on shown evidence.
- **Blocked, not survived.** A claim nobody could attack has not survived anything; recording it as survived would pass it on unchecked.

See SKILL.md § 4–5.

- **Unused angles, ≥2 per round.** Re-running an angle repeats its earlier answer; a quiet round on a reused angle is a repeat, not convergence. Two fresh angles that change nothing is the stop signal. Five rounds cap refute and three rounds cap cut so a disputed claim ends as `unconverged` or `cut-capped` and is reported rather than looping.
- **Rebut needs new evidence.** The CLI hashes rebuttal evidence so a finder cannot force endless rounds by repeating itself.
- **Kill and downgrade reopen dependents.** A claim resting on a refuted or narrowed claim is untested against the new fact until it gets another round.

See SKILL.md § 6.

- **Computed cutoff.** Whether a claim is reported comes from the cut fields and configured rules, computed by the CLI and re-checked on every replay. An agent typing `reported` would reintroduce the judgment the cut stage exists to pin down. Nothing verified is dropped: below-cutoff claims go to the appendix, and inconclusive, unconverged and cut-capped claims, and claims tagged with a rule listed in `cutoff.report_rules`, are always reported. `report_rules` claims are exempt from the per-lens cap: the caller has ruled that each one must be reported.
- **Gap-hunt rules are stricter.** A gap-hunt finder is briefed to find what the lenses missed, so it yields more marginal claims.
- **Gap hunt by `R2`.** Within five agents there is no spare agent for the gap hunt. `R2` files it because `R1` can then refute those claims without breaking the finder-never-refutes rule; with one refuter (quick depth) the gap claims' only refuter would be their finder, so quick depth has no gap hunt.

See SKILL.md § 7.

- **Memory-ledger.** The slate ledger holds this artifact's claims; memory-ledger holds facts that stay true on an unrelated later review. Minting only with a runnable check keeps the memory ledger verifiable. A missing memory-ledger is recorded, never fatal, because converge must work standalone.

Ledger file.

- **JSONL + flock.** Parallel role agents write the same slate. Replay-validate-append under an exclusive `flock` serialises writers so none is lost and every write is checked against the state it lands on. Atomic rename alone lets two writers each replace the other's update. Append-only events replay and validate more simply than a rewritten document; people read `render`. POSIX-only is fine: both hosts run on macOS or Linux.
