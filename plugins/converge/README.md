# Converge

Converge checks factual claims through independent finding, refutation, and evaluation.
It records evidence and verdicts in a slate and computes which findings meet the cutoff.

Get Gear through the CLI plugin. Initialize one coordination store per shared host.
Open a slate with `gear converge converge init` and the applicable lenses and angles.
Give the returned invitations to their assigned participants.
Each participant joins once, polls the store, records claim actions, and completes its assignments.

Main reads results through the same poll command. Before finishing, main renders the slate and runs its gate.
A later review opens a new slate in the same store.

The [Converge skill](skills/converge/SKILL.md) describes the role rules and handback.
