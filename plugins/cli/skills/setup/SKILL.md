---
name: setup
description: Prepare the shared Python runtime and required installed plugins before a Bootgear workflow.
---

## When to invoke, inputs, and handback outcomes

Use this skill before a workflow needs sibling plugins, or when Gear requests runtime setup.

Inputs: the current host and an optional installed target plugin name.

Hand back the runtime path and checked plugins to the caller, or the setup error and its next action.

## Procedure

1. Check that Python 3.12 and uv are available. Report any missing prerequisite.
2. Call `cli:gear` and use its returned absolute executable path.
3. Run `<gear> --host <host> cli setup --plugin <name>` when the caller supplies a target plugin.
   Otherwise, run `<gear> --host <host> cli setup`.
4. Return the setup result to the caller.

## Judgment rules and safety boundaries

Run setup only for an explicit skill invocation or a Gear setup request.

Do not install or change dependencies during normal Gear commands or hooks.

If a host sandbox denies a Gear call, stop and tell the user to restart the host without its sandbox.

## Fallbacks

If the CLI plugin is missing, install it through the host, then invoke this skill again.

If setup fails, return its error and next action. Do not hide the failure.

## Host mechanics

Read only the section for the calling host. Skip the other host's section.

### Claude Code

Use `claude` as `<host>`.
If the CLI plugin is missing, run `/plugin install cli@bootgear` first.
Let Claude install declared dependencies. If setup reports missing plugins, complete native installation and retry.

### Codex CLI

Use `codex` as `<host>`.
If the CLI plugin is missing, run `codex plugin add cli@bootgear` first.
Targeted setup installs missing declared plugins through Codex and checks their enabled installed roots.
Ask the user to trust the cli plugin hooks in `/hooks`. Codex skips an untrusted hook, and the session then keeps its stored plugin list.
