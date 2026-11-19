# Ledger mechanics

Get the absolute Gear path from `cli:gear`. Use `claude` or `codex` as `<host>`.
Use help for commands, flags, and current examples:

```text
<gear> --host <host> memory-ledger ledger --help
<gear> --host <host> memory-ledger ledger <command> --help
```

## Select a ledger

Use `resolve-roots --json` to see the effective roots and `rules` to read their charters.
Run `doctor` first on errors. If roots are missing, tell the user to run the memory-ledger setup skill.

Search shared and local by default. For a deputy entry, carry `--only deputy` on each supported lookup, write and save. Check subcommand help for support. Add the selector if a printed next command omits it.

```text
<gear> --host <host> memory-ledger ledger resolve "<question>" --only deputy
<gear> --host <host> memory-ledger ledger show <slug> --only deputy --data
<gear> --host <host> memory-ledger ledger save --only deputy
```

Pass exactly one of `--shared`, `--local`, or `--deputy` to `new` for an explicit destination. A missing root is a refusal. Do not retry by writing to a different ledger. Use the deputy recording workflow for confirmed standing user decisions.

Use `rules --init` only to seed a missing `WHAT-BELONGS.txt`. Keep that extension.
Create each folder's `_about` entry in the same commit as its first entry. Use the question `What belongs here?` and rivals for competing scopes. Do not create `_meta/`. Keep one home per slug. Resolve collisions explicitly. Use full slugs in links such as `[[tech/<folder>/<slug>]]`.

## Record and verify

Use Gear for entries, checks, votes, and assertions. Keep committed answers and checks intact. Add a check or write a rival when a check needs replacement. Never edit confidence, checked dates, or signatures by hand.

`new`, `rival`, and `add-evidence` report shell check results without requiring them to pass. Read the output before trusting an entry. Write connector checks as `<Tool>: <what to ask it>` with the complete input. Run those checks yourself with the named tool. Run every check before `sign`; signing records the verdict only.

```text
<gear> --host <host> memory-ledger ledger sign <slug> <answer-id> --fail --output "<actual output>"
```

Gear takes signer identity from the host environment. If explicitly needed, place `--session-id` before the subcommand. A Codex signer is `codex:<full-session-id>`; any supplied `--as` must match. Stop on an identity refusal.

Use a branch name for a branch-scoped `--ref`. Use a portable repo name for shared evidence. Set or correct its repository through `set-repo`. Use `promote` for a verified mainline answer when its checks can run on mainline. If a check names the old branch, write a rival with a new check.

For structured match or answer data, use `resolve --data` or `show --data`. For the command envelope use `--json`. Use `show --all-sigs` when the default view omits relevant signatures.

## Save the result

Run `save` in the same working stretch. It stages entries, commits per ledger, and pushes where a remote exists. Use `--no-push` for local commits when publishing is outside the task's permission. Follow its output on a push refusal and preserve the local commit. Use `save` for Git operations except an approved folder split. Do not use branches, PRs, force-push, or commit `.ledger-cache.json`.
