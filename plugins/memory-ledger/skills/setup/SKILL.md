---
name: setup
disable-model-invocation: true
description: Set up or check the memory ledger. Use on a new machine, for a missing or invalid root, or to add a ledger.
---

## Inputs and outcomes

Ask for paths, the shared remote URL, and confirmations as needed.
Return one result to the user.

- Complete — `doctor` with no failures and a `rules` row per ledger, roots with counts, and a tagged `resolve` result.
- Stopped — `doctor` failure and cause, the minimum Python version, or `selftest` failure.
- Partial — declined write and the work that remains.

Return proposed audit classifications before moving entries.

## Procedure

Use `<gear> --host <host> memory-ledger ledger <command>` for the commands below.
Run steps in order. Stop at the first hard failure. Open only the reference for the step that needs it.

1. Run `doctor` and report its table verbatim. Carry warnings into setup. Stop on any `FAIL`.
   Run `selftest` before changing files.
2. Run `resolve-roots`. Use shared for team facts and local for machine facts.
   Defaults are `~/.memory-ledger/shared` and `~/.memory-ledger/local`. Confirm any different path.
   If a populated ledger exists or placement is unclear, read [ledger-split.md](references/ledger-split.md).
   On first install, create fresh roots. Seed each repo with `rules --init --only <shared|local>`.
3. If `doctor` reports no local ledger, confirm the path. Create and seed it.

   ```sh
   mkdir -p <local-root> && cd <local-root> && git init -q .
   printf '.ledger-cache.json\n' > .gitignore
   <gear> --host <host> memory-ledger ledger rules --init --only local
   <gear> --host <host> memory-ledger ledger rules --only local
   <gear> --host <host> memory-ledger ledger new <folder>/_about --local --q "What belongs here?" \
     --claim "…" --because "…" --evidence "…"
   ```

   Create only needed folders. Explain in the local charter what makes a fact specific to this machine.
   If the deputy root is missing or lacks Git, confirm its path (default `~/.memory-ledger/deputy`).
   Use the same initialization with the deputy path, `--only deputy`, `--deputy`, and `decisions/_about`.
   Keep the deputy root without a remote.
   Commit the local seed with `save --only local -m "Seed the local ledger"`.

4. For a config change, read [config.md](references/config.md). Preview the exact block.
   Keep `memory.root` on the shared ledger. After approval, write the block and run `doctor`. Check both root keys in the config row.
5. If the shared ledger lacks a remote, offer to add one. Use only the URL the user gives.
   After approval, use `git -C <shared-root> remote add origin <url>`. Wait until after the audit to offer a push.
   For that offer, show the commit count (`git -C <shared-root> log --oneline | wc -l`).
   Show the entry count (`<gear> --host <host> memory-ledger ledger list --prose | tail -1`). Get separate push approval.
6. Read the host instructions. When drafting a section, read [instructions-section.md](references/instructions-section.md).
   Show a diff for an existing section, or say that you propose a new section. Write only after approval.
7. Run `audit`. For findings or JSON classification, read [audit.md](references/audit.md).
   Use `audit --json` and optional `--filter <text>` for details. Decide placement yourself and show it before moving anything.
   Wait for confirmation before moving any entry.
8. Run `lint`. On `OVERSIZE` or `REGROUP`, read [folder-shape.md](references/folder-shape.md).
9. Offer CLI auto-approval. If the user opts in, read [permissions.md](references/permissions.md).
10. Run `doctor`, `lint`, `resolve-roots`, and `resolve "<past user question>"`.
    Check for a `rules` row per ledger, shared and local counts, and matching `[shared]` or `[local]` results.
    Report the three outcomes. Stop after setup.

## Rules

Preview exact bytes and get confirmation for config, host instructions, `.gitignore`, remotes, and pushes.
One approval can cover a new empty ledger repo and its `_about.md` entries.
Get approval before splitting folders. Leave interpreter installation and selection to the user.

## Fallbacks

On `doctor` failure, report the cause. Fix it or wait for correction and rerun `doctor` before proceeding.
If Python is below the reported minimum, report it and stop.
Report a failing `selftest` as a code defect and stop.

## Host mechanics

Get the absolute path from `cli:gear`. Gear reads the session ID from the environment.
Use only the current host's row.

| Host | `<host>` | Instructions | Install missing CLI |
|---|---|---|---|
| Claude Code | `claude` | `~/.claude/CLAUDE.md` | `/plugin install cli@bootgear` |
| Codex | `codex` | `~/.codex/AGENTS.md` | `codex plugin add cli@bootgear` |
