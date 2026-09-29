# review reference

This document records the design choices behind
[SKILL.md](SKILL.md). It does not add review steps.

## Findings go through converge

A finding is a claim produced by reasoning that could be wrong about the
codebase. Self-verification inside one invocation is not independent: a
mistaken assumption can survive both the finding and its check. The review
therefore files every claim in a converge slate, where finders, refuters and
cutters are different agents and the ledger, not the reviewer, records what
survived. The model — facts versus choices, role separation and its trust
boundary, computed cutoff — is documented in the converge skill's own
reference; this skill relies on it through the public `converge` CLI and the converge skill only.

Lenses are topics; find angles are ways of looking. Declaring only the angles
whose tell matches the diff, and recording the rest as not applicable, makes
coverage checkable and stops corner-case digging that no tell supports. The
design-pattern catalog adds a cost scenario to each architecture angle,
because a design claim with no concrete cost is an opinion; the design
meanings of the evaluation fields in `references/lenses.md` let the same
cutoff rank design and correctness claims.

The agent budget is at most five agents per task, main
included, for token efficiency — every spawned agent re-reads the diff. One
review slate is one task; a later debate on its choices has its own budget.
So one finder covers every lens (one brief listing all of them and their
angles), refuters and the cutter are reused across rounds, and depth picks the
refuter count: `full` gets two refuters so the gap hunt can be filed by R2 and
refuted by R1 without a claim's finder refuting it; `quick` gets one refuter,
which leaves no agent to refute gap-hunt claims, so `quick` has no gap hunt.
Converge enforces the cap per slate (`caps.agents`). Reusing a refuter across
rounds does not weaken refute: converge's unused-angle rule still forces
every round onto attack angles never used on that claim, which is what a
fresh refuter per angle would otherwise protect. See the converge skill's
reference for the full argument.

The gap hunt runs after the lenses because a finder briefed with the render
so far looks for what every lens missed rather than repeating them, and the
ticket check in both directions catches missing and unasked work that no lens
owns. Its claims face a higher bar (converge's gap-hunt cutoff rule) because
an open-ended "what did everyone miss" search is where corner cases
accumulate.

In a run, the slate id and converge dir are recorded in the decisions so the
`review` node's leave check can run `converge gate` against the ledger rather
than trusting the caller's word that review finished.

## One interface, two entry points

Review findings and comment application share the same review domain but have
different starting states. A new review needs a findings pass. Applying
existing comments does not. Keeping both entry points in one interface gives
callers one handback contract while preserving the shorter application path.

## Override precedence

An active `engine` settlement is the authoritative source for project
review selection. Direct invocation checks project registration because no
settlement has already made that decision.

Passing the exact sub-task label prevents a depth-specific override from being
chosen from assumptions about the diff.

## Acceptance modes

`accepted_only` is the safer default because code changes require an explicit
signal from outside the review that the reviewer wants the proposed change.
The review cannot infer that intent from nearby comments, a general PR
approval, or a question.

`auto_within_permitted_mutations` is separate because it permits automatic
application only when the settlement already authorizes the mutation. The mode
removes the extra per-finding acceptance step; it does not expand the
authorized mutation scope.

## Cutoff decides reporting; the render is the record

Every claim is filed before any cutoff runs, so callers can see every
observed issue in the render's appendix; filtering first would hide
below-cutoff claims. Converge's computed cutoff decides what is reported, so
reporting does not depend on how a reviewer tagged severity. The one exception
is a claim tagged with a review-standard rule at or above the standard's
`cutoff:`: the project already ruled that breaking it must be reported, so the
cut stage's frequency judgment does not get to move it to the appendix.

This preserves the distinction between:

- `clean`: no reported, inconclusive or unconverged claim remains; and
- `below_cutoff`: claims remain, but only in the appendix.

Only `clean` establishes that the change has no remaining, real claim above
the bar — an `inconclusive` or `unconverged` claim still counts as remaining,
since nobody could rule it out.

Auto-apply is limited to reported, survived, trivial or local claims because
those are facts with a contained fix. Cross-cutting and redesign claims carry
a `choice`: the facts are agreed but what to do is not, which is a decision
for debate or the user, not for the review loop.

## Loop outcomes

Each outcome represents a different state:

- `clean` means review left no reported, inconclusive or unconverged claim.
- `below_cutoff` means only appendix claims remain.
- `blocked` means required work needs permission or a decision that is not
  available — including an inconclusive or unconverged claim, an undecided
  `choice`, or a converge role agent that could not run.
- `no_progress` means repeating the attempted fix has produced no new result.
- `iteration_cap` means the configured bound ended the loop while claims
  remain.

These states prevent permission limits, failed fixes, configured standards, and
actual cleanliness from being reported as the same result.

## Reporting categories

The four comment categories account for every in-scope comment and preserve
the difference between completed work, accepted work that could not be
completed, an explicit rejection, and an unresolved interpretation.

Reporting all findings across all iterations preserves the review record when a
later iteration fixes an earlier finding or introduces a new one.

## Depth

Review depth scales with risk through the caller's label. `quick` keeps the
two lenses whose misses cost most on any change — correctness and tests —
with four agents and no gap hunt; `full` adds security, architecture,
simplicity and contract, a second refuter and the gap hunt, for changes whose
failure modes and impact are wider. Defaulting to `full` means an unlabelled
call never silently gets the lighter pass.
