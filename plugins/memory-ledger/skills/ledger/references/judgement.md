# Ledger judgement

## Choose a ledger

Read each open ledger's `WHAT-BELONGS.txt` with `ledger rules`. Apply its rules first.

- Use shared for durable facts about code, products, business, and third parties that teammates can verify.
- Use local for machine-specific facts and reusable snapshots of changing data.
- Prefer mainline, locked dependencies, applied migrations, or closed date ranges. Vendor settings, open PRs, and live counts can change.
- Treat absent work in active development as temporary unless a documented decision makes it durable.
- Date the claim. For a reusable count, put the method in shared and the measured value in local.
- Choose the destination. Ask the user if placement is unclear or the entry concerns a person.
- Follow the CLI's confirmation guidance before publishing an append-only shared entry.
- For portability, run `audit`. Use `audit --json` to inspect answers with checks.
  Ask if a teammate can run each check on their machine and get the same result.

## Judge the match

1. Resolve before reading or writing. Compare each candidate question with yours.
2. In `(n/m terms)`, check which terms match. Check `UNKNOWN` terms for a missing distinction.
3. Use `show` for a match. Verify and sign it or write a rival.
4. For a different question, use the `MINT` leaf. Choose the folder from its `_about` scope.
5. Use `--only` for deliberate scoped reads. Use `--in <folder>` only with an explicit scope.
6. On a near-duplicate refusal, read the named entry before considering `new --anyway`.

## Write the claim

- Write one falsifiable claim per answer, up to 40 words. Use separate entries for independent questions.
- Add `--alt-terms` for search phrases, symbols, and errors that describe the question.
- Name the slug for its question. Preserve committed answers, IDs, and checks.
- Use `add-evidence` to add a check. Write a rival to replace a check or correct the answer.
- For `OVERSIZE` or `REGROUP`, propose a split. After approval, use `git mv` and update each slug heading before saving.
- Store only reusable questions with verifiable answers. Keep secrets and erasable data out.

## Write the evidence

1. Check the clause that drives the decision. Give each independent check its own `--evidence` flag.
2. Use `&&` if shell steps must run in order. Avoid `;`. Use `cd <repo> &&` or `git -C <repo>` when needed.
3. Prefer paths relative to the repo. Use `--repo <name>` for another checkout.
   Use standard paths for tool caches. Avoid personal home paths.
4. Prefer discovery over fixed paths or data. Make missing dependencies and unreadable sources fail visibly.
5. Include the ref in a branch check, for example `git grep … origin/<branch> …`.
6. Check the full claim. Use these checks to test its limits.

| Observation | Next check |
|---|---|
| No match | Try alternate names, dynamic names, config, and call sites. Run a positive control. |
| Match | Check reachability. Exclude fixtures, comments, and disabled flags. |
| Path-limited search | Search the tree and services that deploy the same code. |
| Count | Check the population, inner joins, soft deletes, and date range. |
| Definition or annotation | Check the effective runtime value after overrides and profiles. |
| Documentation | For runtime claims, check current behavior. |
| Silent exit zero | Make the check fail once. |

## Verify and sign

1. Before each use, read the answer and run all current `Evidence:` lines. Use the named connector for connector checks.
2. Run a check that would fail if the claim were false. Add it if reusable. Write a rival if it narrows the claim.
3. Use `sign` for a pass or `sign --fail --output` with the real failure. Use `refute --output` to contest another signature.
4. To correct your own verdict, rerun the checks and sign again.
5. Use your current AI session, including for another session's seed. Never use the user's identity or invent one.
   A subagent that shares your session reports its evidence to you. Sign once.
6. Treat `e=N` as the check count at signing. Run added checks before signing again.
7. Check why evidence fails. Write a rival when necessary. Save the verified result in the same work session.

## Judge confidence and conflicts

Use confidence and signatures as leads. Rerun checks. A failure can result from the wrong branch, missing build, or unavailable network.
`refute` adds an opposing vote and keeps the original. For `SPLIT`, write a rival with a check that separates the conditions.

Use `assert` only for a human ruling that a check cannot decide. Ask the user first.
Pass their reason with `--why`. Use `--clear` before replacement. Use the CLI and keep contrary signatures visible.

- For different answers, name the answer ID and the difference in the rival.
- Carry valid checks with `--keep-evidence <answer-id>`. Each answer keeps its own signatures.
- Run checks to decide which answers apply. Keep every applicable answer visible.
- On `REF-LANDED`, promote a verified mainline answer. If a check uses the old branch, write a rival with mainline evidence.
- On `REF-GONE`, check the saved ref and repo. Confirm if the work landed or stopped before dropping the entry.
- For a false answer, sign the failure on the original. Use `rival` for the correction and proof.
