---
name: start
description: Start an Engine run. Use when the user explicitly requests a new run.
disable-model-invocation: true
---

## Inputs and outcome

Take the user's original request. Leave the handback to `engine:clarify` and `engine:execute`.

## Procedure

Invoke `engine:clarify` with the original request. It settles the run and hands off to `engine:execute`.

## Host mechanics

Use the host skill interface.
