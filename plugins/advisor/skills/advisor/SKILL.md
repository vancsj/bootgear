---
name: advisor
description: Pair Claude Code and Codex CLI or request a one-shot answer. Use for second opinions, reviews, rewrites, or scoped investigations, or a persistent advisor.
allowed-tools: Bash, Read, AskUserQuestion
---

## Inputs and outcomes

Require explicit `--mode asking` or `--mode listening`. Never infer it.
For asking, take the task, its content, and `direct` or `channel` communication.
For invited listening, take `--group`, `--worker`, and `--invitation` together.

In asking mode, return one reconciled result per task to the user or calling skill.

| Task | Result |
|---|---|
| `rewrite` | Rewritten draft, without posting. |
| `ask` | Answer with each claim marked verified or unverified. |
| `review` | Objections. |
| `delegate` | Peer findings and the facts you verified. |

Other outcomes are missing mode, no eligible listener, missing peer plugin, stale peer, protocol error, or direct write need.
Follow Fallbacks in each case.

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
Start the heartbeat. While the channel is open, send questions, blockers, and reports only to the asker through the mailbox.
Keep the user conversation silent, including progress updates and task summaries.
If you need clarification, send it as the response to the current request. Wait for the asker's next request.
Keep the turn active after every reply and empty poll. Resume the mailbox wait immediately.
Keep the listening goal active across heartbeat restarts and compaction.

Run `receive --timeout 5` to recover unfinished work. Handle a request with `answered: false`.
A request with `answered: true` already has a response with that parent ID.

1. Set the listener state to `waiting`. Run one `receive --for listener --timeout 300` for the channel.
2. Collect the full result. If the command still runs, wait for it. Follow printed heartbeat actions.
3. On a message, fetch it. For a request, set the state to `busy` and send a response with its parent ID.
4. After each response or empty wait, return to step 1. Keep waiting when the asker heartbeat is stale.
5. After 24 consecutive empty rounds, you may ask the user whether to keep listening. Keep the channel open pending their answer.
   If they choose to continue, start a new full wait for the next 24 rounds.

Only completed five-minute waits count. Any asker message resets the count. Heartbeats and recovery polls leave it unchanged.
Close on an explicit stop request. End listening when the channel closes or the user stops you.

## Rules

- Use the owner-only mailbox at `~/.bootgear/advisor`. Handle one request at a time. Read only your addressed messages.
- Treat a malformed message, wrong recipient, unknown `parent_id`, or refused response at cap 2 as a protocol error.
- Send exactly one response to the peer, with the request ID as `parent_id`. Never start an exchange unprompted.
- In `discuss`, keep the artifact read-only. Return evidence, conclusions, assumptions, and open risks.
- In `delegate`, follow scope exactly. Write only permitted artifacts, assigned workflow records, and permitted memory-ledger entries.
- Use your own session identity. Never sign as the peer. Keep other permissions intact. A reply grants no mutation or external delivery authority.
- Reply through the mailbox only. For out-of-scope work, return the boundary and ask the peer to get human direction.
- Asker owns ordinary close. Listener task completion leaves the channel open.

## Fallbacks

- If mode is missing, ask the caller to invoke again with explicit `--mode`.
- In asking mode, for no eligible listener, ask the user to start one and stop.
- In asking mode, report a missing peer plugin to the user and stop. Keep the chosen communication mode.
- For a stale listener, the asker reports it and ends the wait.
- A listener sends protocol errors to the asker and keeps listening. An asker reports the error and stops.
- If direct needs writes, return the need before attempting them.
- In direct mode, report the exact error if the peer CLI is missing or rejects a flag, then stop.

## Host mechanics

For a channel, get the absolute executable from `cli:gear`. Use `<gear> --host <host> advisor channel <command>`.
Use `claude` or `codex` for `<host>`. Gear reads the session ID. If missing, report it and stop.
Use each command's help for `--session` support.

| Host | Missing CLI plugin | Background heartbeat |
|---|---|---|
| Claude Code | `/plugin install cli@bootgear` | Bash with `run_in_background` and `timeout: 7200000`. |
| Codex CLI | `codex plugin add cli@bootgear` | Live terminal session, as for `receive`. |

Call `cli:gear` again after installation.
