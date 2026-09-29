---
name: advisor
description: Pair Claude Code and Codex CLI through a shared mailbox, or route a one-shot call to Codex. Use when the user asks Codex a question, wants a second opinion, wants a draft rewritten, wants delegated investigation, or when starting/continuing Codex as the dedicated advisor for Claude Code.
allowed-tools: Bash, Read, AskUserQuestion
---

Every invocation requires an explicit `--mode {asking|listening}` argument. If the triggering text carries no explicit `--mode` value, stop and ask the caller to re-invoke with one — never infer a mode from which host is running, from the triggering task, or from any other contextual signal. `--mode` decides which of the two sections below to follow; the channel's own `--role` (`listener` or `asker`, see `references/channel.md`) is fixed by that same choice, not a separate decision.

## mode=asking

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

### Reporting back

Never echo Codex's banner, streamed reasoning, or raw request/response payload into the transcript — only the final answer, reconciled against verified facts. One call, one clean answer; not the exchange that produced it.

## mode=listening

Read-only advisor for the paired session. Don't contact the peer except in response to a mailbox request. Never answer the human directly for a mailbox request.

```sh
CHANNEL_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/advisor/scripts/channel.py"
```

Set `SESSION_ID` to your own host's real session identifier — on Codex CLI, the same value its hooks deliver as `session_id` in their payload; on Claude Code, its own real session identifier — not a value you invent or copy from an unrelated shell variable. If no real session identifier is available to you in this invocation, fail rather than fabricate one; `SESSION_ID` is used for addressing/attribution (see `references/channel.md`), not pairing correctness, but it must still be genuine.

### 0. Escalation

Every `channel.py` call needs `sandbox_permissions: require_escalated` — `~/.bootgear/advisor` is outside the normal writable roots. Escalate on every call, not just the first.

### 1. Register first, report immediately

See `references/channel.md` for the pairing procedure.

### 2. Goal

Create the durable goal: *continuously poll the mailbox and process requests until the user stops the advisor or closes the channel.* Not per-request — don't mark complete after one answer or one empty poll. If a conflicting goal exists, report it and get direction instead of replacing it silently. Keep it active across compactions.

### 3. Check for unfinished work

```sh
python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 5
```
Read-only, safe anytime. Check the last 3 for a request from `<peer>` with no later response of yours naming it as `parent_id` — that's open; handle it in the loop below as if freshly arrived.

### 4. First poll

Before any other work, run one bounded `receive` and collect its output. Foreground, or a terminal session polled with `write_stdin`. Exit status `1` = no new message (its `note` says so); a request can take many minutes to come, so start the next bounded wait immediately. A background listener nobody polls doesn't count as listening.

Never return to the human after one empty poll while claiming to still be listening — start the next `receive` immediately, until a request arrives, the user stops the advisor, or the channel closes.

### 5. Listener loop

`<mine>` is your own role — `listener` if you're in `mode=listening`, `asker` if you're in `mode=asking` (see `references/channel.md`) — fixed by mode, never chosen freely; `<peer>` is the other one.

```sh
while :; do
  python3 "$CHANNEL_SCRIPT" state --channel "$CHANNEL" --role <mine> --value waiting >/dev/null
  RECEIVE_JSON=$(python3 "$CHANNEL_SCRIPT" receive --channel "$CHANNEL" --for <mine> --timeout 300)
  RECEIVE_STATUS=$?
  if [ "$RECEIVE_STATUS" -eq 1 ]; then continue; fi
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
