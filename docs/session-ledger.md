# Session ledger

The session ledger is the on-disk record of one engine run. It holds the run's settlement, decision trail, open work, progress reports and state-machine position. A long run compacts its context, and the ledger is what keeps the settled facts outside the model's context. `recall` re-reads the ledger from disk instead of trusting what the model remembers. The ledger belongs to one run and is not shared between runs. Durable facts shared across sessions belong in [memory-ledger](memory-ledger.md).

Code: `plugins/engine/src/engine/session.py`, exposed as `task session init|validate|read|record-decision|next-question-id|update-todo|record-pitch|close`. The `## state` and `## machines` sections are written by `task state`; see [state-machine.md](state-machine.md). Only these commands write the file. No skill edits it directly.

## Location

The ledger is one Markdown file per run, at `<dir>/<run-id>.md`. The directory `<dir>` defaults to `~/.bootgear/session/` and can be changed with `--dir`. That default is outside every repo, so the ledger is never committed. `<run-id>` is the host's session ID, and it may contain only letters, digits, `.`, `_` and `-`. The engine hooks find the ledger by that session ID in the default directory. A single writer is assumed, and the file is never locked.

## Layout

```markdown
# session: <run-id> — <YYYY-MM-DD>

## settlement
task_type: <task-type>
goal:
  succeeded: <condition>
  failed: <condition>
state_machine: |
  name: <machine-name>
  nodes: ...
session_dir: <abs-dir>

## decisions
- <ts> [solo] <summary>
- <ts> [debate] [q1] round 0, party '<role>': <topic, scope, principles, cutoff>

## todos
- [x] <done todo>
- [ ] <open todo>

## pitches
- <ts> — <progress report>

## state
current: <node>
started: <ts>
- <ts> clarify -> <node> (<reason>)

## machines
- v2 <ts> at <node> (<reason>)
  name: <machine-name>
  nodes: ...

## closed
<ts> — succeeded
```

The file always has five sections, in this order: `settlement`, `decisions`, `todos`, `pitches` and `state`. `init` writes all five. Two more sections can follow `state`. `## machines` is optional and appears when a run amends its machine. `## closed` is written once, by `close`, and is always last. `<ts>` is a local timestamp to the minute. Decision, pitch and transition entries are one timestamped line each; a todo line carries no timestamp; a `## machines` entry is a timestamped header line followed by the machine's YAML.

## Sections

**Settlement.** This is the YAML output of `clarify`. It holds the task type, request assessment, approach, principles, per-domain `source_of_truth`, the debate rules and roster, the domain-skill manifest, autonomy scope, `goal`, the resolved `state_machine` (a block scalar) and `session_dir`.

- `init` writes the settlement once. It refuses when a ledger for that run already exists, unless `--force` is passed; `--force` overwrites the existing ledger, closed or not. It also refuses a settlement that has a line which looks like a section heading.
- `init` always replaces any `session_dir:` value in the settlement with the directory it resolved itself.
- `init` checks the value and type of the fields that are present, except that it only parses `state_machine` as YAML and does not check the shape of `goal` or `autonomy.permitted_mutations`. `session validate` adds those checks: every required field is present, `autonomy.no_further_questions` is true, `autonomy.permitted_mutations` is a non-empty list, `goal` has `succeeded` and `failed`, and `state_machine` passes `state validate`.
- The settlement is never rewritten after `init`.

**Decisions.** This section is append-only. Each entry has the form `- <ts> [<mode>] [<qN>] <summary>`. The mode is `solo`, `resolve`, `debate`, `debate-capped`, `debate-degraded` or `scope-settled`. Only the four debate modes carry a question tag, and they must carry one. The debate rules are:

- Question IDs start at `q1` and have no gaps. `next-question-id` issues them and refuses to issue one while another question is open, so at most one question is open at a time.
- A question starts with `round 0, party '<role>': ...` for scoping. It must be closed with `scope-settled` before any round 1 or later entry. Round numbers never go down.
- A question closes once, with `unanimous_convergence:` (mode `debate`), `round_cap:` or `consented_stop:` (mode `debate-capped`), or `degraded_convergence:` (mode `debate-degraded`). Each prefix must be followed by content. Nothing more is recorded for that question after it closes.

**Amendments.** Settlement fields change only through decisions. An amendment is a `solo` entry `AMENDMENT <field>: <old> -> <new>` with exactly one ` -> ` and a non-empty value on each side. The latest valid amendment of a field overrides the settlement from the next `recall` onward. `session_dir` cannot be amended, because `recall` needs it to find the ledger. A change to `session_dir` needs a new run. `state_machine` can be amended only by `task state amend`, which writes its own `AMENDMENT state_machine` decision.

**Todos.** Each entry is exactly `- [ ] <text>` or `- [x] <text>`. This section is the only one edited in place, apart from the `current:` line in `## state`.

- `update-todo "<text>"` adds an open todo, and `--done` marks a todo done.
- Reopening a done todo requires `--reopen`, so completed work is never undone silently.
- Text is matched first as an exact match and then as a substring. When the text matches more than one todo, `update-todo` refuses.

**Pitches.** This section is append-only. Each entry has the form `- <ts> — <text>` and records a progress report to the user, so a resumed run knows what it last reported.

**State.** This section holds `current: <node>`, `started: <ts>` and the transition log. `init` writes `current: clarify` and `started:`. `task state transition` rewrites `current:` and appends one log line per move. `started:` gives run age without file timestamps, because every ledger write changes those.

**Machines.** Each entry is one mid-run machine version, from `v2` upward with no gaps. The entry has a header line followed by the machine YAML, indented two spaces. The settlement machine is `v1`. `task state amend` is the only writer.

## Close

`close succeeded|failed [--reason]` appends `## closed` with the outcome, and `failed` requires a reason. `close` refuses in three cases:

- A debate question is still open.
- `current:` is not already the matching terminal node. `close` then names the transition or close command to run.
- The ledger is already closed.

After close, every write is refused except an `init --force` overwrite, but the ledger stays readable. The ledger is kept after the run, as the audit record.

## Reading

`read` prints the whole ledger or one `--section`. It can also print only open todos (`--open-only`), the last N decisions and pitches (`--last N`), or one debate's entries (`--question qN`). `--json` returns section lines; only `--section state --json` also parses `## state` into `current`, `started` and `transitions`. The state-nudge hook reads the ledger through `read --section state --json`. The session-start and stop hooks read the ledger file directly, for the settlement and the `## closed` heading.

## Validation

Every command that opens an existing ledger checks the whole file before it reads or writes anything:

- **Structure**: each of the five sections appears exactly once and in order. There is at most one `## closed`, and it follows `## state` and `## machines`. There is at most one `## machines`, and a line that looks like `## machines` is treated as the section only after `## state`.
- **Decisions**: every tagged entry is re-checked against the question-ID, round, close-prefix and one-open-question rules. An entry whose tag is hidden by a malformed or unknown mode bracket is refused. An untagged entry with an unknown mode is accepted.
- **Todos**: every line must be a well-formed checkbox followed by text.
- **Writes**: free-text values must be a single line. A settlement line that reads as a section heading is refused. Every write goes to a temp file with an unpredictable name and is then renamed over the ledger, so a crash never leaves a half-written file.

The check covers the whole decisions section. One malformed tagged entry anywhere in it blocks every read and write of the ledger.
