---
name: ask
description: Answer a judgement question as the user's deputy from their recorded decisions and pinned assertions, citing every entry used, or escalate to the user. Call before any judgement point in engine, converge or review.
---

Answer a question the way the user would, from their own past decisions. Return one outcome.

## Inputs

- The question, stated plainly.
- The options, each one line.
- The stakes, one line: what goes wrong if the answer is wrong.
- The caller's name, for the handback.

## Procedure

1. Run `python3 <plugin-dir>/scripts/deputy.py candidates "<question>"`. Pass the question as one quoted argument.
2. If the output is `ESCALATE deputy-root-absent`, return `escalate` with that reason.
3. If the output is `NO-CANDIDATES`, return `escalate` with reason `no-matching-entries`.
4. Read each `CANDIDATE` block in full. Each has a slug, its question, its answer, its `Because:` context and reason, and whether it is an assertion (`asserted`) or a decision.
5. For each candidate, mark it:
   - **agreeing**: it supports one option;
   - **conflicting**: it supports a different option;
   - **unrelated**: it does not answer this question.
   Judge by meaning, not by matching words.
6. Check the rules, in order:
   - **Assertion.** If an assertion covers the question, return `answered` at confidence `1.00` with that assertion's slug, at any stakes. Do not weigh decisions against it.
   - **Decisions, below the threshold.** Answer only when the agreeing answers carry at least 3 votes in total and none conflicts. A vote is one `Evidence:` line on an agreeing answer. Confidence is that total vote count. Otherwise return `escalate`.
   - **Decisions, at or above the threshold.** Do not answer from votes. Return `escalate`, and list the agreeing and conflicting slugs as the basis for the debate.
7. Cite only slugs that appear in the `CANDIDATE` list. A slug outside it makes the answer invalid: return `escalate`.
8. Return `answered` with: the answer, the confidence, `source: assertion` or `source: votes`, the cited agreeing slugs, the conflicting slugs if any, and one line of reasoning.

## Outcomes

- `answered`: the answer, confidence, `source`, cited slugs and reasoning above.
- `escalate`: the reason. The caller asks the user where its own rules allow it.
- `not-applicable`: the question asks for a hard-gate action (production change, outward send, irreversible action, goal sign-off, or permitted mutations). Return it without judging.

## After a user answer to an escalation

Call the `record` skill with the question, the user's answer, the reason, the options and the stakes shown to the user. Do not treat the user's answer as an assertion.

## Rules

- Never answer a hard-gate action.
- Never write an assertion. Only `deputy.py assert`, after the user confirms in the conversation, pins one.
- The deputy's own past answers do not count as agreeing cases.
