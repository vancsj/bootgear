---
name: spec-review
description: Independently review requirements, design, and ticket artifacts for correctness, completeness, architecture fit, simplicity, proportionality, and testability before implementation.
---

Review the artifact independently.

## Inputs and outcomes

Obtain from the caller the original request/ticket text, artifact paths, base commit, project root, `<run-id>`, `<session-dir>`, and `<n>`, the spec-review visit number (active run only).

Hand back to the caller (`execute` in an active run, the user standalone) `blocked`, or the lists below, with the render path, slate and converge directory.

- `blocked`: a required role or evidence path is unavailable, no request or ticket text was supplied (lens `request-fit` needs one), the slate cannot be resumed, the gate failed, or `<n>` is 5 and `revise` or `choices` is non-empty. Return the missing role or evidence path, or the claim IDs, the slate and the converge directory.
- `revise`: claim IDs with text; each must be addressed before re-review (`task.md` regenerated when a task artifact exists).
- `choices`: claim IDs with text.
- `inline`: claim IDs with text; does not block `ready`.
- `unchecked`: follow-up claims with reason `unverified`, reported and never attacked.
- `deferred`: claim IDs with text; implementation-level claims for the review stage.
- `follow-up`: all other follow-up claims, each labelled with its status.

Branch: `choices` non-empty -> `spec-debate` (the `revise` list goes on to `spec` afterwards); else `revise` non-empty -> `spec`; else `ready`: `inline` non-empty -> `spec` (the author applies the `inline` patches, no new slate), which then goes straight to implementation or ticket delivery; `inline` empty -> implementation or ticket delivery. `ready` holds when `revise` and `choices` are empty and the gate passes.

In an active engine run, leave only through the current state-machine branch. A `ready` result is the only result that permits implementation or final ticket delivery.

## Workflow

Check for an override → collect inputs → `init` the slate with the cutoff table → find, gap hunt, escalate, cut and attack with fresh converge roles → render and map → hand back `blocked` or the lists. `choices` go to `spec-debate` and back through `spec`; `revise` goes back to `spec`; `ready` lets implementation proceed, through `spec` first when `inline` is non-empty; every re-review is a full new slate.

## Procedure

1. Read the active engine settlement when `<run-id>` is supplied. Resolve `spec_review_override` as a skill name or sub-task mapping, including any valid amendment; otherwise use this skill. In standalone use, delegate once to a registered project spec-review skill when one matches.
2. Give each fresh converge role (except an `advisor` `r2`, which is the run's one listener and keeps its earlier slates' context) only the request/ticket, the artifact paths, relevant project docs and repository evidence at the base commit, and its role brief.
3. Use fresh converge roles through the public `converge` capability. Use slate `<run-id>-spec-review-<n>` and ledger directory `<session-dir>/converge`; standalone uses `spec-review-<YYYYMMDD-HHMMSS>` and `$HOME/.bootgear/converge`. If slate `<run-id>-spec-review-<n>` already exists in the converge directory, do not `init`; resume it with the actions `converge status` prints, and hand back `blocked` only when a required role or evidence cannot be supplied. Pass the project root, the six lenses `request-fit,clarity-completeness,architecture-fit,simplicity,proportionality,testability`, and the absolute paths of [references/angles.yaml](references/angles.yaml) and [references/design-patterns.yaml](references/design-patterns.yaml) as two values of one `--angles` flag (`--angles <abs>/angles.yaml <abs>/design-patterns.yaml`) to `init`; a repeated `--angles` flag keeps only its last file. In an active run with `<n>` >= 3 add `--pass <n>` to `init`; with `<n>` 1 or 2, and always standalone, omit `--pass`. Do not use `--snapshot` or `--since`. In an active run, write the settlement with `task session read <run-id> --dir <session-dir> --section settlement --prose > <converge-dir>/<slate>.settlement.yaml` and pass `--settlement <that file>` to `init`. Brief the finder with each lens's definition from [references/lenses.md](references/lenses.md).
4. Pass the absolute path of [references/cutoff.yaml](references/cutoff.yaml) as `--defaults` to `init`. Slates 1-2 attack and report claims whose `impact` is `security`, `data-loss`, `wrong-output` or `clarity` and whose `reach` is `normal` or `crafted`; from slate 3 only the first three impacts are reported and `clarity` claims become follow-ups; `request-fit` keeps the first rule. The table turns cheap fixes off, so no claim is `fix-now` and none takes a `fix-check`. Never set `steps.cut` to `none`.
5. Use separate finder, refuter, and cutter roles. Brief the cutter to pass, at the after cut, the artifact edit that fixes the claim as a unified diff with `--patch "$(cat fix.diff)"`, so `trivial` is typed only when the patch earns it. Run or mark not-applicable every find angle in `references/angles.yaml` and `references/design-patterns.yaml` for its lens. The five spec-only attack angles are in `references/angles.yaml`; when an angle's trigger is absent, the refuter records `angle-na` with reason `trigger absent: <why>`. Also brief the cutter:
   - an `implied-requirement` claim the stated outcome needs is rated `wrong-output`;
   - a `design-assumption` claim whose assumption is false is rated `wrong-output`;
   - a `simplicity` or `proportionality` claim is rated impact `clarity` unless the design it describes would give a wrong result; then it takes a non-`clarity` impact and a `choice`;
   - for a claim filed under the `implementation-level` angle, difficulty is `cross-cutting` or `redesign` whenever the fix changes a statement of a requirement or design, whatever the patch size, and `trivial` or `local` only when the fix adds code-level detail and changes no statement; a detail-only fix over converge's cheap patch limits (1 file, 10 lines) is rated `cross-cutting`.

   Finder, refuters, and cutter write their own events. The converge gap hunt runs by default; brief: what did every lens miss, and does the artifact match the request in both directions.
6. Check request fit, clarity/completeness, architecture fit, architectural best practices, minimal/clean/pragmatic alternatives where redesign is required, simpler clean alternatives, proportionality, and testability, per the lens definitions in `references/lenses.md`. Mark architecture-fit not applicable when the artifact has no design.
7. Render with `converge render <slate> --dir <converge-dir> > <converge-dir>/<slate>.md`. Map it mechanically, first rule first:
   1. missing role, missing coverage, open claims or failed gate -> `blocked`.
   2. status `disputed` -> `revise`, except a finding of lens `simplicity` or `proportionality` (rules 4-5 decide it).
   3. survived claim whose `trigger` (from `converge status --json`) starts `implementation-level:` and whose last cut difficulty is not `cross-cutting` or `redesign` -> `deferred`.
   4. a finding of lens `simplicity` or `proportionality` with no `choice` -> follow-up.
   5. a finding whose cut carries a `choice` -> `choices`, listed even when `revise` is also non-empty.
   6. status `survived` with difficulty `trivial` -> `inline`, except a `clarity` finding at `<n>` >= 3 -> follow-up.
   7. any other finding -> `revise`.

   Follow-up claims go to `unchecked` (reason `unverified`) or `follow-up`. At `<n>` = 5 with `revise` or `choices` non-empty, hand back `blocked`. Run the converge gate after cutoff and pass `--leave-arg slate=<slate> --leave-arg converge_dir=<converge-dir>` when leaving the state node.
8. Hand back per `Inputs and outcomes`.

## Rules

- Do not edit code or silently settle a disputed interpretation.
- Never give a role the author transcript, `*-notes.md`, or another role's reasoning.
- The main role writes only `init`.
- Severity and blast radius help prioritize a finding but do not decide whether a requirement is complete.
- Use the original request as the intent source, repository code/tests/docs as current-behaviour evidence, and the active settlement's source-of-truth order for contested domain facts. A choice is not a factual finding; leave it for `spec-debate` after `resolve` cannot settle it.
- A design-invalidating defect is never `deferred`; the cutter rates it `cross-cutting` or `redesign`, so mapping rule 3 does not defer it.

## Fallbacks

Stop with `blocked` if a required role is unavailable.

## Host mechanics

Claude invokes `spec:spec-review`. The skill's `converge` dependency is declared by the `spec` plugin.
