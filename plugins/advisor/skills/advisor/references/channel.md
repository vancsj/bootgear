# communication=channel

Requires the `advisor` Codex CLI plugin, installed via `codex plugin add advisor@bootgear`. If missing, tell the user it isn't installed — do not silently fall back to `direct`.

`channel.py` is co-located under this skill for both hosts:

```sh
CHANNEL_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/advisor/scripts/channel.py"
```

Read your own PID once at session start — the long-lived host process (Claude Code's or Codex CLI's own top-level process), not a subprocess's PID, and not `$$` (see below for why). Read your own real session identity from your host's own hook-provided value, not a shell-discoverable variable or a placeholder you fill in by hand. Then get that PID's exact start time from `channel.py` itself, not from `ps -o lstart` or any other shell command — `ps`'s whole-second resolution cannot satisfy the exact-match comparison `is_alive` uses (a genuinely still-running process would falsely read as dead the moment its actual start time has nonzero microseconds, which is nearly always):

```sh
SESSION_ID="<this host's real session id, from its own hook mechanism>"
PID="<this host's own long-lived process PID>"
PID_STARTED_AT=$(python3 "$CHANNEL_SCRIPT" whoami --pid "$PID" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pid_started_at"])')
```

A channel is a one-off lease on a live process pair, not a durable record — it is valid only while the process that registered a given seat is still alive. A process restart fails the liveness check for that seat. `register --channel` with the same session ID overwrites the seat's PID and start time, so a restarted process that keeps its session ID can take the seat back; any other session gets `seat_claimed`, even when the holder is dead. A closed channel refuses both. Compaction is not a restart (same process, same PID) and does not affect a seat's lease.

`listener`/`asker` are fixed by function, not by host: the seat you register as is exactly the mode you're running (`mode=listening` registers as `listener`, `mode=asking` registers as `asker`) — there is no separate mode field to keep in sync, the role name IS the behavior. Either host can be either one in a given pairing; nothing here fixes Claude Code or Codex CLI to one role.

## mode=listening: always register fresh

```sh
CHANNEL_JSON=$(python3 "$CHANNEL_SCRIPT" register --role listener --session "$SESSION_ID" --pid "$PID" --pid-started-at "$PID_STARTED_AT")
CHANNEL=$(printf '%s' "$CHANNEL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["channel"])')
printf 'Channel: %s\n' "$CHANNEL"
```

No lookup, no cache, no ownership check — every listening invocation, including one following a restart, registers a fresh channel and reports its number immediately, before anything else. There is nothing of a prior lease to come back to.

## mode=asking: scan, then claim or ask the user

```sh
python3 "$CHANNEL_SCRIPT" list --live-for asker
```

- **One or more results** → pick the most recently updated (a deterministic tie-breaker, not a claim about which candidate is actively polling), and claim it:
  ```sh
  python3 "$CHANNEL_SCRIPT" register --role asker --channel "$CHANNEL" --session "$SESSION_ID" --pid "$PID" --pid-started-at "$PID_STARTED_AT"
  ```
  - **Claim succeeds** → proceed with `CHANNEL` set.
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
Your response already listed (by `parent_id`), whatever the exit code → `fetch` it, don't resend. Not there → resume normal `receive` polling. This assumes the same process. After a restart the seat's lease has lapsed until the same session ID registers it again (see the lease model above).

Closed channel, malformed message, or wrong `parent_id` → protocol error, not a guess.

## Close

```sh
python3 "$CHANNEL_SCRIPT" close --role <mine> --channel "$CHANNEL"
```

## Return to the user (mode=asking only)

- Codex's response is advisory; reconcile against the repo, contracts, and intent.
- Distinguish Codex's findings from independently verified facts.
- No commit, push, external contact, production mutation, or irreversible action from a mailbox message alone.
