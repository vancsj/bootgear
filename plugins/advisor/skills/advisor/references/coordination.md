# Persistent advice

Get Gear through `cli:gear`. Use its command help for the coordination interface.

## Request

Initialize the coordination store. Reserve a seat for the advisor and send its first request.
Use the approved launcher and give it the seat invitation.

Start the background heartbeat. Poll for the assignment result and acknowledge its delivery ID.
Match the result to the assignment ID from send.
Keep shared seats until the owning workflow ends. To stop an advisor, release its seat.
The seat keeps open assignments and unread deliveries.

## Listen

Use `join <invitation>` to take the seat.
Poll with a wait interval. Poll again after an empty result or after completion.
Acknowledge each delivery with its ID. Resume an open assignment after an interruption.
Run the seat heartbeat in the background. Follow the restart command when it stops.
Send a blocked report if evidence, authority, or a needed input is missing.
Run poll after compaction. End the turn when poll returns `stopped`.
An idle advisor can end its pairing after the requester stays offline past the grace period.

## Resume

Try to resume a stale advisor. If it cannot resume, replace its seat and give the replacement its invitation.
The new participant polls for its open work. Report a missing launcher or host to the requester.
