---
name: ask
description: Answer a judgement question as the user's deputy from their recorded decisions and pinned assertions, citing every entry used, or escalate to the user. Call before any judgement point in engine, converge or review.
---

Answer a question the way the user would, from their own past decisions. Return one outcome.

## Inputs and outcomes

Inputs:

- The question, stated plainly.
- The options, each one line.
- The stakes, one line: what goes wrong if the answer is wrong.
- The caller's name, for the handback.

Outcomes, handed back to the caller:

- `answered`: the answer, the confidence, `source`, the cited slugs and the reasoning (Procedure step 8).
- `escalate`: the reason. The caller asks the user where its own rules allow it.
- `not-applicable`: the question asks for a hard-gate action (production change, outward send, irreversible action, goal sign-off, or permitted mutations). Return it without judging.

## Procedure

1. Call `cli:gear`, then run `<gear> --host <host> deputy deputy candidates "<question>"`. Pass the question as one quoted argument.
2. If the output is `ESCALATE deputy-root-absent`, return `escalate` with that reason. If the output is `ESCALATE memory-ledger-not-found`, return `escalate` with reason `memory-ledger-not-found`.
3. Treat `NO-CANDIDATES` as an empty ranked search.
4. Run `<gear> --host <host> deputy deputy index --asserted` even when the ranked search has no matches.
   If the index fails, return `escalate` with its diagnostic.
   Read the ranked candidates and every potentially applicable assertion in the index.
   Use `candidates "<slug>" --limit 1` to open each additional entry and verify its slug.
   Read entries with unclear relevance. If scope remains unclear or a relevant entry cannot be read, escalate.
5. For each candidate, mark it:
   - **agreeing**: it supports one option;
   - **conflicting**: it supports a different option;
   - **unrelated**: it does not answer this question.
   Judge by meaning, not by matching words.
6. If there are no applicable entries, return `escalate` with `no-matching-entries`. Then apply these rules:
   - **Assertion.** If applicable assertions conflict, return `escalate` with their slugs.
     When applicable assertions agree, return `answered` at confidence `1.00`. Cite the applicable slugs.
   - **Decisions, well-confirmed.** Answer only when the agreeing answer has memory-ledger band `well-confirmed`, with no equally or more confirmed conflict. Confidence is that answer's `conf` value. Otherwise return `escalate`.
   - **Decisions, below well-confirmed.** Return `escalate`, and list the agreeing and conflicting slugs as the basis for the debate.
7. Cite slugs only from the `CANDIDATE` blocks read in this invocation, including opened index entries.
   Return the candidate slugs so the caller can check the citations.
8. Return the answer, confidence, source, and cited slugs. Also return one line of reasoning.
   Set `source` to `assertion` or `votes`. Include agreeing slugs and any conflicting slugs.
9. Apply the user's answer to the current case. Offer **Save for future cases** when the decision can recur.
   Call the record skill if the user opts in and the caller allows a confirmation question.

## Rules

- Never answer a hard-gate action.
- Use the record skill to save an explicitly confirmed standing decision.
- The deputy's own past answers do not count as agreeing cases.
- Each entry follows the Q&A standards in `references/qa-standards.md`. Read that file when an entry's shape is unclear.

## Host mechanics

Call `cli:gear`. Replace `<gear>` with its literal absolute path in each tool call.
Replace `<host>` with `claude` or `codex`, based on the current host.
The standards file is `references/qa-standards.md` in this plugin.
If `cli:gear` is missing on Claude Code, run `/plugin install cli@bootgear`. On Codex, run `codex plugin add cli@bootgear`.
The CLI reads the host from `--host` and the session id from the environment.
