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

The shared core is mirrored in both independently installable engine bundles:

- `src/engine/host_adapter.py` — input bounds, normalization, validation,
  host context, dispatch, effects, rendering, and safe traces.
- `src/engine/host_contracts.py` — host/event fields, matchers, handlers,
  capabilities, and plugin-root paths.
- `src/engine/policy.py` — static handler mapping and the current recall, stop,
  and state-nudge policies.
- `hooks/adapter.py` — host-specific stdin entry point and import bootstrap.

The Claude and Codex cores are byte-identical. Host wrappers supply their own
root environment, paths, input contract, and output envelope. The engine layer
does not import advisor, mailbox, or memory-ledger implementation modules.

## V1 events

| Host | Event | Matcher | Handler(s) | Result |
|---|---|---|---|---|
| Claude | `SessionStart` | `compact` | `session_recall` | native context; without an active ledger, principles only |
| Claude | `Stop` | none | `stop_reminder` | native context |
| Claude | `PostToolUse` | `.*` | `state_nudge` | native context |
| Claude | `PreCompact` | `manual|auto` | `compaction_observe` | observe only |
| Claude | `PostCompact` | `manual|auto` | `compaction_observe` | observe only |
| Codex | `SessionStart` | `^(startup\|resume\|compact)$` | `session_recall` | session id and principles always; with an active ledger, goal, and compact adds recall |
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

| Host | Root variable | Source | Hooks | Task command |
|---|---|---|---|---|
| Claude | `CLAUDE_PLUGIN_ROOT` | `src/` | `hooks/` | `bin/task` |
| Codex | `PLUGIN_ROOT` | `src/` | `hooks/` | `scripts/task` |

Legacy hook script paths remain direct compatibility entry points. Installed
manifests invoke `hooks/adapter.py` so shared behavior flows through the new
layer.

## Verification

The canonical parameterized fixture corpus lives under
`plugins/engine/tests/fixtures/host_adapter/`; Claude and Codex runners execute
it through their respective adapters. The Codex bundle drift test compares the
mirrored executable core, policy, contracts, and wrapper support files with a
narrow host-path/rendering adaptation allowlist.

The exact host contracts are checked against the official Claude Code and Codex
hook references and fresh-host smoke checks. Fixture tests remain authoritative
for exact envelopes, malformed input, unknown fields, identity, handler binding,
compaction matchers, side effects, and renderer behavior.
