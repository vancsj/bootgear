# Audit

## UNPORTABLE

`ledger audit` reports only **UNPORTABLE** evidence. It flags absolute and `~`-relative paths except standard tool caches and system directories.
Examples are `~/.gradle/`, `~/.m2/`, `~/.npm/`, `/etc/`, `/usr/`, `/bin/`, `/sbin/`, `/opt/`, `/var/`, `/Applications/`, `/Library/`, and `/System/`.

## Classify the JSON results

Use `audit --json`. For a large ledger, use `--filter` by folder.
Ask if another person can run each line on their machine and get the same answer.

- If no, propose the local ledger.
- If yes with a local prerequisite, keep it shared. Fix the check so a missing cache or service fails visibly.
- If yes, keep the entry. Accept a conventional tool directory or an exception in the ledger rules.

## Move an entry

After approval, use `git mv` and update its `# <slug>` heading. Check `lint` for `HEADER` errors.
