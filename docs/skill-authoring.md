# Skill authoring

These rules apply to every skill in `plugins/` and `codex-plugins/`.

## Public interface

Skills are public functions. Another skill sees a skill's signature and never
its body. The public interface of a skill is:

- its **name**, used to invoke it through the `Skill` tool (for example
  `memory-ledger:ledger`, `spec`, `review`);
- the **name and meaning of each settlement field** it reads or writes,
  stated inline where the field is used.

A skill never refers to another skill's internal file, section, heading,
script path, or layout. The other skill owns that structure and can rename it,
restructure it, or replace it with a project override, and a reference into it
goes stale without any error. If a caller needs a fact, state it inline, even
if the same short fact then appears in two places. A skill may call another
skill by name, and a plugin that does so must declare the callee as a
dependency or bundle a copy of it.

Every line of a skill, host adapter sections included, names another skill
by its plain public name, without Claude `/` or Codex `$` punctuation. Only
host adapter sections describe plugin-root paths, session identity, agent
mechanism, and output wiring. A
shared skill names the public command it calls in its common sections, and
puts the resolved path in `## Host mechanics`. Claude adapters use
`<plugin-dir>/bin/<command>` and Codex adapters use
`<plugin-root>/scripts/<command>`. Each wrapper resolves the project root from
its own location.

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
| `converge` | `full` or `refute-only` slate processing. | `converged`, `unconverged`, or `blocked`. |
| `advisor` | `asking` (`direct`/`channel` × `rewrite`/`ask`/`review`/`delegate`) or `listening`. | One reconciled answer, or mailbox state. |
| `memory-ledger:ledger` | Capability, resolve/show, verify, append, sign, rival, hook envelope. | Result for that operation; only write operations append. |
| `memory-ledger:setup` | Dependency check, roots, config wiring, optional remote, audit. | One result per requested check or mutation. |
| `spec` | `requirements`, `design`, `sign-off`, `task`. | A stage artifact, an explicit open question, or a structural refusal. |
| `test` | Write cases, run tests, triage reports. | Separate cases-written, run, and triage results with real output. |
| `review` | New review or applying accepted comments, `quick`/`full` depth. | `handoff`, `comment_only`, `clean`, `below_cutoff`, `blocked`, `no_progress`, or `iteration_cap`. |

## SKILL.md and reference.md

- `SKILL.md` is the action contract. It says when to invoke the skill, the
  inputs it needs, what it hands back and to whom, every outcome, judgment
  rules, safety boundaries, and what to do when the owning CLI is
  unavailable. It holds no rationale. Edge-case handling that changes the
  action stays in `SKILL.md`.
- `reference.md` sits next to `SKILL.md` and holds the rationale, kept as
  short as possible. It is not a second procedure manual.
- The harness supplies the skill name from frontmatter, so `SKILL.md` has no
  H1 that repeats it.

## Reference form

A `SKILL.md` refers to its own `reference.md` only by an exact heading path:

- ``Read `reference.md` § `Heading` ``
- ``Read `reference.md` § `Parent` > `Child` ``

The heading text is the source spelling, not an anchor or line number. When a
heading is renamed, its callers change in the same commit.

`quality/check_skill_references.py` runs in the quality gate
(`quality/check.py`). It scans every `SKILL.md` and `reference.md` under both
plugin trees and rejects:

- a heading path that does not resolve in the adjacent `reference.md`, or
  that matches more than one heading;
- ``Read `reference.md` `` with no `§` heading path;
- a path to another skill's `SKILL.md` or `reference.md`, or wording like
  "the X skill's reference/file/section/heading";
- a `/name` or `$name` invocation of another skill on any line, host adapter sections included;
- an H1 that repeats the frontmatter name.

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
