---
name: gear
description: Find the Gear executable. Use when a caller needs its path or a command example.
---

## Inputs and outcomes

Take the current host. Return the absolute Gear path and one example for that host, or a setup error.

## Procedure

1. Find this skill's absolute installation path.
2. Go up two directories from the skill directory.
3. Append `/bin/gear` to the plugin root.
4. Return the expanded path and the example.

## Rules

Use the installed plugin. Run commands as `<gear> --host <host> <plugin> <command> [arguments]`.

## Fallbacks

If the CLI plugin is missing, install it and call this skill again.
If the installation has no Gear executable, return the setup error.

## Host mechanics

Use the resolved path for `<gear>`. Give only the example for the current host.

| Host | Example | Install |
|---|---|---|
| Claude Code | `<gear> --host claude list` | `/plugin install cli@bootgear` |
| Codex CLI | `<gear> --host codex list` | `codex plugin add cli@bootgear` |
