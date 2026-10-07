---
name: start
description: Start a new engine run. Use when the user explicitly asks to start a new engine run.
disable-model-invocation: true
---

Stable entry point for the `engine` plugin. Invoke the public `engine:clarify` skill through the `Skill` tool, passing along the user's original request.

`clarify` settles the run with the user and hands it to `execute`; `start` returns nothing itself.
