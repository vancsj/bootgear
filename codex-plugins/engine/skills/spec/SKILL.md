---
name: spec
description: Gather requirements, design an approach for real trade-offs, get sign-off, and derive a mechanical task breakdown. Use when requirements, a design choice, or an implementation checklist must be settled before implementation.
---

Use this process unless an override applies.

## Check for an override first

Use this precedence before doing other work, and again before each of the 4
stages below when `spec_override` is a mapping — a bare skill name applies
to the whole task and only needs checking once, but a mapping is keyed by
sub-task label, and each stage (`requirements`, `design`, `sign-off`, `task`)
is its own sub-task that may have its own matching entry:

1. **Active `engine` run.** If the current `<run-id>` has a session ledger, run:

   ```text
   task session read <run-id> --dir <session-dir> --section settlement
   ```

   Read `spec_override` from the settlement, then scan the session ledger's decisions for an `AMENDMENT spec_override` entry — a later, explicit change to this field recorded mid-run. If one exists, its most recent value wins over the field just read.

   - A bare `<skill-name>` applies to the task.
   - A mapping from sub-task label to `<skill-name>` applies to the matching sub-task — for this skill's own stages, use the labels `requirements`, `design`, `sign-off`, `task`.

   `clarify` registers this entry once per run. If it is absent, or a mapping has no matching label for the current stage, use the default for that stage. Do not search for another override.

2. **Standalone invocation.** If there is no active run or session ledger, check whether the current project has a more specialized spec skill whose description matches the task. If one exists, invoke that public skill name and stop.

3. **Default.** Otherwise, run the default implementation below.

Use only clearly named or registered overrides. When invoking one inside an active `engine` run, provide `<run-id>`, `<engine-root>`, and `<session-dir>` — the same three identifiers `execute` received for this run — so it can read the settlement or record its result. Pass each as its own argument to every engine task call; never interpolate one into a shell string with other text.

An override must return each stage's artifact as defined in that stage's own "Return the ... artifact" step below. If it does not, the override is incompatible; fix the override rather than compensating here.

## Default implementation

Four stages: requirements, design, sign-off, task breakdown. Each returns
its own artifact via its own "Return the ... artifact" step; nothing here
decides an open question itself. Stages 1 and 2 each write two files — see
"Skeleton and notes" below.

### Stage 1: requirements

1. **Investigate.** Read the supplied ticket, bug report, or request. Inspect current behavior in the relevant codebase area before writing requirements.

2. **Write `requirements.md`** (skeleton — see "Skeleton and notes"). State:

   - what the feature, fix, or task must do;
   - its constraints;
   - its boundaries, including explicit out-of-scope items;
   - the current behavior observed and where it is located;
   - the specific compatibility target, rather than only "preserve compatibility".

   Write this as tersely as the facts allow: bullets over prose, no
   restating context already in the ticket or settlement, no padding. Keep
   only what's specific to this task; see "Cite-not-embed" below for
   durable rationale.

   `goal` in an `engine` run is a short done-condition. `requirements.md`
   is the fuller description that makes that done-condition checkable.

3. **Write `requirements-notes.md`** for rationale — see "Skeleton and notes."

4. **List open questions.** Record conflicting signals, missing ticket details, and design choices with real trade-offs. Do not guess or run `resolve` or `debate`; this stage produces the artifact and does not decide its own open questions.

5. **Return the requirements artifact.** `requirements.md`'s content and suggested path, `requirements-notes.md`'s suggested path, and the open-questions list. `spec` does not decide where either file actually lives — the caller does. A direct caller answers the open questions itself. In an `engine` run, `execute` runs `resolve` and, if needed, `debate` for each one before design starts.

### Stage 2: design

Only for a task whose requirements stage found real design trade-offs — an
implementation choice with more than one reasonable shape, not a
mechanical follow-through with one obvious path. Skip straight to sign-off
otherwise; see "Progressive disclosure." A skipped stage 2 means stage 3
checks `requirements.md` instead of `design.md` — see "The completeness
check."

1. **Propose an approach.** For each open design trade-off the requirements stage named, state the options actually considered and which one this stage picks. Name what each rejected option would have cost or risked — not just that it was rejected.

2. **Write `design.md`** (skeleton). What changes, where, and in what order — concrete enough that "implement this" doesn't require another design decision mid-build. Cite an existing pattern in the codebase being mirrored, rather than re-deriving a convention already settled elsewhere. Apply the same terseness as `requirements.md`: this file is what stage 3 checks against, so padding here makes the completeness check harder to satisfy honestly, not easier.

3. **Write `design-notes.md`** for rationale — see "Skeleton and notes."

4. **Return the design artifact.** `design.md`'s content and suggested path, `design-notes.md`'s suggested path, and any trade-off it could not resolve on its own — carried into sign-off as an open question, not decided here either.

### Stage 3: sign-off

1. **Run the completeness check.** Read only `design.md` (or, if stage 2 was skipped, `requirements.md`) — never the `-notes.md` file. See "The completeness check" for the exact criteria. If a change fails a criterion, name the failing criterion and the change. If `design.md` failed, return to stage 2 with the specific gap. If `requirements.md` failed because stage 2 was skipped, run stage 2 now — the failure means this task needed the design stage after all, so the check both catches the gap and corrects the skip. Do not proceed to the next step until this passes.

2. **Check the result against `goal` and every constraint stage 1 recorded.** Confirm nothing was dropped or contradicted.

3. **Judge whether this needs more than a solo sign-off.** Read `spec_debate_mode` from the settlement (default `mandatory`; see "spec_debate_mode"). Under `mandatory`, always attempt `resolve` on `requirements.md` and `design.md` together, or on `requirements.md` alone if stage 2 was skipped; escalate to `debate` only if `resolve` cannot decide and the disagreement is at or above `debate_threshold`. Under `threshold`, use `execute`'s own below-threshold solo-decision rule instead: sign off directly when the task is narrow, reversible, and has no open design trade-off (or one already resolved in stage 2); attempt `resolve`/escalate only at or above threshold. Either way, do not call `resolve`/`debate` directly from inside `spec`: report the specific unresolved trade-off as this stage's open question instead. In an `engine` run, `execute` runs `resolve`, then `debate` if needed, using its own `spec-debate` node — calling either directly from inside `spec` has no admission path and would debate the same trade-off `spec-debate` already exists to debate. A standalone caller without an active run resolves it itself.

4. **Iterate on rejection.** If sign-off rejects the design (from either step 1 or step 3), return to stage 2 with the specific objection; do not silently patch the artifact and re-submit without naming what changed and why.

5. **Return the sign-off artifact.** The final shape, ready for stage 4 if signed off, or the specific open trade-off if it needs `resolve`/`debate` first.

### Stage 4: task breakdown

Only reached once sign-off's completeness check (stage 3, step 1) has
passed. Never runs before that, and never on a design that failed it.

1. **Derive the checklist.** Write `task.md`: an ordered list of concrete
   implementation steps, each one traceable to a specific statement in
   `design.md` (or `requirements.md` if stage 2 was skipped). Do not add a
   step that makes a choice `design.md` didn't already make.

2. **Refuse structurally on a gap, never decide one.** If a step cannot be
   derived from a single, unambiguous statement in the signed-off
   document — it's silent, ambiguous, or offers more than one *substantive*
   option (what to build, which file, what behavior results) — stop.
   Return no `task.md`. Return instead the specific step you could not
   derive and the missing or ambiguous statement. Do not choose, do not
   infer the likely intent, do not call `resolve` or `debate`, and do not
   record the gap as an open question of your own; report it and stop.
   This should not happen if stage 3's completeness check passed
   correctly — treat it as a signal that the check missed something, not
   as a decision for this stage to make.

   Picking a physical list order for changes criterion 3 declared
   order-independent is not a substantive option under this rule — the
   design already said the order doesn't matter, so any order the
   checklist prints them in is equally correct. Refusing here would
   penalize a design for correctly declaring order-independence.

3. **Return the task artifact.** `task.md`'s content and suggested path,
   or the structural refusal from step 2.

## Skeleton and notes

Each of `requirements.md`/`design.md` (the skeleton) pairs with
`requirements-notes.md`/`design-notes.md` (its notes file). The skeleton is
the always-read main content: it must state the facts stage 3's
completeness check reads, and only those and closely related ones, as
tersely as the facts allow. The notes file holds rationale, cited
`memory-ledger` entries, considered-and-rejected alternatives, and
anything else read conditionally rather than by default.

The completeness check (stage 3, step 1) reads only the skeleton files,
never a `-notes.md` file. This is structural, not a policy the check
enforces: a fact that exists only in a notes file is invisible to the
check and cannot satisfy or fail a criterion. So the boundary runs the
other way — a notes file must never be the *sole* location of a
criteria-relevant fact, or the doc's overall record misleads a later
reader even though the gate itself can't be fooled by it. Write every
fact the criteria test into the skeleton; the notes file may explain or
justify it, not carry it alone.

## The completeness check

Stage 3 reads the skeleton file under check (`design.md`, or
`requirements.md` if stage 2 was skipped) against these four criteria.
Check each one by reading; none require an aggregate judgment:

1. Every change names a specific file, or a named new file, plus the
   function, section, or heading within it.
2. Each change states the resulting behavior, not only the edit.
3. The changes have a stated order, or are explicitly declared
   order-independent.
4. No change is stated as "TBD," "to be decided during implementation,"
   "depends on," or "either X or Y."

If any criterion fails, name the failing criterion and the specific change
that fails it, and run or return to stage 2 as described in "Stage 3:
sign-off," step 1. Never proceed to stage 4 on a failing check, and never
let stage 4 make the judgment call this check exists to catch upstream.

## spec_debate_mode

A settlement field, set once by `clarify`, read by stage 3. Two values:

- **`mandatory`** (default): stage 3 always attempts `resolve` on
  `requirements.md` and `design.md` together, escalating to `debate` (via
  `execute`'s `spec-debate` node, never a direct call from `spec`) only if
  `resolve` cannot decide and the disagreement is at or above
  `debate_threshold`.
- **`threshold`**: sign off solo below
  `debate_threshold`, attempt `resolve`/escalate only at or above it.

Either value leaves the completeness check (stage 3, step 1) and stage 4's
non-escalation unchanged; `spec_debate_mode` only changes how often stage 3
attempts `resolve`, never whether stage 4 can reach `resolve`/`debate` — it
never can, under either value.

## Progressive disclosure

Scale the detail, and the stages actually run, to the task:

- For a small, well-scoped ask with no real design trade-off, use a brief investigation, a terse `requirements.md`, no open questions, skip stage 2 entirely, sign off in stage 3 against `requirements.md`, and derive a short `task.md` in stage 4.
- For a large or ambiguous ask, investigate more deeply, write a fuller (but still terse per doc, not per section count) `requirements.md`, list every identified open question, run stage 2 for any real trade-off, and use `spec_debate_mode`/`debate_threshold` to decide whether sign-off needs `resolve`/`debate`.

## Host mechanics

- Resolve the public session command to `<plugin-root>/scripts/task`.
- Pass `<plugin-root>` as `<engine-root>` in the handoff to this skill.
