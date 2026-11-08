---
name: setup
description: Prepare the shared Python runtime for installed Bootgear plugins.
---

## When to invoke, inputs, and handback outcomes

Use this skill when Gear reports that the shared runtime is missing or not ready.

Input: the current host, Claude Code or Codex CLI.

Hand back the ready runtime path, or the setup error and its next action.

## Procedure

1. Check that Python 3.12 and uv are available. Report any missing prerequisite.
2. Call `cli:gear` and use its returned absolute executable path.
3. Run `<gear> --host <host> cli setup` for the current host.
4. Return the runtime result to the caller.

## Judgment rules and safety boundaries

Run setup only when the caller requests it or Gear reports a missing runtime.

Do not install or change dependencies during normal Gear commands or hooks.

## Fallbacks

If the CLI plugin is missing, install it through the host, then invoke this skill again.

If setup fails, return its error and next action. Do not hide the failure.

## Host mechanics

For Claude Code, use `claude` as `<host>`.
If the CLI plugin is missing, run `/plugin install cli@bootgear` first.

For Codex CLI, use `codex` as `<host>`.
Run setup with host-level file and network access.
If the CLI plugin is missing, run `codex plugin add cli@bootgear` first.
