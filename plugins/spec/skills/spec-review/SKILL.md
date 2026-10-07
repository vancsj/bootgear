---
name: spec-review
description: Independently review requirements, design, and ticket artifacts for correctness, completeness, architecture fit, simplicity, proportionality, and testability before implementation.
---

Review the artifact independently.

## Inputs and outcomes

Obtain from the caller the original request/ticket text, artifact paths, base commit, project root, `<run-id>`, and `<session-dir>`.

Hand back exactly one outcome, using precedence `blocked > revise > choices > ready`:

- `blocked`: a required review role or evidence path is unavailable; return the missing role or evidence path, slate, and converge directory to the caller (`execute` in an active run, the user standalone);
- `revise`: an artifact correction is required; return claim IDs, render path, slate, and converge directory to `spec`, which must address each claim and regenerate `task.md` when a task artifact exists before re-review;
- `choices`: only unresolved material interpretations or design choices remain; return claim IDs, render path, slate, and converge directory to `spec-debate`;
- `ready`: no unresolved correctness or completeness claim remains; return the render path, slate, and converge directory to the caller (`execute` in an active run, the user standalone).

In an active engine run, leave only through the current state-machine branch. A `ready` result is the only result that permits implementation or final ticket delivery.

## Workflow

Check for an override → collect inputs → write the cutoff config → `init` the slate → find, refute and cut with fresh converge roles → render and map → hand back one outcome. `revise` goes back to `spec`, which revises and returns for re-review; `choices` goes to `spec-debate`, which returns through `spec` and re-review; only `ready` lets implementation proceed.

## Procedure

1. Read the active engine settlement when `<run-id>` is supplied. Resolve `spec_review_override` as a skill name or sub-task mapping, including any valid amendment; otherwise use this skill. In standalone use, delegate once to a registered project spec-review skill when one matches.
2. Give each fresh converge role only the request/ticket, the artifact paths, relevant project docs and repository evidence at the base commit, and its role brief.
3. Use fresh converge roles through the public `converge` capability in `full` mode. Use slate `<run-id>-spec-review-<n>` and ledger directory `<session-dir>/converge`; standalone uses `spec-review-<YYYYMMDD-HHMMSS>` and `$HOME/.bootgear/converge`. Pass the project root, the six lenses `request-fit,clarity-completeness,architecture-fit,simplicity,proportionality,testability`, and the absolute path of [references/find-angles.yaml](references/find-angles.yaml) as the angle file to `init`; do not use snapshot or review-pass flags. Brief the finder with each lens's definition from [references/lenses.md](references/lenses.md).
4. Write `<converge-dir>/<slate>.yaml` with a match-all report cutoff before `init`: `cutoff: {report_if: [{frequency: [every-call, common, rare, contrived]}], report_if_gap_hunt: [{frequency: [every-call, common, rare, contrived]}]}` and `caps: {per_lens: 50}`. Pass it with `--config`. This keeps correctness/completeness findings reportable regardless of severity or frequency.
5. Use separate finder, refuter, and cutter roles. Run or mark not-applicable all eight dedicated find angles in `references/find-angles.yaml` for their named lenses. Finder, refuters, and cutter write their own events.
6. Check request fit, clarity/completeness, architecture fit, architectural best practices, minimal/clean/pragmatic alternatives where redesign is required, simpler clean alternatives, proportionality, and testability, per the lens definitions in `references/lenses.md`. Mark architecture-fit not applicable when the artifact has no design.
7. Render with `converge render <slate> --dir <converge-dir> > <converge-dir>/<slate>.md`. Map it mechanically: a reported factual/completeness defect is `revise`; `choices` is allowed only when every reported claim has a cut `choice` and no factual/completeness defect remains; an inconclusive or unconverged claim is `revise`; missing role, missing coverage, open claims, or failed gate is `blocked`; only an empty reported set with a passing gate is `ready`. Run the converge gate after cutoff and pass `--leave-arg slate=<slate> --leave-arg converge_dir=<converge-dir>` when leaving the state node.
8. Hand back one outcome per `Inputs and outcomes`.

## Rules

- Do not edit code or silently settle a disputed interpretation.
- Never give a role the author transcript, `*-notes.md`, or another role's reasoning.
- The main role writes only `init`.
- Severity and blast radius help prioritize a finding but do not decide whether a requirement is complete.
- Use the original request as the intent source, repository code/tests/docs as current-behaviour evidence, and the active settlement's source-of-truth order for contested domain facts. A choice is not a factual finding; leave it for `spec-debate` after `resolve` cannot settle it.

## Fallbacks

Stop with `blocked` if a required role is unavailable.

## Host mechanics

Claude invokes `spec:spec-review`. The skill's `converge` dependency is declared by the `spec` plugin.
