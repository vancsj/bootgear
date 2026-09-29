---
name: start
description: Start a new engine run. Use when the user explicitly asks to start a new engine run.
disable-model-invocation: true
---

Stable entry point for the `engine` plugin. Invoke the public `engine:clarify` skill through the `Skill` tool, passing along the user's original request.

Do not duplicate or summarize `clarify`'s checklist here. When `engine`'s state machine gains a stage before `clarify`, update this delegation target, the state machine, and onboarding docs together, in the same change.
