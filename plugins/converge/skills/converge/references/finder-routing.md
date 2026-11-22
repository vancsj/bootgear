# Routed finder handoff

Read main's `work` output. Use the planned host, model and effort for each routed finder.
Follow the host section below. Before reservation, confirm the native arguments, unshadowed role and supported lifecycle.
If the host cannot honor the profile, report a blocked assignment with the worker and the cause.

Send `launch` one JSON `launches` list. Use each ready worker's `id`, `host`, `model`, and `effort`.
Include only workers that fit the available native slots. On refusal, correct the batch and retry.
Start each accepted worker once. Pass the exact returned arguments, slate and worker IDs, and full assignment.
Keep the native handle from that worker's own call. Match each receipt to the worker ID in that call.
Tell the finder to complete its assigned coverage and return. Use its same native identity for later actions.

Send `launch-result` one JSON `outcomes` list. Follow public help for the fields.
Use `finished` after the native turn returns. Include its handle and original worker ID as `receipt_worker`.
Add available actual `model` and `effort` under `effective`. With a known mismatch, follow Gear's blocked handback.
For a host failure, record `blocked` and its reason. Include the handle and `receipt_worker` with any native evidence.
Keep missing effective evidence unverified. Never fill it from the launch request.
On recovery, reuse a finished handle. For an attempted worker, recover the original receipt and record its outcome.
If recovery fails, record a block and its cause. Follow main's work for the next assignments.

## Host mechanics

### Claude Code

Use native `Agent` with `model` and `effort`. Use unshadowed `general-purpose`.
Inspect loaded project, user and plugin agent definitions and effective settings for overrides.
Check `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` and `CLAUDE_CODE_EFFORT_LEVEL` before reserving a finder.
Use the original Agent ID with `SendMessage` for later work. Release the slot through native turn completion.
Use available resolved model and `SubagentStop` effort for that Agent ID.

### Codex

Use clean `spawn_agent` with `model` and `reasoning_effort`. Check whether configured `default` shadows the built-in role.
Use the lifecycle supported by the registered host tools. Report a block if a required operation is unavailable.
With `close_agent`, release a completed slot when needed. For later work, use `resume_agent` and `send_input`.
With `followup_task`, save the canonical task name as the handle. Use it to resume the completed worker.
Use available child metadata for observed model and effort.
