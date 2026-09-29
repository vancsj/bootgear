---
name: debate
description: Run a multi-party decision debate when `resolve` cannot settle a decision that passes `debate_threshold`; stop at `debate_round_cap`.
---

Run `debate` when `resolve` cannot settle a decision. Treat `debate` as part of
`engine`. Do not require another debate mechanism.

Read `session_dir` from the settlement unconditionally. Pass every free-text
value as its own argument to the public session interface. The CLI owns the
exact command syntax and refusal shape.

## Intake

Before getting a question id, classify the disputed point:

- If reading code, running a check, or re-running a memory-ledger entry's
  evidence can settle it, it is a factual dispute. Refuse it without calling
  `record-decision`, as "Direct calls" refusals do, and hand it back to the
  caller for the `converge` skill.
- If it is a fact no source can settle, report it to the caller as
  `inconclusive`. Do not debate it.
- Otherwise it is a choice. Continue.

## Question id

Before round 1, ask the public session interface for a stable question ID.

Resume an existing debate with its question ID from the session ledger.
If `next-question-id` refuses because a prior question lacks a closing entry,
resume that question instead of starting another.

## Round 0: scoping

Round 0 settles topic, scope, principles, and cutoff threshold. `session.py`
mechanically allows no round 1+ entry before a `scope-settled` close; that
close cannot be the question's first entry.

Each party independently states its own understanding, recorded as
`round 0, party '<role>': ...`. Then discuss and reconcile as an ordinary
round 2+ response: agree, refine, or refute named points.

Every roster party records a real round-0 entry or an
`UNAVAILABLE`/`NO-RESPONSE` marker (see "Unavailable party"); at least one
real entry is required. An all-marker round 0 routes to `debate-degraded`,
not `scope-settled`.

After one discussion pass, the main agent closes round 0 with a synthesis;
unanimity is not required, and `scope_settled:` does not claim full
agreement. Carry unresolved points forward as named caveats; do not extend
round 0.

Record the close through the public session interface with mode
`scope-settled`, the question ID, and a one-line summary naming topic, scope,
principles, cutoff, and preserved dissent.

## Before debating

Confirm that `resolve` ran and did not decide. Accept direct calls only when
`debate_admission` allows them and the "Direct calls" checks pass.

Call `recall --section settlement` and read:

- `debate_roster`
- `debate_parties`
- `debate_round_cap`
- `convergence_policy`
- `consented_stop_allowed`
- `debate_admission`
- `debate_party_config` — the settlement mapping already resolved by
  `task config resolve --name debate-parties`; do not re-read lower layers.
- `source_of_truth`
- `debate_threshold`
- `task_type`
- `goal`
- `principles`

Scan the full decisions section for `AMENDMENT` entries; the latest valid
amendment wins for the next round.

Brief every party in round 1 and later rounds with:

- the plain decision
- `source_of_truth` for every domain
- `debate_threshold` and why the decision reached `debate`
- the run's `task_type` and `goal`
- merged user, project, and task principles

Do not use `approach`.

## Settled facts

Include the caller's converge render, when it has one, in every party's brief
as settled facts. Parties argue only the choice, not the facts in the render.

## Parties

Read stable IDs from `debate_roster`. Invoke exactly its enabled IDs. Record
the stable ID in every round entry; use configured labels only in prose.
A question runs at most 5 parties including `main-agent`; agents used by the
caller's review or converge slate don't count toward it.

For each `debate_party_config.parties.<id>`, apply `label` and `prompt` to the
brief, use `mechanism` when present, and omit the party when `enabled: false`.
Reject an invalid configuration before dispatch.

Use the configured host-supported mechanism for each enabled party. The
built-in IDs are ordinary peers, and custom entries use
`{id, label, prompt, mechanism}`. Require an independent round-1 position and
later responses for every enabled party. Record `UNAVAILABLE` with the
observed failure when a configured dispatch cannot run.

## Rounds

Record one position per party per round. Require independent positions in
round 1; every round 2+ position must explicitly respond to each other
party's latest recorded position by agreeing, refining, or refuting named
points. Record positions as they arrive, preserve earlier positions, and do
not restate unchanged positions.

At each round start:

1. Recall `--section settlement`.
2. Scan the decisions section for `AMENDMENT` entries.
3. Apply the current settlement and amendment state.
4. Brief every party from that recalled state.

Apply amendments to `debate_roster` and `debate_parties` from the next round;
do not restart or invalidate recorded rounds. Continue already-listed parties
in the amended roster. Stop asking removed parties from the next round,
except for one retry already owed; stop them after that retry. Ask added
parties from the next round; treat their first position as an independent
round-1-style position. Keep each absence episode separate from another
party's pending retry.

Apply an amendment to `debate_round_cap` at the next round-start recheck.
Finish the current round under its start state; if the cap is reached, close
at that recheck with `--mode debate-capped`. Run any owed retry first,
regardless of the amended cap.

Treat the start-of-round recheck as atomic. Do not re-brief or re-poll a party
already recorded after a mid-round amendment or apply that amendment to
remaining parties. Apply it at the next round-start recheck.

After compaction, inspect the highest round tagged to this question. A party
is dealt with if the ledger contains either:

```text
round N, party '<role>':
```

or an unavailability marker. If fewer than the full roster are dealt with,
resume that partial round and poll only parties with neither entry. Use the
settlement/amendment state in effect at that round's start recheck. If every
roster party has an entry or marker, treat the round as complete and perform
the next round-start recheck.

Because `session.py` records no recheck marker, recover partial-round start
state as the state strictly before its first recorded response or
unavailability marker; do not add a round-start marker.

### Stuck round

Before the cap, a round is stuck when every party essentially repeats its
prior position unchanged.

Call `resolve` again with the current positions. Ask whether
`source_of_truth` or `principles` settles the disagreement in a way no party
has applied.

When `resolve` decides the issue:

1. Let `resolve` record its own `--mode resolve` entry without `--question`.
2. Require its summary to state that it broke a debate stall.
3. Do not treat that entry as closing this question.
4. Immediately record a closing entry for `<qid>` with
   `--mode debate-capped` and a `round_cap:` summary.
5. Name the resolved answer and cite the `resolve` entry that supplied it.

When `resolve` does not decide the issue, continue toward `round_cap`.

### Unavailable party

Classify a party as unavailable only when a native subagent cannot be created
or times out.

Treat empty output, unparseable output, and multi-line output from a completed
process as responses, not unavailability.

For a non-empty response, record a faithful single-line summary of its
substance. Follow `session.py`'s `_single_line`; do not pass a literal line
break to `record-decision --summary`; condense multi-line responses in your
own words.

For an empty or unparseable response, record:

```text
round N, party '<role>': NO-RESPONSE (<detail>)
```

Put the literal token `NO-RESPONSE` immediately after the colon. Set
`<detail>` to what was observed, such as empty stdout or unparseable output.
Count this placeholder as the party's position for the round.

For genuine process-level unavailability, record immediately:

```text
round N, party '<role>': UNAVAILABLE (<detail>)
```

Put the literal token `UNAVAILABLE` immediately after the colon.

Count an unavailability marker as the party's dealt-with slot for
partial-round recovery. Do not count it as a responding party for unanimity,
`consented_stop`, or closing-mode selection.

When a party responds after an unavailability marker for the same round N:

- Append an ordinary round-N entry if round N+1 has not started and the question
  has not closed.
- Do not edit or remove the marker.
- Use the late response as the actual round-N position for party count,
  unanimity, and the round-N+1 brief.
- If a round-N+1 entry already exists, discard the late response.
- If the question has closed, discard the late response.
- Do not record the late response under round N+1.

Follow `session.py`'s `_max_recorded_round`, round-number comparison, and
`_has_closing_entry` checks.

For every genuine unavailability, first apply the reversibility and impact
test from `debate_threshold` in the settlement.

When the decision is at the high end of what `debate_threshold` sends to
`debate`:

- Fail the stakes assessment; judge using reversibility and blast radius, not a
  numeric scale or field, and state the reasoning.
- Do not use `debate-degraded` under any party count. Treat the absence as a
  stuck round, name the gap, and continue toward a `--mode debate-capped` close
  with a `round_cap:` summary.
- Do not use the party-count rules below. Set `no_further_questions` to
  `true` in v1. Do not pause for a human.

When the stakes assessment passes:

- Count only parties that respond in that round.
- Retry every still-unavailable party exactly once, together, in the next round
  before recording any closing entry. Give one retry round to all parties
  missing when the retry is triggered — not a separate retry per party.
  Brief every party in that round to state `goal: kept` or
  `goal: narrowed <what>` against the current `goal` in its position.
- Give the retry regardless of `debate_round_cap`; run one retry round beyond
  the cap when necessary. Treat this as the only case that may run beyond
  `debate_round_cap` — close every other stall at the cap.

Give each party exactly one retry per continuous absence. Use the retry round as
the next round after the absence begins. Do not give a second retry for the
same continuous absence. Start a new retry episode only after the party has
returned for at least one round and later becomes unavailable again.

Count a returning party from its return round onward. If it has no round-1
position, treat its return position as an independent round-1-style stance but
record it under the current round number. Otherwise require it to respond to
the latest state.

Do not record any entry after the question has a closing entry. Do not record
a closing entry while a retry is owed.

Track staggered absence episodes independently. Recheck all retry obligations
after every completed round, including new absences that begin during another
party's retry round.

After every owed retry has passed:

- Define `responded` as having at least one real, non-marker position recorded
  anywhere in the debate.
- Treat a party whose every recorded entry is `UNAVAILABLE` as not responded.
- If exactly one party has responded, record `--mode debate-degraded` with a
  summary beginning `degraded_convergence:`. State that the debate collapsed
  to that judgment. Name every absence episode and retry.
- If two or more parties have responded and agree unanimously, record
  `--mode debate-degraded` with a summary beginning
  `degraded_convergence:`. Name every absence episode and retry.
- Before either `degraded_convergence` close, every party that has responded
  states `goal: kept` or `goal: narrowed <what>` against the run's current
  `goal` in its position in the last retry round; do not add a round for it. A
  late round-N response does not count. If any says `narrowed`, or a
  responding party has no statement, record `--mode debate-capped` with a
  `round_cap:` summary naming the narrowing or the missing statement instead.
- If two or more parties have responded without unanimity before the cap,
  record `--mode debate-capped`. Name every party ever unavailable, every
  retry, and the dissent.
- Do not use `consented_stop` in a round containing a live absence. Permit
  `consented_stop` in a later full-roster round when every party votes `CUT`.
- If zero parties have ever responded, record `--mode debate-capped` with a
  `round_cap:` summary. Name every unavailable party, every episode, and every
  retry. State that no party ever responded.
- Do not use `debate-degraded` when zero parties have responded.

For every `debate-degraded` entry and every `debate-capped` entry in the
assessment-passes branch, name every missing party, confirm the stakes
assessment, and confirm the one-round retry.

For a high-stakes `round_cap:` close, name the gap and confirm the stakes
assessment. Do not claim that a retry occurred.

## Ending a round

Use exactly one outcome:

- **`unanimous_convergence`** — only when every party agrees on the
  substance, no live objection changes the outcome, the angle round below
  changed nothing, and the agreed answer still delivers the run's current
  `goal` (settlement plus any `AMENDMENT goal`). Only an `AMENDMENT goal`
  narrows the goal; a debate cannot.
- **`consented_stop`** — only when `consented_stop_allowed` is `true` and
  every party in that round explicitly votes `CUT`. Silence, absence, and
  non-response mean non-consent; one `continue` vote rules it out. Record
  every party's last position and every `CUT` voter. Require the main agent to
  state its position and strongest unresolved objection.
- **`round_cap`** — when `debate_round_cap` is reached without either
  outcome. Use default cap `10` unless `clarify` sets another. Require the
  main agent to decide, state its position and strongest unresolved objection;
  record `--mode debate-capped`.

### Angle round

When every party agrees, run one more round before recording
`unanimous_convergence`. Ask the public `converge` command for the `decide`
and `attack` angle lists.

Each party declares at least two of those angles that no party has used on
this question, applies them to the agreed answer, and starts its position
with `angles: <ids>`. It then states whether the agreed answer delivers the
run's current `goal`: `goal: kept`, or `goal: narrowed <what>` naming the
part dropped or called out of scope. A `goal: narrowed <what>` is a new
objection. Record the angle-round position as:

```text
round N, party '<role>': angles: <id>,<id>; goal: kept; <position or response in one line>
```

Record `unanimous_convergence` only if that round changes nothing: no party
changes its position and no new objection is raised. Otherwise continue with
ordinary rounds.

Use `--mode debate-capped` with a `round_cap:` summary when "Stuck round"
breaks a debate before the cap.

A genuine tie is neither `unanimous_convergence` nor `consented_stop`.
Continue to `round_cap` unless every party explicitly votes `CUT`.

`session.py` checks only that a `consented_stop:` summary has content after
the prefix. Enforce `consented_stop_allowed` and the complete `CUT` vote set
yourself.

## Recording

Record each round through the public session interface with this debate's
question ID and a one-line party position.

For a closing outcome, omit the `round N` prefix and record one of the public
outcomes: `unanimous_convergence`, `consented_stop`, `round_cap`, or
`degraded_convergence`. Include the question ID and the outcome's required
positions, dissent, or absence data.

Use only these mode/prefix combinations:

- `--mode debate`: `round N, party ...` or `unanimous_convergence:`
- `--mode debate-capped`: `consented_stop:` or `round_cap:`
- `--mode debate-degraded`: `degraded_convergence:`
- `--mode scope-settled`: `scope_settled:` (closes round 0 only, see
  "Round 0: scoping")

Do not begin a round entry with `unanimous_convergence:` or
`degraded_convergence:`; begin it with
`round N, party '<role>':`.

Record at most one `debate-capped` or `debate-degraded` closing entry. Use
exactly one `debate-capped` outcome: `consented_stop` or `round_cap`.

## Direct calls

Read `debate_admission` from the run manifest.

Allow direct calls only from skills named in `debate_admission`; a missing or
empty list allows none.

Before accepting a direct call, confirm:

- the calling skill is in `debate_admission`
- the decision is stated plainly
- at least two live alternatives are already in conflict
- the calling skill checked its own `source_of_truth` and settled `principles`
- those sources did not decide the issue
- the decision passes `debate_threshold` based on reversibility and impact

Refuse a call that fails any check. Do not call `record-decision`. Tell the
calling skill which check failed and route it through the public `resolve`
skill.

For an accepted call, use the same brief, rounds, and recording. Require the
calling skill to assemble the full brief.

## Host mechanics

- Resolve the public session command to `<plugin-root>/scripts/task`.
- Resolve the public `converge` command through the host adapter.
- Use the host-supported party dispatch mechanism; do not substitute another
  host's mechanism.
