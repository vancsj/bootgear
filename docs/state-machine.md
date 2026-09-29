# State machine

Every engine run moves through a state machine: a YAML graph of named nodes and legal edges. The machine lives in the run's [session ledger](session-ledger.md). `task state transition` is a hard gate: it refuses an illegal move instead of logging it. The machine enforces only which moves are legal. The work inside a node is still done by skills (`execute`, `resolve`, `debate`, the domain `spec`/`test`/`review` skills), which call `transition` when they finish.

Code: `plugins/engine/src/engine/state.py` (commands `transition`, `current`, `amend`, `show`, `validate`, `diagram`), with ledger I/O shared from `session.py`.

## Schema

```yaml
name: example-review
description: a minimal machine with one gated review loop.
nodes:
  clarify:
    next: [review]
  review:
    reminder:                          # optional
      do: "Review the change with review."
      leave: "`converge gate` exited 0 for this review's slate."
      leave_check: [converge, gate, "{slate}", --dir, "{converge_dir}"]
      branches:
        fix: "An accepted finding requires a correction."
        succeeded: "The review is clean."
    next: [fix, succeeded]
  fix:
    max_visits: 3                      # optional
    reminder:
      do: "Apply the accepted findings."
    next: [review]
  succeeded:
    terminal: true
  failed:
    terminal: true
```

Each node may have these fields:

- `next`: the list of legal destinations. Every non-terminal node must have a non-empty list. A terminal node has none.
- `terminal`: a boolean, false by default. Only `succeeded` and `failed` may be terminal, and both must be.
- `max_visits`: a positive integer, allowed only on a non-terminal node. `transition` refuses to enter the node once the run has entered it that many times. Entries are counted from the `## state` log across every machine version, and the start node gets one implicit entry at `init`.
- `reminder`: an optional mapping.
  - `do`: one line saying what to do in the node, naming the skill in its call form.
  - `branches`: one line per destination saying what it means. Its keys must match `next` exactly.
  - `leave`: one line saying what must be true before leaving the node. It turns on the leave gate.
  - `leave_check`: an argv list the engine runs when the node is left. It requires `leave`. Its only braces may be `{name}` placeholders, with `name` matching `[a-z_]+`.

Every machine has these fixed nodes. `clarify` is the only start node. `succeeded` and `failed` are the only terminal nodes, and they match the two outcomes of `session close`. There is no shared sub-machine. `spec-debate`, `triage-debate` and `review-debate` are ordinary nodes, and each declares its own exits.

`task state validate <path>` checks a machine against these rules. It also checks three more things:

- Every `next:` target exists.
- Every node is reachable from `clarify`, counting the implicit `failed` edge.
- `succeeded` is reachable.

It also refuses two node names that map to the same Mermaid ID, because `-` and `_` become the same character in a Mermaid ID. `validate` rejects a `reminder.skill` field. When a machine already in a ledger has one, `do` is printed with `Call the <skill> skill.` appended on the same line. `task state diagram <path>` prints `stateDiagram-v2` source for a valid machine only. It labels each edge with its `branches` text.

### The universal failed edge

Every non-terminal node can move to `failed`, even though no `next:` list names it. `validate` counts this edge for reachability, and `transition` always accepts `--to failed` from a non-terminal node. Every other destination, `succeeded` included, must be in the current node's `next:` list. A move to `failed` still passes the node's `leave` gate. Only `leave_check` is skipped for `failed`, so a run can still fail when the check cannot pass.

## Override tiers

`clarify` resolves the machine once, before it writes the settlement:

1. **Built-in**: `plugins/engine/state-machines/<task_type>.yaml`. There is one for each task type: `ticket-writing`, `bug-triage`, `ticket-to-pr` and `pr-review`. Each starts with `clarify -> inspect`. Every `review` node carries the `converge gate` `leave_check`, and every `fix` node, plus `review-debate` in `pr-review`, sets `max_visits` so the review and fix loops end.
2. **Project**: `.bootgear/config/state-machine-<task_type>.yaml`. When this file exists, it replaces the built-in machine completely. It is not merged. People own it, and no skill writes it.
3. **Per-run**: `clarify` can adjust the resolved machine for this run. For example, it can drop `fix` from a review of someone else's PR. It validates the result, shows the diagram and every `leave_check` argv for the user to approve, and records the complete machine in the settlement's `state_machine: |` block scalar.

After the settlement is written, the tiers are never resolved again. The run's machine starts as the settlement machine, which is v1. Only `amend` can change it.

## Transition: the hard gate

```text
task state transition <run-id> --dir <session-dir> --to <node> --reason "<why>" [--confirm-leave] [--leave-arg name=value ...]
```

`transition` reads the machine in force and `current:` from the ledger. It refuses the move in any of these cases:

- The ledger is closed.
- The current node is terminal.
- The destination is not a node, or it is neither in `next:` nor `failed`.
- The destination has reached its `max_visits` limit.
- The current node has a `leave` and `--confirm-leave` was not passed.
- The current node has a `leave_check` that fails, and the destination is not `failed`.

On success, it makes one atomic write. The write updates `current:` and appends `- <ts> <from> -> <to> (<reason>)` to the `## state` log. When a check ran, the log line ends with `[leave_check exit 0: <argv>]`. A refused move writes nothing.

`transition` does not check that `/goal` is actually met. When the destination is terminal, it prints a `CONFIRM` line that asks the caller to confirm the goal's matching condition. It then prints the `session close` command as the next step. `session close` refuses to run until `current:` equals the outcome.

### The leave gate

`leave` is enforced only by the caller's word: `--confirm-leave` is a bare flag. The gate guarantees that the model cannot leave a node without deliberately asserting that the condition holds. `leave_check` adds a check the engine runs itself:

- Each `{name}` placeholder is filled from exactly one `--leave-arg name=value`. `transition` refuses a missing arg, an extra arg, a repeated arg, an empty value, a multi-line value, or a value that starts with `-`. These refusals are skipped for `--to failed`, because the check does not run. `transition` refuses `--leave-arg` on a node without a `leave_check` for every destination.
- `argv[0]` is resolved on `PATH`, where the Claude plugin `bin/` directories are. On Codex, the plugin's own `scripts/<argv[0]>` is tried first, then `PATH`. The check runs without a shell and with no stdin, in its own process group. Its timeout is 120 s, or the value of `ENGINE_LEAVE_CHECK_TIMEOUT`. `transition` refuses the move on a non-zero exit or a timeout, and quotes the last 40 lines of output.
- A passing check never replaces `--confirm-leave`, and `--confirm-leave` never bypasses a failing check.

A `leave_check` is code that the engine runs, so the approval of the check at `clarify` is the point of trust.

## Amend

```text
task state amend <run-id> --dir <session-dir> --machine-file <file> --reason "<why>"
```

The settlement is write-once, so a machine that changes mid-run is appended as a new version. `amend` exits at once on a closed ledger. Otherwise it collects every problem and names them in one refusal:

- The current node is terminal.
- The reason is blank, spans more than one line, or contains ` -> `.
- The new machine file fails the full `validate` rules.

Only when the new machine is valid does it also refuse these:

- The current node is missing from the new machine.
- The new machine is identical to the machine in force.
- The new machine changes the current node's `leave` or `leave_check`.
- No `next:` path leads from the current node to `succeeded`.

On success, it makes one atomic write:

- It appends `- v<N> <ts> at <node> (<reason>)` to `## machines`, followed by the machine as YAML indented two spaces.
- It appends a decision: `[solo] AMENDMENT state_machine: v<N-1> -> v<N> (added: ...; removed: ...; ...), <reason>`.

The machine in force is the newest `## machines` entry. When there is none, it is the settlement machine. `record-decision` refuses a hand-written `AMENDMENT state_machine`. `task state show` prints the machine in force and its version, and it is the starting point for the next edit.

## How reminders reach the model

- **On entry**: `transition` and `amend` print the node's `do`, `branches`, `leave` and `leave_check`. In JSON mode, `do` is returned as `next`.
- **On demand**: `task state current` prints the current node and its full reminder from disk.
  - A node with no reminder prints `no reminder: work toward /goal`.
  - A terminal node prints `terminal: close the ledger` and the close command.
  - The `recall` skill runs `current` at the start of every `execute` iteration and after a compaction, so a node's `do` is not lost when the context is compacted.
- **Hooks** in `plugins/engine/hooks/`:
  - `SessionStart` with matcher `compact` tells the model to run `recall`, and adds the merged principles. It adds the settlement `goal` only when `goal` is plain text.
  - `Stop` tells the model to run `recall` before it ends a turn during an open run.
  - `PostToolUse` sends a nudge when `## state` has recorded no transition for 5 minutes. If the state still has not changed 15 minutes after that nudge, it sends one escalated nudge, then stays silent for that state. It measures time from the last log line or from `started:`, never from file timestamps, because every ledger write changes those.
  - Each hook finds the ledger by the host `session_id` under `~/.bootgear/session/`.
