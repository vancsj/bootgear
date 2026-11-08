---
name: gear
description: Return the absolute Gear executable path for the current host and a command example.
---

## When to invoke, inputs, and handback outcomes

Use this skill when a caller needs the Gear executable path.

Input: the current host, Claude Code or Codex CLI.

Hand back the absolute path to `bin/gear` and one command example for that host.

## Procedure

1. Resolve this skill's installed directory as an absolute path.
2. Go up two directories from that directory to this plugin's root.
3. Append `/bin/gear` and expand the path.
4. Return the path and a host-specific command example.

## Judgment rules and safety boundaries

Use the path from this plugin's installed root.

Run commands as `<gear> --host <host> <plugin> <command> [arguments]`.

## Fallbacks

If the CLI plugin is missing, install it through the host, then invoke this skill again.

If Gear is missing from the installed plugin, return that setup error.

## Host mechanics

Return the expanded absolute path. Use `claude` or `codex` in the example, based on the current host.
Replace `<gear>` in the example with the absolute path you returned.
Claude Code example: `<gear> --host claude list`.
Codex CLI example: `<gear> --host codex list`.
Return only the example for the current host.
On Claude Code, install it with `/plugin install cli@bootgear`.
On Codex CLI, install it with `codex plugin add cli@bootgear`.
