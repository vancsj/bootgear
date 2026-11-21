---
name: setup
description: Prepare the shared Python runtime and required plugins. Use before a workflow needs them or when Gear requests setup.
---

## Inputs and outcomes

Take the host and an optional installed target plugin name.
Return the runtime path, checked plugins, and pending user actions to the caller, or return the setup error.

## Procedure

1. Check for Python 3.12 and uv. Report missing prerequisites.
2. Get the absolute Gear path from `cli:gear`.
3. Run `<gear> --host <host> cli setup`. Add `--plugin <name>` when the caller supplies a target.
4. Return the result and its next step.

## Rules

Run setup only on explicit request or when Gear requests it.
Keep dependency changes out of normal commands and hooks.
Report installation, hook trust, and session loading separately.
Keep the caller's blocker open while required user actions remain.

## Fallbacks

If setup fails, return the error and next action.
If a sandbox denies Gear, stop. Tell the user to restart the host without its sandbox.

## Host mechanics

Read only the current host's section.

### Claude Code

Use `--host claude`. If absent, install with `/plugin install cli@bootgear`, then retry.
Let Claude install declared dependencies. If setup reports missing plugins, install them through Claude and retry.

### Codex CLI

Use `--host codex`. If absent, run `codex plugin add cli@bootgear`, then retry.
Targeted setup installs declared plugins and checks their enabled roots.
Relay follow-up actions for all new or changed plugins.
Keep user actions pending if setup reports `activation: unverified`.
