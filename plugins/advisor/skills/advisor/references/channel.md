# Channel communication

Use `<gear> --host <host> advisor channel <command>` with the current session ID.
If the asker finds the peer plugin absent, report it and stop. Codex installs it with `codex plugin add advisor@bootgear`.
Keep channel mode.

## Pair

- Listening owns `listener`. Run `register --role listener` on each new listening invocation.
  Start the printed heartbeat and listen silently.
- Asking owns `asker`. Run `list --live-for asker`. Follow its claim action for the most recently updated eligible listener.
  A busy listener can be absent. On `seat_claimed` or `channel_closed`, rescan once and try one more claim.
  If no claim succeeds, tell the user to start a listener and stop. Only listeners create channels.

Only the registering session can reclaim a seat, including after staleness or restart. A closed channel refuses registration.
Follow the skill's heartbeat rules.

### Invited worker

Asker uses `reserve --group GROUP --worker ID`. Keep the reserved channel through the review group's visits.
Start the asker heartbeat that `reserve` prints if it is absent.
Use the approved `launch` template or pass the invitation to the operator for early startup.
Use `wait-listener` for this group and worker. Use its channel and receiving host.
Listener passes all three invitation fields to `register --role listener` using its own host and session.
Reuse the same invitation fields for registration after interruption. Follow the printed heartbeat command.
Use `reservations --group GROUP` to find channels for continuation or final closure.
The original asker keeps one active request per worker. Resume it from the saved receipt.

## Send and track

```sh
<gear> --host <host> advisor channel send \
  --channel <channel> --from <mine> --to <peer> \
  --kind request --body-file - <<'REQUEST'
<task body with the type and required fields from the selected task reference>
REQUEST
```

Save `{channel, message_id}` to a receipt file in the task directory before waiting. Remove the receipt after reading its reply.
Use the request ID on this channel as `--parent-id`. A bad or unknown ID is a protocol error.
At the request cap, receive first. Never raise the cap. A refused response at the cap is a protocol error.
Ordinary sends to stale or unowned peers return `peer_not_live`. A `stop` message can still go through.

## Receive

Run `<gear> --host <host> advisor channel receive --channel <channel> --for <mine> --timeout 300`.
Match `parent_id` to the receipt. An `answered: true` request already has a response.
Follow printed actions in order, including heartbeat restarts. Fetch unread messages before the next wait. Fetch marks them read.

| Result | Action |
|---|---|
| Exit 0 | Fetch, even when the peer is stale. Handle it before polling. |
| Exit 1, peer live or unowned | Follow the wait action. Restart grace counts as live. |
| Exit 1, `peer_live: false` | Run any local heartbeat restart. The asker reports the stale peer. The listener continues its bounded waits. |

For an asker, allow 12 waits of 300 seconds before reporting unavailability this round.
Allow 12 more while a live listener reports `busy`.
Use real bounded waits. On Codex, use one call per poll. On Claude Code, run one listener iteration at a time.
Keep `waiting` and `busy` updates. Read the complete output before continuing.

## Resume

Use injected status or `whoami`. Follow `next`. Without an open seat, pair for the current mode.
After a process restart in the same session, reclaim the seat and restart its heartbeat.
Run a read-only `receive --timeout 5`. Check receipts for replies regardless of exit status.
Fetch matches. Keep waiting for other receipts. Never resend an outstanding request.
If an asker finds an unread reply without a receipt, fetch it, report the error, and stop.
With no unread messages or matches, resume normal polling. A listener reports malformed requests through the mailbox.

## Close

Use `<gear> --host <host> advisor channel close --role <mine> --channel <channel>`.
The asker closes after a standalone ask or the last task in its workflow.
The listener closes only on an explicit stop instruction. Keep the channel open while waiting for an asker.
