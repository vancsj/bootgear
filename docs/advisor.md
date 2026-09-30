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
interrupts, or the channel closes; when the asker's seat reads dead it
runs `close --if-peer-stale`, which closes the channel and ends its own
heartbeat unless the asker is live again or a request is waiting, in which
case it keeps listening. It never starts a conversation, never
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
    channel.json              seat owners, heartbeat stamps, state, timestamps
    channel.lock              per-channel write lock
    receive-<role>.lock       at most one waiting receive per role
    messages/<message_id>.json
```

- **Channel.** A channel has a number of at least four digits and two seats,
  `listener` and `asker`. The role matches the mode. A seat records the
  host's session ID and a `seen_at` heartbeat.
- **Lease.** A channel is one-time. A seat is live while its owner's `seen_at`
  stamp is under 10 seconds old, or while it is inside a restart grace; a
  seat with no stamp is stale. `register`
  stamps the seat, and the owner then keeps it fresh with `heartbeat`, which
  stamps every 3 seconds. `heartbeat --session` must match the seat's owner,
  so no other session can refresh it. Seat ownership is a string match on
  the session ID within the owner-only mailbox, not an authentication.
  `heartbeat` runs in the background and ends with one JSON line whose
  `next` names the follow-up: on stdout `{"stopped": ...}` with
  `channel_closed`, `max_age` (`--max-age`, 6180 seconds by default; `next`
  is the same command), `signal` (SIGTERM, SIGINT or SIGHUP), or
  `seat_taken` (exit 2) when this session does not hold the seat, at start
  or later; on stderr an error with category `heartbeat_failed` after three
  failed stamps in a row (an unreadable or missing record included),
  `channel_missing`, `invalid_args` or `invalid_role`. A `max_age` stop
  writes `<role>_restart_until`, 720 seconds ahead, under the channel lock;
  the seat reads live until then unless the same owner's next stamp clears
  it first. A value that is not a finite timestamp, or lies more than the
  grace ahead, counts as absent. The total bound is `--max-age` plus the
  grace, 6900 seconds by default, below Claude Code's 2-hour background
  task cap. After any other stop the seat can read stale until a new
  heartbeat's first stamp. `register --channel` with the same
  session ID takes the seat back, so a restarted process that keeps its
  session ID can reclaim it and start a new `heartbeat`; any other session
  gets `seat_claimed`, even when the holder is stale or restarting.
  The 10-second bound on a dead seat holds after a normal host exit and a
  confirmed heartbeat termination. After a crash, kill or terminal close, an
  orphaned heartbeat keeps the seat live up to `--max-age` plus the restart
  grace. A lock or disk
  stall longer than 10 seconds makes a live seat read stale until its next
  beat.
- **Pairing.** A listener always creates a new channel. An asker runs
  `list --live-for asker --session S`, which prints the open channels updated
  in the last 48 hours whose listener is live and whose asker seat is free
  or held by S, most recently updated first, and a `next` command that
  registers the first. A listener that is busy counts as taken and may be
  absent. With no candidate, `list` prints a `note` and exits 0, and its
  `next` says to wait with `--wait 120` only for a listener the asker
  started itself or the user said is starting, and otherwise to tell the
  user and stop; `--wait N` polls up to N seconds and exits 1 on timeout.
  Both hosts must run the same advisor version (1.2.0): a listener from an
  older version stamps its seat on a different cadence, so its liveness
  reads wrong. The asker claims the most recently updated channel. If another
  session already holds the seat (`seat_claimed`) or the channel has closed
  (`channel_closed`), it rescans once and claims once more, then stops. With
  no candidate it tells the user to start a listener.
- **Messages.** A message has a kind (`request`, `response`, or `stop`), a
  sender, a recipient, and a body. A response carries the `parent_id` of its
  request, and replies are matched by `parent_id`, not by arrival order.
  `send` refuses when the recipient already has the pending cap (2) of unread
  non-stop messages, and with `peer_not_live` when the recipient's seat is
  unowned or stale; a `stop` message is always accepted.
- **Reading.** `receive` blocks until an unread message arrives or the
  timeout passes. It returns the last three messages as previews and prints a
  runnable `next` command and `peer_live` (`true`, `false`, or `null` when the
  peer seat has no owner). When `peer_live` is false, `next` is omitted and a
  note tells the caller to report to the user; while the peer is live only
  through its restart grace, the note says it is restarting its heartbeat
  and to keep waiting. Exit code `1` means no new
  message; the caller waits again unless `peer_live` is false. `receive` never changes
  state, so it is safe after compaction.
  `fetch` returns the full body and marks the message read.
- **Lifecycle.** `state` records `waiting`, `busy`, or `closed` for a role.
  `close` sets `closed` and clears both seats' `<role>_restart_until`, so no
  seat reads live on a closed channel once its stamp passes the TTL.
  `close --if-peer-stale` is the listener's stale-peer close: under the
  channel lock it closes only if the peer seat is not live (the restart
  grace counts as live) and no unread message is addressed to the closing
  role, and otherwise refuses with `peer_live` or `unread_message`, leaving
  the channel open, with a `next` that runs `receive` again. A request sent
  between the listener's stale `receive` and its close therefore keeps the
  channel open. A peer silent past the TTL when the close runs counts as
  dead, and a restart later than that cannot rejoin the closed channel. A
  closed channel refuses registration, `send`, and `receive`, the last two
  with `channel_closed` and a `next`.

Every write takes the channel lock and is atomic (temporary file, then
rename). Every subcommand refuses a bad argument, a parse error or unknown flag
included, as one JSON line with `invalid_args` or `invalid_role`, one
correct `example` invocation of the subcommand in argv (with an absolute
`--root` whenever the root is not the default, an abbreviated `--root`
included), the other `commands`, and a `next`. A bad role, `--kind`,
`--value`, `--message-id` or empty body is refused before anything is
written; a `--channel` that is not at
least four digits and a `--session` that is empty or starts with `-` are
refused, as are non-finite `--wait`, `--interval` and `--max-age`.
`heartbeat` prints non-default `--interval` and `--max-age` in its `next`
so that they parse back to the same values. Malformed messages, the wrong recipient, an unmatched `parent_id`, or
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
- **Both.** `SESSION_ID` must be the host's real session identifier. If it is not
  available, the skill fails instead of making one up. Claude Code passes
  `$CLAUDE_CODE_SESSION_ID`; Codex CLI passes the `session_id` the host
  gives the agent in its context (no shell environment variable carries it).
- **Heartbeat.** Claude Code starts `heartbeat` with the Bash tool's
  `run_in_background` and `timeout: 7200000`; Codex CLI leaves it running in a terminal session.
