---
name: ask
description: Answer a judgement question from the user's saved decisions or escalate it. Use before judgement in Engine, Converge or Review.
---

## Inputs and outcomes

Take the question, one line per option, one line of stakes, and the caller name.
Return one outcome to the caller.

- `answered` gives the answer, confidence, source, cited slugs, and one line of reasoning.
- `escalate` gives the reason. The caller asks the user where allowed.
- `not-applicable` hands a hard gate back without advice.

## Procedure

1. Return `not-applicable` for a hard gate.
2. Get Gear from `cli:gear`. Run `<gear> --host <host> deputy deputy candidates "<question>"`.
   Pass the question as one quoted argument. Treat `NO-CANDIDATES` as an empty ranked search.
3. Run `<gear> --host <host> deputy deputy index --asserted` even when the ranked search is empty.
   Read the ranked candidates. Open every potentially applicable assertion with `candidates "<slug>" --limit 1`.
   Verify each slug. Read entries with unclear relevance. Escalate if you cannot read one or confirm its scope.
4. Compare each question, answer, and reason by meaning. Identify agreeing, conflicting, and unrelated entries.
   Return `escalate` with `no-matching-entries` if none apply.
5. If applicable assertions conflict, escalate with their slugs.
   If they agree, answer with confidence 1.00 and source `assertion`. Cite the applicable slugs.
6. Answer from votes only at band `well-confirmed` with no equally or more confirmed conflict.
   Use the answer's `conf` and source `votes`. Otherwise escalate with the agreeing and conflicting slugs.
7. Cite only `CANDIDATE` blocks you read, including entries opened from the index.
   Return the candidate slugs so the caller can check citations. Include any agreeing and conflicting slugs.
8. Apply the user's answer to the current case. Keep a one-off in the active Engine run, if present.
   Offer **Save for future cases** when it can recur. Use `deputy:record` if the user opts in and confirmation is allowed.

## Rules

Hard gates include production changes, outward sends, irreversible actions, goal sign-off, and permitted mutations.
Count the user's decisions only. The deputy's past answers add no support.
Read [the QA standards](../../references/qa-standards.md) if an entry's shape is unclear.

## Fallbacks

For `ESCALATE deputy-root-absent` or `ESCALATE memory-ledger-not-found`, escalate with that reason.
If the index fails, escalate with its diagnostic.
If `cli:gear` is missing, install `cli@bootgear` through the host.

## Host mechanics

Use the absolute path from `cli:gear` and host `claude` or `codex`.
Gear reads the session id from the environment.
