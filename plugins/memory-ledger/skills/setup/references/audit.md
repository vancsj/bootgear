# Audit

## UNPORTABLE

`ledger.py audit` reports **UNPORTABLE** only: Evidence lines containing an
absolute path into somebody's home directory.

Answer bodies are immutable, so the fix is a new answer carrying a portable
check: `ledger.py rival <slug> --keep-evidence <aN> --evidence "…"` with a
repo-relative path, or `--repo <name>` to name the checkout instead of embedding
its location.

## Classifying `audit --json`

`ledger.py audit --json [--filter <text>]` dumps every answer with its question,
claim and check, uncategorised and unranked. Work through them — `--filter` to
take a folder at a time on a large ledger — asking one question of each:

> Could someone else, on their own machine, run this line and get the same answer?

- **No** → the entry belongs in the local ledger.
- **Yes, but only once some local state exists** (a populated cache, a running
  service) → the entry stays shared and the *check* is the defect. Fix it even
  when nothing moves: with the state absent it fails silently and is signed `✗`.
- **Yes** → nothing to do. A path under `~/` counts as portable when it is a
  tool's conventional directory, such as a package manager's cache (`~/.gradle/`,
  `~/.m2/`, `~/.npm/`), or the ledger's rules name it.

## Moving an entry

Moving an entry is `git mv` and fixing its `# <slug>` header line (lint reports
`HEADER` if you forget).
