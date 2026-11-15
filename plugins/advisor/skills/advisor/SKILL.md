---
name: advisor
description: Pair Claude Code and Codex CLI through a mailbox, or send a one-shot prompt to either CLI. Use for second opinions, reviews, rewrites, scoped investigations, or a persistent advisor.
allowed-tools: Bash, Read, AskUserQuestion
---

## When to use, inputs and handback

Every invocation requires an explicit `--mode {asking|listening}` argument. If the triggering text carries no explicit `--mode` value, stop and ask the caller to re-invoke with one — never infer a mode from which host is running, from the triggering task, or from any other contextual signal. `--mode` decides which of the two workflows below to follow. The role you register with follows from `--mode` (see `references/channel.md` when using the channel).

Inputs: `--mode`; in `mode=asking`, the task (`rewrite`, `ask`, `review`, `delegate`) and its content, and the communication (`direct` or `channel`).

Handback in `mode=asking`, to the caller (the user or the calling skill), one reconciled answer per task:

- `rewrite` → the rewritten draft, not posted.
- `ask` → the answer, with each claim marked verified or unverified.
- `review` → the list of objections.
- `delegate` → the peer's findings, separated from independently verified facts.

Outcomes:

- answered (the handback above);
- `--mode` missing → asked the caller to re-invoke;
- channel has no listener available → told the user to start one;
- channel peer `advisor` plugin not installed → told the user;
- peer heartbeat stale → told the user;
- protocol error → reported, no guess;
- direct call needs a write → returned the need before attempting the write;
- `mode=listening` stopped (`stop` request, user interrupt, turn limit, channel closed, or stale peer) → reported the stop reason to the user.

## Workflow

- **asking**: pick the communication and task docs → verify the facts the prompt relies on → send (`direct`: one call to the other CLI; `channel`: pair, send, receive by `parent_id`) → treat the reply as advisory and verify its checkable claims → hand back one reconciled answer (see "Reporting back") → `channel`: close.
- **listening**: register → report the channel number → heartbeat → durable goal → recover an unfinished request → poll loop (fetch, answer, send response) → stop on `stop`, the user, a stale peer or a closed channel → close and report the stop reason.

### mode=asking

Two independent choices — load exactly one doc from each row.

**Communication** — how you reach the peer:

| | Doc | When |
|---|---|---|
| `direct` | `references/direct.md` | One-shot to the other CLI, with the task supplied in the prompt. |
| `channel` | `references/channel.md` | Persistent mailbox; the peer investigates on its own (files, commands), can take minutes, survives across turns/compaction. |

**Task** — what you want:

| | Doc | When |
|---|---|---|
| `rewrite` | `references/rewrite.md` | Polish a draft before posting. |
| `ask` | `references/ask.md` | A straight opinion or answer. |
| `review` | `references/review.md` | Adversarial objections on a decision/conclusion. |
| `delegate` | `references/delegate.md` | Hand off investigation or scoped work the peer does itself. |

Any task can use either communication doc — pick `channel` when the task needs Codex to look things up itself or the exchange may take several rounds; `direct` otherwise. `delegate` almost always needs `channel`.
Select `channel` before assigning workflow-record or memory-ledger writes.

### Heartbeat (channel, both modes)

After `register`, run the heartbeat from its `next` line in the background (see "Host mechanics"). Keep it running until `close`. The command has this form:

```sh
<gear> --host <host> advisor channel heartbeat --channel <channel> --role <mine>
```

- It prints nothing while it runs. It ends with a `stopped:` line and a `next:` line; do what `next` says. After a `max_age` stop the seat stays live only for a 720-second restart grace, so run `next` promptly.
- The host reports the task stopped with no output, or the handle is lost. Then run `register --channel <channel> --role <mine>` again, and start the heartbeat it prints.
- A hook message `advisor: your heartbeat for channel N (ROLE) is not running; ...`: act on it like a `next` — start the command it names in a new background session.

### After compaction (channel, both modes)

Do what the `next` of the injected seat status says. With no status in context, run `<gear> --host <host> advisor channel whoami`. Then do what its `next` says (see `references/channel.md` § Resuming after compaction).

### mode=listening

Keep the target artifact read-only unless the request permits changes.
Write only assigned workflow records and permitted memory-ledger entries outside that artifact.
Verify and record your own entries under your own identity. Never sign as the peer.
Keep every other write limit. Do not contact the peer except in response to a mailbox request.
Never answer the human directly for a mailbox request.

#### 1. Register first, report immediately

Register the listener seat with `references/channel.md` § mode=listening, report the channel number to the user, then start the heartbeat (see "Heartbeat").

#### 2. Goal

Create the durable goal: *continuously poll the mailbox and process requests until the user stops the advisor or closes the channel.* Not per-request — don't mark complete after one answer or one empty poll. If a conflicting goal exists, report it and get direction instead of replacing it silently. Keep it active across compactions.

#### 3. Check for unfinished work

```sh
<gear> --host <host> advisor channel receive --channel <channel> --for <mine> --timeout 5
```
Read-only, safe anytime. Check the last 3 for a request from `<peer>` with `answered: false` — that's open; handle it in the loop below as if freshly arrived. `answered: true` means you already sent a response naming it as `parent_id`.

#### 4. First poll

Before any other work, run one bounded `receive` and collect its output. Foreground, or a terminal session polled with `write_stdin`. Exit status `1` = no new message (its `note` says so). A request can take many minutes to come, so start the next bounded wait immediately. If its `peer_live` is `false`, do not wait: run `close --role <mine> --channel <channel> --if-peer-stale`. If it closes, your heartbeat ends; tell the user the asker's heartbeat is stale. If it refuses, do what its `next` says and keep listening. A background listener nobody polls doesn't count as listening.

Never return to the human after one empty poll while claiming to still be listening — start the next `receive` immediately, until a request arrives, `close --if-peer-stale` closes the channel, the user stops the advisor, or the channel closes.

#### 5. Listener loop

`<mine>` is your own role — `listener` if you're in `mode=listening`, `asker` if you're in `mode=asking` — fixed by mode, never chosen freely; `<peer>` is the other one. Replace `<channel>` in the first line with the channel number.

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

This loop is for Claude Code only. Codex CLI does not loop: it makes one `receive` call per poll. On exit 0, fetch and answer the message, then run `receive` again. On exit 1, run `receive` again. Never run `receive` again while a message is still unread.

`close --if-peer-stale` closes only while `<peer>` is still not live and no unread message waits for `<mine>`; otherwise it refuses (`peer_live` or `unread_message`, exit 2), the channel stays open, and the loop keeps listening.

After `break`: the loop has closed the channel, so your heartbeat ends with `channel_closed`; stop listening and tell the user the peer's heartbeat is stale.

## Rules

### Reporting back

Never echo the peer's banner, streamed reasoning, or raw request/response payload into the transcript — only the final answer, reconciled against verified facts. One call, one clean answer; not the exchange that produced it.

### Handling requests (listening)

- `discuss` → keep the target artifact read-only; return evidence, conclusions, assumptions, open risks.
- `delegate` → follow the stated scope exactly. No commit, push, external contact, production mutation, or irreversible action unless explicitly authorized.
- One response per request, addressed to `<peer>`, with `parent_id` = the request's id.
- `send` rejects at the pending cap (2) — treat a rejected response send as a protocol error, not a reason to raise the cap.
- Malformed message, wrong recipient, or unmatched `parent_id` → hard protocol error. Don't guess or fall back to ordinary work.

### Safety and lifecycle

- Mailbox: `~/.bootgear/advisor`, owner-only.
- One request at a time. Never read or answer messages addressed to `<peer>`.
- Don't start a conversation with the peer unprompted.
- Stop on a `stop` request, a user interrupt, or the turn limit. Report the stop reason if possible.
- Out-of-scope request → return the boundary, ask the peer to get human direction.
- Close on session end:
  ```sh
  <gear> --host <host> advisor channel close --role <mine> --channel <channel>
  ```

## Fallbacks

- No `--mode` → ask the caller to re-invoke with one.
- Channel: no session id in the environment → stop and tell the user.
- CLI plugin missing → Claude Code: run `/plugin install cli@bootgear`; Codex CLI: run `codex plugin add cli@bootgear`. Then call `cli:gear` again.
- Channel peer `advisor` plugin missing → tell the user; never fall back to `direct`.
- Direct peer CLI missing or refusing a flag → report the exact error and stop.
- No eligible listener → tell the user to start one and stop.
- Peer heartbeat stale → close with `--if-peer-stale` (listening) or tell the user instead of waiting again.
- Protocol error → report it; no guess.

## Host mechanics

For channel mode, call `cli:gear`. Replace `<gear>` with its literal absolute path in each tool call.
Replace `<host>` with `claude` or `codex`, based on the current host.
Run channel commands as `<gear> --host <host> advisor channel <command> [arguments]`.

Channel commands read this session's id from the environment. If no session id is in the environment, stop and tell the user.
Only `register`, `heartbeat`, `list` and `whoami` accept `--session`; the environment normally supplies it.

Background heartbeat:

- Claude Code: the Bash tool with `run_in_background` and `timeout: 7200000`.
- Codex CLI: a terminal session left running, as for `receive`.
