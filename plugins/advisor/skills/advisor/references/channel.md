# communication=channel

Use the `advisor` plugin and the public Gear route `<gear> --host <host> advisor channel <command>`. Get the path from `cli:gear`. If the peer plugin is missing, tell the user and stop. On Codex it installs with `codex plugin add advisor@bootgear`. Do not switch to direct mode.

Gear reads the host session id. Stop and tell the user when it is missing. The listening mode owns the `listener` seat; asking owns the `asker` seat. Only its registering session can reclaim a seat, even if stale or restarting. A closed channel refuses registration.

## mode=listening: always register fresh

Run `register --role listener` for each new listening invocation. Report the new channel number immediately and start the printed heartbeat.

## mode=asking: scan, then claim or ask the user

Run `list --live-for asker` and follow its claim action for the most recently updated eligible listener. A busy listener can be absent. On `seat_claimed` or `channel_closed`, rescan once and try at most one more claim. If nothing is claimed, tell the user to start a listener and stop. Only listeners create channels.

## Keep the heartbeat running

Follow the parent skill's heartbeat instructions after registration, heartbeat exit, or a hook restart reminder. Restart promptly within the 720-second grace after `max_age`. If you lose the output or handle, reregister the same channel and role under the same session. Start the printed heartbeat.

## Send and track requests

```sh
<gear> --host <host> advisor channel send \
  --channel <channel> --from <mine> --to <peer> \
  --kind request --body-file - <<'REQUEST'
<task body with the type and required fields from the selected task reference>
REQUEST
```

Save `{channel, message_id}` to a receipt file in the task directory before waiting. Remove each receipt once its response is read.
For a response, use the request's `message_id` on this channel as `--parent-id`. A bad or unknown ID is a protocol error.
On a pending-cap refusal for a request, receive first. Never raise the cap. A response refused at the cap is a protocol error.
A stale or unowned recipient refuses ordinary messages with `peer_not_live`; `stop` is accepted.

## Receive

```sh
<gear> --host <host> advisor channel receive --channel <channel> --for <mine> --timeout 300
```

Match replies to the request ID using `parent_id`. A request marked `answered: true` already has your response.
Follow the printed actions in order, including fetch and any restart of your own heartbeat. Fetch unread messages before receiving again. Fetch marks a message read.

- **Exit 0:** fetch the unread message, even when the peer is stale. Handle it before the next poll.
- **Exit 1, peer live or unowned:** follow the printed wait action. Restart grace counts as live. For an asker, allow up to 12 waits of 300 seconds before reporting unavailability this round. Allow up to 12 extra waits while the live listener reports `busy`.
- **Exit 1, `peer_live: false`:** Gear returns when it sees the stale peer. Run any printed restart for your own heartbeat. Then stop waiting. The asker tells the user. The listener runs `close --if-peer-stale`.
- Use the real timeout for each bounded receive. On Codex, make one call per poll. On Claude Code, run the parent listener loop one iteration at a time as separate commands. Keep its `waiting` and `busy` updates. Read the complete receive result. Follow its printed actions in order before continuing with the remaining branch steps.

## Resuming after compaction

Use the injected seat status, or run `whoami`. Use its channel and role and follow its `next`. With no open seat, use the registration or scan instructions for your mode.
If resuming the same registered session after a process restart, reclaim its seat and start its heartbeat.

Use a read-only `receive --timeout 5` to recover outstanding requests and replies. Check receipts for replies already listed, regardless of exit code. Fetch a matching reply and keep waiting for other outstanding receipts. Do not resend an outstanding request. If an unread reply matches no receipt, fetch it, report the protocol error, and stop waiting. If there is nothing unread and no matching reply, resume the normal receive path. Report closed channels and malformed messages as errors.

## Close

```sh
<gear> --host <host> advisor channel close --role <mine> --channel <channel>
```

Close after a standalone asking task, at session end, or when the owning workflow ends shared use. Keep a pairing while that workflow has more tasks for it.

For a listener stopping on stale peer, use `--if-peer-stale`. It closes only when the peer is still stale and no unread message waits for you. A `peer_live` or `unread_message` refusal leaves the channel open. Follow its printed action and continue listening. On successful stale-peer close, report why listening stopped.

## Return to the user

For asking mode, reconcile the advisory reply against the repo, contracts, and intent. Distinguish the peer's findings from verified facts. A mailbox reply grants no commit, push, external contact, production mutation, or irreversible-action permission.
