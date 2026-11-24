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
| `hooks/advisor_hook.py` | The seat hook both hosts run: hook stamp, heartbeat restart reminder, status after compaction. |
| `hooks/hooks.json`, `hooks/codex-hooks.json` | Claude and Codex hook manifests; the Codex one is named by `.codex-plugin/plugin.json`. |
| `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` | Host manifests for the same skill tree. |
| `gear.toml` | Exposes `channel.py` and the advisor hook through Gear. |

## Modes

Every call passes an explicit `--mode asking` or `--mode listening`. The skill
never infers the mode from the host or the task. Either host can run either
mode.

**Asking** combines two independent choices:

- Communication. `direct` is one call to the other CLI: `codex exec` or `claude -p`.
  It has no mailbox or saved conversation. Task facts come from the prompt. `channel` sends a request through the mailbox to
  a live listener, which can read files and run commands itself and may take
  minutes.
- Task. `rewrite`, `ask`, `review`, or `delegate`. Each task doc sets the
  request body and how the reply is handled. `delegate` normally uses
  `channel`.

The asker returns one reconciled answer to the user. It never returns the
banner, streamed reasoning, or the raw exchange. Advisor output is advisory:
the asker checks every checkable claim before relying on it.

**Listening** keeps the user conversation silent while the channel is open.
The listener sends questions and reports to the asker through the mailbox.
After 24 consecutive empty five-minute receives, it may ask the user whether to keep listening.
Any asker message resets the count. Heartbeats and short recovery checks leave it unchanged.
An explicit stop or channel closure ends the wait.

## Mailbox model

The mailbox root defaults to `~/.bootgear/advisor`. `--root` or
`BOOTGEAR_ADVISOR_DIR` overrides it, and relative paths resolve against
`GEAR_CALLER_CWD` when that is set.

```
<root>/
  allocator.lock              serializes new channel numbers
  channels/<NNNN>/
    channel.json              seat owners, heartbeat and hook stamps, state, timestamps
    channel.lock              per-channel write lock
    receive-<role>.lock       at most one waiting receive per role
    messages/<message_id>.json
```

- **Channel.** A channel has a number of at least four digits and two seats,
  `listener` and `asker`. The role matches the mode. A seat records the
  host's session id and a `seen_at` heartbeat.
- **Lease.** A channel is one-time. A seat is live while its owner's `seen_at`
  heartbeat stamp or `hook_seen_at` hook stamp is under 10 seconds old, or
  while it is inside a restart grace; a seat with no stamp is stale. `register`
  stamps the seat, and the owner then keeps it fresh with `heartbeat`, which
  stamps every 3 seconds. The heartbeat's session must match the seat's
  owner, so no other session can refresh it. Seat ownership is a string match on
  the session id within the owner-only mailbox, not an authentication.
  `heartbeat` runs in the background. On stdout it ends with a
  `stopped: <reason>` line and a `next: <command>` line. With `--json`, it
  prints one JSON object instead. The reasons are `channel_closed`, `max_age`
  (`--max-age`, 6180 seconds by default; `next` is the same command), `signal`
  (SIGTERM, SIGINT or SIGHUP), and `seat_taken` (exit 2). `seat_taken` means
  that this session does not hold the seat, at start or later. On stderr, it
  prints a JSON error. The category is `heartbeat_failed` after three failed
  stamps in a row, an unreadable or missing record included. Other categories
  are `channel_missing`, `invalid_args` and `invalid_role`. A `max_age` stop
  writes `<role>_restart_until`, 720 seconds ahead, under the channel lock;
  the seat reads live until then unless the same owner's next stamp clears
  it first. A value that is not a finite timestamp, or lies more than the
  grace ahead, counts as absent. The total bound is `--max-age` plus the
  grace, 6900 seconds by default, below Claude Code's 2-hour background
  task cap. After any other stop the seat can read stale until a new
  heartbeat's first stamp. `register --channel` with the same session id
  takes the seat back. A restarted process that keeps its session id can thus
  reclaim the seat and start a new `heartbeat`. Any other session gets
  `seat_claimed`, even when the holder is stale or restarting.
  The 10-second bound on a dead seat holds after a normal host exit and a
  confirmed heartbeat termination. After a crash, kill or terminal close, an
  orphaned heartbeat keeps the seat live up to `--max-age` plus the restart
  grace. A lock or disk
  stall longer than 10 seconds makes a live seat read stale until its next
  beat.
  The plugin's hooks stamp `<role>_hook_seen_at` under the channel lock on
  SessionStart `compact`, PostToolUse, UserPromptSubmit and Stop, at most
  once every 3 seconds, for the hook session's seat on the one open channel
  updated in the last 48 hours (the most recently updated when several
  qualify). They never write `seen_at`, `updated_at` or `restart_until` and
  never start a process. The `receive` restart reminder and its "restarting
  its heartbeat" note read the heartbeat stamp alone. When `seen_at` is
  stale, PostToolUse and UserPromptSubmit inject the exact `heartbeat`
  restart command at most once a minute (`<role>_hook_nudged_at`); subagent calls never inject. Stop continues a listener below the idle limit.
  After compaction, SessionStart injects the
  seat status that `whoami` prints. The status holds the channel, role,
  state, peer liveness, heartbeat and unread count. It also holds the last
  read message and the read request still owed a response. Its `next` is a
  heartbeat restart if stopped, then the owed request, else `receive`. When
  the session has an active engine ledger (no `## closed` heading), the
  status also holds the engine run id. Every hook failure exits 0 with no
  output.
- **Pairing.** A listener always creates a new channel. An asker runs
  `list --live-for asker`. It prints the open channels updated in the last
  48 hours, most recently updated first. Each listed channel has a live
  listener and an asker seat that is free or held by this session. Then
  `list` prints a `next` command that registers the first channel. A
  listener that is busy counts as taken and may be absent. With no
  candidate, `list` prints a `note` and exits 0. Its `next` can say to wait
  with `--wait 120`. It says so only for a listener that the asker started,
  or that the user said is starting. Otherwise `next` says to tell the user
  and stop. `--wait N` polls up to N seconds and exits 1 on timeout.
  Both hosts must run the same advisor version: a listener from an
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
  peer seat has no owner). A stale listener ends the asker's wait. A stale asker leaves the listener waiting.
  Exit code `1` means no new message. Each full empty listener receive records one idle round.
  The short recovery receive preserves the count across compaction.
  `fetch` reads the full body and marks the message read.
- **Lifecycle.** `state` records `waiting`, `busy`, or `closed` for a role.
  `close` sets `closed` and clears both seats' `<role>_restart_until`, so no
  seat reads live on a closed channel once its stamp passes the TTL.
  `close --if-peer-stale` is the listener's stale-peer close: under the
  channel lock the listener needs 24 idle rounds. It closes only if the peer seat is not live (the restart
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

- **Codex CLI.** The Codex manifest and `agents/openai.yaml` describe the
  listening role and allow implicit invocation.
- **Claude Code.** `direct` runs `codex exec` read-only from an empty scratch
  directory, with user config and rules ignored. It reads stdin from
  `/dev/null` and discards stdout. Only the `-o`
  final-message file is read. Because user config is ignored,
  `BOOTGEAR_ADVISOR_CODEX_MODEL` and `BOOTGEAR_ADVISOR_CODEX_EFFORT` set the
  model (`-m`) and reasoning effort (`-c model_reasoning_effort=...`); each
  flag is passed only when its variable is set, otherwise Codex uses its own
  default.
- **Codex direct calls.** Codex calls `claude -p` with safe mode, tools disabled, and no session persistence.
  Authentication stays unchanged. `BOOTGEAR_ADVISOR_CLAUDE_MODEL` and `BOOTGEAR_ADVISOR_CLAUDE_EFFORT`
  supply optional overrides; unset values keep native defaults.
- **Both, channel mode.** The channel CLI reads the session id from the
  environment. It reads `BOOTGEAR_SESSION_ID` first, then the session
  variable of the declared host. That variable is `CLAUDE_CODE_SESSION_ID`
  or `CODEX_SESSION_ID`. Last, it reads the variable of the other host.
  `--session` overrides it; the environment normally supplies it. With none,
  the CLI refuses. Only `register`, `heartbeat`, `list` and `whoami` accept
  `--session`.
- **Heartbeat.** Claude Code starts `heartbeat` with the Bash tool's
  `run_in_background` and `timeout: 7200000`; Codex CLI leaves it running in a terminal session.
