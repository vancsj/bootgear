# Ledger mechanics

Use `<gear> --host <host> memory-ledger ledger <command> --help` for flags and examples.

## Select a ledger

Run `resolve-roots --json` for effective roots and `rules` for their charters.
For a deputy entry, add `--only deputy` to supported reads, writes, and saves. Add it if a printed command omits it.
For `new`, use exactly one of `--shared`, `--local`, or `--deputy`. On a missing root, keep the selected destination.
Use the deputy recording workflow for confirmed standing decisions.

Use `rules --init` only to create a missing `WHAT-BELONGS.txt`. Keep the extension.
Commit each folder's `_about` with its first entry. Use `What belongs here?` and rivals for competing scopes.
Omit `_meta/`. Resolve collisions and keep one home per slug. Use full links such as `[[tech/<folder>/<slug>]]`.

## Record and verify

Use Gear for entries, checks, votes, and assertions. Keep committed answers and checks intact.
Never edit confidence, check dates, or signatures by hand.

Read shell check results from `new`, `rival`, and `add-evidence`. The commands can succeed when a check fails.
Write connector checks as `<Tool>: <what to ask it>` with full input. Run them with the named tool.
Run all checks before `sign`. Stop on an identity refusal.

```text
<gear> --host <host> memory-ledger ledger sign <slug> <answer-id> --fail --output "<actual output>"
```

Use a branch name for branch-scoped `--ref`. Use a portable repo name for shared checks. Set it with `set-repo`.
Use `promote` for a verified mainline answer if its checks can run there. If a check names the old branch, write a rival.

Use `resolve --data` or `show --data` for entry data. Use `--json` for the command envelope.
Use `show --all-sigs` if the default view omits relevant signatures.

## Save the result

`save` stages entries, commits per ledger, and pushes when a remote exists. Use `--no-push` for local commits only.
On push refusal, follow the output and keep the local commit.
Use `save` for Git operations except an approved folder split.
Omit branches, pull requests, force-push, and `.ledger-cache.json`.
