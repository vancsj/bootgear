---
name: spec
description: Gather requirements, design an approach for real trade-offs, get sign-off, and derive a mechanical task breakdown — investigating current behavior, listing open questions instead of guessing, and skipping stages a small task doesn't need. Terse skeleton docs with rationale kept in a separate notes file. Runs standalone and delegates to a project-specific spec skill when one is registered. Use when requirements, a design choice, or an implementation checklist must be settled before implementation.
---

Use this process unless an override applies.

## Inputs and outcomes

Inputs: the ticket, bug report, or request; the codebase; in an active run,
also `<run-id>`, `<engine-root>`, `<session-dir>`, and the stage sub-task
label; on re-entry, the `spec-review` render and claim IDs.

Hand back to the caller (`execute` in an active run, the user standalone)
exactly one outcome:

- **package** (stage 5): the requirements, design when stage 2 ran, and
  `task.md` paths, the open interpretations or material design choices, and
  the exact repository evidence the independent `spec-review` stage must
  inspect.
- **`blocked`** (stage 4): the step that could not be derived and the
  missing or ambiguous statement; on re-entry, also the claim IDs and
  evidence.
- **delegated**: an override ran; it returns each stage's artifact as defined
  in that stage's "Return the ... artifact" step.

The default implementation hands back once, at stage 5, with every stage's
artifact included. A stage's artifact is returned on its own only when an
override handles that stage.

## Workflow

1. Check for an override; delegate if one applies.
2. Stage 1: requirements.
3. Stage 2: design, only for real trade-offs.
4. Stage 3: completeness check; on a failure, go back to stage 2 or revise
   requirements.
5. Stage 4: task breakdown; on a gap, one loop back to stage 2 or 3, then
   `blocked`.
6. Stage 5: return the package to the caller, who runs `spec-review`.
7. On `revise`, re-enter at stage 3 and return a refreshed package.

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

2. **Standalone invocation.** If there is no active run or session ledger, check whether the current project has a more specialized spec skill whose description matches the task. If one exists, invoke it and stop.

3. **Default.** Otherwise, run the default implementation below.

Use only clearly named or registered overrides. When invoking one inside an active `engine` run, provide `<run-id>`, `<engine-root>`, and `<session-dir>` — the same three identifiers `execute` itself received for this run — so it can read the settlement or record its result. Pass each as its own argument to any session call it makes; never interpolate one into a shell string with other text.

An override must return each stage's artifact as defined in that stage's own "Return the ... artifact" step below. If it does not, the override is incompatible; fix the override rather than compensating here.

## Default implementation

Five stages: requirements, design, independent review package, task breakdown, and package return. Each returns
its own artifact via its own "Return the ... artifact" step; nothing here
decides an open question itself. Stages 1 and 2 each write two files — see
"Skeleton and notes" below.

### Scale to the task

Scale the detail, and the stages actually run, to the task:

- For a small, well-scoped ask with no real design trade-off, use a brief investigation, a terse `requirements.md`, no open questions, skip stage 2 entirely, complete the review package check against `requirements.md`, derive a short `task.md`, and return the package.
- For a large or ambiguous ask, investigate more deeply, write a fuller (but still terse per doc, not per section count) `requirements.md`, list every identified open question, run stage 2 for any real trade-off, and use `spec_debate_mode`/`debate_threshold` to decide whether the engine needs `resolve`/`debate` after review.

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
   only what's specific to this task; see "Skeleton and notes" below for
   durable rationale.

   In an `engine` run, `requirements.md` makes the short `goal` checkable.

3. **Write `requirements-notes.md`** for rationale — see "Skeleton and notes."

4. **List open questions.** Record conflicting signals, missing ticket details, and design choices with real trade-offs. Do not guess or run `resolve` or `debate`; this stage produces the artifact and does not decide its own open questions.

5. **Return the requirements artifact.** `requirements.md`'s content and suggested path, `requirements-notes.md`'s suggested path, and the open-questions list. `spec` does not decide where either file actually lives — the caller does. A direct caller answers the open questions itself. In an `engine` run, open choice claims are handled by `execute` after independent `spec-review`, through `resolve` and, if needed, `debate`.

### Stage 2: design

Only for a task whose requirements stage found real design trade-offs — an
implementation choice with more than one reasonable shape, not a
mechanical follow-through with one obvious path. Skip straight to the review package
otherwise; see "Scale to the task." A skipped stage 2 means stage 3
checks `requirements.md` instead of `design.md` — see "The completeness
check."

1. **Propose an approach.** For each open design trade-off the requirements stage named, state the options actually considered and which one this stage picks. Name what each rejected option would have cost or risked — not just that it was rejected.

2. **Write `design.md`** (skeleton). What changes, where, and in what order — concrete enough that "implement this" doesn't require another design decision mid-build. Cite an existing pattern in the codebase being mirrored, rather than re-deriving a convention already settled elsewhere. Apply the same terseness as `requirements.md`.

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

   Ordering changes the design declared order-independent (criterion 3) is
   not a substantive option under this rule.

3. **Return the task artifact.** `task.md`'s content and suggested path,
   or the structural refusal from step 2 after the one retry is exhausted.

### Stage 5: return review package

Return the requirements, design when stage 2 ran, and `task.md` paths, the open interpretations or material design choices, and the exact repository evidence the independent `spec-review` stage must inspect. Do not call `resolve` or `debate`; the state machine owns those decisions after review.

### Re-entry from independent review

When `spec-review` returns `revise`, read its render and claim IDs, address each claim in the skeleton artifacts, rerun stages 3–5, and return the refreshed package. Do not treat the review as a new requirement or silently drop an unresolved claim. If stage 4 returns `blocked` on re-entry, return `blocked` with the claim IDs and evidence.

## Skeleton and notes

Each of `requirements.md`/`design.md` (the skeleton) pairs with
`requirements-notes.md`/`design-notes.md` (its notes file). The skeleton is
the always-read main content: it must state the facts stage 3's
completeness check reads, and only those and closely related ones, as
tersely as the facts allow. The notes file holds rationale, cited
`memory-ledger` entries, and anything else read conditionally rather than by
default. Considered alternatives and their costs belong in the `design.md`
skeleton because independent review must inspect them.

Terseness never excuses a missing fact: a change with no stated file,
behavior, or order still fails "The completeness check" however short the
document is.

Cite-not-embed: when a "why" would still hold on a later, unrelated task,
cite a `memory-ledger` entry instead of restating it, and put it in the
`-notes.md` file, not the skeleton.

The completeness check (stage 3, step 1) reads only the skeleton files,
never a `-notes.md` file. Write every fact the criteria test into the
skeleton; the notes file may explain or justify it, never carry it alone.

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
prepare for independent review," step 1. Never proceed to stage 4 on a
failing check, and never let stage 4 make the judgment call this check
exists to catch upstream.

## spec_debate_mode

A settlement field, set once by `clarify`, read by the engine after `spec-review`. Two values:

- **`mandatory`** (default): every unresolved choice claim returned by
  `spec-review` is sent to `resolve`; unresolved claims at or above
  `debate_threshold` go to `debate` through the `spec-debate` node.
- **`threshold`**: below-threshold choice claims are decided solo; only
  above-threshold claims are sent to `resolve` and possibly `debate`.

## Host mechanics

- Invoke a skill through the `Skill` tool.
- Resolve the public session command to `<engine-root>/bin/task`, with
  `<engine-root>` from `execute`'s handoff.
