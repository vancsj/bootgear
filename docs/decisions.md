# decisions

bootgear separates two kinds of open question. Each kind has its own
path. A run never mixes the two.

- A **fact** has one right answer. Code, a test or a command shows it.
- A **choice** has more than one valid answer. The answer depends on
  priorities. Only people decide it.

## Components

| Component | Handles | Ends as |
|---|---|---|
| `converge` | Facts behind a set of claims | `survived`, `disputed`, `unverified` or `killed`, with a separate `cut` field |
| `resolve` (engine) | A disagreement that one settled source of truth can decide | Decided by one domain, or passed on |
| `deputy` | A choice the user already decided in the same way | `answered` with cited entries, `escalate`, or `not-applicable` for a hard gate |
| `debate` (engine) | A choice that `resolve` and `deputy` cannot settle | A closed question with its answer and preserved dissent |
| User | Hard gates, and every choice that the paths above escalate | The user's answer |

## Flow

```
open question
  |
  +-- fact --> converge --> survived | killed | disputed
  |                           (a disputed fact stays in converge)
  |
  +-- choice in execute
        |
        v
      threshold check: below debate_threshold in threshold mode --> solo in execute
        |  at or above debate_threshold
        v
      resolve: does a source_of_truth domain settle it?
        |  yes --> decided, recorded as mode resolve
        |  no
        v
      deputy:ask    (never for a hard gate)
        |  assertion      --> solo decision, cites the assertion slug
        |  not-applicable --> hard gate: execute uses the threshold path
        |  escalate       --> debate, with deputy_slugs
        v
      debate        (only choices at or above debate_threshold)
        |  factual dispute --> refused, sent to converge
        |  no source can settle it --> inconclusive
        |  choice --> rounds --> closing outcome
```

A choice below `debate_threshold` in `threshold` mode is decided solo in
`execute`. It does not reach `resolve`.

## Hard gates

The deputy never answers a hard gate. The user decides these:

- production changes;
- outward sends;
- irreversible actions;
- goal sign-off;
- permitted mutations.

## Converge: facts only

`converge` checks claims with separate finder, refuter and cutter agents.
Each claim ends with one status:

- `survived`: no refutation holds, or the refuter agreed with the finder's rebuttal.
- `disputed`: the refuter disagreed with the rebuttal, and the finder rebutted again.
- `killed`: the finder declined to rebut a refutation.
- `unverified`: the claim was cut before any attack.

A claim with a remaining decision carries a `choice`. The caller sends that
choice to `deputy:ask`, except for a hard gate, which goes to the user. A factual
dispute never goes to `debate`.

## Resolve: settled sources first

`resolve` classifies the disagreement into one domain of the settlement's
`source_of_truth`. The domains are `scope and outcome`, `current behavior`,
`implementation approach` and `correctness`. The settlement names the source
for each domain.

`resolve` never invents a source. When no settled source covers the
disagreement, it moves to `deputy:ask`, then to `debate` if the deputy escalates.
When the settlement is silent or ambiguous, the same path applies. In a stuck
round, `resolve` does not call `deputy:ask`. It reports that no domain settles the
disagreement, and `debate` continues toward `debate_round_cap`.

## Deputy: the user's past decisions

The deputy stores decisions and pinned assertions. Facts stay in the
memory ledger.

A hard-gate question returns `not-applicable` before any rule runs. For any other
question, the deputy reads the matching entries and marks each one as agreeing,
conflicting or unrelated. The rules apply in this order:

1. **Assertion.** A pinned assertion that covers the question returns
   `answered` at confidence `1.00`, at any stakes.
2. **Decisions at `well-confirmed`.** The deputy answers only when the agreeing
   answer has the `well-confirmed` band and no conflicting answer has an equal
   or higher band. The confidence is that answer's `conf` value.
3. **Other decisions.** The deputy returns `escalate`, and lists the agreeing
   and conflicting slugs as the basis for debate.

The deputy cites only slugs from its candidate list. Any other slug makes
the answer invalid, and the deputy escalates. Its own past answers do not
count as votes.

Only the user creates an assertion. The user must confirm it in the
conversation before `deputy.py assert` pins it.

## Debate: choices only

`debate` runs when `resolve` and `deputy` cannot settle a choice that passes
`debate_threshold`.

- **Admission.** Only skills named in `debate_admission` may call `debate`
  directly. A direct call must pass every check the `debate` skill lists:
  the caller is listed, the decision is stated plainly, at least two live
  alternatives conflict, the caller checked its own sources, those sources did
  not decide the issue, and the decision passes the threshold.
- **Parties.** `debate_roster` lists the stable party ids. At most five parties
  run, including `main-agent`. At least two parties run.
- **Round 0** settles topic, scope, principles and cutoff. It closes with
  `scope-settled`.
- **Round 1** gives independent positions. Round 2 and later rounds answer each
  other party's latest position.
- **Stuck round.** A round with no progress goes to `resolve` again. The
  debate then continues toward `debate_round_cap`.

A debate hands back exactly one of: `Refused` (a factual dispute; nothing
recorded), `inconclusive` (a fact no source can settle; nothing debated), or a
closed question.

Each closing outcome maps to one ledger mode:

| Closing outcome | Ledger mode |
|---|---|
| `unanimous_convergence` | `debate` |
| `consented_stop` | `debate-capped` |
| `round_cap` | `debate-capped` |
| `degraded_convergence` | `debate-degraded` |

For `consented_stop` and `round_cap`, the main agent gives the decided answer.
When `resolve` decides a disagreement, its ledger entry uses mode `resolve` and
names the domain that settled it.

## Related docs

- [engine.md](engine.md): the engine loop, settlement, resolve and debate.
- [converge.md](converge.md): slates, cutoff and gate.
- [session-ledger.md](session-ledger.md): decision entries and their modes.
- [memory-ledger.md](memory-ledger.md): the ledger of settled facts and its deputy root.
