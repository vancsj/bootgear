# communication=channel

Requires the `advisor` Codex CLI plugin, installed via `codex plugin add advisor@bootgear`. If missing, tell the user it isn't installed — do not silently fall back to `direct`.

`CHANNEL_SCRIPT` is `scripts/channel.py` in this skill's directory:

- Claude Code: `CHANNEL_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/advisor/scripts/channel.py"`.
- Codex CLI: `CHANNEL_SCRIPT="<directory holding SKILL.md>/scripts/channel.py"`, as an absolute path.

Session ID: the host's real session identifier, never an invented one.

- Claude Code: `$CLAUDE_CODE_SESSION_ID`.
- Codex CLI: the `session_id` the host gives you in your context; the shell has no environment variable for it.

```sh
SESSION_ID="<this host's session id>"
```

A channel is a one-time lease on two seats, kept alive by a heartbeat. The seat's owner (the session ID that registered it) runs `heartbeat`, which stamps `seen_at` every 3 seconds; a seat is live while its stamp is under 10 seconds old, or while it is inside a restart grace. Only the owner's `--session` can refresh it; `receive` only reads. A seat with no stamp is stale.

- `register` prints `next`: the `heartbeat` command. Run it in the background right after `register`, and keep it until `close`. Claude Code: the Bash tool with `run_in_background` and `timeout: 7200000` (background Bash is capped at 2 hours). Codex CLI: a terminal session left running.
- `heartbeat` prints nothing while it runs and ends with a `stopped:` line and a `next:` line saying what to do. A `max_age` stop records a 720-second restart grace on the seat: it reads live until the grace ends or the same session's next stamp clears it, so a seat stays live at most `--max-age` (default 6180 seconds) plus the 720-second grace (6900 seconds by default) past its last start. While the peer is live only through its grace, `receive` says it is restarting its heartbeat and to keep waiting. When the host reports the task stopped with no output, start a new heartbeat with the same session; after any stop other than `max_age` the seat can read stale until the new heartbeat's first stamp.
- `register --channel` with the same session ID takes the seat back; any other session gets `seat_claimed`, even when the holder is stale or restarting. A closed channel refuses both.
- `send` to a peer whose seat is stale or unowned fails with `peer_not_live`; `--kind stop` is always accepted. `receive` reports `peer_live` (`true`, `false`, or `null` when the peer seat has no owner).
- A busy listener counts as taken and may be absent from `list --live-for`. `list --live-for` offers only channels whose own seat is free or already held by this `--session`.

`listener`/`asker` are fixed by function, not by host: the seat you register as is exactly the mode you're running (`mode=listening` registers as `listener`, `mode=asking` registers as `asker`).

## mode=listening: always register fresh

Output is prose; add `--json` (or set `BOOTGEAR_OUTPUT=json`) when a script parses it.

```sh
CHANNEL_JSON=$(python3 "$CHANNEL_SCRIPT" register --role listener --session "$SESSION_ID" --json)
CHANNEL=$(printf '%s' "$CHANNEL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["channel"])')
printf 'Channel: %s\n' "$CHANNEL"
```

No lookup, no cache — every listening invocation, including one following a restart, registers a fresh channel and reports its number immediately, then starts the heartbeat (above).

## mode=asking: scan, then claim or ask the user

```sh
python3 "$CHANNEL_SCRIPT" list --live-for asker --session "$SESSION_ID"
```

It prints the channels, most recently updated first, then `next:`; `next` is the `register` command for the first channel. An empty result exits 0 with a `note` and a `next`; do what `next` says. `--wait N` returns as soon as a candidate exists; a `--wait` timeout exits `1`.

- **One or more results** → pick the most recently updated, and claim it:
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

`--parent-id` must be the 32-character `message_id` of a request the peer sent you on this channel. Otherwise `send` refuses with `invalid_args` (bad format) or `unknown_parent_id` (no such request) and writes nothing.

Save `{channel, message_id}` to a receipt file (e.g. `<task-dir>/codex-pending.json`) before waiting — a long wait can cross a compaction boundary. Delete it once read.

## Receive

```sh
python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 300
```

Returns the last 3 messages as `{message_id, sender, kind, parent_id?, preview}`, plus `answered` on each request addressed to you: true once you have sent a response naming it as `parent_id`. Match your response by `parent_id == ` your request's `message_id`, not by recency. Exit `1` with a `note` means no new message yet: a reply can take many minutes, so re-run with a long `--timeout` instead of resending. Re-run up to 12 times (300s each) before reporting the peer unavailable this round. If the listener's `state` is `busy`, keep re-running: busy waits do not count toward the 12, up to 12 of them.

`next` can have two lines, run in order. When a line says "your heartbeat is not running", start that heartbeat in a new background session and keep it running.

`peer_live: false` means the peer's heartbeat is stale: the output carries the note "peer heartbeat stale; tell the user instead of waiting again" and no `next`. Tell the user instead of waiting again.

Never wrap `receive` in your own short-timeout poll loop — pass the real timeout to one call.

Claude Code: run the listener loop in `SKILL.md` step 5, which fetches on exit 0. Codex CLI: make one `receive` call per poll, with no loop. On exit 0, fetch and answer the message, then `receive` again. On exit 1, `receive` again. Never call `receive` again while a message is unread.

Then:
```sh
python3 "$CHANNEL_SCRIPT" fetch --channel "$CHANNEL" --message-id "$RESPONSE_ID"
```

## Resuming after compaction

`receive` never mutates state, so it's always safe to call cold:
```sh
python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 5
```
Your response already listed (by `parent_id`), whatever the exit code → `fetch` it, don't resend. Nothing unread and no response listed → resume normal `receive` polling. This assumes the same process. After a restart the same session ID runs `register` again, then starts a new `heartbeat`.

Your outstanding requests are the `message_id`s in your receipt file. An unread reply whose `parent_id` matches one of them is a real reply: `fetch` it and keep waiting for the rest. An unread reply whose `parent_id` matches none of them → protocol error: `fetch` it (that marks it read, so `receive` stops returning at once), tell the user, and stop waiting. Do not keep polling.

Closed channel or malformed message → protocol error, not a guess.

## Close

```sh
python3 "$CHANNEL_SCRIPT" close --role <mine> --channel "$CHANNEL"
```

`close` closes unconditionally. `close --if-peer-stale` rechecks under the channel lock that the peer seat is not live (a restart grace counts as live) and that no unread message is addressed to `<mine>`; it closes only if both hold, and otherwise refuses with `peer_live` or `unread_message` (exit 2), leaves the channel open, and its `next` is the `receive` to run to keep listening. A peer silent past the 10-second TTL when the close runs counts as dead; it cannot rejoin the closed channel later. Closing clears both seats' restart grace. `send` and `receive` on a closed channel fail with `channel_closed`; tell the user.

## Return to the user (mode=asking only)

- Codex's response is advisory; reconcile against the repo, contracts, and intent.
- Distinguish Codex's findings from independently verified facts.
- No commit, push, external contact, production mutation, or irreversible action from a mailbox message alone.
