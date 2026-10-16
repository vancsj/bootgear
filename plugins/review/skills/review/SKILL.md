---
name: review
description: Review a diff, branch, or PR for correctness, architecture, security, simplicity, and convention fit, then apply accepted feedback. Works standalone and delegates to a project review skill when one is registered. Use when a change needs reviewing or review comments need applying.
---

Review a change and apply accepted feedback.

## Inputs and outcomes

Inputs: the diff, branch, or PR under review; the linked ticket, if any; the
depth label `quick` or `full`; in an active run, also `<run-id>`,
`<engine-root>`, `<session-dir>`, the sub-task label, and `review_fix_mode`.

Hand back to the caller (`execute` in an active run, the user standalone)
each iteration's slate id, converge dir and `converge render` output:
findings in rank order with their status, `fix-now` claims with their patches
(`converge render --json` `fix_now`) and any `fix-check` recorded on them,
`choice` claims, follow-up claims with their status, and killed claims with
their evidence. When the default implementation selects packs, also hand back
the angle packs enabled for the slate, each with the reason, or, when none is
enabled, that none is, with the reason. A re-review that reads its packs from
the previous slate's `.packs` file hands them back marked as carried from the
previous slate. Return follow-up claims in the handback; do not record them.

A new review ends with exactly one outcome:

- **`handoff`:** In an active run, the current node has a `fix` edge (`machine.nodes[current].next` includes `fix`) and the
  mode would apply at least one claim, or revert a patch whose `fix-check`
  failed; this holds for a render whose only claims to apply are `fix-now`
  claims. The `fix` node takes over. Return the fix list: the ids of those
  claims, each marked `apply` or `revert`.
- **`comment_only`:** In an active run, the current node has no `fix` edge (`machine.nodes[current].next` lacks `fix`).
  Every finding and `fix-now` claim is reported and none is applied, whatever
  `review_fix_mode` says.
- **`clean`:** A re-review's render, or an active run's single-pass render,
  has no finding, no `fix-now` claim and no follow-up.
- **`below_cutoff`:** The render has no finding, no `fix-now` claim and at
  least one follow-up.
- **`blocked`:** A role or find coverage is missing, a finding has status
  `disputed`, a finding or `fix-now` claim needs a mutation outside the mode's
  permission — an unaccepted claim under `accepted_only`, an undecided
  `choice`, or a mutation outside `permitted_mutations` — or the `converge`
  skill handed back `blocked`.
- **`no_progress`:** The loop again finds the same unchanged claim after
  trying to fix it, with no new information.
- **`iteration_cap`:** The configured iteration cap is reached with live
  claims remaining and none of the other outcomes applies. The default cap is
  `5`, unless project configuration sets another value.

In an active run where the current node has a `fix` edge and the fix list is
empty, the outcome is the one the render gives: `clean`, `below_cutoff`, or
`blocked`. Standalone, `fix-now` claims are reported with the findings and
none is applied.

Report claims from every iteration, not only the final iteration. State the
ending outcome and iteration count. `execute` uses these fields to update its
todos and determine whether the broader task is complete. This skill does not
decide whether that broader task is complete.

When applying feedback, account for every in-scope comment:

- **`applied`:** The change was made, verification (the affected suite, or
  whatever check applies — a lint, a type-check, a build) passed, and the
  result reported.
- **`accepted but not applied`:** Acceptance was clear, but a verification
  failure or conflict blocked the change. Name the blocker.
- **`rejected or won't-fix`:** No action was taken. State the reason from the
  thread.
- **`unclear`:** Acceptance or intent could not be determined. Name the
  ambiguity so the caller can resolve it.

An apply-only request (start at sub-task 6) hands back only this per-comment
accounting; it has no loop outcome. For `handoff`, return the fix list (claim
ids) in place of the applied-feedback accounting; nothing was applied. For
`comment_only`, report every finding as a comment, with none applied.

## Workflow

1. Check for an override; delegate if one applies.
2. An apply-only request runs sub-task 6, then reports.
3. A new review runs sub-task 1 (depth), 2 (start the slate), 3 (find
   through `converge`), 4 (gap hunt, `full` only), then converge's escalate,
   cut and attack steps, and 5 (cutoff, render, route choices).
4. In an active run, end with `handoff`, `comment_only`, or the render's
   outcome. Standalone, apply what the fix mode permits, re-review on a new
   slate, and repeat until one outcome applies.

## Check for an override first

1. If an active `engine` run exists, read its settlement through the engine
   session interface using the exact `<run-id>` and `<session-dir>` supplied by
   `execute`.

   Then scan the active run's full decisions for `AMENDMENT review_override` or
   `AMENDMENT review_fix_mode`; the latest valid value wins over the field read
   above.

   Find `review_override`. It is either:

   - a skill name; or
   - a mapping from sub-task label to skill name.

   For a mapping, use the exact depth label passed by `execute`. Do not infer
   the label from the diff. If the active run has no matching override, use this
   skill's default. Do not search again.

2. Without an active run, check whether the current project has a registered
   review skill that fits the task. Delegate to it when one exists.

3. Otherwise, use the default implementation below.

When delegating from an active run, pass `<run-id>`, the host engine root, and
`<session-dir>` using the active run's handoff contract. The delegated skill
must return the fields defined in `Inputs and outcomes`.

## Default implementation

"Apply the accepted comments on this PR" starts at sub-task 6 and skips
sub-tasks 1–5. It does not start a new review. A new review of a diff or
branch starts at sub-task 1 and continues under `Iterate to closure`.

Run every `converge` action below with the same `<converge-dir>`. The CLI owns
the accepted event shape and prints the fixed next action after each state
change.

### 1. Depth

Use the depth label passed by the caller, else `full`:

- `quick`: lenses `correctness,tests`; agents main, F, R1, C; no gap hunt.
- `full`: lenses `correctness,security,architecture,tests,simplicity,contract,consistency`;
  agents main, F, R1, R2, C; gap hunt by R2.

This slate is one task: never use more than these agents on it, and reuse
each one across rounds. The cap counts this slate only; a later debate on its
choices has its own budget. F covers every find angle of every lens; angles
per claim per round come from the `status --json` `plan`.

Each lens's scope and finder brief is in
[references/lenses.md](references/lenses.md).

### 2. Start the slate

Choose the slate id and the converge dir:

- In an active run: slate `<run-id>-review-<n>`, where `<n>` counts this run's
  review slates from 1; converge dir `<session-dir>/converge` as an absolute
  path.
- Standalone: slate `review-<UTC timestamp as YYYYMMDD-HHMMSS>`; converge dir
  `$HOME/.bootgear/converge` as an absolute path.

Initialize the slate through the public `converge` command with the selected
depth, lenses, angle files, and project root. The angle files are
[references/find-angles.yaml](references/find-angles.yaml) for every depth;
for each lens in the depth, its `references/angles-<lens>.yaml` when that file
exists ([references/angles-security.yaml](references/angles-security.yaml),
[references/angles-tests.yaml](references/angles-tests.yaml),
[references/angles-simplicity.yaml](references/angles-simplicity.yaml),
[references/angles-consistency.yaml](references/angles-consistency.yaml));
[references/design-patterns.yaml](references/design-patterns.yaml) and
[references/evaluate-angles.yaml](references/evaluate-angles.yaml) when the
`architecture` lens is in the depth; and each angle pack enabled below. Pass
the absolute path of [references/cutoff.yaml](references/cutoff.yaml), the
per-lens cutoff policy, as `--defaults` to `init`.

Select the angle packs before `init`. Each `references/pack-*.yaml`
([references/pack-web.yaml](references/pack-web.yaml),
[references/pack-typed-oop.yaml](references/pack-typed-oop.yaml),
[references/pack-concurrency-db.yaml](references/pack-concurrency-db.yaml),
[references/pack-test-tooling.yaml](references/pack-test-tooling.yaml)) opens
with one line `# use when: <project property>`. Read that line of every pack and
enable the pack when the project has the property, judging from project-wide
sources only: the host's project instruction file (`CLAUDE.md` or
`AGENTS.md`), the project docs, and the build and manifest files at the
project root. Never use the diff or the changed-file list. Enable a pack when
unsure; enable none when the sources give no stack information. For a
re-review (a pass `<n>` ≥ 2, or a standalone review on a new slate after an
iteration), read the packs from `<converge-dir>/<previous slate>.packs`; when
that file is missing, select anew. Write the enabled pack file names, one per
line, to `<converge-dir>/<slate>.packs` (an empty file when none). In an
active run, record
`task session record-decision <run-id> --dir <session-dir> --mode solo --summary "review angle packs <slate>: <names or none>; <reason>"`.
If `init` refuses with a duplicate angle id that names a pack, remove that
pack from `--angles` and from the `.packs` file, and run `init` again.

In an active run, write the settlement with
`task session read <run-id> --dir <session-dir> --section settlement --prose > <converge-dir>/<slate>.settlement.yaml`
and add `--settlement <that file>` to `init`. At `quick`, add `--refuters 1`.

In an active run, add `--snapshot --pass <n>` to `init`; for `<n>` ≥ 2, also
add `--since <run-id>-review-<n-1>`. Also add `--project-root <repo root>` to
`init`, where `<repo root>` is the top level of the work tree holding the
change under review. Right after `init` succeeds, record the slate so
`execute` prunes its snapshot however the review ends:

```text
task session record-decision <run-id> --dir <session-dir> --mode solo --summary "review slate <slate> snapshot=<sha>"
```

If `init` refuses a `--since` check, keep `--pass <n>` and stop: have
`execute` run `resolve` for the baseline this pass reviews against, with the
scope source that a re-review reviews only the change since the previous
pass's snapshot. `init` carries no other baseline, so the decision is one of:
rerun `init` without `--since`, reviewing the full change as a recorded
widening; or stop the review `blocked`. Record that decision, then act on it.

If the project has `.bootgear/config/review-standard.md`, first write
`<converge-dir>/<slate>.yaml` containing
`cutoff: {report_rules: [<every rule ID whose severity is at or above the standard's cutoff:>]}`
and add `--config <converge-dir>/<slate>.yaml` to `init`.

### 3. Find, escalate, cut, attack

Run the `converge` skill on the slate with the depth's agents: at `full`, two
refuters (R1, R2) and the gap hunt of sub-task 4; at `quick`, one refuter (R1)
and no gap hunt. The find comes first, then sub-task 4, then converge's
escalate, cut and attack steps.

Spawn one finder, F, for every lens from sub-task 1. Give it one brief listing
every lens with its scope and brief from `references/lenses.md` and that
lens's find angles from the angle files of sub-task 2, plus the actual diff
(not only commit messages or the PR description) and the linked ticket if any.

For `<n>` ≥ 2, also give F the `git diff` command `init` printed and the
previous slate's `converge render` output as settled context. A claim outside
that diff is in scope only when the diff changes that code's behaviour. When
the previous pass's `fix` node applied `fix-now` patches, this pass is their
one-round re-review: tell F to report only problems those patches introduce.

If the project has `.bootgear/config/review-standard.md`, give F its rules and
have it tag each claim that breaks one with `--rule R###`.
A claim tagged with a rule at or above the standard's `cutoff:` is never
cut; converge's cutoff decides whether every other claim is cut.

### 4. Gap hunt

`full` only; `quick` has no gap hunt. Right after find coverage, before any
claim is escalated or cut, continue R2 as the gap-hunt finder, filing its
claims with `--as r2` and `origin: gap-hunt`; they go through the same
`converge` steps as the lens claims, with R1 attacking them. Brief R2 with:

- the current `converge render` output;
- the diff and the linked ticket;
- the question: what did every lens miss, and does the ticket match the diff
  in both directions (asked but missing, present but unasked)?

### 5. Cutoff, render and choices

Run the fixed cutoff action printed by the CLI once `converge status`
reports `phase: cutoff`, so it is the slate's latest state-changing event.
Report the render's findings, follow-ups and killed claims, each follow-up
labelled with its status.

Route every finding carrying a `choice` (a follow-up keeps its `choice` in
the follow-up list):

- Before routing, call `deputy:ask` for the choice. The answer is advisory and
  never counts as acceptance. If `deputy` is not installed, record
  `no-deputy:not-installed` and route the choice as usual.
- In an active run: report it to the caller for the `review-debate` node. A
  factual dispute is not a choice; it stays in converge.
- Standalone: report it to the user.
- A deputy-answered choice is named in the report to the user, with its cited slugs.
  Production change, outward send, irreversible action, goal sign-off, or permitted mutations are never sent to `deputy:ask`.

When the previous pass's `fix` node applied `fix-now` patches, record a
`fix-check` on the previous slate for each, as its main agent, after this
slate's cutoff:

```text
converge fix-check <previous slate> --dir <converge-dir> --as main --claim <id> --outcome pass|fail --evidence "<checks run and their result>" --review-slate <slate>
```

Record `pass` only when the `fix` node's tests and checks passed and this
slate holds no finding; otherwise record `fail`, and the claim goes in the fix
list marked `revert`. Then rerun `converge cutoff` on the previous slate.

In an active run, record the slate, the converge dir and the `snapshot=<sha>`
that `init` printed; the caller passes the first two as
`--leave-arg slate=<slate> --leave-arg converge_dir=<converge-dir>` when
leaving `review`:

```text
task session record-decision <run-id> --dir <session-dir> --mode solo --summary "review slate <slate> converge_dir=<converge-dir> snapshot=<sha> <render counts>"
```

### 6. Apply accepted feedback

Apply only comments accepted under `Acceptance` in `Rules`. Before a fix that
needs acceptance, call `deputy:ask`; its answer is advisory and never counts as
acceptance. If `deputy` is not installed, record `no-deputy:not-installed` and
ask the user as usual. After applying a change, run the suite that `test` would
select for the affected code and report the result.

## Iterate to closure

A new review loops through converge, permitted fixes, and re-review. A direct
standalone review uses `accepted_only` unless the caller explicitly selects
another mode. In an active run, use `review_fix_mode` from the run manifest.

In an active run, read the machine in force through the public engine state
interface before applying any claim. The fix mode then only selects the fix
list; end the iteration after sub-task 5 with the outcome from `Inputs and
outcomes`.

Standalone, one iteration runs sub-tasks 1–5, applies what the mode permits,
and re-reviews the result with a new slate, until one outcome applies.

## Rules

### Acceptance

Acceptance is per comment. It requires either:

- a reply to that specific comment that explicitly agrees to the change, such
  as "do this," "agreed, go ahead," or a thumbs-up; or
- that specific comment being marked `resolved-as-agreed`.

These do not count as acceptance:

- a question or pushback, such as "can you clarify?" or "why this way?";
- no reply;
- an overall PR approval;
- a comment marked `resolved-as-rejected` or `won't-fix`.

Treat unclear acceptance as `unclear`. Do not apply the comment.

A finding with status `survived` is real, not accepted — acceptance means
someone outside this review wants it fixed. Under
`review_fix_mode: accepted_only`, a `survived` finding still needs that explicit
outside signal. The exception is
`review_fix_mode: auto_within_permitted_mutations`, defined below.

If acceptance or intent is unclear, report the ambiguity. Do not choose an
interpretation. In an active `engine` run, the caller decides whether
`execute` should run `resolve` or `debate` against the settlement's
`source_of_truth`, usually the ticket or PR thread. Apply the change only
after the decision is settled.

### Fix modes

In an active run, apply no claim in any mode; fixing happens only in the
`fix` node.

`accepted_only`: report claims without applying them until a human or
`execute`, after `resolve` or `debate`, explicitly accepts each claim.
Re-review after an accepted fix. Do not apply a claim based only on this
review's own report.

`auto_within_permitted_mutations`: apply automatically only `fix-now`
claims, each by its patch, within the settlement's `permitted_mutations`.
This mode adds no mutation permission. Never apply this way a finding, or a
`disputed`, follow-up, killed or `choice` claim; those follow the
`accepted_only` rule. Findings with a `choice` go to the `review-debate` node
in a run, or to the user standalone. A `fix-now` patch outside
`permitted_mutations` also follows the `accepted_only` rule. The `fix` node
applies the patches and runs the tests and checks; the next review pass is
their re-review and records `fix-check` (sub-task 5). After a failed
`fix-check`, the `fix` node reverts that claim's patch.

Without an active run there is no settlement and no `permitted_mutations` to
stay within — a standalone caller selecting this mode gets `accepted_only`
behavior instead: report every claim, apply none.

## Fallbacks

If the `converge` skill hands back `blocked` (a role agent was
unavailable), stop and report `blocked`, naming the missing role. Claims start
`survived`; the fresh-eye batch is mandatory.

## Host mechanics

- Use the host's engine task adapter for session and state commands.
- Use the host's `converge` adapter and its bundled review reference files.
- Claude's adapters are `<engine-root>/bin/task`, with `<engine-root>` from
  `execute`'s handoff, and bare `converge` in Bash (the converge plugin's
  `bin/` is on PATH).
