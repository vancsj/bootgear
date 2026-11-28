# Persistent advice

Get Gear through `cli:gear`. Use its command help for the coordination interface.

## Request

Initialize the store. Reserve the advisor seat and use `assign` to request work.
Use the approved launcher and give it the seat invitation.

Start the background heartbeat. Follow `poll` and acknowledge its message ID.
Match the result to the assignment ID from `assign`.
Keep shared seats until the owning workflow ends. To stop an advisor, release its seat.
The seat keeps open assignments and unread messages.

## Listen

Use `join <invitation>` to take the seat.
Poll with a wait interval. Poll again after an empty result or after completion.
Acknowledge a message with its `mN` ID. Resume open work after an interruption.
Complete work with its `aN` ID and include your reply in that call.
Run the seat heartbeat in the background. Follow the restart command when it stops.
Use `blocked` when you cannot proceed. Use `send` for information during work.
Run poll after compaction. End the turn when poll returns `stopped`.
An idle advisor can end its pairing after the requester stays offline past the grace period.

## Resume

Try to resume a stale advisor. If it cannot resume, replace its seat and give the replacement its invitation.
The new participant polls for its open work. Report a missing launcher or host to the requester.
