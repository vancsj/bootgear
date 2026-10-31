# Deputy question and answer standards

## Scope

- The deputy store holds decisions only.
- A fact goes to the memory ledger, not to the deputy store.
- A decision is kept when one general question states it.
- Votes show whether a decision recurs. Do not drop a decision because it has one vote.

## Question

- Write one question for each entry.
- Ask one general question. Name no session, branch, pull request, finding, pass, slate or date.
- Do not list options in the question. Do not use `or`, `either`, `(a)` or `A:`.
- Do not use pronouns: `I`, `me`, `my`, `you`, `your`, `it`, `its`, `itself`.
- Use active voice and approved words.
- Use plain words. Do not invent names for a concept.
- Keep each sentence to 20 words or fewer.

## Answer

- Give each answer an id: `a1`, `a2`, and so on.
- Write one option for each answer.
- Do not use pronouns.
- Keep each sentence to 20 words or fewer.
- Do not write a bare letter or number, such as `A` or `2`.
- A different answer to the same question is a rival. It takes the next id on the same entry.
- Do not put a scope in an answer. Ask a second question for each scope.

## Votes and reasons

- A file that gives the same answer adds one vote to that answer.
- A file that gives a different answer starts a rival with zero votes.
- A combined file can add a vote to each question it answers.
- Give the reason as one sentence with one clause.
- Do not use a semicolon in the reason.
- Give the session check as the evidence line.

## Excluded from general votes

- Session-only notes. Do not count them.
- Pinned rules. A pinned rule is a rule, not a vote.
- Answers that depend on one project. Store them in that project.

## Hard gates

The deputy never answers these. The user decides:

- Production changes.
- Outward sends.
- Irreversible actions.
- Goal sign-off.
- Permitted mutations.
