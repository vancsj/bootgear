# clarify — design rationale

## Why clarify owns work questions

Only `clarify` asks work questions, allowing `execute` to run autonomously after `goal` confirmation. `recall`'s lost-`session_dir` question restores a pointer to an already-settled run and does not reopen the work. See SKILL.md § What to settle.

## Why task type is compared literally

Downstream dispatch reads `task_type` as an exact v1 value; descriptions, alternate spellings, and paraphrases are not equivalent. An unmatched value is a broken settlement rather than an approximate task classification. See SKILL.md § What to settle.

## Why state-machine resolution happens in `clarify`, not `execute`

`execute` hard-requires `state_machine` in settlement and never resolves or substitutes one. Resolution is a mechanical procedure with its own pass/fail (`state validate`) and a generated diagram (`state diagram`), so it belongs in the same place tiers 1-3 are already defined and applied — not inferred, defaulted, or skipped silently. See SKILL.md § What to settle.

## Why request assessment is separate from state-machine resolution

Sizing a request (scope, affected surfaces, a coarse estimate) and shaping the workflow graph (which nodes this run needs) are different judgments: one has no binary check, the other has a validator and a diagram. Bundling them into one step risks skipping the judgment call once the mechanical one passes, or vice versa. Both default to skipping the first framing accepted uncritically, which is why investigation happens before task type is settled, not after. See SKILL.md § What to settle.

## Why approach and principles are separate

Approach defines the workflow; principles constrain every step. Keeping them separate distinguishes how the work proceeds from what the run must never do, which `debate` needs when source-of-truth order cannot settle a contested decision. See SKILL.md § What to settle.

## Why source of truth is per-domain, not a flat list

A flat list cannot resolve conflicts: "code always wins" contradicts a ticket changing current behavior. Per-domain authorities for scope/outcome, current behavior, implementation approach, and correctness avoid that conflict. See SKILL.md § What to settle.

## Why debate threshold anchors on reversibility and blast radius

Wrong calls cost more when they are hard to reverse or broad in effect, regardless of perceived difficulty. These axes give `execute` a repeatable test instead of a new judgment call for each decision. See SKILL.md § What to settle.

## Why unavailable-party retries get one extra round

An owed retry is required work for an unavailable party, not ordinary debate continuation. The extra round keeps that obligation distinct from the normal `debate_round_cap`, so any positive cap remains valid. See SKILL.md § What to settle.

## Why `convergence_policy` defaults to unanimous, and why `consented_stop` exists

`unanimous`, not majority: debate should expose disagreement, not override it. If unanimity fails, `consented_stop` and `round_cap` are honest fallbacks: the former requires every party to agree debate is unproductive and vote to stop without substantive agreement; the latter bounds exhaustion and is not resolution. `consented_stop_allowed: false` removes the first fallback. See SKILL.md § What to settle.

## Why autonomy is settled explicitly

Explicit `no_further_questions` keeps `execute` autonomous after goal confirmation, while `permitted_mutations` bounds actions taken without another question. The `recall` exception restores a lost run pointer rather than reopening a work decision. See SKILL.md § What to settle.

## Why domain overrides resolve at call time

The initial specialized-skill question avoids repeated interruption during execution, but dispatch must resolve the current value because a later `AMENDMENT` can change it. Mapping fallback preserves the general default for sub-tasks without a matching label, just as an absent override does. See SKILL.md § What to settle.

## Why the run manifest exists separately from the override fields

Overrides record the user's choice; the manifest records resolved, available capabilities. `recall` restores the manifest after compaction because compaction can lose which skills and agents are available, not merely what was decided. See SKILL.md § What to settle.

## Why the manifest is a planned-capability list, not a prediction

The manifest lists capabilities this run may call, not every transitive helper or incidental tool. The `decisions` log records actual calls as they happen; a prediction would be stale before `execute` ends and add nothing. See SKILL.md § What to settle.

## Why `goal` stays high-level

A short high-level `goal` gives `execute` a completion boundary without prescribing the implementation. A task-specific failed condition distinguishes no path to completion from a temporary stall; generic placeholders cannot make that distinction. See SKILL.md § Drafting `goal`.

## Why `${CLAUDE_SESSION_ID}` supplies `run-id`

`${CLAUDE_SESSION_ID}` identifies the active Claude Code session in skill body text, giving the settlement the real run identity required by `init`. See SKILL.md § Writing the settlement.

## Why `init` owns `session_dir`

`init` is the one process that resolves `--dir` and writes the settlement, so it knows the exact absolute path it stored. A separate earlier command could use a different working directory, and caller prediction could diverge; replacing any caller-supplied value prevents a stale or guessed pointer. The printed `INIT <path>` line exposes the same stored path. See SKILL.md § Writing the settlement.

## Why `session_dir` travels through every handoff

Writing the path into the ledger helps after the ledger is located, not before: `recall` needs `--dir` to locate the ledger file before it can read its contents. Unconditional propagation keeps every handoff addressable and avoids assuming that the default path is still correct until the first successful post-compaction `recall`. See SKILL.md § Writing the settlement.

## Why the existing-ledger refusal does not get a suffix

An existing ledger at the run path indicates that `clarify` is being rerun for the same session. Appending a suffix would create a second run identity instead of preserving the existing settlement and ledger. See SKILL.md § Writing the settlement.

## Why the settlement is write-once

If a settled item proves wrong mid-run, an amendment belongs in the ledger's `decisions` section instead of silently rewriting the initial settlement. `execute` records the amendment there, not through a `clarify` update path, so the ledger preserves both the initial settlement and later changes. See SKILL.md § Writing the settlement.
