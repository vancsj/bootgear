# task=rewrite

Rewrite a draft (issue/ticket body, PR description, review comment, chat message). Return it; post only with user approval.

## Accuracy

Before rewriting, verify every claim a reader could act on: symbols, behaviour, counts, causes. Remove unverified claims or keep their hedge. Tell Codex not to remove a required hedge.

## Prompt structure

State this rule in every prompt:

> No narration. No justification. No filler. No decoration. Use plain English. Use no jargon except
> broadly used industry terms. Common idioms are allowed when clear and useful. Remove
> figurative language only when decorative, obscure, dramatic, or less precise than direct wording. Do
> not invent words, claims, or details. Preserve key meaning, reasons, qualifications, operational
> requirements, meaningful numbers, exact identifiers, and structure. Make the result shorter where
> possible. Remove wording, not meaning.

State the required rewrite: shorter and restructured where useful.

- One read is enough; every noun/referent resolves.
- Bugs open with the reproducible scenario, not a mechanism restatement.
- Cut restated context, soft framing, hedging, explanatory closers.
- Short sentences over long compounds; restructuring is allowed and expected.

Structure contract:

- Keep the draft's existing structure: bullet lists stay bullets, numbered lists stay numbered, tables stay tables, code blocks stay verbatim. Rewrite the wording inside them.
- Never instruct "plain prose" or ban lists and fragments. A destination without headers is not a destination without structure.
- Reproduce symbol names, paths, IDs and numbers character-for-character.

Then the destination-specific rule:

- Templated destinations (e.g. repo issue templates): preserve exact headers and document shape too.
- Chat destinations: use only the markup that destination renders; never nest emphasis markers.
- PR review comments, issue comments, everything else: the contract above is the whole rule.

Use one prompt per draft. Derive constraints from that draft's destination and the user's latest instruction.

## Check the rewrite

- Symbol names, IDs, numbers, and required hedges preserved exactly.
- Templated destinations: rewritten headings match the active template before posting.
