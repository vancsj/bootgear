---
name: spec-review
description: Independently review requirements, design, and ticket artifacts for correctness, completeness, architecture fit, simplicity, proportionality, and testability before implementation.
---

## Inputs and outcomes

Obtain the request, confirmed intent amendments, primary artifact paths, base commit, and project root from the caller.
In an active run, also obtain run ID, session directory, and `<n>`, the cumulative spec-review visit number.
Read primary Open questions. Do not treat the ticket as proof of current behaviour.
Optional input: raw observation inventory path.
When supplied, read [references/observations.md](references/observations.md) for independent checks and feedback gates.

Hand back to the caller (`execute` in an active run, the user standalone):

- `blocked`: missing role, evidence, request, coverage, resumable slate, or passing gate; include the diagnostic and affected claim IDs.
- `revise`: claim IDs and text requiring author revision before another review.
- `choices`: claim IDs and text requiring a caller decision.
- `inline`: claim IDs and text with eligible artifact patches; these permit `ready`.
- `unchecked`: follow-ups with reason `unverified`, reported without attack.
- `deferred`: implementation-level claim IDs and text for implementation and code review.
- `follow-up`: other follow-up claims, each labelled with its status.
- `ready`: `revise` and `choices` are empty, and the required gate passes.

Include the render path, slate, and converge directory with every result.
With observations, include `observations_path`, `checks_path`, and independent `checks` from the public observation contract.
At visit five, remaining `revise` or `choices` returns `blocked` with those claims.

Follow the current machine's branch in an active run.
Send choices to debate, then drafting; send revise to drafting.
Only ready permits implementation or ticket delivery.
Ready with inline patches returns through drafting, applies those patches, and uses the same slate and required ready-exit gate.
Start no new slate on that inline path.

## Procedure

1. Resolve overrides, collect inputs, and brief independent roles.
2. Init or resume the slate with the cutoff and angles below.
3. Run normal converge finding, gap hunting, escalation, cuts, attacks, replies, and verdicts.
4. Render, map results in order, run the gate, and return the public handback.

### Overrides and role context

In an active run, read the settlement through the public session command.
Use `spec_review_override` as a skill name or stage mapping, including its latest valid amendment.
Otherwise use this skill.
Standalone, delegate once to a registered project spec-review skill when one matches.
Require the same public handback from an override.

Give fresh converge roles only authoritative intent, primary artifacts, relevant repository evidence, standards, and their role briefs.
Include raw observations when supplied.
Exclude author transcripts, notes, hypotheses, private unresolved lists, suspect-line lists, and another role's reasoning.
An advisor `r2` retains its earlier slates' context as the run's one listener.

Name project principles, host user principles, and applicable project standards in each role brief when present.
Use `.bootgear/config/principles.md` and applicable standard files in `.bootgear/config/`.
In an active run, also supply the settlement's principles.
Each role reads them before finding, attacking, or cutting.

### Slate and coverage

Use the public converge capability with separate finder, refuter, and cutter roles.
Use slate `<run-id>-spec-review-<n>` and directory `<session-dir>/converge` in an active run.
Standalone, use `spec-review-<YYYYMMDD-HHMMSS>` and `$HOME/.bootgear/converge`.
If the slate exists, resume through public status actions. Do not init it again.
Every later review visit uses a new slate and fresh roles, except the retained advisor listener.

Supply the project root and these six lenses to init:

```text
request-fit,clarity-completeness,architecture-fit,simplicity,proportionality,testability
```

Pass absolute paths for [references/angles.yaml](references/angles.yaml) and [references/design-patterns.yaml](references/design-patterns.yaml) through one `--angles` flag:

```text
--angles <absolute-angles-path> <absolute-design-patterns-path>
```

Do not repeat the flag. Use `--pass <n>` only for active-run visits three and later.
Omit `--pass` on visits one and two, and standalone.
Do not use `--snapshot` or `--since`.
For active runs, export the public settlement and pass that file through `--settlement`:

```text
task session read <run-id> --section settlement --prose > <converge-dir>/<slate>.settlement.yaml
```

Read [references/lenses.md](references/lenses.md) when briefing each lens.
Run or mark not applicable every find angle for its lens from both angle files.
When a spec-only attack trigger is absent, record `angle-na` with `trigger absent: <why>`.
Use the normal converge gap hunt to check missed concerns and request fit in both directions.
Never disable the cut step.

### Cutoff and remedy

Pass [references/cutoff.yaml](references/cutoff.yaml) as the absolute `--defaults` path at init.
The cutoff uses implementation difficulty and disables automatic cheap fixes.
No claim receives fix-now or fix-check treatment.
Visits one and two report eligible clarity, security, data-loss, and wrong-output findings.
Later visits retain security, data-loss, and wrong-output; request-fit also retains clarity.

The finder files each `loc` as the primary artifact's absolute path and line.
The cutter rates the production remedy using the effective difficulty basis from public converge status.
Cite affected paths, callers, scope, and migration needs in normal difficulty evidence.
Document size does not decide production remedy difficulty.
Measure any artifact patch separately through converge.
Supply a real unified diff through the public patch input when an inline correction is appropriate.
Use only CLI-derived `artifact_patch_eligible` from status or render. A role cannot assert that field.

Brief these finding rules:

- An implied requirement needed for the stated outcome takes impact `wrong-output`.
- A false design assumption takes impact `wrong-output`.
- Simplicity and proportionality findings take `clarity` unless they cause a wrong result; then include the appropriate impact and choice.
- Use the existing `implementation-level:` trigger only for code details that preserve sound requirement and design contracts.
- Keep requirement-invalidating and design-invalidating defects in spec review, regardless of remedy difficulty.

Apply architecture checks wherever architecture statements appear, including requirements-only packages.
Check hidden assumptions across prose, diagrams, tables, and tasks.
Mark a check not applicable only when its affected mechanism is absent.
For changed trust boundaries, permissions, external inputs, or sensitive data, trace STRIDE threats through controls and verification.

### Render and mapping

Render through the public command:

```text
converge render <slate> --dir <converge-dir> > <converge-dir>/<slate>.md
```

Read public status and map results in this order:

1. Missing role, coverage, required evidence, open claim work, or a failed gate returns `blocked`.
2. A disputed finding returns `revise`, except simplicity or proportionality findings handled by rules four and five.
3. A survived claim with a public `trigger` starting `implementation-level:` returns `deferred`.
4. A simplicity or proportionality finding without a choice returns follow-up.
5. A finding whose cut carries a choice returns `choices`, even when revise also contains findings.
6. A survived, trivial, contract-preserving clarity finding with public `artifact_patch_eligible: true` returns `inline`.
7. Any other finding returns `revise`.

Apply the effective cutoff before mapping findings.
A contract-invalidating finding or missing eligible patch cannot become inline.
Send follow-ups to `unchecked` for reason `unverified`, or otherwise to `follow-up`.
At visit five, return `blocked` when revise or choices remains.
Run the public converge gate before a ready handback.
With observations, also complete the public observation coverage gate.
Keep the slate and converge directory in every handback. Use the selected exit's public check for leave arguments.
Return the handback to the caller.

## Judgment rules and safety

Do not edit code or silently settle disputed intent.
The main role writes only init. Finder, refuters, and cutter write their own events.
Use authoritative intent for desired behaviour and code, tests, and contracts for current behaviour.
Use the active settlement's source order for contested domain facts.
Leave choices to the caller's resolve and debate path.
Severity and reach do not decide whether requirements are complete.
A sound-contract detail can defer even when its production remedy spans components or its document patch is large.
Keep contract-invalidating defects outside the implementation-level trigger.
Preserve normal attacks, finder replies, narrowing, withdrawal, verdicts, cuts, coverage, and gates.
Passing a rerun or returning no claim alone does not establish required behavioural coverage.
A factual result grants no mutation or delivery permission.

## Fallbacks

Return `blocked` when a required role, public capability, or evidence path is unavailable.
Include the actual diagnostic, named mechanism, pending work, and next caller action.
Do not replace missing request evidence with the author's interpretation.

## Host mechanics

Invoke skills by public name.
If required converge or spec-feedback capability is missing, return `blocked` with its actual diagnostic and named mechanism.
Keep `session_dir` in context; pass `--dir` only for a custom session directory.
