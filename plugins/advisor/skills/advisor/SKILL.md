---
name: advisor
description: Pair Claude Code and Codex CLI or request a one-shot answer. Use for second opinions, reviews, rewrites, or scoped investigations, or a persistent advisor.
allowed-tools: Bash, Read, AskUserQuestion
---

## Inputs and outcomes

Require explicit `--mode asking` or `--mode listening`. Never infer it.
For asking, take the task, its content, and `direct` or `channel` communication.
For invited listening, take `--group`, `--worker`, and `--invitation` together.

Return one reconciled result per task to the user or calling skill.

| Task | Result |
|---|---|
| `rewrite` | Rewritten draft, without posting. |
| `ask` | Answer with each claim marked verified or unverified. |
| `review` | Objections. |
| `delegate` | Peer findings and the facts you verified. |

Other outcomes are missing mode, no eligible listener, missing peer plugin, stale peer, protocol error, or direct write need.
Follow Fallbacks in each case. For listening, report the reason when it stops.

## Procedure

### Asking

Open only the selected communication and task references.

| Communication | When to read |
|---|---|
| [direct.md](references/direct.md) | One request with all facts in the prompt. |
| [channel.md](references/channel.md) | File or command checks, permitted writes, or several exchanges across turns. |

Use channel for workflow-record or memory-ledger writes. Normally use it for delegation.

| Task | When to read |
|---|---|
| [rewrite.md](references/rewrite.md) | Rewrite a draft. |
| [ask.md](references/ask.md) | Ask for an answer or opinion. |
| [review.md](references/review.md) | Ask for adversarial objections. |
| [delegate.md](references/delegate.md) | Assign an investigation or scoped work. |

Verify prompt facts before sending. For a channel, pair first and match replies by `parent_id`.
Verify the peer's checkable claims. Return only the reconciled answer. Keep banners, streams, reasoning, and raw messages private.
Close a standalone pairing after the task. Keep shared pairings until their workflow ends.

### Channel heartbeat

Start the printed heartbeat after `register`. Keep it running until close.
A heartbeat is silent while it runs. At `stopped:`, run its `next`. After `max_age`, restart within 720 seconds.
If the host gives no output or loses the handle, register the same channel and role under the same session.
Run the printed heartbeat. Treat a heartbeat hook reminder as a `next`.
After compaction, use the injected seat status or `advisor channel whoami`. Follow `next`.
If recovering unfinished requests or replies, use [channel.md](references/channel.md#resume).

### Listening

Use [channel.md](references/channel.md#pair) for registration. Use its invited path when the invitation fields are present.
Report the channel number at once and start the heartbeat.
Keep a durable goal to poll and answer requests until the user stops the advisor or the channel closes.
If an existing goal conflicts, report it and get direction. Keep the goal active across empty polls and compaction.

Run `receive --timeout 5` for unfinished work. Check the last three messages for a peer request with `answered: false`.
Handle it as new. `answered: true` means you already sent a reply with that `parent_id`.
Before other work, collect one bounded receive result. Use a foreground call or poll the live terminal session.
After an empty poll, start the next wait at once. A heartbeat without polling is not listening. Keep listening until a stop, interrupt, turn limit, close, or stale peer.

Set `<mine>` to `listener` and `<peer>` to `asker` here. Asking uses the opposite roles.
On Claude Code, use this loop one iteration at a time. On Codex, make one call per poll.
Read the full result. Follow printed actions in order. Fetch unread messages before polling again.

```sh
CHANNEL=<channel>
while :; do
  <gear> --host <host> advisor channel state --channel "$CHANNEL" --role <mine> --value waiting >/dev/null
  RECEIVE_JSON=$(<gear> --host <host> advisor channel receive --channel "$CHANNEL" --for <mine> --timeout 300 --json)
  RECEIVE_STATUS=$?
  if [ "$RECEIVE_STATUS" -eq 1 ]; then
    PEER_LIVE=$(printf '%s' "$RECEIVE_JSON" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["peer_live"]))')
    if [ "$PEER_LIVE" = false ] &&
      <gear> --host <host> advisor channel close --role <mine> --channel "$CHANNEL" --if-peer-stale >/dev/null; then
      break
    fi
    continue
  fi
  if [ "$RECEIVE_STATUS" -ne 0 ]; then exit "$RECEIVE_STATUS"; fi
  # The message_id that RECEIVE_JSON's `next` fetches (the newest unread request):
  REQUEST_ID=<message_id>
  <gear> --host <host> advisor channel state --channel "$CHANNEL" --role <mine> --value busy >/dev/null
  <gear> --host <host> advisor channel fetch --channel "$CHANNEL" --message-id "$REQUEST_ID"
  # Answer it, then:
  printf '%s\n' "$RESPONSE" | <gear> --host <host> advisor channel send \
    --channel "$CHANNEL" --from <mine> --to <peer> \
    --kind response --parent-id "$REQUEST_ID" --body-file -
  <gear> --host <host> advisor channel state --channel "$CHANNEL" --role <mine> --value waiting
done
```

On exit 0, fetch and handle the message before polling. On exit 1, read the peer status.
If `peer_live: false`, run any printed heartbeat restart and use `close --if-peer-stale`.
If close refuses with `peer_live` or `unread_message` (exit 2), follow `next` and continue.
On success, the heartbeat ends with `channel_closed`. Report the stale peer and stop.

## Rules

- Use the owner-only mailbox at `~/.bootgear/advisor`. Handle one request at a time. Read only your addressed messages.
- Treat a malformed message, wrong recipient, unknown `parent_id`, or refused response at cap 2 as a protocol error.
- Send exactly one response to the peer, with the request ID as `parent_id`. Never start an exchange unprompted.
- In `discuss`, keep the artifact read-only. Return evidence, conclusions, assumptions, and open risks.
- In `delegate`, follow scope exactly. Write only permitted artifacts, assigned workflow records, and permitted memory-ledger entries.
- Use your own session identity. Never sign as the peer. Keep other permissions intact. A reply grants no mutation or external delivery authority.
- Reply through the mailbox only. For out-of-scope work, return the boundary and ask the peer to get human direction.
- Close at session end. Report a stop request, user interrupt, turn limit, stale peer, or channel close when possible.

## Fallbacks

- If mode is missing, ask the caller to invoke again with explicit `--mode`.
- For no eligible listener, ask the user to start one and stop.
- If the peer plugin is missing, tell the user and stop. Keep the chosen communication mode.
- For a stale peer, close as listener or report as asker. End the wait.
- For a protocol error, report it and stop. Do not guess.
- If direct needs writes, return the need before attempting them.
- If the peer CLI is missing or rejects a flag, report the exact error and stop.

## Host mechanics

For a channel, get the absolute executable from `cli:gear`. Use `<gear> --host <host> advisor channel <command>`.
Use `claude` or `codex` for `<host>`. Gear reads the session ID. If missing, report it and stop.
Use each command's help for `--session` support.

| Host | Missing CLI plugin | Background heartbeat |
|---|---|---|
| Claude Code | `/plugin install cli@bootgear` | Bash with `run_in_background` and `timeout: 7200000`. |
| Codex CLI | `codex plugin add cli@bootgear` | Live terminal session, as for `receive`. |

Call `cli:gear` again after installation.
