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
3. If the output is `NO-CANDIDATES`, return `escalate` with reason `no-matching-entries`.
4. Read each `CANDIDATE` block in full. Each has a slug, question, answer, `Because:` context, and reason.
   It also names the entry type: `asserted` or decision.
5. For each candidate, mark it:
   - **agreeing**: it supports one option;
   - **conflicting**: it supports a different option;
   - **unrelated**: it does not answer this question.
   Judge by meaning, not by matching words.
6. Check the rules, in order:
   - **Assertion.** If an assertion covers the question, return `answered` at confidence `1.00` with that assertion's slug, at any stakes. Do not weigh decisions against it.
   - **Decisions, well-confirmed.** Answer only when the agreeing answer has memory-ledger band `well-confirmed`, with no equally or more confirmed conflict. Confidence is that answer's `conf` value. Otherwise return `escalate`.
   - **Decisions, below well-confirmed.** Return `escalate`, and list the agreeing and conflicting slugs as the basis for the debate.
7. Cite only slugs that appear in the `CANDIDATE` list. A slug outside it makes the answer invalid: return `escalate`.
8. Return the answer, confidence, source, and cited slugs. Also return one line of reasoning.
   Set `source` to `assertion` or `votes`. Include agreeing slugs and any conflicting slugs.
9. After the user answers an escalation, call the `record` skill in this conversation.
   Use the reply, options, and stakes only to derive canonical wording.
   Show the full record and fixed Because sentence. Write only after the user confirms.
   Do not store the raw reply or treat it as an assertion.

## Rules

- Never answer a hard-gate action.
- Never write an assertion. Only `deputy.py assert`, after the user confirms in the conversation, pins one.
- The deputy's own past answers do not count as agreeing cases.
- Each entry follows the Q&A standards in `references/qa-standards.md`. Read that file when an entry's shape is unclear.

## Host mechanics

Call `cli:gear`. Replace `<gear>` with its literal absolute path in each tool call.
Replace `<host>` with `claude` or `codex`, based on the current host.
The standards file is `references/qa-standards.md` in this plugin.
If `cli:gear` is missing on Claude Code, run `/plugin install cli@bootgear`. On Codex, run `codex plugin add cli@bootgear`.
The CLI reads the host from `--host` and the session id from the environment.
