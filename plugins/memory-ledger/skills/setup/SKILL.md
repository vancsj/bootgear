---
name: setup
disable-model-invocation: true
description: Set up (or re-check) the memory-ledger — verify python/git/config dependencies, create the local ledger beside the shared one, wire the config file and the host instructions file, add a shared remote, and audit existing entries for ones filed in the wrong ledger. Run it on a new machine, when a root is missing or misconfigured, or when adding the second ledger to an existing single-ledger setup.
---

Set up the memory-ledger for this user.

```
Claude: ledger.py = ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py
Codex: ledger.py = ${PLUGIN_ROOT}/scripts/ledger.py
Claude: instructions file = ~/.claude/CLAUDE.md
Codex: instructions file = ~/.codex/AGENTS.md
```

That placeholder is substituted with the plugin's real location before you read this,
so it resolves wherever the plugin was installed and the skill needs no path of its
own. `ledger.py` below is shorthand for it — there is no `bin/`, so it is not on
`PATH` and the full form is what you type.

**Every step that writes outside the ledger repos needs explicit confirmation, and
you show the exact bytes before writing them.** That covers the config file,
the instructions file, any `.gitignore`, any git remote, and any push. Creating a
ledger repo and its `_about.md` entries is the one thing you may do after a single
yes, because it is a new empty directory and reversible with `rm -rf`.

Work the steps in order and stop at the first hard failure — each one depends on
the one before.

## 1. Dependencies

```
ledger.py doctor
```

Report its table verbatim. `doctor` checks the interpreter version and path, git,
`CLAUDE_CODE_SESSION_ID`, which config file is being read and what it says, both
roots, whether each is a git repo, entry counts, remotes, writability, and whether
the cache is git-ignored.

- **Any `FAIL` stops setup.** Fix the named cause and re-run. Do not proceed to
  step 2 with a failing interpreter or a missing git — everything after it writes
  files.
- `warn` lines are the work this skill exists to do. Carry them into the steps below.
- If python is below the floor `doctor` names, say so and stop. Do not install or
  switch interpreters on the user's behalf.

Then confirm the arithmetic still holds:

```
ledger.py selftest
```

A failing `selftest` means the constants in `ledgerlib/constants.py` and the ones
the skill body states in prose have drifted apart. That is a code bug, not a setup
problem — report it and stop.

## 2. Decide the two roots

```
ledger.py resolve-roots
```

Two ledgers, and which is which is not interchangeable:

| | holds | git remote |
|---|---|---|
| **shared** | facts anyone on the team can re-check: the codebase, the product, the business, third-party contracts | yes, eventually — that is the point of it |
| **local** | facts true of this machine only: shell profile, tool config, personal scratch paths, locally-bound services | never |

**The split is not tidiness, it is irreversibility.** Git history is append-only,
so a machine-local fact committed to the shared ledger cannot be taken back out
once that ledger has a remote — `git rm` removes the file and leaves the history.
Two repos is the only arrangement that survives the shared one being published.

Defaults are `~/.memory-ledger/shared` and `~/.memory-ledger/local` — under a
dot-directory of the tool's own, because a default has to be somewhere that
exists for everybody and `$HOME` is the only directory that qualifies. Ask
before choosing anything else, and take the user's answer: where someone keeps
repos is their filing habit, not something to infer.

An existing ledger with entries in it is treated as **the shared one** — do not
repurpose it as the local ledger, and do not move it. On a first install both
roots are created fresh. `resolve-roots` shows where it actually is; leave it there and record that path in the config rather
than relocating it to match a default.

## 3. Create the local ledger

Only if `doctor` reported it missing. Confirm the path first, then:

```
mkdir -p <local-root> && cd <local-root> && git init -q .
printf '.ledger-cache.json\n' > .gitignore
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

## 4. Wire the config file

Show the user the exact block before writing. `memory.root` keeps naming the
**shared** ledger rather than being renamed: where that key is already set, it
points at the team ledger, and silently re-pointing it at a local repo would
send writes somewhere that is never pushed — a failure with no symptom until
the team notices nothing arrived.

```yaml
memory:
  root: <the shared ledger's path>
  local_root: <the local ledger's path>
```

Written to `~/.memory-ledger/config.yaml`. **`doctor` names the file it actually
read — write to that one**, not to a new file that will lose to it: a
directory-local `.memory-ledger/config.yaml` beats the home one, and `.bootgear/`
is read second at both levels — that is the wider framework this ledger ships
inside, and it is deliberately not required. If the file exists,
show a diff of the `memory:` block rather than the whole file, and preserve
everything else.
`$LEDGER_ROOT` / `$LEDGER_LOCAL_ROOT` override it; `--root` / `--local-root`
override those.

Verify with `ledger.py doctor` — the config row should now name both keys.

## 5. Shared remote (optional, and the user's call)

If `doctor` says the shared ledger has no remote, the team cannot read anything
in it. Ask whether to add one. If yes, take the URL from the user — never guess
it — then:

```
git -C <shared-root> remote add origin <url>
```

**Do not push.** Show the user what the first push would publish
(`git -C <shared-root> log --oneline | wc -l` commits, `ledger.py list --prose | tail -1`
entries) and let them run it or ask you to. A first push of a ledger that has
been accumulating locally is the moment every past filing decision becomes
public, so it gets its own yes.

Before offering to push, work step 7 — publishing a ledger that still holds
machine-local entries is the exact failure the two-ledger split exists to prevent.

## 6. Instructions file

Read the instructions file. If it already has a memory-ledger section, propose an
updated version reflecting two ledgers and show it as a diff. If it has none —
the normal case on a first install — propose a new section instead, and say
plainly that you are adding one rather than editing one. Do not write
until the user accepts. Keep it to the rules the user needs at the moment of
using the ledger; the mechanism lives in the skill, not in the instructions file, and a
second copy there is one that drifts.

The facts a two-ledger setup adds, and nothing more:

- Reads span both ledgers; `--only shared|local` narrows.
- `new` needs `--shared` or `--local`, and there is no default.
- Shared history is append-only. Judge the entry and write it; ask only when you
  genuinely cannot place it — it reads general but leans on this machine, or it
  is about a person.

## 7. Audit what is already filed

```
ledger.py audit
```

That reports **UNPORTABLE** only: Evidence lines containing an absolute path into
somebody's home directory. It is the one thing here a program may assert, because
it is a fact about the string rather than an opinion about the entry. Such a check
fails for every other person for the reason "you are not them", and that failure
gets signed `✗` and counted by the tally as a refutation of the claim.

Answer bodies are immutable, so the fix is a new answer carrying a portable
check: `ledger.py rival <slug> --keep-evidence <aN> --evidence "…"` with a `~`
or `git -C ~/<checkout>` form. It starts unconfirmed and earns its own votes —
correct, since nobody has verified the new check.

**Which ledger an entry belongs in has no heuristic, and you make the call, not
the tool.** Run:

```
ledger.py audit --json [--filter <text>]
```

It dumps every answer with its question, claim and check, uncategorised and
unranked. Work through them — `--filter` to take a folder at a time on a large
ledger — asking one question of each:

> Could someone else, on their own machine, run this line and get the same answer?

- **No** → the entry belongs in the local ledger.
- **Yes, but only once some local state exists** (a populated cache, a running
  service) → the entry stays shared and the *check* is the defect. This is the
  one worth fixing even when nothing moves: when the state is absent the command
  exits non-zero with no output, which the next session cannot tell apart from a
  proven absence, so it signs `✗` and the ledger records a refutation that never
  happened.
- **Yes** → nothing to do, including when the path looks personal. A directory
  under `~/` is very often a convention the whole team shares, which is exactly
  why no pattern is allowed to decide this.

Report your proposed classification to the user and let them confirm before
anything moves. Moving an entry is `git mv` and fixing its `# <slug>` header line
(lint reports `HEADER` if you forget).

## 8. Folder shape

```
ledger.py lint
```

`OVERSIZE` means a folder holds more direct entries than the cap and should be
split; the line names candidate sub-folders and marks the ones that already
exist, which are the cheapest splits because the destination and its `_about.md`
are already there. `REGROUP` is the softer version for folders under the cap.

Both are advisory and neither has a `--fix`. Splitting is a judgement about what
the entries mean, and an automatic move would rewrite slugs that other entries
point at with `[[wikilinks]]`. Offer to do a split; do not perform one unasked.
When you do move entries, fix the `# <slug>` header in each and re-run `lint`.

## 9. Permissions (optional)

**Auto-approve the whole CLI, not a read-only subset.** A ledger maintained by AI
sessions has to be writable by them unattended, and the loop this tool exists for
— resolve, run the `Evidence:` line, sign — is dead if the sign needs a prompt.
An allowlist that covers only reads looks cautious and quietly stops the ledger
accumulating, which is the failure it was meant to prevent.

The writes are safe for a specific reason, not a general one: every subcommand
only ever edits files inside a ledger root, and a ledger root is a git repo, so a
wrong entry is one checkout away from gone. Match on the script name with no
subcommand gate — a new subcommand added later must never be the thing that
reintroduces a prompt.

The one genuinely outward action is `save` pushing to a remote, and that only
exists once the user has deliberately added one.

Ask where their permission rules live before writing any; setups differ, and a
rule added to the wrong place silently never fires. If they have a
permission-hook plugin, that is the mechanism rather than `settings.json`. Check
first whether a rule already covers it — this may well be done already. Show the
exact pattern you propose and let them decide.

## 10. Verify

```
ledger.py doctor
ledger.py lint
ledger.py resolve "<something the user has asked before>"
```

Setup is done when `doctor` shows no failures, both ledgers appear in
`resolve-roots` with entry counts, and a `resolve` returns candidates tagged
`[shared]` / `[local]`. Report those three results and stop — do not go on to
file anything.
