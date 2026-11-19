---
name: review
description: Review a diff, branch, or PR for correctness, architecture, security, simplicity, and convention fit, then apply accepted feedback. Works standalone and delegates to a project review skill when one is registered. Use when a change needs reviewing or review comments need applying.
---

In an active Engine run, keep `session_dir` in context. Omit `--dir` for the default `~/.bootgear/session`; pass `--dir <session-dir>` only for a custom directory.

## Inputs and outcomes

Take the diff, branch or PR, any linked ticket, and depth (`quick` or `full`).
Engine callers also supply `<engine-root>`, `<session-dir>`, sub-task label and `review_fix_mode`.
Authoring callers supply authoring context, the fixed task folder and any current self-review checkpoint.

For every iteration, give `execute` or the standalone user the slate ID, Converge directory and render.
Include ranked findings with status, choices, follow-ups with status, killed claims with evidence, and `fix-now` patches with any `fix-checks`.
Report the enabled angle packs and reason, including none, or mark them as carried from the previous slate.
Return follow-ups to the caller for recording. State the ending outcome and iteration count.

- **`handoff`** — the current Engine node has a `fix` edge and the mode permits a fix or requires a revert. Return the claim IDs marked `apply` or `revert`, including when the only applicable claims are `fix-now`.
- **`comment_only`** — the current Engine node has no `fix` edge. Report every finding and `fix-now` claim as a comment, regardless of mode.
- **`clean`** — the re-review or Engine single-pass render has no findings, `fix-now` claims, or follow-ups.
- **`below_cutoff`** — only follow-ups remain.
- **`blocked`** — author checking is incomplete, source selection awaits confirmation, or a required role or find coverage is missing. Also use for a disputed finding or blocked Converge handback. Use when a finding or `fix-now` claim lacks acceptance, a decided choice, or mutation permission it needs.
- **`no_progress`** — the same unchanged claim returns after a fix attempt without new evidence.
- **`iteration_cap`** — live claims remain at the configured cap and no other outcome applies. Default cap is 5.

With a `fix` edge and an empty fix list, use the render's `clean`, `below_cutoff`, or `blocked` result.
Only the caller judges whether the broader goal is complete.

For apply-only requests, return one disposition per in-scope comment and omit the loop outcome:

- **`applied`** — changed and verified. Include the result.
- **`accepted but not applied`** — name the conflict or failed verification.
- **`rejected or won't-fix`** — give the reason from the thread.
- **`unclear`** — state the unresolved acceptance or intent.

## Workflow

Complete the author checkpoint when applicable, then check for a review override. For apply-only requests, start at step 6. For a new review, choose depth and start a slate. Run Converge with the required briefs and gap hunt, then report cutoff and disposition. Re-review on a new slate after permitted fixes.

## Author checkpoint

Before a new independent slate or override delegation, check whether independent feedback changed the artifact after its author check.
If it did, invoke self-review with the related independent reference and renew the closed checkpoint before delegation.
Otherwise, reuse a completed checkpoint only when public status confirms clean or limit-reached for this handoff.
If no completed checkpoint applies, invoke self-review for stage code on authoring paths.
Give the author check the complete current diff and fixed task folder.
Ordinary edits and retries never reset the open checkpoint's count.
Return the public author-review reference and all still-open references to the caller, separately from independent findings.
Keep author hypotheses and suspect lists out of independent role briefs.

On needs-selection, return blocked with checkpoint kind source-selection, candidates, pending scope and missing confirmation.
The direct caller obtains confirmation; an active execute caller uses clarify checkpoint mode.
On unavailable, return blocked with the actual diagnostic and named missing mechanism. Never bypass the author check.
A completed cap leaves deeper issues open. The caller retains them until explicit independent disposition.

## Check for an override first

In an Engine run, use the session interface with the supplied directory. Check the latest valid `review_override` and `review_fix_mode` amendments in the full decisions. Use the effective override as a skill name or pick the exact caller-supplied depth label from its mapping. With no match, use the default below. Standalone, use a registered project review skill when it fits.

Pass the hand-filled test brief from step 3 to the override. Require it in every new or continued role brief. Allow memory-ledger lookup and record for read-only roles. Pass the Engine root and session directory when active. Require the same handback fields.

## Default implementation

Use the same `<converge-dir>` for every action on the slate.

### 1. Depth

Use the depth label passed by the caller, else `full`:

- `quick`: lenses `correctness,tests`; agents main, F, R1, C; no gap hunt.
- `full`: lenses `correctness,security,architecture,tests,simplicity,contract,consistency`;
  agents main, F, R1, R2, C; gap hunt by R2.

Reuse each seat and stay within the depth's role budget. A later debate has its own budget. The finder covers every find angle of each lens.

Each lens's scope and finder brief is in
[references/lenses.md](references/lenses.md).

### 2. Start the slate

Choose the slate id and the converge dir:

- In an active run: slate `<run-id>-review-<n>`, where `<n>` counts this run's
  review slates from 1; converge dir `<session-dir>/converge` as an absolute
  path.
- Standalone: slate `review-<UTC timestamp as YYYYMMDD-HHMMSS>`; converge dir
  `$HOME/.bootgear/converge` as an absolute path.

Use Converge `init` with the depth's lenses and project root. Include [references/find-angles.yaml](references/find-angles.yaml) and each selected lens's `references/angles-<lens>.yaml` when present. For architecture, also include [references/design-patterns.yaml](references/design-patterns.yaml) and [references/evaluate-angles.yaml](references/evaluate-angles.yaml). Pass the absolute path of [references/cutoff.yaml](references/cutoff.yaml) as `--defaults`. For `quick`, set `--refuters 1`.

Read every `# use when:` in the [web](references/pack-web.yaml), [typed OOP](references/pack-typed-oop.yaml), [concurrency and DB](references/pack-concurrency-db.yaml), and [test tooling](references/pack-test-tooling.yaml) packs. Select from project instructions, docs and root build files or manifests. Exclude the diff and changed-file list. Enable a pack when unsure. If those sources give no stack information, enable none. For a re-review, reuse the previous slate's `.packs` list when present. Save one enabled file name per line in `<converge-dir>/<slate>.packs`, or an empty file. Include the packs in `init`. On a duplicate angle ID naming a pack, remove it from the list and the command, then retry.

In an active run, write the settlement with
`<gear> --host <host> engine task session read --section settlement --prose > <converge-dir>/<slate>.settlement.yaml`
and supply it with `--settlement`.

In an active run, add `--snapshot --pass <n>` to `init`; for `<n>` ≥ 2, also
add `--since <run-id>-review-<n-1>`. Use the root of the worktree holding the change. Right after `init`, record the slate for snapshot cleanup:

```text
<gear> --host <host> engine task session record-decision --mode solo --summary "review slate <slate> snapshot=<sha>"
```

After a successful `init` in an active run, record the final pack list from
`<converge-dir>/<slate>.packs`:

```text
<gear> --host <host> engine task session record-decision --mode solo --summary "review angle packs <slate>: <names or none>; <reason>"
```

On a `--since` refusal, keep the pass number and pause. Ask `execute` to resolve the re-review baseline against the rule that it covers changes since the previous snapshot. Record the decision. Rerun without `--since` only after approval to widen to the full change. Otherwise return `blocked`.

If the project has `.bootgear/config/review-standard.md`, first write
`<converge-dir>/<slate>.yaml` containing
`cutoff: {report_rules: [<every rule ID whose severity is at or above the standard's cutoff:>]}`
and add `--config <converge-dir>/<slate>.yaml` to `init`.

### 3. Find, escalate, cut, attack

Hand the slate to `converge`. Use its public `work` and `act` flow for role routing, actions, and stale-work recovery. Supply the role's actor and executing host when preparing its work. Give the finder the selected lens scopes, actual diff and linked ticket. Run full review's gap hunt after find coverage, before escalation and cutting.

Give each role the host user-principles file, project principles and standards in `.bootgear/config/`, and the Engine settlement principles when active. Require it to read applicable files before acting.

Before each new or continued finder brief, the main agent fills this required part by hand:

```text
Tests already ran:
- latest test: <recorded command>; result: <one recorded result line>
```

Use the latest test command recorded in the run ledger, even if it covers only part of the tests.
Use one result line from that record. Include no exit code or record path.
Do not combine commands that did not run together.
If no test result is recorded, write `none recorded`.
Tell the role to skip redundant runs covered by recorded test commands.
The role can probe behaviour those commands did not cover.
Allow memory-ledger lookup and record, including for read-only roles.
Scope other write limits to preserve these operations.

For pass 2 or later, give F the diff command from `init` and the previous render. Claims outside the diff need a behavior change caused by it. After a `fix-now` patch, restrict this one-round re-review to problems those patches introduce.

If the project has `.bootgear/config/review-standard.md`, give F its rules and
have it tag each claim that breaks one with `--rule R###`.
A claim tagged with a rule at or above the standard's `cutoff:` is never
cut; converge's cutoff decides whether every other claim is cut.

### 4. Gap hunt

Brief the full review's gap hunter with:

- the current `converge render` output;
- the diff and the linked ticket;
- the hand-filled test part and instructions from sub-task 3, refreshed for each new or continued turn;
- the question: what did every lens miss, and does the ticket match the diff
  in both directions (asked but missing, present but unasked)?

### 5. Cutoff, render and choices

Follow Converge's printed cutoff and render actions. Use the current render for disposition.

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
<gear> --host <host> converge converge fix-check <previous slate> --dir <converge-dir> --as main --claim <id> --outcome pass|fail --evidence "<checks run and their result>" --review-slate <slate>
```

Record `pass` only when the `fix` node's tests and checks passed and this
slate holds no finding; otherwise record `fail`, and the claim goes in the fix
list marked `revert`. Then rerun `converge cutoff` on the previous slate.

In an active run, record the slate, directory, snapshot and counts. Supply leave arguments from the selected exit's public check.

```text
<gear> --host <host> engine task session record-decision --mode solo --summary "review slate <slate> converge_dir=<converge-dir> snapshot=<sha> <render counts>"
```

### 6. Apply accepted feedback

Apply only comments accepted under `Acceptance` in `Rules`. Before a fix that
needs acceptance, call `deputy:ask`; its answer is advisory and never counts as
acceptance. If `deputy` is not installed, record `no-deputy:not-installed` and
ask the user as usual. After applying a change, run the suite that `test` would
select for the affected code and report the result.

## Iterate to closure

Engine runs read the machine in force and effective fix mode, then return from step 5. Standalone defaults to `accepted_only`, applies accepted feedback and re-reviews on a new slate until one outcome applies. Report standalone `fix-now` claims without applying their patches.

## Rules

### Role scope

Keep the reviewed artifact read-only during independent judging.
Roles may write their assigned workflow records and read or record memory-ledger entries.
Keep other write limits and judging independence. Never supply author private analysis to judging roles.

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

A `survived` finding still needs acceptance from outside this review.

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

If a standalone caller selects automatic mode, report every claim and apply none. An apply-only request still follows the per-comment acceptance rules.

## Fallbacks

If required self-review is missing, return blocked and name the missing skill.

If the `converge` skill hands back `blocked` (a role agent was
unavailable), stop and report `blocked`, naming the missing role. Claims start
`survived`; the fresh-eye batch is mandatory.

## Host mechanics

Call `cli:gear` for the absolute path. Use `claude` on Claude Code and `codex` on Codex.
Run `<gear> --host <host> engine task <command>` and `<gear> --host <host> converge converge <command>`.
Take the run id from `CLAUDE_CODE_SESSION_ID` or `CODEX_SESSION_ID` on the corresponding host.
If `cli:gear` is missing, install `cli@bootgear` through the host.
On Codex, if a required sibling skill is missing, report `cli:setup` with target `review`. Resume after setup verifies the plugins.
