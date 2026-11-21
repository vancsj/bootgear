---
name: ask
description: Answer a judgment question from the user's saved decisions or escalate it. Use before judgment in Engine, Converge, or Review.
---

## Inputs and outcomes

Take the caller's name, the question, one line per option, and one line of stakes.
Return one result to the caller.

| Result | Handback |
|---|---|
| `answered` | Answer, confidence, source, cited slugs, and one line of reasoning. |
| `escalate` | Reason and applicable slugs. The caller asks the user where allowed. |
| `not-applicable` | Hard gate without advice. |

## Procedure

1. For a hard gate, return `not-applicable`.
2. Get Gear from `cli:gear`. Run `<gear> --host <host> deputy deputy candidates "<question>"`.
   Pass the question as one argument. Treat `NO-CANDIDATES` as an empty search.
3. Run `<gear> --host <host> deputy deputy index --asserted` even when the search is empty.
   Read the ranked candidates. Open each potentially applicable assertion with `candidates "<slug>" --limit 1`.
   Verify each slug. Read entries of unclear relevance. Escalate if you cannot read an entry or confirm its scope.
4. Compare the question, answer, and reason for each entry. Check for agreement, conflict, and relevance.
   If none apply, escalate with `no-matching-entries`.
5. If applicable assertions conflict, escalate with their slugs.
   If they agree, return confidence 1.00, source `assertion`, and the applicable slugs.
6. Use votes only at band `well-confirmed` with no conflict at equal or higher confidence.
   Return the answer's `conf` and source `votes`. Otherwise escalate with the agreeing and conflicting slugs.
7. Cite only `CANDIDATE` blocks you read. Include agreeing and conflicting slugs.
8. Apply the answer to the current case. Keep one-off decisions in the active Engine run, if present.
   If the decision can recur, offer **Save for future cases**.
   Call `deputy:record` if the user opts in and the caller permits confirmation.

## Rules

Hard gates include production changes, outward sends, irreversible actions, goal sign-off, and mutation permissions.
Count only the user's decisions.
If an entry's format is unclear, read [qa-standards.md](../../references/qa-standards.md). Skip it otherwise.

## Fallbacks

For `ESCALATE deputy-root-absent` or `ESCALATE memory-ledger-not-found`, escalate with the reason.
If the index fails, escalate with its diagnostic.
If `cli:gear` is missing, install `cli@bootgear` through the host.

## Host mechanics

Use the absolute path from `cli:gear`. Use `claude` or `codex` for `<host>`.
Gear reads the session ID from the environment.
