# Ledger judgement

## Choose a ledger

Read each open ledger's `WHAT-BELONGS.txt` with `ledger rules`. Its rules take precedence over these defaults.

- Use shared for durable codebase, product, business, and third-party facts teammates can verify. Use local for machine-specific facts and reusable snapshots of moving state.
- Prefer claims tied to mainline, a locked dependency, an applied migration, or a closed date window. A live vendor setting, PR status, or open-ended production count can drift. Keep task-only work state with the task.
- Treat claims about missing work under active development as perishable. A documented design decision can make such a claim durable.
- Date the claim rather than the question. When a tally has a reusable method, put the method in shared and the measured count in local.
- Choose the destination yourself. Ask the user about uncertain placement or entries about people. Follow the CLI's confirmation guidance before publishing an append-only shared entry.
- Read every open ledger when judging a match. Narrow with `--only` only for a deliberate scoped read.
- For portability audits, use `audit` to find machine-bound evidence and `audit --json` to inspect all answers with checks. Ask whether a teammate could run each check on their machine and get the same result.

## Judge the match

1. Resolve before reading or writing. Read each candidate and compare its question with yours. In `(n/m terms)`, check which of your `m` terms its `n` matches actually cover. Check any `UNKNOWN` terms for a missing distinction.
2. Read a matching entry with `show`. Verify and sign it, or add a rival if it needs a correction.
3. If the question differs, use the resolver's `MINT` leaf. Choose the folder from its `_about` scope. Never invent a slug.
4. Use `--in <folder>` only with an explicit scope. A guessed folder can hide an existing answer.
5. Read the entry named in a near-duplicate refusal before considering `new --anyway`.

## Write the claim

- Give each answer one falsifiable claim in at most 40 words. Use a separate entry for each independent question.
- Add `--alt-terms` for phrases someone would search for without knowing the entry exists. Include symbols, error text, and alternate phrasings. Describe the question instead of the answer.
- Name the slug for its question. Keep committed answers, answer IDs, and evidence intact. Add a check with `add-evidence`; use a rival to replace a check or correct a claim.
- For `OVERSIZE` or `REGROUP`, propose a folder split. On approval, use `git mv` and update each slug heading before saving.
- Keep secrets and erasable data out of the ledger. Record only questions with answers another session can check.

## Write the evidence

1. Give a repeatable check for the clause that drives the decision. Split independent checks across repeated `--evidence` flags. Avoid `;` chaining, which can hide a failed step. If checks must share a shell command, use failure-propagating chaining such as `&&`. Use `cd <repo> &&` or `git -C <repo>` when a command needs that checkout.
2. Prefer repo-relative paths. Use `--repo <name>` to identify a different checkout. A conventional tool cache can use its standard path. Avoid personal home paths.
3. Prefer discovery over a fixed path or input. Guard live-state checks so a missing dependency or unreadable source fails visibly. Use `git grep -E` for alternatives.
4. Include the ref in a branch claim's check, such as `git grep … origin/<branch> …`. A pass on a different checkout does not verify that branch.
5. Cover the full claim. A partial check can pass while its omitted clause is false.

Check what the observation actually proves:

| Check | What to verify next |
| --- | --- |
| Search returns no match | Try alternate spellings, dynamic names, configuration, and call sites. Run a positive control. |
| Search returns a match | Check that the code is reachable and that a fixture, comment, or disabled flag does not explain the hit. |
| Search is path-scoped | Widen it to the tree and any sibling service that deploys the same code. |
| Query returns a count | Check population boundaries, inner joins, soft deletes, and the date window. |
| Definition or annotation | Check the effective runtime value after overrides and profiles. |
| Documentation or vendor page | Check current behavior when the claim is about runtime. |
| Silent exit zero | Make the check fail once before trusting a pass. |

## Verify and sign

1. Read the answer before every use. Run every current `Evidence:` line. Run connector checks with the tool they name.
2. Name an observation that would be false if the claim were wrong. Run that broader check. Add it if a later agent can reuse it. Write a rival if the claim proves narrower than the checks suggest.
3. Use `sign` for a pass. For a failure, use `sign --fail --output` with the real output. Use `refute --output` to contest another session's signature. Correct your own verdict by rerunning the checks and signing again.
4. Sign under the current AI session, including when an earlier session wrote the seed. A subagent sharing your session reports its evidence to you; sign once. Never sign as the user or invent an identity. The CLI records a verdict after you run the checks.
5. Read `e=N` as the number of checks available when a signature was cast. Rerun added checks before re-signing. Judge broken checks from the evidence and write a rival when needed.
6. Save each verified result in the same working stretch.

## Judge confidence and conflicts

Use confidence and signatures as leads. Rerun the checks before relying on any answer. A failing signature alone cannot settle the claim. It can come from the wrong branch, a missing build, or unavailable network. `refute` adds an opposing vote and preserves the original. For `SPLIT` evidence, write a rival with a check that distinguishes the conditions that produced the split.

An asserted answer records a human ruling. Use `assert` only when a check cannot decide the question, as with intent or a standing decision. Ask the user first. Supply their reason with `--why`; use `--clear` before replacing a ruling. Keep contrary signatures visible and use the CLI to change the assertion.

When answers disagree:

- Write a rival that names the answer ID and states the difference in its claim.
- Carry still-valid checks with `--keep-evidence <answer-id>`. The rival earns its own signatures; the original and its signatures stay intact.
- Use the checks to decide which answer applies. Keep all applicable answers visible.
- On `REF-LANDED`, promote a verified mainline answer. If a check names the old branch, use a rival with a mainline check. For `REF-GONE`, check the stored ref and repo. Confirm whether the work landed or was abandoned before dropping any entry.
- For a proven false answer, record the failing check output under the original with `sign --fail --output`. Use `rival` to add the corrected claim and its proof.
