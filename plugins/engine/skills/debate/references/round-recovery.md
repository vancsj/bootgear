# Recover a debate round

## Partial round after compaction

Find the highest round tagged with the question ID. A party has a slot if its `round N, party '<role>':` entry exists.
An unavailability marker also fills the slot. If all slots are full, perform the next round-start check.
Otherwise poll only parties with no entry or marker. Use the effective state before the first response or marker.
Keep that state for the entire round. Do not add a round-start marker or repeat a brief to a recorded party.

## Stuck round

Before the cap, a round stalls if every party repeats its prior position without material change.
Send the current positions to `resolve`. Ask whether a source of truth or principle settles the issue.
If `resolve` cannot decide, continue toward the cap.

If `resolve` decides, require its `--mode resolve` entry without `--question`. Its summary must say it broke a stall.
That entry leaves the question open. Close it at once with the question ID, `--mode debate-capped`, and `round_cap:`.
Name the decided answer and cite the `resolve` entry.
