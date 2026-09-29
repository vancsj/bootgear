# Advisor

The `advisor` plugin connects a Claude Code session to a Codex CLI session,
so one host can ask the other for a rewrite, an opinion, an adversarial
review, or delegated investigation. One plugin directory ships to both hosts.

## Components

| Component | Role |
|---|---|
| `skills/advisor/SKILL.md` | The skill contract: mode selection, the listener loop, safety rules. |
| `skills/advisor/references/` | One doc per communication (`direct`, `channel`) and per task (`rewrite`, `ask`, `review`, `delegate`). |
| `skills/advisor/scripts/channel.py` | The mailbox CLI. Both hosts use this one copy. |
| `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` | Host manifests for the same skill tree. |
| `gear.toml` | Exposes `channel.py` as the `channel` gear command. |

## Modes

Every call passes an explicit `--mode asking` or `--mode listening`. The skill
never infers the mode from the host or the task. Either host can run either
mode.

**Asking** combines two independent choices:

- Communication. `direct` is one `codex exec` call. It has no state, and
  Codex sees only the prompt. `channel` sends a request through the mailbox to
  a live listener, which can read files and run commands itself and may take
  minutes.
- Task. `rewrite`, `ask`, `review`, or `delegate`. Each task doc sets the
  request body and how the reply is handled. `delegate` normally uses
  `channel`.

The asker returns one reconciled answer to the user. It never returns the
banner, streamed reasoning, or the raw exchange. Advisor output is advisory:
the asker checks every checkable claim before relying on it.

**Listening** is a read-only advisor loop. The listener registers a fresh
channel and reports its number. It then waits on the mailbox, answers one
request at a time, and keeps listening until it receives a `stop`, the user
interrupts, or the channel closes. It never starts a conversation, never
answers the human directly for a mailbox request, and takes no irreversible
action unless the request's scope authorizes it.

## Mailbox model

The mailbox root defaults to `~/.bootgear/advisor`. `--root` or
`BOOTGEAR_ADVISOR_DIR` overrides it, and relative paths resolve against
`GEAR_CALLER_CWD` when that is set.

```
<root>/
  allocator.lock              serializes new channel numbers
  channels/<NNNN>/
    channel.json              seat owners, PIDs, PID start times, state, timestamps
    channel.lock              per-channel write lock
    receive-<role>.lock       at most one waiting receive per role
    messages/<message_id>.json
```

- **Channel.** A channel has a number of at least four digits and two seats,
  `listener` and `asker`. The role matches the mode. A seat records the
  host's session ID, the long-lived host PID, and that PID's exact start time
  as `whoami` reports it.
- **Lease.** A channel is valid only while the processes in its seats are
  alive. Liveness compares the recorded start time with the start time the
  OS reports for the PID and requires an exact match, which catches reused
  PIDs. A process restart fails that check. `register --channel` with the
  same session ID overwrites the seat's PID and start time, so a restarted
  process that keeps its session ID can take the seat back; any other
  session gets `seat_claimed`, even when the holder is dead. Compaction keeps
  the same process, so it keeps the seat.
- **Pairing.** A listener always creates a new channel. An asker runs
  `list --live-for asker`, which returns open channels updated in the last
  48 hours whose listener is not confirmed dead. The asker claims the most
  recently updated one. If another session already holds the seat
  (`seat_claimed`) or the channel has closed (`channel_closed`), it rescans
  once and claims once more, then stops. With no candidate it tells the user
  to start a listener.
- **Messages.** A message has a kind (`request`, `response`, or `stop`), a
  sender, a recipient, and a body. A response carries the `parent_id` of its
  request, and replies are matched by `parent_id`, not by arrival order.
  `send` refuses when the recipient already has the pending cap (2) of unread
  non-stop messages.
- **Reading.** `receive` blocks until an unread message arrives or the
  timeout passes. It returns the last three messages as previews and prints a
  runnable `next` command. Exit code `1` means no new message; the caller
  waits again. `receive` never changes state, so it is safe after compaction.
  `fetch` returns the full body and marks the message read.
- **Lifecycle.** `state` records `waiting`, `busy`, or `closed` for a role.
  `close` sets `closed`. A closed channel refuses registration, `send`, and
  `receive`.

Every write takes the channel lock and is atomic (temporary file, then
rename). Malformed messages, the wrong recipient, an unmatched `parent_id`, or
a closed channel are protocol errors. They are never guessed around.

## Permissions

The mailbox is owner-only. `channel.py` creates or re-chmods the root,
`channels/`, and each channel and `messages/` directory to `0700`, and every
record, message, and lock file to `0600`, on every call.

## Host differences

- **Codex CLI.** The mailbox root is outside the sandbox's writable roots, so
  every `channel.py` call runs with escalated sandbox permissions. The Codex
  manifest and `agents/openai.yaml` describe the listening role and allow
  implicit invocation.
- **Claude Code.** `direct` runs `codex exec` read-only from an empty scratch
  directory, with user config and rules ignored. It runs outside the Bash
  sandbox, reads stdin from `/dev/null`, and discards stdout. Only the `-o`
  final-message file is read. Because user config is ignored,
  `BOOTGEAR_ADVISOR_CODEX_MODEL` and `BOOTGEAR_ADVISOR_CODEX_EFFORT` set the
  model (`-m`) and reasoning effort (`-c model_reasoning_effort=...`); each
  flag is passed only when its variable is set, otherwise Codex uses its own
  default.
- **Both.** `SESSION_ID` must be the host's real session identifier, and
  `PID` must be the host's long-lived top-level process. If either is not
  available, the skill fails instead of making one up. Liveness reads the
  start time through macOS `proc_pidinfo`.
