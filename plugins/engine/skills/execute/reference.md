# execute — design rationale

## Required settlement fields

`clarify` resolves and writes `task_type`, `approach`, `principles`,
`source_of_truth`, `debate_threshold`, `debate_round_cap`,
`convergence_policy`, `consented_stop_allowed`, the run manifest
(`spec_skill`, `test_skill`, `review_skill`, `debate_roster`,
`review_fix_mode`), `autonomy` (`no_further_questions`,
`permitted_mutations`), `goal`, and `state_machine` unconditionally.

An absent required field therefore means the settlement is broken, not
that a default applies. `execute` cannot ask `clarify` to rebuild it
mid-run, so it fails the run instead. See SKILL.md § Picking up from clarify.

## session_dir exact match

`session_dir` is written by `session.py` as `str(path.parent)` from the
single resolution performed by `init`. The `<session-dir>` carried through
each handoff must therefore be the same canonical string.

A relative value reintroduces working-directory dependence. A mismatch
indicates stale context or a different ledger, including another run's
ledger at a different `--dir` with the same run id. See SKILL.md § Picking up from clarify.

## Resolved skill fields

`spec_override`, `test_override`, and `review_override` record the user's
choice, which may be a mapping or absent. `spec_skill`, `test_skill`, and
`review_skill` record the resolved skill for the current delegation.

The manifest fields describe what the run may use; they are not a
dispatch target. An override can change at call time, so reading the
manifest directly can dispatch a stale value. See SKILL.md § Picking up from clarify.

## Separate session.py arguments

Free text can contain backticks, `$(`, or quotes. Interpolating it into
one shell string lets the shell interpret it. Passing each argument
separately keeps it as data. See SKILL.md § Calling session.py safely.

## Settlement field shapes

An empty or placeholder `principles` value reaches every `debate` party
as no constraint. An empty `source_of_truth` mapping leaves `resolve`
without a domain truth source and sends decisions to `debate`
unnecessarily.

Malformed overrides can pass settlement presence checks and fail only
when a domain skill applies its own "Check for an override first" step.
See SKILL.md § Picking up from clarify.

## Debate roster and party shapes

A roster containing only `main-agent` is self-ratification rather than a
debate. A custom roster role without a matching `debate_parties` entry
has no dispatch mechanism.

An unsupported `mechanism` has no dispatch path. A registered party
missing from the roster and a roster role without a registered party
leave the two sides inconsistent. See SKILL.md § Picking up from clarify.

## Debate role encoding

`session.py` rejects `\n` and `\r` through `_single_line`, and a round
entry embeds the role in one `--summary` value. A multiline role makes
the position unrecordable.

`ROUND_ENTRY_RE` finds the role terminator by scanning for the first
`':` after the opening quote. An embedded `':` therefore truncates the
role during read-back and corrupts recorded positions. See SKILL.md § Picking up from clarify.

## Control-loop names

`clarify`, `execute`, `resolve`, `debate`, and `recall` are engine
control steps, not domain skills. `execute` and `resolve` are the
always-admitted and normal escalation paths; `debate` is its own callee;
`clarify` and `recall` have no legitimate direct debate admission.

Allowing these names as overrides or admission targets can replace
domain work with loop control or permit recursive debate calls. See SKILL.md § Picking up from clarify.

## Amendment value shape

`session.py` stores amendment sides as plain text and does not parse a
structured field's shape. A list such as `debate_roster`, a mapping such
as `source_of_truth`, or a multi-part value such as `goal` therefore
requires a complete replacement value.

A diff, field name, or incomplete prose cannot be checked by
`recall`'s cross-field validation or `execute`'s shape validation. See SKILL.md § Applying a mid-run amendment.

## AMENDMENT value boundaries

The first ` -> ` separates the old and new values. Allowing that
substring inside either value makes the amendment ambiguous. See SKILL.md § Applying a mid-run amendment.

## session_dir amendment

An amendment to `session_dir` cannot be found at its new location because
reading the amendment already requires the current `--dir`, which is
provided by `session_dir`. A ledger move therefore requires a fresh
`clarify`/`init`. See SKILL.md § Applying a mid-run amendment.

## Amendment precedence

Amendments are separate decisions because the settlement remains the
original record. A full decisions scan is required because `--last N`
can omit an older authoritative amendment. See SKILL.md § Applying a mid-run amendment.

## permitted_mutations bounds the goal

If `goal` requires a mutation absent from `permitted_mutations`,
performing it would expand the run's authorized scope. The mismatch is a
settlement conflict for `clarify`, not a decision for `execute`. See SKILL.md § Task-type dispatch.

## Threshold routing

A reversible, narrow decision below the threshold does not require
cross-party resolution. A decision at or above the threshold requires
`resolve`, with `debate` reserved for escalation. Recording both solo
and debated decisions would create conflicting settlement records. See SKILL.md § The loop.

## Repeated stuck steps

A stall is not a third outcome, but repeating the same blocked step with
no new information is not progress. The second identical failure triggers
a fresh check of the failed condition instead of a third attempt. See SKILL.md § The loop.

## Exhausted stalls

A run can exhaust every unit of work without matching `goal`'s failed
condition. The exhausted-stall path records that missing condition
coverage while still providing the required terminal `failed` outcome.
See SKILL.md § The loop.

## Missing dependencies

`engine` declares `converge`, `spec`, `test`, `review`, `advisor` and
`memory-ledger` as plugin dependencies, so the platform installs them with it. A required
skill can still be missing, for example after the user removes it. Installing
it is not a `permitted_mutations` action, so the task has no path to done
and must fail rather than retry. See SKILL.md § Delegating to `spec`, `test`,
and `review`.

`memory-ledger` is the one exception to this failure rule: it is never
required for `goal`, so `missing` or `unconfigured` is recorded as a
capability state rather than treated as a task failure — see SKILL.md §
Checking and recording in memory-ledger.

## Skill-tool invocation

Invoke `spec`, `test` and `review` as `spec:spec`, `test:test` and `review:review`:
a bare name fails when another installed plugin ships a skill of the same name.
The platform provides no stronger guarantee for calling them than invoking the
`Skill` tool by that name. Their output must
therefore be read and checked against the request. See SKILL.md § Delegating to `spec`, `test`, and `review`.

## Open debates before close

`close` refuses to end a run while any `[qN]` question remains open.
An interrupted debate can leave that state across a crash, interrupted
session, or compaction, so recall must resume it before new work and
goal-check. See SKILL.md § The loop.

## Close exactly once

A run without `close` has no valid terminal ledger state. An unresumed
open debate causing `close` to refuse is an execution bug, not a normal
outcome; the required recovery is to resume and close the named question,
then retry `close`. See SKILL.md § Ending the run.

## Failed outcome distinction

A matched failed condition means the goal is genuinely undoable. An
exhausted-stall failure means the run lacks a matching failed condition,
not that the goal itself was undoable. The final pitch records the
distinction for the next run. See SKILL.md § Ending the run.
