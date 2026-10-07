---
name: setup
disable-model-invocation: true
description: Set up (or re-check) the memory-ledger — verify python/git/config dependencies, create the local ledger beside the shared one, wire the config file and the host instructions file, add a shared remote, and audit existing entries for ones filed in the wrong ledger. Run it on a new machine, when a root is missing or misconfigured, or when adding the second ledger to an existing single-ledger setup.
---

## When to use, inputs and handback

Set up the memory-ledger for this user: on a new machine, when a root is missing
or misconfigured, or when adding the second ledger to an existing single-ledger
setup.

Inputs: none up front; the user answers paths, the remote URL, and each
confirmation as the steps reach them.

Hand back to the user, from step 10: `doctor` with no failures and a `rules` row
per ledger, both ledgers in `resolve-roots` with entry counts, and a `resolve`
result tagged `[shared]` / `[local]`. Step 7 also hands the user a proposed
classification to confirm before anything moves.

Outcomes:

- completed — the three results above;
- stopped at a `doctor` `FAIL`, with its cause;
- stopped because python is below the floor `doctor` names;
- stopped at a failing `selftest` (a code bug);
- partly done because the user declined a write (config, instructions file,
  remote, permissions) — name what remains.

## Workflow

`doctor` + `selftest` → resolve the roots → create the local ledger (rules,
`_about`, save) → wire the config → shared remote (push only after step 7, with
its own yes) → instructions file → audit filings → folder shape → permissions
(optional) → verify → report the three results and stop.

Work the steps in order and stop at the first hard failure — each one depends on
the one before.

### 1. Dependencies

```
ledger.py doctor
```

Report its table verbatim.

- **Any `FAIL` stops setup** (see "Fallbacks").
- `warn` lines are the work this skill exists to do. Carry them into the steps below.

Then confirm the arithmetic still holds:

```
ledger.py selftest
```

### 2. Decide the two roots

```
ledger.py resolve-roots
```

Read `references/ledger-split.md` before deciding which root is shared and which
is local, and whenever a ledger with entries already exists.

Defaults are `~/.memory-ledger/shared` and `~/.memory-ledger/local`. Ask
before choosing anything else, and take the user's answer.

On a first install both roots are created fresh; once each repo exists, seed its
rule file with `ledger.py rules --init --only <shared|local>`.

### 3. Create the local ledger

Only if `doctor` reported it missing. Confirm the path first, then:

```
mkdir -p <local-root> && cd <local-root> && git init -q .
printf '.ledger-cache.json\n' > .gitignore
```

Seed its rule file, then read it:

```
ledger.py rules --init --only local
ledger.py rules --only local
```

Then seed its charter — a folder with no `_about.md` is an orphan and `lint`
reports it:

```
ledger.py new <folder>/_about --local --q "What belongs here?" \
  --claim "…" --because "…" --evidence "…"
```

Mirror only the top-level folders the user actually needs; an empty ledger with
three speculative folders is three orphan charters. One is usually enough to
start. The local charter should say what makes a fact local — true of this
machine, not re-checkable by a teammate — not merely list topics.

Commit it:

```
ledger.py save --only local -m "Seed the local ledger"
```

### 4. Wire the config file

Show the user the exact block before writing. `memory.root` names the shared
ledger; never re-point it at the local one. Read `references/config.md` when
writing or diffing the config file.

Verify with `ledger.py doctor` — the config row should now name both keys.

### 5. Shared remote (optional, and the user's call)

If `doctor` says the shared ledger has no remote, the team cannot read anything
in it. Ask whether to add one. If yes, take the URL from the user — never guess
it — then:

```
git -C <shared-root> remote add origin <url>
```

**Do not push.** Show the user what the first push would publish
(`git -C <shared-root> log --oneline | wc -l` commits, `ledger.py list --prose | tail -1`
entries) and let them run it or ask you to; the first push gets its own yes.

Before offering to push, work step 7.

### 6. Instructions file

Read the instructions file. If it already has a memory-ledger section, propose an
updated version reflecting two ledgers and show it as a diff. If it has none —
the normal case on a first install — propose a new section instead, and say
plainly that you are adding one rather than editing one. Do not write
until the user accepts. Keep it to the rules the user needs at the moment of
using the ledger. Read `references/instructions-section.md` when drafting the
section.

### 7. Audit what is already filed

```
ledger.py audit
ledger.py audit --json [--filter <text>]
```

**Which ledger an entry belongs in has no heuristic, and you make the call, not
the tool.** Read `references/audit.md` when `audit` reports findings and when
classifying the `audit --json` output.

Report your proposed classification to the user and let them confirm before
anything moves.

### 8. Folder shape

```
ledger.py lint
```

Read `references/folder-shape.md` when `lint` reports `OVERSIZE` or `REGROUP`.

### 9. Permissions (optional)

Offer to auto-approve the ledger CLI. Read `references/permissions.md` only when
the user opts in.

### 10. Verify

```
ledger.py doctor
ledger.py lint
ledger.py resolve "<something the user has asked before>"
```

Setup is done when `doctor` shows no failures and a `rules` row per ledger,
both ledgers appear in `resolve-roots` with entry counts, and a `resolve` returns candidates tagged
`[shared]` / `[local]`. Report those three results and stop — do not go on to
file anything.

## Rules

**Every step that writes outside the ledger repos needs explicit confirmation, and
you show the exact bytes before writing them.** That covers the config file,
the instructions file, any `.gitignore`, any git remote, and any push. Creating a
ledger repo and its `_about.md` entries is the one thing you may do after a single
yes, because it is a new empty directory and reversible with `rm -rf`.

- Never push unasked, and never guess a remote URL.
- Never install or switch interpreters on the user's behalf.
- Never split a folder unasked.

## Fallbacks

- **Any `doctor` `FAIL` stops setup.** Fix the named cause and re-run. Do not
  proceed to step 2 with a failing interpreter or a missing git — everything
  after it writes files.
- If python is below the floor `doctor` names, say so and stop.
- A failing `selftest` is a code bug, not a setup problem: report it and stop.

## Host mechanics

```
Claude: ledger.py = ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py
Codex: ledger.py = ${PLUGIN_ROOT}/scripts/ledger.py
Claude: instructions file = ~/.claude/CLAUDE.md
Codex: instructions file = ~/.codex/AGENTS.md
```

`ledger.py` is not on `PATH`; type the full form.
