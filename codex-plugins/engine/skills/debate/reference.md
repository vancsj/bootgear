# debate — design rationale

`SKILL.md` defines the procedure. This file explains the design choices.

## Full brief

See `SKILL.md` § Before debating. Every party receives every `source_of_truth`
domain because an untouched domain may still decide the question. Limiting the
brief to escalation-named domains could hide an applicable principle.

## Independent round 1

See `SKILL.md` § Parties and § Rounds. Recording round-1 positions before
showing them to other parties reduces first-speaker bias. The rule controls the
brief, not the technical isolation of newly spawned agents.

## Roster size

The `main-agent` counts because it contributes a
judgment. Excluding it would change unanimity for the default three-party
roster.

## Stuck rounds

See `SKILL.md` § Stuck round. Repeating positions does not reveal a principle
that nobody applied. A second `resolve` call checks the current positions
against `source_of_truth` and `principles`; continuing without new evidence
adds no decision value.

## Missing parties

See `SKILL.md` § Unavailable party. Agreement among remaining parties does not
prove that a reduced roster is safe. Reusing the reversibility and impact test
gives a missing party the same treatment as an initially insufficient roster.

## Unanimity

See `SKILL.md` § Ending a round. Majority voting discards an unresolved
holdout's information. `debate` requires convergence or an explicit stop.

## `consented_stop` and `round_cap`

See `SKILL.md` § Ending a round. `consented_stop` records an explicit group
decision to stop. `round_cap` records failure to agree by the limit. They
therefore provide different settlement signals despite sharing
`--mode debate-capped`.

## `debate-degraded` and `debate-capped`

See `SKILL.md` § Unavailable party and § Ending a round. Agreement with a
reduced roster is `debate-degraded`; failure to reach agreement before the cap
is `debate-capped`. The outcomes are mutually exclusive.

## Direct-call refusal

See `SKILL.md` § Direct calls. `solo` records an actual below-threshold
decision. A refused direct call reaches no decision, so recording any
`record-decision` mode would falsely represent it as settled. This matches
`resolve`'s escalation behavior.

## Facts versus choices

See `SKILL.md` § Intake, § Settled facts and § Angle round. A factual dispute
has an answer that code, a check or a ledger entry's evidence can produce;
debating it trades evidence for persuasion, and a debate verdict on a fact
would read as settled when nobody checked it. The converge skill settles facts
with separate finders, refuters and cutters, so `debate` refuses them and
hands them back. The refusal records nothing for the same reason a refused
direct call records nothing: no decision was reached. A fact no source can
settle stays `inconclusive` rather than being voted into a fact.

Giving every party the converge render as settled facts keeps the rounds on
the remaining choice instead of re-arguing claims that already survived
refutation.

Agreement reached from the same starting framing can share the same blind
spot. The angle round makes each party look at the agreed answer from at
least two decide or attack angles nobody has used on the question yet;
unanimity stands only if that changes nothing. Declaring the angles in the
round entry makes "unused" checkable from the session ledger. The round uses
the ordinary round-entry grammar, so the session ledger is unchanged.

## Engine boundary

Keeping `debate` within `engine` prevents callers from assuming a second debate
framework is required.

## Session directory

The public contract requires `session_dir` in the settlement, including the
default location. Passing it on every `session.py` call keeps session reads and
writes on the same run.

## Question ids

See `SKILL.md` § Question id. One open question at a time lets
The recall contract's last `[qN]` tag identifies the debate to resume. Reusing
the existing id preserves one ledger history across compaction or interruption.

## Settlement recall

See `SKILL.md` § Before debating and § Rounds. The escalation payload is
decision-specific and may omit the run manifest. A resumed caller may have no
settlement context, and an `AMENDMENT` may have landed after `resolve`'s
recall. Fresh settlement recall prevents stale roster, cap, policy, or brief
data.

## Roster selection

See `SKILL.md` § Parties. `clarify` proposes the full three-built-in roster but
does not require it as a floor. Requiring `main-agent` plus one other party
prevents a self-debate whose only possible result is agreement with itself.

## Built-in role literals

See `SKILL.md` § Parties. The short literals distinguish built-in roles from
unregistered custom roles in the execute contract's roster check. Longer
descriptions would break that classification.

## Custom parties

See `SKILL.md` § Parties. Custom parties are peers rather than sequential
reviewers, so they need independent first positions and later responses.
Unique role labels keep ledger entries and roster amendments unambiguous.

## Ledger order

See `SKILL.md` § Rounds. Recording positions as they arrive preserves evidence
that can be inspected after compaction. Reconstructing positions from context
could lose or alter an earlier judgment.

## Amendment rechecks

See `SKILL.md` § Rounds. Amendments can arrive between rounds and after
`resolve`'s earlier recall. Applying roster and cap changes only at the next
round boundary preserves already-recorded work while making later rounds use
current settlement state.

## Round atomicity

See `SKILL.md` § Rounds. A round must represent one brief and one settlement
state. Applying a mid-round amendment to only some parties would make the
round's positions incomparable.

## Partial-round recovery

See `SKILL.md` § Rounds. The ledger must distinguish a complete round from a
partial one after compaction. `session.py` records party actions but not the
recheck itself, so the state immediately before the first action is the
closest recoverable approximation. Adding a round-start marker would close
that narrow timing gap at the cost of an extra write per round.

## Unavailable responses

See `SKILL.md` § Unavailable party. Process failure and poor party output are
different events. Treating empty or malformed output as unavailable would
invent a failure and trigger an unjustified retry.

## Response markers

See `SKILL.md` § Unavailable party. `NO-RESPONSE` distinguishes a completed
but unusable process result from `UNAVAILABLE`, which identifies a process
failure. The literal prefixes make both cases mechanically identifiable.

## Availability counts

See `SKILL.md` § Unavailable party and § Rounds. Recovery asks whether every
party was dealt with; unanimity asks how many parties actually responded.
Counting an unavailability marker for both questions would conflate those
states.

## Late responses

See `SKILL.md` § Unavailable party. `session.py` is append-only and enforces
non-decreasing round numbers and closing-entry finality. The deadline prevents
a late round-N result from changing a later round or reopening a closed
question.

## Stakes assessment

See `SKILL.md` § Unavailable party. A reduced roster is acceptable only when
the decision's reversibility and impact make the missing judgment tolerable.
The same test keeps an initially small roster and a temporarily reduced roster
under one safety standard.

## High-stakes absence

See `SKILL.md` § Unavailable party. High-stakes decisions cannot be settled by
agreement among fewer parties. The branch therefore preserves the unresolved
gap and uses the capped outcome without pretending that degraded convergence
occurred.

## Retry rounds

See `SKILL.md` § Unavailable party. A single missed round does not establish
that a party cannot contribute. One shared retry gives every missing party a
fair opportunity while preventing one absence from creating an unbounded
debate.

## Continuous absences

See `SKILL.md` § Unavailable party. One retry per continuous absence avoids both
repeatedly retrying the same failure and permanently denying a party that later
returns after a distinct failure.

## Returning parties

See `SKILL.md` § Unavailable party. A returning party must affect later
judgments immediately, so the reduced count cannot persist. A party without a
round-1 position needs an independent stance rather than a response shaped by
positions it never saw.

## Staggered absences

See `SKILL.md` § Unavailable party. Different parties can fail in different
rounds, so retry obligations must be tracked per episode instead of assuming
one contiguous absence window.

## Degraded closure

See `SKILL.md` § Unavailable party. A single surviving judgment can be recorded
as degraded convergence, and multiple surviving judgments can use that outcome
only when they agree. Zero real positions cannot converge, so it requires a
capped close.

## Consent during absence

See `SKILL.md` § Unavailable party and § Ending a round. A party that is absent
cannot cast `CUT`, so a live absence prevents consented stopping in that round.
Once the full roster returns, a later unanimous `CUT` vote is independently
valid.

## Recording modes

See `SKILL.md` § Recording. `session.py` uses mode and prefix combinations to
classify in-progress positions and closing entries. Reserved prefixes prevent
party text from being mistaken for a close, and append-only closing entries
prevent a closed question from being reopened.

## Closing entries

See `SKILL.md` § Recording. Limiting a question to one closing entry keeps its
terminal state unambiguous. Making `debate-capped` choose exactly one outcome
preserves the distinction between explicit consent and unresolved disagreement.
