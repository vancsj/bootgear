# Skill authoring

These rules apply to every skill in `plugins/` and `codex-plugins/`.

## Public interface

Skills are public functions. Another skill sees a skill's signature and never
its body. The public interface of a skill is:

- its **name**, used to invoke it through the `Skill` tool (for example
  `memory-ledger:ledger`, `spec`, `review`);
- its **modes** and their **handbacks**;
- its **`settings` subcommand**, which prints what a caller must supply to use
  it: the settlement fields it reads, their value domains and defaults.

A skill never refers to another skill's internal file, section, heading,
script path, or layout. The other skill owns that structure and can rename it,
restructure it, or replace it with a project override. A caller learns a
callee's settings by running `settings`, never by reading the callee's files.
A skill may call another skill by name; a Claude plugin that does so must
declare the callee as a dependency, and a Codex skill states what to do if the
callee is missing.

Every line of a skill, host adapter sections included, names another skill
by its plain public name, without Claude `/` or Codex `$` punctuation. Only
host adapter sections describe plugin-root paths, session identity, agent
mechanism, and output wiring. A
shared skill names the public command it calls in its common sections, and
puts the resolved path in `## Host mechanics`. `engine` and `converge` call a
wrapper (`<plugin-dir>/bin/<command>` on Claude, `<plugin-root>/scripts/<command>`
on Codex) that resolves the project root from its own location. `memory-ledger`
and `advisor` call their Python script directly under the plugin root.

## Public skill contracts

Each public skill defines its callable contract per operation or mode:

- **invocation**: the public name and any host adapter;
- **operation or mode**: a value the caller can see;
- **inputs**: required arguments, settlement fields, and value domains, and
  which values the caller provides and which are resolved;
- **handback**: every distinct outcome and the fields each one carries;
- **effects**: reads, ledger or state writes, artifacts, subprocess or agent
  calls, and external mutations, each with its permission boundary.

A shared field vocabulary does not make unrelated operations interchangeable.

| Skill | Operations or modes | Handback |
| --- | --- | --- |
| `engine:start` | Start from the original request. | Hands off to `engine:clarify`. |
| `engine:clarify` | Assessment, task type, state machine, goal, run manifest. | Confirmed settlement with run ID, `session_dir`, `goal`, `state_machine`, permitted mutations; or a work question. |
| `engine:execute` | Run the settled state machine. | Progress handbacks; terminal `succeeded` or `failed`. |
| `engine:recall` | Read settlement, amendments, todos, current node, pitches. | Current run state; read-only. |
| `engine:resolve` | Resolve one contested decision from `source_of_truth`. | Resolved from a named source, or escalated to `engine:debate`. |
| `engine:debate` | Scope, rounds, retries, angle round, convergence. | `unanimous_convergence`, `consented_stop`, `round_cap`, or `degraded_convergence`. |
| `converge` | Slate processing: find, attack and cut; claim statuses `survived`, `disputed`, `unverified`, `killed`. | `converged`, `unconverged`, or `blocked`. |
| `advisor` | `asking` (`direct`/`channel` × `rewrite`/`ask`/`review`/`delegate`) or `listening`. | One reconciled answer, or mailbox state. |
| `memory-ledger:ledger` | Capability, resolve/show, verify, append, sign, rival, hook envelope. | Result for that operation; only write operations append. |
| `memory-ledger:setup` | Dependency check, roots, config wiring, optional remote, audit. | One result per requested check or mutation. |
| `spec` | `requirements`, `design`, `sign-off`, `task`. | A stage artifact, an explicit open question, or a structural refusal. |
| `test` | Write cases, run tests, triage reports. | Separate cases-written, run, and triage results with real output. |
| `review` | New review or applying accepted comments, `quick`/`full` depth. | `handoff`, `comment_only`, `clean`, `below_cutoff`, `blocked`, `no_progress`, or `iteration_cap`. |

## SKILL.md and reference docs

- `SKILL.md` is the action contract. It says when to invoke the skill, the
  inputs it needs, what it hands back and to whom, every outcome, judgment
  rules, safety boundaries, and what to do when the owning CLI is
  unavailable. Edge-case handling that changes the action stays in
  `SKILL.md`.
- No rationale in a skill doc or its reference docs, and absolutely no
  maintainer rationale (design history, alternatives considered, why the doc
  is laid out as it is). Design rationale belongs in tickets, PR bodies and PR
  comments.
- Explaining why an action is required is fine, kept to a clause or a short
  sentence.
- A skill can have several reference docs next to `SKILL.md`. They implement
  progressive exposure: detail needed only on some paths lives in a reference
  doc, and `SKILL.md` points to it where it applies. Each reference doc is
  focused on one topic and concise. None is a second procedure manual.
- The harness supplies the skill name from frontmatter, so `SKILL.md` has no
  H1 that repeats it.

## Reference form

A `SKILL.md` points to its own reference docs by file name, where the detail
applies and with the condition for reading it. It never names another skill's
file, section or heading, writes another skill's name with `/` or `$`, or
opens with an H1 that repeats its own name. Review checks this against
`.bootgear/config/review-standard.md`.

## CLI-owned reminders and skill prose

Detail belongs in CLI output, not skill prose, when all of these are true:
the CLI derives it from validated state or configuration, it matters at a
specific decision point, it can be printed as a fixed command, legal
destination, field, gate, or refusal correction, and a test covers its prose
and JSON output. Otherwise it stays in the skill.

- The CLI that owns the state prints the reminder. The engine
  `state current`/`transition` commands print the node reminder, branches,
  and leave gates. `session validate` reports every settlement problem in one
  grouped refusal. State-changing `converge` commands print the next step.
- `next` appears only when validated state fixes the next action. When the
  model must choose, the CLI lists the legal branches and what each means.
- A skill names the public command it calls and uses that command's output.
  It does not repeat the command's argument table, state shape, or recovery
  steps, and it drops any line that repeats a reminder.
- Judgment always stays in the skill: goal checks, debate positions, angle
  selection, review severity, requirements, test interpretation, and safety.
  A CLI reminder, `--confirm-leave`, or a successful command is never proof
  that work is complete.
