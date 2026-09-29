# spec reference

This document records the design choices behind
[SKILL.md](SKILL.md). It does not add spec steps.

## Four stages, not one pass

A single requirements-and-questions pass conflates two different kinds of
work: finding out what's needed (requirements) and deciding how to build it
when more than one shape would work (design). Folding design into
requirements either skips real trade-offs or bloats every requirements
statement with implementation detail a small task never needed. Splitting
lets a mechanical task skip stage 2 entirely while a genuinely ambiguous
one gets a dedicated pass, and lets sign-off check the actual shape that
will be built rather than a requirements paragraph that never committed to
one. Stage 4 is split out for the same reason design was split from
requirements: turning a signed-off design into an ordered checklist is a
different kind of work again, mechanical rather than exploratory, and
giving it its own stage is what makes its non-escalation guarantee
possible to state and check — see "Why stage 4 can never escalate."

## Sign-off reports the decision, execute makes it

A design's sign-off is itself a decision, and engine already has a rule
for which decisions need more than one party: `debate_threshold`. Giving
sign-off a separate, spec-specific escalation rule would duplicate that
mechanism and risk drifting from it. But `spec` calling `resolve`/`debate`
directly would duplicate `ticket-to-pr.yaml`'s own `spec-debate` node — the
same trade-off debated twice, once invisibly inside `spec` and once in the
node that exists for exactly this. So stage 3 reports an above-threshold
trade-off as an open question instead, and `execute`'s `spec-debate` node
runs the actual `resolve`/`debate` — one reversibility/blast-radius
judgment for the whole run, made in one visible place, not duplicated
inside a domain skill.

`spec_debate_mode: mandatory` changes only how often stage 3 *attempts*
`resolve` — always, rather than only above `debate_threshold` — not
whether an escalation, once needed, still routes through `spec-debate`
rather than a direct call. The distinction that matters isn't
attempt-frequency, it's who's allowed to actually run `debate`; that
stays exactly as before.

## Why stage 4 can never escalate

A checklist derived from a design can only be as concrete as the design
allows. If the design under-specifies something, deriving a checklist
from it means either inventing the missing decision (a judgment call) or
flagging it somehow — and flagging it in `task.md` itself, even as an
unescalated caveat, still leaves a real unresolved decision sitting in
the one artifact meant to require no more decisions. That was considered
and rejected: it just relocates the judgment call into a different
document instead of removing it.

The actual fix is upstream: stage 3's completeness check (see "The
completeness check") gates entry to stage 4 on the design already being
concrete enough that deriving a checklist requires no new judgment call.
This makes non-escalation a property of what reaches stage 4, not a
promise about how stage 4 behaves once there. Stage 4 itself still gets
one more layer for when the check was wrong: derive cleanly, or refuse
structurally by naming the specific gap and returning no artifact — never
choosing, inferring, or recording its own open question. Both of stage
4's exits are non-decisions, so there is nothing for any escalation path
to admit.

The completeness check runs against the skeleton file only
(`design.md`/`requirements.md`), never the paired `-notes.md` file — see
"Skeleton and notes." This makes the boundary structural rather than a
rule the check has to actively enforce: a fact that exists only in notes
is invisible to the check, so it cannot make an incomplete skeleton pass.

## Skeleton and notes

Splitting each doc into an always-read skeleton and a conditionally-read
notes file is a direct extension of "Terse skeleton, not terse content"
below: the skeleton is what both a human and stage 3's completeness check
read by default, so keeping it lean serves both readers at once. Physical
files, not sections within one file, were chosen over the alternative
(one file per stage with an internal `## Rationale` heading) because the
completeness check then has an architectural reason to never see notes
content, rather than a self-imposed rule about which section to skip —
the same shape as the rest of this design's preference for structural
guarantees over instructions trusted to be followed.

## Terse skeleton, not terse content

Conciseness and cite-not-embed solve different problems and both are
needed. Cite-not-embed shortens durable, cross-run rationale by citing a
`memory-ledger` entry instead of restating it — but it says nothing about
this task's own specific content (what must be built, which files, what
behavior results), which always stays inline regardless of memory-ledger.
Without a separate conciseness rule, that inline content can still bloat
without limit, which is the actual failure mode this rule prevents. So skeleton files apply both: durable rationale gets cited rather
than restated, and whatever content remains gets written as tersely as
the facts allow — bullets over prose, no restating context already
available in the ticket or settlement, no padding.

Terseness is deliberately not slack on the completeness criteria: a
change with no stated file, behavior, or order still fails "The
completeness check" no matter how short the overall document is.
Brevity that omits a required fact is not concise, it's incomplete — the
four criteria are what keeps the two from being confused with each
other.

## Cite-not-embed

Requirements and design both explain why current behavior or a chosen
pattern is the way it is. When that "why" would still be true on a later,
unrelated task, restating it inline duplicates whatever already recorded
it and drifts from that source over time. Citing a `memory-ledger` entry
keeps one place correcting itself as understanding changes, and the doc
carries only what's genuinely specific to this task's scope. This content
belongs in the `-notes.md` file, not the skeleton — see "Skeleton and
notes."
