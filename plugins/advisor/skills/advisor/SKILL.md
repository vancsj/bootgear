---
name: advisor
description: Pair Claude Code and Codex CLI through a shared mailbox, or route a one-shot call to Codex. Use when the user asks Codex a question, wants a second opinion, wants a draft rewritten, wants delegated investigation, or when starting/continuing Codex as the dedicated advisor for Claude Code.
allowed-tools: Bash, Read, AskUserQuestion
---

## When to use, inputs and handback

Every invocation requires an explicit `--mode {asking|listening}` argument. If the triggering text carries no explicit `--mode` value, stop and ask the caller to re-invoke with one — never infer a mode from which host is running, from the triggering task, or from any other contextual signal. `--mode` decides which of the two workflows below to follow. The role you register with follows from `--mode` (see `references/channel.md` when using the channel).

Inputs: `--mode`; in `mode=asking`, the task (`rewrite`, `ask`, `review`, `delegate`) and its content, and the communication (`direct` or `channel`).

Handback in `mode=asking`, to the caller (the user or the calling skill), one reconciled answer per task:

- `rewrite` → the rewritten draft, not posted.
- `ask` → the answer, with each claim marked verified or unverified.
- `review` → the list of objections.
- `delegate` → Codex's findings, separated from independently verified facts.

Outcomes:

- answered (the handback above);
- `--mode` missing → asked the caller to re-invoke;
- no listener available → told the user to start one;
- Codex `advisor` plugin not installed → told the user;
- peer heartbeat stale → told the user;
- protocol error → reported, no guess;
- `mode=listening` stopped (`stop` request, user interrupt, turn limit, channel closed, or stale peer) → reported the stop reason to the user.

## Workflow

- **asking**: pick the communication and task docs → verify the facts the prompt relies on → send (`direct`: one `codex exec`; `channel`: pair, send, receive by `parent_id`) → treat the reply as advisory and verify its checkable claims → hand back one reconciled answer (see "Reporting back") → `channel`: close.
- **listening**: register → report the channel number → heartbeat → durable goal → recover an unfinished request → poll loop (fetch, answer, send response) → stop on `stop`, the user, a stale peer or a closed channel → close and report the stop reason.

### mode=asking

Two independent choices — load exactly one doc from each row.

**Communication** — how you reach Codex:

| | Doc | When |
|---|---|---|
| `direct` | `references/direct.md` | One-shot, no persistence, Codex sees only the prompt. |
| `channel` | `references/channel.md` | Persistent mailbox; Codex investigates on its own (files, commands), can take minutes, survives across turns/compaction. |

**Task** — what you want:

| | Doc | When |
|---|---|---|
| `rewrite` | `references/rewrite.md` | Polish a draft before posting. |
| `ask` | `references/ask.md` | A straight opinion or answer. |
| `review` | `references/review.md` | Adversarial objections on a decision/conclusion. |
| `delegate` | `references/delegate.md` | Hand off investigation or scoped work Codex does itself. |

Any task can use either communication doc — pick `channel` when the task needs Codex to look things up itself or the exchange may take several rounds; `direct` otherwise. `delegate` almost always needs `channel`.

### Heartbeat (channel, both modes)

Right after `register`, start the heartbeat in the background (see "Host mechanics") and keep it running until `close`:

```sh
python3 "$CHANNEL_SCRIPT" heartbeat --channel "$CHANNEL" --role <mine> --session "$SESSION_ID"
```

- It prints nothing while it runs. It ends with a `stopped:` line and a `next:` line; do what `next` says. After a `max_age` stop the seat stays live only for a 720-second restart grace, so run `next` promptly.
- Host reports the task stopped with no output, or handle lost: run `register` again with the same `SESSION_ID`, then start a new heartbeat.

### mode=listening

Read-only advisor for the paired session. Don't contact the peer except in response to a mailbox request. Never answer the human directly for a mailbox request.

Set `CHANNEL_SCRIPT` and `SESSION_ID` as in "Host mechanics". Run every `channel.py` call with the host's escalation, if any (see "Host mechanics").

#### 1. Register first, report immediately

Register the listener seat with `references/channel.md` § mode=listening, report the channel number to the user, then start the heartbeat (see "Heartbeat").

#### 2. Goal

Create the durable goal: *continuously poll the mailbox and process requests until the user stops the advisor or closes the channel.* Not per-request — don't mark complete after one answer or one empty poll. If a conflicting goal exists, report it and get direction instead of replacing it silently. Keep it active across compactions.

#### 3. Check for unfinished work

```sh
python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 5
```
Read-only, safe anytime. Check the last 3 for a request from `<peer>` with `answered: false` — that's open; handle it in the loop below as if freshly arrived. `answered: true` means you already sent a response naming it as `parent_id`.

#### 4. First poll

Before any other work, run one bounded `receive` and collect its output. Foreground, or a terminal session polled with `write_stdin`. Exit status `1` = no new message (its `note` says so); a request can take many minutes to come, so start the next bounded wait immediately — unless its `peer_live` is `false`: then run `close --role <mine> --channel "$CHANNEL" --if-peer-stale`. If it closes, your heartbeat ends; tell the user the asker's heartbeat is stale. If it refuses, do what its `next` says and keep listening. A background listener nobody polls doesn't count as listening.

Never return to the human after one empty poll while claiming to still be listening — start the next `receive` immediately, until a request arrives, `close --if-peer-stale` closes the channel, the user stops the advisor, or the channel closes.

#### 5. Listener loop

`<mine>` is your own role — `listener` if you're in `mode=listening`, `asker` if you're in `mode=asking` — fixed by mode, never chosen freely; `<peer>` is the other one.

```sh
while :; do
  python3 "$CHANNEL_SCRIPT" state --channel "$CHANNEL" --role <mine> --value waiting >/dev/null
  RECEIVE_JSON=$(python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 300 --json)
  RECEIVE_STATUS=$?
  if [ "$RECEIVE_STATUS" -eq 1 ]; then
    PEER_LIVE=$(printf '%s' "$RECEIVE_JSON" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["peer_live"]))')
    if [ "$PEER_LIVE" = false ] &&
      python3 "$CHANNEL_SCRIPT" close --role <mine> --channel "$CHANNEL" --if-peer-stale >/dev/null; then
      break
    fi
    continue
  fi
  if [ "$RECEIVE_STATUS" -ne 0 ]; then exit "$RECEIVE_STATUS"; fi
  # The message_id that RECEIVE_JSON's `next` fetches (the newest unread request):
  REQUEST_ID=<message_id>
  python3 "$CHANNEL_SCRIPT" state --channel "$CHANNEL" --role <mine> --value busy >/dev/null
  python3 "$CHANNEL_SCRIPT" fetch --channel "$CHANNEL" --message-id "$REQUEST_ID"
  # Answer it, then:
  printf '%s\n' "$RESPONSE" | python3 "$CHANNEL_SCRIPT" send \
    --channel "$CHANNEL" --from <mine> --to <peer> \
    --kind response --parent-id "$REQUEST_ID" --body-file -
  python3 "$CHANNEL_SCRIPT" state --channel "$CHANNEL" --role <mine> --value waiting
done
```

This loop is for Claude Code only. Codex CLI does not loop: it makes one `receive` call per poll. On exit 0, fetch and answer the message, then run `receive` again. On exit 1, run `receive` again. Never run `receive` again while a message is still unread.

`close --if-peer-stale` closes only while `<peer>` is still not live and no unread message waits for `<mine>`; otherwise it refuses (`peer_live` or `unread_message`, exit 2), the channel stays open, and the loop keeps listening.

After `break`: the loop has closed the channel, so your heartbeat ends with `channel_closed`; stop listening and tell the user the peer's heartbeat is stale.

## Rules

### Reporting back

Never echo Codex's banner, streamed reasoning, or raw request/response payload into the transcript — only the final answer, reconciled against verified facts. One call, one clean answer; not the exchange that produced it.

### Handling requests (listening)

- `discuss` → read-only investigation; return evidence, conclusions, assumptions, open risks.
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
  python3 "$CHANNEL_SCRIPT" close --role <mine> --channel "$CHANNEL"
  ```

## Fallbacks

- No `--mode` → ask the caller to re-invoke with one.
- No real session id available → fail.
- Codex `advisor` plugin missing → tell the user it isn't installed; never fall back to `direct`.
- No eligible listener → tell the user to start one and stop.
- Peer heartbeat stale → close with `--if-peer-stale` (listening) or tell the user instead of waiting again.
- Protocol error → report it; no guess.

## Host mechanics

Set `CHANNEL_SCRIPT` to `scripts/channel.py` in this skill's directory:

- Claude Code: `CHANNEL_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/advisor/scripts/channel.py"`.
- Codex CLI: `CHANNEL_SCRIPT="<directory holding this SKILL.md>/scripts/channel.py"`, as an absolute path.

Set `SESSION_ID` to the host's real session identifier, never an invented one; if none is available, fail.

- Claude Code: `SESSION_ID="$CLAUDE_CODE_SESSION_ID"`.
- Codex CLI: the `session_id` the host gives you in your context; the shell has no environment variable for it.

Escalation (Codex CLI): every `channel.py` call needs `sandbox_permissions: require_escalated` — `~/.bootgear/advisor` is outside the normal writable roots. Escalate on every call, not just the first.

Background heartbeat:

- Claude Code: the Bash tool with `run_in_background` and `timeout: 7200000`.
- Codex CLI: a terminal session left running, as for `receive`.
