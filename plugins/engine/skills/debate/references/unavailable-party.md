# Unavailable parties

## Classify and record

Use `UNAVAILABLE` only when the configured dispatch cannot run. See the skill's host mechanics.
Treat completed dispatches as responses. Summarize nonempty, parseable output faithfully on one line.
For empty or unparseable output, record the first form. Count it as the party's position for that round.
For failed dispatch, record the second form immediately. Use the actual detail.

```text
round N, party '<role>': NO-RESPONSE (<detail>)
round N, party '<role>': UNAVAILABLE (<detail>)
```

Place the marker directly after the colon. `UNAVAILABLE` fills the slot for recovery and supplies no vote or response.
If a late reply arrives before round N+1 starts and before closure, append its real position to round N.
Keep the marker. Use the reply for count, unanimity, and the next brief. Otherwise discard it.

## Assess stakes

For each genuine absence, apply the settlement's reversibility and impact test.
At the high end of the threshold, fail the assessment and state why. Use reversibility and impact, without a numeric score.
Treat the absence as a stall. Continue toward `debate-capped` with a `round_cap:` summary.
Name the gap and stakes. Do not claim retry. Skip the party-count rules. Do not pause for a person. Keep `no_further_questions: true`.

## Retry when the stakes assessment passes

Count real responses in that round. Retry all still-missing parties together in the next round before closure.
Ask each party for `goal: kept` or `goal: narrowed <what>` in its retry-round position.
Run owed retries past the cap if necessary. Only an owed retry permits a round past the cap.
Give one retry per continuous absence. Start a new episode only after a return for at least one round.
Track episodes separately. After each round, check for new absences, including those during another retry.
Count returns from their actual round. Require a first independent position if there is no round-1 stance.
Otherwise require a response to the latest state. Never close while a retry remains due.

## Close after all retries

Count a party as responded if it has any real, non-marker position in the debate.

- **Zero:** record `debate-capped` with `round_cap:`. State that no party responded.
- **One:** use `debate-degraded` with `degraded_convergence:`. State that the result rests on that party's judgment.
- **Two or more, unanimous:** use `debate-degraded` with `degraded_convergence:`.
- **Two or more, dissent:** use `debate-capped`. Preserve the dissent.

Before either degraded close, require `goal: kept` from every responding party in the last retry round.
A late reply from a prior round does not count. Do not add a round.
For narrowing or a missing statement, use `debate-capped` with `round_cap:` and name the problem.

Reject `consented_stop` while a live absence remains. Allow it in a later full-roster round with all `CUT` votes.
For each degraded or capped close under this branch, name every missing party, episode, and retry.
Confirm the stakes assessment and one-round retry.
