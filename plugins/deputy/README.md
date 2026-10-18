# deputy

> **Your proxy for judgement questions.**
> It answers from your own recorded decisions, or it escalates to you.

`deputy` answers a judgement question the way you would, from your recorded decisions and
pinned assertions. It cites every entry it uses. When it cannot settle the question, it
returns `escalate`, and the AI asks you. Your answer to an escalation becomes a new decision
that the deputy can cite later.

The plugin has two skills:

| Skill | What it does |
|---|---|
| `deputy:ask` (Codex: `$deputy:ask`) | answers a question from recorded decisions and assertions, or escalates |
| `deputy:record` (Codex: `$deputy:record`) | records your answer to an escalated question as a decision |

The decisions live in a separate memory-ledger root, `~/.memory-ledger/deputy`. The
`LEDGER_DEPUTY_ROOT` variable overrides the path.

---

## Reminders

Two hooks remind the AI to use the deputy. Each adds one line of context.

| Event | Reminder |
|---|---|
| `UserPromptSubmit`, on both hosts | Before it asks you a work question, the AI calls `deputy:ask`. If your prompt answers an escalated question, the AI calls `deputy:record`. |
| `PostToolUse` on `AskUserQuestion` (Claude Code) or `request_user_input` (Codex) | If `deputy:ask` escalated the question you just answered, the AI calls `deputy:record`. |

Both reminders tell the AI to call `deputy:record` only when your answer is already written
in a session ledger file. On Codex, `request_user_input` is available in Plan mode only, so
the second reminder fires only there.

The hooks print nothing when the deputy root does not exist, in a subagent, or on any error.

---

## Setup

Install the plugin on each host that will use it:

```
/plugin marketplace add vancsj/bootgear
/plugin install deputy@bootgear
```

```
codex plugin marketplace add vancsj/bootgear
codex plugin add memory-ledger@bootgear
codex plugin add deputy@bootgear
```

Requirements:

- Claude Code installs `memory-ledger` with `deputy` as a declared dependency.
- Codex has no dependency mechanism. Install `memory-ledger@bootgear` on Codex yourself.
  Without it, `deputy:ask` returns `escalate` and `deputy:record` is refused.

Codex skips a new or changed hook until you trust it. After you install or update the
plugin, review the hooks with `/hooks` in Codex and trust them. Until then, no reminder
fires on Codex.

---

## Standalone, or as bootgear gear

Nothing here needs the rest of bootgear. The `engine`, `converge` and `review` skills call
`deputy:ask` at their judgement points when `deputy` is installed.
