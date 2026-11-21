# Channel communication

Use `<gear> --host <host> advisor channel <command>` with the current session ID.
If the peer plugin is absent, report it and stop. Codex installs it with `codex plugin add advisor@bootgear`.
Keep channel mode.

## Pair

- Listening owns `listener`. Run `register --role listener` on each new listening invocation.
  Report the number at once. Start the printed heartbeat.
- Asking owns `asker`. Run `list --live-for asker`. Follow its claim action for the most recently updated eligible listener.
  A busy listener can be absent. On `seat_claimed` or `channel_closed`, rescan once and try one more claim.
  If no claim succeeds, tell the user to start a listener and stop. Only listeners create channels.

Only the registering session can reclaim a seat, including after staleness or restart. A closed channel refuses registration.
Follow the skill's heartbeat rules.

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
| Exit 1, `peer_live: false` | Run any local heartbeat restart. The asker reports the stale peer. The listener attempts stale close. |

For an asker, allow 12 waits of 300 seconds before reporting unavailability this round.
Allow 12 more while a live listener reports `busy`.
Use real bounded waits. On Codex, use one call per poll. On Claude Code, run one listener iteration at a time.
Keep `waiting` and `busy` updates. Read the complete output before continuing.

## Resume

Use injected status or `whoami`. Follow `next`. Without an open seat, pair for the current mode.
After a process restart in the same session, reclaim the seat and restart its heartbeat.
Run a read-only `receive --timeout 5`. Check receipts for replies regardless of exit status.
Fetch matches. Keep waiting for other receipts. Never resend an outstanding request.
If an unread reply matches no receipt, fetch it, report the error, and stop.
With no unread messages or matches, resume normal polling. Report closed channels and malformed messages.

## Close

Use `<gear> --host <host> advisor channel close --role <mine> --channel <channel>`.
Close after a standalone ask, at session end, or after the last task in the owning workflow.
On a stale peer, the listener adds `--if-peer-stale`. Close requires a stale peer and no unread message.
On `peer_live` or `unread_message`, follow the printed action and continue listening.
Report the reason when stale close succeeds.
