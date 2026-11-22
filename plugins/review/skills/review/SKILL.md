---
name: review
description: Review a change for defects or apply accepted feedback. Use for a diff, branch, pull request, or review comments.
---

## Inputs and outcomes

Take the diff, branch, or PR, linked ticket, and depth. In Engine, take both run paths, sub-task label, and `review_fix_mode`.
For authoring, take the context, fixed task folder, and current self-review checkpoint if present.

Each iteration, return the slate ID, Converge directory, render, and iteration count to `execute` or the standalone user.
Include ranked findings, status and choices, follow-ups with status, killed claims with evidence, `fix-now` patches, and `fix-checks`.
Report angle packs, including none, and the reason or previous slate source. Return follow-ups for caller recording.

| Outcome | Condition and handback |
|---|---|
| `handoff` | Engine has a `fix` edge. Return permitted `apply` or required `revert` claim IDs, even for only `fix-now`. |
| `comment_only` | Engine has no `fix` edge. Report all findings and `fix-now` claims as comments in any mode. |
| `clean` | The re-review or Engine pass has no findings, `fix-now`, or follow-ups. |
| `below_cutoff` | Only follow-ups remain. |
| `blocked` | Author check, confirmation, role, or coverage missing. Also use for a disputed finding or blocked Converge result. |
| `blocked` | A finding or `fix-now` lacks required acceptance, remedy choice, or permission. |
| `no_progress` | The same claim returns unchanged after a fix, without new evidence. |
| `iteration_cap` | Live claims remain at the cap and no other outcome applies. Default cap is 5. |

With a `fix` edge and no applicable fixes, return `clean`, `below_cutoff`, or `blocked` from the render.
Leave overall goal completion to the caller.

For apply-only, omit the loop outcome. Return one disposition per in-scope comment.

- `applied` with verification result.
- `accepted but not applied` with the conflict or failed check.
- `rejected or won't-fix` with the thread reason.
- `unclear` with the unresolved acceptance or intent.

## Procedure

For apply-only, go to Apply feedback. Otherwise complete the author checkpoint when applicable, select an override, then review.

### Author checkpoint

Before an independent slate or override, check related feedback since the last author check.
If it changed the artifact, renew through self-review with the independent reference.
Otherwise reuse only a public `clean` or `limit-reached` checkpoint for this handoff.
On an authoring path without an applicable checkpoint, invoke code-stage self-review with the complete diff and fixed task folder.
Keep its count on edits and retries. Return the author record and open references separately from findings.
Keep hypotheses and suspect lists private. The caller retains open items until independent disposition.

On `needs-selection`, return `blocked` with source-selection kind, candidates, scope, and missing confirmation.
A direct caller obtains confirmation. Engine uses clarify checkpoint mode.
On `unavailable`, return `blocked` with the diagnostic and mechanism. Do not bypass the check.

### Choose an override

In Engine, read the full decisions through the supplied session directory. Apply valid `review_override` and `review_fix_mode` amendments.
Use the override's bare skill or exact caller depth mapping. If unmatched, use this workflow.
Standalone, use a registered project skill that fits. Pass the test brief below and both run paths when active.
Require the same handback and a fresh test brief for each new or continued role. Allow memory-ledger access.

### Choose depth and start the slate

Use the caller's depth or `full`.

- `quick`: lenses `correctness,tests`. Use main, F, R1, and C. Skip gap hunt.
- `full`: lenses `correctness,security,architecture,tests,simplicity,contract,consistency`.
  Use main, F, R1, R2, and C. R2 runs gap hunt.

Reuse seats. Keep the depth's role budget. A later debate uses its own budget.
Use one absolute directory throughout the slate.

| Run | Slate | Directory |
|---|---|---|
| Engine | `<run-id>-review-<n>`, counted from 1 | `<session-dir>/converge` |
| Standalone | `review-<UTC YYYYMMDD-HHMMSS>` | `$HOME/.bootgear/converge` |

Use Converge `init` with the depth's lenses and worktree root. For quick use `--refuters 1`.
Pass [find-angles.yaml](references/find-angles.yaml) and each selected `references/angles-<lens>.yaml` when present.
For architecture, also pass [design-patterns.yaml](references/design-patterns.yaml) and [evaluate-angles.yaml](references/evaluate-angles.yaml).
Use the absolute [cutoff.yaml](references/cutoff.yaml) path as `--defaults`. Let Converge load these YAML files.

On re-review, reuse the previous slate's `.packs` list if present. Otherwise read only `# use when:` in these packs.

- [pack-web.yaml](references/pack-web.yaml)
- [pack-typed-oop.yaml](references/pack-typed-oop.yaml)
- [pack-concurrency-db.yaml](references/pack-concurrency-db.yaml)
- [pack-test-tooling.yaml](references/pack-test-tooling.yaml)

Select from project instructions, docs, and root build files or manifests. Exclude the diff and changed-file list.
Enable a pack when unsure. If the sources have no stack information, enable none.
Save enabled file names, one per line, to `<converge-dir>/<slate>.packs`, or save an empty file.
Pass enabled packs to init. On a duplicate angle ID naming a pack, remove that pack from the file and command. Retry.

If `.bootgear/config/review-standard.md` exists, write `<converge-dir>/<slate>.yaml` before init.
Set `cutoff: {report_rules: [<rule IDs at or above cutoff>]}`. Pass it with `--config`.

In Engine, export the settlement and pass it with `--settlement`. Pass the run ID with `--review-group`.
For standalone advisor reviews, pass the user's approved launcher settings with `--settlement`.
For later standalone visits, pass the prior slate ID with `--continue-from`.

```text
<gear> --host <host> engine task session read --section settlement --prose > <converge-dir>/<slate>.settlement.yaml
```

Add `--snapshot --pass <n>`. From pass 2, add `--since <run-id>-review-<n-1>`.
On a `--since` refusal, keep the pass number. Ask `execute` to settle the baseline and record the decision.
Use changes since the previous snapshot. Expand to the full change only after approval. Otherwise return `blocked`.

After successful Engine init, record the snapshot and final pack list as solo decisions.

```text
review slate <slate> snapshot=<sha>
review angle packs <slate>: <names or none>; <reason>
```

### Run Converge

Use public `work` and `act`. Give prepared work the actor and receiving host. Refresh stale work.
Give the finder the actual diff, linked ticket, and the selected lens rows from [lenses.md](references/lenses.md).
Read the changed behavior checks that apply. Give the cutter its selected cut dimensions. Skip unused lens rows.
Require find coverage for every selected angle. In full review, run gap hunt after find coverage, before escalation and cut.

Name host user principles, project principles, and standards for each role. Include settlement principles in Engine.
Tell each role to read applicable files first.

Give finder, gap hunter, and cutter these claim rules.

- In `claim`, name expected behavior, who relies on it, and the observable consequence.
- In `trigger`, name the caller action, input, or state.
- In `evidence`, cite the requirement or contract and the source path to the result. Mark any unverified link.
- Set the tier from the checks you ran. For test gaps, name a wrong result that can pass.
- Preserve relevant context when widening or revising. Include new source anchors, trigger details, and unverified links.

The cutter rates the current text and any updated trigger or evidence. For `cosmetic`, explain which outcomes and actions stay intact.
Where a claim breaks a project review rule, tag `--rule R###`. Do not cut a rule claim at or above the standard cutoff.
Use Converge cutoff for other claims.

Fill this block yourself before each new or continued finder or gap hunter brief, and for overrides.

```text
Tests already ran:
- latest test: <recorded command>; result: <one recorded result line>
```

Use the latest recorded command, even if narrow. Exclude exit code and record path. Do not combine commands.
Use `none recorded` if absent. Tell roles to skip covered runs and probe gaps when needed.

From pass 2, give the finder the diff command from init and the previous render.
Require out-of-diff claims to show a behavior change caused by the diff.
For a `fix-now` re-review, use one round limited to patch-caused problems.

Give the gap hunter the current render, diff, linked ticket, and current test brief.
Ask what every lens missed and whether the diff omits requested work or adds unrequested work.

### Report and route findings

Follow Converge cutoff and render. Use the current render for disposition.
Keep each follow-up's `choice` with it. For each finding with a choice, ask `deputy:ask` before routing.
Cite answered slugs and report the answer. If deputy is absent, record `no-deputy:not-installed`.
In Engine, return choices for `review-debate`. Standalone, return them to the user. Keep factual disputes in Converge.

After a patch-only pass, read [patch-checks.md](references/patch-checks.md) to record the previous slate's fix checks.
In Engine, record this solo decision and supply the selected exit's public leave inputs.

```text
review slate <slate> converge_dir=<converge-dir> snapshot=<sha> <render counts>
```

Read the effective machine and fix mode. Return after this pass in Engine.
Standalone defaults to `accepted_only`. Apply accepted feedback and re-review on a new slate until an outcome applies.
Report standalone `fix-now` without applying patches.

### Apply feedback

For apply-only or a standalone fix, use the acceptance rules below.
Before a fix needing acceptance, ask `deputy:ask`. It gives advice only.
If it is absent, record `no-deputy:not-installed` and ask the user as usual.
After applying a fix, run the suite `test` would select for the change. Report the result.

## Rules

Keep independent review read-only for the artifact. Allow assigned records and memory-ledger reads and writes.
Preserve other write limits and role independence. Keep private author analysis out.

### Acceptance

Require explicit agreement on the individual comment, such as “do this,” a thumbs-up, or `resolved-as-agreed`.
Questions, pushback, silence, overall PR approval, `resolved-as-rejected`, and `won't-fix` give no acceptance.
A survived finding still needs external acceptance. Report ambiguous acceptance or intent as `unclear`. Do not apply it.
In Engine, let the caller use `resolve` or `debate` with its authority. Apply only after settlement and explicit acceptance.

### Fix modes

In Engine, only the `fix` node applies or reverts claims. Under `accepted_only`, require explicit acceptance per claim.
A human can accept it. In Engine, `execute` can accept it after resolve or debate. Re-review after a fix.

For `auto_within_permitted_mutations`, auto-apply only `fix-now` patches within permissions.
Handle findings, disputed, follow-up, killed, choice, and out-of-permission claims under `accepted_only`.
In `fix`, apply and test eligible patches. Re-review and record `fix-check`. On failure, the `fix` node reverts that patch.
Standalone automatic mode reports all claims without applying them. Apply-only still uses individual acceptance.

Keep production changes, outward sends, irreversible actions, goal sign-off, and mutation permission out of deputy.

## Fallbacks

If required self-review is missing, return `blocked` and name it.
On blocked Converge, stop and name the missing role. Claims start `survived`. Require the fresh-eye batch.

## Host mechanics

Get Gear from `cli:gear`. Use `<gear> --host <host> engine task <command>` or `<gear> --host <host> converge converge <command>`.
Use `claude` and `CLAUDE_CODE_SESSION_ID` on Claude Code. Use `codex` and `CODEX_SESSION_ID` on Codex.
Keep `session_dir`. Omit `--dir` for `~/.bootgear/session`. Add it for a custom directory.
If the CLI is absent, install `cli@bootgear` through the host.
On Codex, report `cli:setup` for `review` if a sibling is missing. Resume after verification.
