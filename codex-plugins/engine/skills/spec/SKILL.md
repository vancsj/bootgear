---
name: spec
description: Gather requirements, design an approach for real trade-offs, get sign-off, and derive a mechanical task breakdown. Use when requirements, a design choice, or an implementation checklist must be settled before implementation.
---

Use this process unless an override applies.

## Check for an override first

Use this precedence before doing other work, and again before each of the 4
stages below when `spec_override` is a mapping — a bare skill name applies
to the whole task and only needs checking once, but a mapping is keyed by
sub-task label, and each stage (`requirements`, `design`, `review`, `task`)
is its own sub-task that may have its own matching entry:

1. **Active `engine` run.** If the current `<run-id>` has a session ledger, run:

   ```text
   task session read <run-id> --dir <session-dir> --section settlement
   ```

   Read `spec_override` from the settlement, then scan the session ledger's decisions for an `AMENDMENT spec_override` entry — a later, explicit change to this field recorded mid-run. If one exists, its most recent value wins over the field just read.

   - A bare `<skill-name>` applies to the task.
   - A mapping from sub-task label to `<skill-name>` applies to the matching sub-task — for this skill's own stages, use the labels `requirements`, `design`, `review`, `task`.

   `clarify` registers this entry once per run. If it is absent, or a mapping has no matching label for the current stage, use the default for that stage. Do not search for another override.

2. **Standalone invocation.** If there is no active run or session ledger, check whether the current project has a more specialized spec skill whose description matches the task. If one exists, invoke that public skill name and stop.

3. **Default.** Otherwise, run the default implementation below.

Use only clearly named or registered overrides. When invoking one inside an active `engine` run, provide `<run-id>`, `<engine-root>`, and `<session-dir>` — the same three identifiers `execute` received for this run — so it can read the settlement or record its result. Pass each as its own argument to every engine task call; never interpolate one into a shell string with other text.

An override must return each stage's artifact as defined in that stage's own "Return the ... artifact" step below. If it does not, the override is incompatible; fix the override rather than compensating here.

## Default implementation

Five stages: requirements, design, independent review package, task breakdown, and package return. Each returns
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

5. **Return the requirements artifact.** `requirements.md`'s content and suggested path, `requirements-notes.md`'s suggested path, and the open-questions list. `spec` does not decide where either file actually lives — the caller does. A direct caller answers the open questions itself. In an `engine` run, open choice claims are handled by `execute` after independent `spec-review`, through `resolve` and, if needed, `debate`.

### Stage 2: design

Only for a task whose requirements stage found real design trade-offs — an
implementation choice with more than one reasonable shape, not a
mechanical follow-through with one obvious path. Skip straight to the review package
otherwise; see "Progressive disclosure." A skipped stage 2 means stage 3
checks `requirements.md` instead of `design.md` — see "The completeness
check."

1. **Propose an approach.** For each open design trade-off the requirements stage named, state the options actually considered and which one this stage picks. Name what each rejected option would have cost or risked — not just that it was rejected.

2. **Write `design.md`** (skeleton). What changes, where, and in what order — concrete enough that "implement this" doesn't require another design decision mid-build. Cite an existing pattern in the codebase being mirrored, rather than re-deriving a convention already settled elsewhere. Apply the same terseness as `requirements.md`: this file is what stage 3 checks against, so padding here makes the completeness check harder to satisfy honestly, not easier.

3. **Write `design-notes.md`** for rationale only — see "Skeleton and notes." Keep every considered alternative and its cost in `design.md` so independent review can inspect it.

4. **Return the design artifact.** `design.md`'s content and suggested path, `design-notes.md`'s suggested path, and any trade-off it could not resolve on its own — carried into the review package as an open question, not decided here either.

### Stage 3: prepare for independent review

1. **Run the completeness check.** Read only the skeleton artifacts — `requirements.md` and `design.md` when stage 2 ran — never the `-notes.md` files. Apply the four criteria in "The completeness check". If one fails, name the criterion and return to stage 2 or revise requirements before continuing; if stage 2 was skipped and requirements fail, run stage 2 now.

2. **Check the result against `goal` and every constraint stage 1 recorded.** Confirm nothing was dropped or contradicted.

3. **Proceed to task breakdown.** Do not return the review package until the task artifact has been derived in stage 4.

### Stage 4: task breakdown

Only reached once the requirements/design completeness check (stage 3, step 1) has
passed. Never runs before that, and never on a design that failed it.

1. **Derive the checklist.** Write `task.md`: an ordered list of concrete
   implementation steps, each one traceable to a specific statement in
   `design.md` (or `requirements.md` if stage 2 was skipped). Do not add a
   step that makes a choice `design.md` didn't already make.

2. **Refuse structurally on a gap, never decide one.** If a step cannot be
   derived from a single, unambiguous statement in the reviewed
   document — it's silent, ambiguous, or offers more than one *substantive*
   option (what to build, which file, what behavior results) — stop.
   Return no `task.md`; make one bounded loop back within `spec` to stage 2 or stage 3 with
   the specific gap, then derive the task again. If the same gap remains, return `blocked` to
   `execute` with the missing statement as the failure reason. Return instead the specific step you could not
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
   or the structural refusal from step 2 after the one retry is exhausted.

### Re-entry from independent review

When `spec-review` returns `revise`, read its render and claim IDs, address each claim in the skeleton artifacts, rerun stages 3–5, and return the refreshed package. Do not treat the review as a new requirement or silently drop an unresolved claim. A blocked return transitions the run to `failed` with the claim IDs and evidence.

### Stage 5: return review package

Return the requirements, design when stage 2 ran, and `task.md` paths, the open interpretations or material design choices, and the exact repository evidence the independent `spec-review` stage must inspect. Do not call `resolve` or `debate`; the state machine owns those decisions after review.

## Skeleton and notes

Each of `requirements.md`/`design.md` (the skeleton) pairs with
`requirements-notes.md`/`design-notes.md` (its notes file). The skeleton is
the always-read main content: it must state the facts stage 3's
completeness check reads, and only those and closely related ones, as
tersely as the facts allow. The notes file holds rationale, cited
`memory-ledger` entries, and anything else read conditionally rather than by
default. Considered alternatives and their costs belong in the `design.md`
skeleton because independent review must inspect them.

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
review package," step 1. Never proceed to stage 4 on a failing check, and never
let stage 4 make the judgment call this check exists to catch upstream.

## spec_debate_mode

A settlement field, set once by `clarify`, read by the engine after `spec-review`. Two values:

- **`mandatory`** (default): every unresolved choice claim returned by
  `spec-review` is sent to `resolve`; unresolved claims at or above
  `debate_threshold` go to `debate` through the `spec-debate` node.
- **`threshold`**: below-threshold choice claims are decided solo; only
  above-threshold claims are sent to `resolve` and possibly `debate`.

Neither value changes the independent correctness/completeness review. They
only control how the engine handles choice claims after that review; debate
never bypasses a re-review.

## Progressive disclosure

Scale the detail, and the stages actually run, to the task:

- For a small, well-scoped ask with no real design trade-off, use a brief investigation, a terse `requirements.md`, no open questions, skip stage 2 entirely, complete the review package check against `requirements.md`, derive a short `task.md`, and return the package.
- For a large or ambiguous ask, investigate more deeply, write a fuller (but still terse per doc, not per section count) `requirements.md`, list every identified open question, run stage 2 for any real trade-off, and use `spec_debate_mode`/`debate_threshold` to decide whether the engine needs `resolve`/`debate` after review.

## Host mechanics

- Resolve the public session command to `<plugin-root>/scripts/task`.
- Pass `<plugin-root>` as `<engine-root>` in the handoff to this skill.
