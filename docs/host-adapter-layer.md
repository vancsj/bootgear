# Host adapter layer

The engine hooks use one host-neutral normalization and policy boundary with
thin Claude Code and Codex adapters at the edges.

```text
host hook stdin
  -> host adapter validates and normalizes
  -> static policy evaluates a normalized event
  -> policy effects apply existing marker/ledger behavior
  -> host renderer emits native output or no controlling output
```

## Package boundary

The engine has one shared source directory for both hosts:

- `src/engine/host_event_input.py` — input bounds, normalization, and validation.
- `src/engine/host_types.py` — shared host event, intent, and output types.
- `src/engine/host_adapter.py` — host context, dispatch, effects, rendering, and safe traces.
- `src/engine/host_contracts.py` — host/event fields, matchers, handlers,
  capabilities, and plugin-root paths.
- `src/engine/policy.py` — static handler mapping, recall and stop policies, and invocation locks.
- `src/engine/policy_markers.py` and `src/engine/policy_state_nudge.py` — marker storage and state reminders.
- `hooks/gear` and `hooks/gear.py` — native hook loader that finds Gear and
  forwards the event to the plugin's registered handler.
- `hooks/adapter.py` — handler entry point and import bootstrap.

The active host selects its native hook registration. Native hook loaders supply host
paths, input contracts, and output envelopes. The engine layer does not import
advisor, coordination store, or memory-ledger implementation modules.

## V1 events

| Host | Event | Matcher | Handler(s) | Result |
|---|---|---|---|---|
| Claude | `SessionStart` | `startup\|clear\|compact` | `session_recall` | native context with an active ledger only: goal, principles and standards block; compact adds recall |
| Claude | `Stop` | none | `stop_reminder` | native context |
| Claude | `PostToolUse` | `.*` | `state_nudge` | native context |
| Claude | `PreCompact` | `manual|auto` | `compaction_observe` | observe only |
| Claude | `PostCompact` | `manual|auto` | `compaction_observe` | observe only |
| Codex | `SessionStart` | `^(startup\|resume\|clear\|compact\|fork)$` | `session_recall` | session id always; with an active ledger only: goal, principles and standards block; compact adds recall |
| Codex | `Stop` | none | `stop_reminder` | continuation-compatible output |
| Codex | `PostToolUse` | `.*` | `state_nudge`, `stop_reminder` | independent context handlers |
| Codex | `PreCompact` | `manual|auto` | `compaction_observe` | observe only |
| Codex | `PostCompact` | `manual|auto` | `compaction_observe` | observe only |

Each manifest command supplies fixed `--handler` and `--matcher-pattern`
arguments. An empty matcher pattern represents an event without matcher support.
Unknown host fields are ignored; malformed known fields, unsupported events,
and contradictory `agent_id`/`agent_type` identity produce a non-controlling
error.

`turn_id` may support existing Codex turn-correlation behavior, but event IDs,
hook invocation IDs, and `turn_id` are not replay or deduplication keys.

## Decisions and effects

Policies return one of:

- `observe` — empty stdout/stderr, exit 0;
- `add_context` — host-native `hookSpecificOutput` context;
- `continue` — only Codex `Stop`, rendered as its existing continuation-compatible
  `decision: "block"` response;
- `error` — bounded stderr, no controlling stdout, exit 0.

Policy evaluation is side-effect-free. Existing marker and ledger updates occur
only in the apply phase after validation and capability checks. Marker updates
remain lock-linearized and atomic, preserving current Stop/PostToolUse
turn-correlation behavior.

The adapter caps stdin at 1 MiB. Test traces are owner-only JSON lines limited
to event, matcher, handler, decision, rendered-result kind, context presence,
and exit status; prompts, tool inputs, transcripts, and paths are excluded.

## Installation paths

| Host | Hook root | Native hook command | Gear command |
|---|---|---|---|
| Claude | `${CLAUDE_PLUGIN_ROOT}` | `hooks/gear --host claude <command>` | `<gear> --host claude <plugin> <command>` |
| Codex | `${PLUGIN_ROOT}` | `hooks/gear --host codex <command>` | `<gear> --host codex <plugin> <command>` |

Hook manifests invoke each plugin's `hooks/gear` loader. The loader derives the
provider name from its own `gear.toml` and forwards the event through Gear.

No hook injects the session identity into a Bash command. Gear CLIs read it from
`BOOTGEAR_SESSION_ID`, then `CLAUDE_CODE_SESSION_ID` or `CODEX_SESSION_ID` for
the declared host, then the other one. An explicit argument wins.

## Verification

The canonical parameterized fixture corpus lives under
`plugins/engine/tests/fixtures/host_adapter/`; Claude and Codex runners execute
it through the shared adapter with explicit host context.
The same engine suite runs for each host. Native cases retain distinct output envelopes and event contracts.

The exact host contracts are checked against the official Claude Code and Codex
hook references and fresh-host smoke checks. Fixture tests remain authoritative
for exact envelopes, malformed input, unknown fields, identity, handler binding,
compaction matchers, side effects, and renderer behavior.
