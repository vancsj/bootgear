---
name: review
description: Review a diff, branch, or PR for correctness, architecture, security, simplicity, and convention fit, then apply accepted feedback. Works standalone and delegates to a project review skill when one is registered. Use when a change needs reviewing or review comments need applying.
---

Review a change and apply accepted feedback. See
Read `reference.md` § `Findings go through converge` for design rationale.

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
must return the fields defined in `Reporting back`.

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
- `full`: lenses `correctness,security,architecture,tests,simplicity,contract`;
  agents main, F, R1, R2, C; gap hunt by R2.

This slate is one task: never use more than these agents on it, and reuse
each one across rounds. The cap counts this slate only; a later debate on its
choices has its own budget. F covers every find angle of every lens; each refuter
takes ≥1 unused attack angle per claim per round, and R1 alone takes ≥2. The
roles and agent ids are the `converge` skill's step 2.

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
depth, lenses, angle files, and project root.

In an active run, add `--snapshot --pass <n>` to `init`; for `<n>` ≥ 2, also
add `--since <run-id>-review-<n-1>`. Also add `--project-root <repo root>` to
`init`, where `<repo root>` is the top level of the work tree holding the
change under review. Right after `init` succeeds, record the slate so
`execute` prunes its snapshot however the review ends:

Record the slate and snapshot through the public engine session command.

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

### 3. Find, refute, cut

Run the `converge` skill in `full` mode on the slate with the
depth's agents: at `full`, two refuters (R1, R2) and the gap hunt of
sub-task 4; at `quick`, one refuter (R1) and no gap hunt.

Spawn one finder, F, for every lens from sub-task 1. Give it one brief listing
every lens with its scope and brief from `references/lenses.md` and that
lens's find angles, plus the actual diff (not only commit messages or the PR
description) and the linked ticket if any.

For `<n>` ≥ 2, also give F the `git diff` command `init` printed and the
previous slate's `converge render` output as settled context. A claim outside
that diff is in scope only when the diff changes that code's behaviour.

If the project has `.bootgear/config/review-standard.md`, give F its rules and
have it tag each claim that breaks one with `--rule R###`.
A claim tagged with a rule at or above the standard's `cutoff:` is always
reported once it survives refute; converge's cutoff decides every other claim
and whether the outcome is `below_cutoff`.

### 4. Gap hunt

`full` only; `quick` has no gap hunt. After refute of the lens claims
converges, continue R2 as the gap-hunt finder, filing its claims with
`--as r2` and `origin: gap-hunt`; R1 refutes them, then C cuts them through
the same `converge` steps. Brief R2 with:

- the current `converge render` output;
- the diff and the linked ticket;
- the question: what did every lens miss, and does the ticket match the diff
  in both directions (asked but missing, present but unasked)?

### 5. Cutoff, render and choices

Run the fixed cutoff action printed by the CLI after the gap-hunt claims
converge.

Run `cutoff` after the gap-hunt claims converge, so it is the slate's latest
state-changing event. The render is the findings list.

Route every claim carrying a `choice`:

- In an active run: report it to the caller for the `review-debate` node. A
  factual dispute is not a choice; it stays in converge.
- Standalone: report it to the user.

In an active run, record the slate, the converge dir and the `snapshot=<sha>`
that `init` printed; the caller passes the first two as
`--leave-arg slate=<slate> --leave-arg converge_dir=<converge-dir>` when
leaving `review`:

Record the slate, converge directory, snapshot, and render counts through the
public engine session command.

If the `converge` skill hands back `blocked` (a role agent was
unavailable), stop and report `blocked`, naming the missing role. Do not
treat any claim it left without a refuter as survived.

### 6. Apply accepted feedback

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

A claim that converge reports as survived is real, not accepted — acceptance
means someone outside this review wants it fixed. Under
`review_fix_mode: accepted_only`, a survived claim still needs that explicit
outside signal. The exception is
`review_fix_mode: auto_within_permitted_mutations`, defined below.

If acceptance or intent is unclear, report the ambiguity. Do not choose an
interpretation. In an active `engine` run, the caller decides whether
`execute` should run `resolve` or `debate` against the settlement's
`source_of_truth`, usually the ticket or PR thread. Apply the change only
after the decision is settled.

After applying a change, run the suite that `test` would select for the
affected code and report the result.

## Iterate to closure

A new review loops through converge, permitted fixes, and re-review. A direct
standalone review uses `accepted_only` unless the caller explicitly selects
another mode. In an active run, use `review_fix_mode` from the run manifest.

In an active run, read the machine in force through the public engine state
interface before applying any claim.

In an active run, apply no claim in any mode; fixing happens only in the `fix` node. The modes below then only select the fix list.

- When `machine.nodes[current].next` includes `fix` and the mode would apply at least one claim, end the iteration after sub-task 5 with outcome `handoff`: return, as the fix list, the ids of those claims; `execute` applies them in the `fix` node.
- When `machine.nodes[current].next` includes `fix` and the fix list is empty, end with the outcome the render gives below: `clean`, `below_cutoff`, or `blocked`.
- Otherwise, end the iteration after sub-task 5 with outcome `comment_only`: report every surviving claim and apply none, whatever `review_fix_mode` says.

### `accepted_only`

Report claims without applying them until a human or `execute`, after
`resolve` or `debate`, explicitly accepts each claim. Re-review after an
accepted fix. Do not apply a claim based only on this review's own report.

### `auto_within_permitted_mutations`

Apply automatically only claims that the cutoff marks `reported`, whose refute
state converged as `survived`, and whose `difficulty` is `trivial` or `local`,
within the settlement's `permitted_mutations`. This mode adds no mutation
permission. Never apply this way an `inconclusive`, `unconverged`, appendix or
`choice` claim, or a claim whose `difficulty` is `cross-cutting` or
`redesign`; those follow the `accepted_only` rule. Cross-cutting and redesign
claims carry a `choice` and go to the `review-debate` node in a run, or to the
user standalone. A fix outside `permitted_mutations` also follows the
`accepted_only` rule.

Without an active run there is no settlement and no `permitted_mutations` to
stay within — a standalone caller selecting this mode gets `accepted_only`
behavior instead: report every claim, apply none.

One iteration runs sub-tasks 1–5, applies what the mode permits, and
re-reviews the result with a new slate.

The loop ends with exactly one outcome:

- **`handoff`:** In an active run, the current node has a `fix` edge and the
  mode would apply at least one claim; the `fix` node takes over. Return the
  fix list: the ids of those claims.
- **`comment_only`:** In an active run, the current node has no `fix` edge.
  Every surviving claim is reported and none is applied.
- **`clean`:** A re-review's render, or an active run's single-pass render,
  has no `reported` claim and no `inconclusive` or `unconverged` claim.
- **`below_cutoff`:** The render has only appendix claims, and no
  `inconclusive` or `unconverged` claim.
- **`blocked`:** A `reported` claim needs a mutation outside the mode's
  permission — an unaccepted claim under `accepted_only`, an undecided
  `choice`, or a mutation outside `permitted_mutations` — or any
  `inconclusive` or `unconverged` claim remains, or the `converge`
  skill handed back `blocked`.
- **`no_progress`:** The loop again finds the same unchanged claim after
  trying to fix it, with no new information.
- **`iteration_cap`:** The configured iteration cap is reached with live
  claims remaining and none of the other outcomes applies. The default cap is
  `5`, unless project configuration sets another value.

Report claims from every iteration, not only the final iteration. State the
ending outcome and iteration count.

## Reporting back

Return each iteration's slate id, converge dir and `converge render` output:
reported claims in rank order, `choice` claims, `inconclusive` and
`unconverged` claims, the appendix, and killed or retracted claims with their
reason.

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

For `handoff`, return the fix list (claim ids) in place of the applied-feedback
accounting above; nothing was applied. For `comment_only`, report every
surviving claim as a comment, with none applied.

For a new review that used `Iterate to closure`, also return the ending outcome
and iteration count. `execute` uses these fields to update its todos and
determine whether the broader task is complete. This skill does not decide
whether that broader task is complete.

## Host mechanics

- Use the host's engine task adapter for session and state commands.
- Use the host's `converge` adapter and its bundled review reference files.
- Codex's adapters are `<plugin-root>/scripts/task` and
  `<plugin-root>/scripts/converge`.
