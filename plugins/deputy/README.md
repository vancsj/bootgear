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

The hooks add reminders to the main agent's context. Subagents receive none.

| Event | Reminder |
|---|---|
| `UserPromptSubmit`, on both hosts | RECORD: record an escalated answer when it is already in a session ledger file. |
| `PostToolUse`, on both hosts | Count one hook-visible completion toward ASK. Question-tool returns also emit RECORD immediately. |
| `PostToolUseFailure`, on Claude Code | Count the failed completion toward ASK. A failed question call does not emit RECORD. |

ASK first appears on the tenth observed completion. Later ASK reminders require both ten more completions and 300 elapsed seconds.
Calls accumulate during cooldown. The next eligible completion emits ASK when both limits pass. No background timer runs.
RECORD does not reset the ASK counter or cooldown. If both reminders are due, the hook emits each once.

Question tools are `AskUserQuestion`, `request_user_input`, and `request_user_input_async`.
On Codex, hosted tools do not trigger tool hooks. MCP error results also lack a completion event in Codex 0.166.0.
Those calls remain outside the count. Claude failure events count where supported.

### Configuration

Use the project's `.bootgear/config/deputy.yaml`:

```yaml
ask_reminder:
  tool_calls: 10
  cooldown_seconds: 300
```

Both settings must be positive integers. The built-in values are 10 and 300.
The hook reads `~/.claude/deputy.yaml` or `~/.codex/deputy.yaml`, then the nearest project file.
Project values override host-user values. Missing keys keep their lower-layer values.
The project search starts at the session's working directory and stops at the repository boundary.

Invalid configuration prints a diagnostic and skips ASK without changing its counter. RECORD remains immediate.
The hook keeps locked cadence state beside the deputy root, in `.deputy-reminder-state`. State is separate for each host and session.

The hooks print nothing when the deputy root does not exist or the event belongs to a subagent.
Other hook errors remain non-blocking.

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

- Python 3.11 or later and `uv` run the hook with its declared PyYAML dependency.

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
