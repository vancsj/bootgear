# resolve — design rationale

See SKILL.md § When to run.

`execute` sends disagreements to `resolve` after applying its debate threshold. Below-threshold disagreements are `solo`; disagreements at or above `debate_threshold` require settlement or `debate`.

The before-debate path resolves an unsettled disagreement before any debate starts. The during-debate path handles positions from a stuck round inside an existing debate. Starting a fresh debate from the during-debate path would nest one debate inside another. The existing debate must continue toward `round_cap`.

See SKILL.md § How it works.

`resolve` checks the settlement before starting `debate` because many `execute` disagreements are already answered by `clarify`.

A compacted context can contain a remembered settlement that is no longer reliable. Calling `recall` with the same `run-id`, `plugin-dir`, and `session-dir` restores the current settlement before resolution.

`source_of_truth` is per-domain. A source settled for `scope and outcome`, `current behavior`, `implementation approach`, or `correctness` does not settle a different domain. Conflicting domains and uncovered domains require `debate`.

Before debate, the caller passes decision-specific context rather than the full settlement. The context gives each party the decision, affected domains, complete `source_of_truth`, `debate_threshold`, `task_type`, `goal`, and `principles`. `debate` reads `debate_roster`, `debate_parties`, `debate_round_cap`, `convergence_policy`, `consented_stop_allowed`, and `debate_admission` through its own `recall` call. Debate-owned configuration does not depend on `resolve` relaying the full settlement.

See SKILL.md § Recording the outcome.

An escalation is not a `resolve` decision. `resolve` found no settled source for the question. `debate` records the outcome with `--mode debate`, `debate-capped`, or `debate-degraded`.

See SKILL.md § What resolve is not.

`resolve` must not invent a `source_of_truth` order. An ambiguous or silent settlement requires `debate`; guessing would hide the unresolved decision.
