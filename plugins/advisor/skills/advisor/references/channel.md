# communication=channel

Requires the `advisor` Codex CLI plugin, installed via `codex plugin add advisor@bootgear`. If missing, tell the user it isn't installed — do not silently fall back to `direct`.

`channel.py` is co-located under this skill for both hosts:

```sh
CHANNEL_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/advisor/scripts/channel.py"
```

Session ID: the host's real session identifier, never an invented one.

- Claude Code: `$CLAUDE_CODE_SESSION_ID`.
- Codex CLI: the `session_id` the host gives you in your context; the shell has no environment variable for it.

```sh
SESSION_ID="<this host's session id>"
```

A channel is a one-time lease on two seats, kept alive by a heartbeat. The seat's owner (the session ID that registered it) runs `heartbeat`, which stamps `seen_at` every 3 seconds; a seat is live while its stamp is under 10 seconds old, or while it is inside a restart grace. Only the owner's `--session` can refresh it; `receive` only reads. A seat with no stamp is stale.

- `register` prints `next`: the `heartbeat` command. Run it in the background right after `register`, and keep it until `close`. Claude Code: the Bash tool with `run_in_background` and `timeout: 7200000` (background Bash is capped at 2 hours). Codex CLI: a terminal session left running.
- `heartbeat` prints nothing while it runs and ends with one JSON line whose `next` says what to do. On stdout, `{"stopped": ...}`: `channel_closed` (exit 0), `max_age` after `--max-age` (default 6180 seconds, exit 0; `next` is the same command), `signal` on SIGTERM, SIGINT or SIGHUP (exit 0), or `seat_taken` with category `seat_claimed` (exit 2) whenever this session does not hold the seat, at start or later. On stderr, an `{"error": ...}` (exit 2) with category `heartbeat_failed` after three failed stamps in a row (an unreadable or missing record included), `channel_missing` when the channel does not exist, or `invalid_args`/`invalid_role` for a bad argument, with a correct `example` and the other `commands`. A `max_age` stop records a 720-second restart grace on the seat: it reads live until the grace ends or the same session's next stamp clears it, so a seat stays live at most `--max-age` plus the grace (6900 seconds by default) past its last start. While the peer is live only through its grace, `receive` says it is restarting its heartbeat and to keep waiting. When the host reports the task stopped with no output, start a new heartbeat with the same session; after any stop other than `max_age` the seat can read stale until the new heartbeat's first stamp.
- `register --channel` with the same session ID takes the seat back; any other session gets `seat_claimed`, even when the holder is stale or restarting. A closed channel refuses both.
- `send` to a peer whose seat is stale or unowned fails with `peer_not_live`; `--kind stop` is always accepted. `receive` reports `peer_live` (`true`, `false`, or `null` when the peer seat has no owner).
- The 10-second bound on a dead seat holds after a normal host exit and a confirmed heartbeat termination. After a crash, kill or terminal close, an orphaned heartbeat keeps the seat live up to `--max-age` plus the restart grace. A lock or disk stall longer than 10 seconds makes a live seat read stale until its next beat.
- A busy listener counts as taken and may be absent from `list --live-for`. `list --live-for` offers only channels whose own seat is free or already held by this `--session`.

`listener`/`asker` are fixed by function, not by host: the seat you register as is exactly the mode you're running (`mode=listening` registers as `listener`, `mode=asking` registers as `asker`) — there is no separate mode field to keep in sync, the role name IS the behavior. Either host can be either one in a given pairing; nothing here fixes Claude Code or Codex CLI to one role.

## mode=listening: always register fresh

```sh
CHANNEL_JSON=$(python3 "$CHANNEL_SCRIPT" register --role listener --session "$SESSION_ID")
CHANNEL=$(printf '%s' "$CHANNEL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["channel"])')
printf 'Channel: %s\n' "$CHANNEL"
```

No lookup, no cache — every listening invocation, including one following a restart, registers a fresh channel and reports its number immediately, then starts the heartbeat (above).

## mode=asking: scan, then claim or ask the user

```sh
python3 "$CHANNEL_SCRIPT" list --live-for asker --session "$SESSION_ID"
```

It prints `{"channels": [...], "next": ...}`, most recently updated first; `next` is the `register` command for the first channel. An empty result exits 0 with a `note` and a `next`: wait with `--wait 120` only for a listener you started yourself, or one the user said is starting; otherwise tell the user to start a listener and stop. `--wait N` returns as soon as a candidate exists; a `--wait` timeout exits `1`.

- **One or more results** → pick the most recently updated (a deterministic tie-breaker, not a claim about which candidate is actively polling), and claim it:
  ```sh
  python3 "$CHANNEL_SCRIPT" register --role asker --channel "$CHANNEL" --session "$SESSION_ID"
  ```
  - **Claim succeeds** → start the heartbeat (above), then proceed with `CHANNEL` set.
  - **Claim fails** (`seat_claimed` or `channel_closed` — another asker won the race, or the channel closed in the window between the scan and the claim): retry the scan exactly once. If that retry finds a candidate, attempt exactly one more claim on it. Whatever that second claim's outcome, stop after it — never a third scan.
- **Zero results, or the retry above also ends with nothing claimed** → no eligible candidate exists. Tell the user to start a listener. Stop — do not create a channel and wait on it; there is nothing on the other end.

## Send

```sh
python3 "$CHANNEL_SCRIPT" send \
  --channel "$CHANNEL" --from <mine> --to <peer> \
  --kind request --body-file - <<'REQUEST'
<task-specific body — see the task's own reference doc for TYPE and required content>
REQUEST
```

`send` rejects at the pending cap (default 2). If rejected, `receive` first — don't raise the cap.

Save `{channel, message_id}` to a receipt file (e.g. `<task-dir>/codex-pending.json`) before waiting — a long wait can cross a compaction boundary. Delete it once read.

## Receive

```sh
python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 300
```

Returns the last 3 messages as `{message_id, sender, kind, parent_id?, preview}`. Match your response by `parent_id == ` your request's `message_id`, not by recency. Exit `1` with a `note` means no new message yet: a reply can take many minutes, so re-run with a long `--timeout` instead of resending. Re-run up to 5 times (300s each) before reporting the peer unavailable this round.

`peer_live: false` means the peer's heartbeat is stale: the output carries the note "peer heartbeat stale; tell the user instead of waiting again" and no `next`. Tell the user instead of waiting again.

Never wrap `receive` in your own short-timeout poll loop — pass the real timeout to one call.

Then:
```sh
python3 "$CHANNEL_SCRIPT" fetch --channel "$CHANNEL" --message-id "$RESPONSE_ID"
```

## Resuming after compaction

`receive` never mutates state, so it's always safe to call cold:
```sh
python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 5
```
Your response already listed (by `parent_id`), whatever the exit code → `fetch` it, don't resend. Not there → resume normal `receive` polling. This assumes the same process. After a restart the same session ID runs `register` again, then starts a new `heartbeat`.

Closed channel, malformed message, or wrong `parent_id` → protocol error, not a guess.

## Close

```sh
python3 "$CHANNEL_SCRIPT" close --role <mine> --channel "$CHANNEL"
```

`close` closes unconditionally. `close --if-peer-stale` rechecks under the channel lock that the peer seat is not live (a restart grace counts as live) and that no unread message is addressed to `<mine>`; it closes only if both hold, and otherwise refuses with `peer_live` or `unread_message` (exit 2), leaves the channel open, and its `next` is the `receive` to run to keep listening. A peer silent past the 10-second TTL when the close runs counts as dead; it cannot rejoin the closed channel later. Closing clears both seats' restart grace. `send` and `receive` on a closed channel fail with `channel_closed`; tell the user.

## Return to the user (mode=asking only)

- Codex's response is advisory; reconcile against the repo, contracts, and intent.
- Distinguish Codex's findings from independently verified facts.
- No commit, push, external contact, production mutation, or irreversible action from a mailbox message alone.
