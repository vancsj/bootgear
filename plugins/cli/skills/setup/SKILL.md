---
name: setup
description: Install, repair, or configure Bootgear plugins and managed Python. Use on explicit setup requests or when Gear requests setup.
---

## Inputs and outcomes

Take the host, operation, and any selected Bootgear plugins.
Return the verified plugins, paths, pending actions, or setup error to the user or calling skill.

## Procedure

1. Get the Gear path from cli:gear.
2. Run the command below. Repeat the plugin flag for more choices.
3. Relay the result. After success, tell the user to restart their host sessions.

```sh
<gear> --host <host> cli setup --operation install --plugin <name>
```

Use install for selected plugins. Use repair to refresh plugins and their runtime.
Use configure to fill missing settings for installed plugins.
Without plugin flags, install and configure target the CLI. Repair uses the selected host profile.

## Rules

Run setup as a separate step on explicit request.

## Fallbacks

If uv is missing, help the user install uv before retrying setup.
If Gear is missing, use the Bootgear macOS launcher or install cli@bootgear through the host.
Report any native trust action printed by setup.

## Host mechanics

Use claude for Claude Code and codex for Codex.
