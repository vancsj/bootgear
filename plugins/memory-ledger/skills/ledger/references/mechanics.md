# Ledger mechanics

Command flags, git/save behaviour, ledger roots resolution, folder layout, the
entry file format, and the resolver's output shape. Reference: nothing here
needs a decision from you. Read it before your first `ledger.py` call this
session, or whenever a flag, path or output shape needs checking.

## Commands

```
Claude: `ledger.py = ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py`
Codex: `ledger.py = ${PLUGIN_ROOT}/scripts/ledger`

ledger.py resolve "<claim or question>" [--in <folder>] [--only shared|local]
ledger.py show <slug>                          # answers, conf, evidence, sigs, recorded output
ledger.py list [--filter <text>] [--all] [--only …]
ledger.py new <slug> (--shared|--local) --q --claim --because --evidence [--evidence …] [--ref <branch>] [--alt-terms]
ledger.py rival <slug> --claim --because --evidence [--evidence …] [--keep-evidence aN] [--ref <branch>]
ledger.py add-evidence <slug> <aN> --evidence "…"   # append a check
ledger.py promote <slug> <aN> [--to <ref>]     # branch claim → mainline, as a NEW answer
ledger.py set-repo <slug> <aN> <repo>          # name the checkout its checks run in
ledger.py sign <slug> <aN> [--fail --output "<failing output>"]
ledger.py refute <slug> <aN> <signer-id> --output "<your contradicting run>"
ledger.py assert <slug> <aN> --why "<what settles it>" [--by NAME] | --clear
ledger.py hash <slug> <aN>                     # h= for an answer as it stands
ledger.py lint [--fix] [--only …]              # drift, voided sigs, folder shape, collisions
ledger.py save [-m "…"] [--no-push] [--only …] # lint --fix, then one commit per ledger
ledger.py audit [--json] [--filter <text>]     # Evidence lines hardcoding a home path
ledger.py doctor                               # python, git, config, both roots
ledger.py resolve-roots [--json]               # where each ledger is, and whether it exists yet
ledger.py doctor --json                         # structured configured/unconfigured/broken status
ledger.py selftest                             # pin the conf/hash constants
```

- Identity, hashes and confidence are computed, never eyeballed. `show` computes `conf` live and marks signatures voided by a later edit; never hand-edit `conf` or `checked`, `lint --fix` recomputes them.
- `sign` computes `h=`, writes your sig line, recomputes `conf`, and on `--fail` records the output beneath your signature as a `>` block. It records your verdict; it does not check the claim. Called again by a session that already signed, it **rewrites that session's own line** — verdict, `e=`, date — and takes any stale `>` block with it, rather than appending a second vote.
- `new`, `rival` and `add-evidence` run each `Evidence:` line you pass and report on each, never refusing on the result. `new` and `rival` also record your own `✓ … (author)`, excluded from `conf`.
- `assert` pins an answer at `1.00` on a human's ruling and writes an `Asserted:` line naming who and why; `--clear` lifts it. The line is outside `h=`, so neither voids a signature.
- `promote` adds an answer scoped to the repo's mainline — from `origin/HEAD`, overridable by `ref:` / `$LEDGER_REF` / `--to` — and leaves the branch answer and its signatures intact.
- A connector check is written `<Tool>: <what to ask it>`. It is not run and not judged, so name the tool and its inputs in full.
- `resolve`, `list`, `lint`, `audit` and `save` take `--only shared|local`. Every slug-addressed command — `show`, `hash`, `sign`, `refute`, `promote`, `rival`, `set-repo`, `add-evidence` — looks the slug up across both ledgers and takes no ledger flag.
- `new` requires `--shared` or `--local`; there is no default.
- `doctor` first when anything is off.
- Output mode: prose is the default for every stdout sink; `--json` or `--prose` on any command overrides, followed by `BOOTGEAR_OUTPUT=json|prose` when no flag is present. The Codex `scripts/ledger` wrapper defaults to prose. `--json` on `doctor`, `audit` and `resolve-roots` keeps its own shape and exit codes. Refusals follow the selected mode and name the command's example and the other commands.

## Git

`save` for all git here; never run git by hand.

- It runs `lint --fix`, stages every entry, commits, and pushes if a remote exists. `-m` overrides the message, `--no-push` commits only.
- One commit per ledger, never one spanning both; a failure in one does not skip the other. `--only` saves one.
- Direct push only — no branches, no PRs, no force-push. On a rejected push it rebases and retries once, then leaves the commit safe locally.
- Never commit `.ledger-cache.json`.

## Roots

- Each ledger is a git repo. `resolve-roots` prints where yours are; missing or unset → `/memory-ledger:setup`.
- Defaults: `~/.memory-ledger/shared` and `~/.memory-ledger/local`.
- Roots come from, each beating the last: `--root` / `--local-root` → `$LEDGER_ROOT` / `$LEDGER_LOCAL_ROOT` → `memory.root` / `memory.local_root` in the config file → the defaults. Relative paths resolve from the caller context, including `GEAR_CALLER_CWD` on the gear route.
- Codex writes pass `--host codex --session-id <exact-id>` and `--as codex:<exact-id>`. The exact hyphenated session ID is retained; a missing, malformed, or conflicting identity is rejected before a write.
- The config file is the first that exists: `./.memory-ledger/config.yaml` → `./.bootgear/config.yaml` → `~/.memory-ledger/config.yaml` → `~/.bootgear/config.yaml`.
- Shared has a remote and reaches the team; local never does.
- The two must be separate repos; the tool refuses if both roots resolve to one path.

## Layout

```
<ledger root>/business/ tech/ process/
  └── <slug>.md                 # entry: Q + answers + sig lines + recorded output
  └── _about.md                 # what belongs in this folder — an entry like any other
```

- Every directory has an `_about.md`, written in the commit that creates the folder: `Q: What belongs here?`, competing visions as rival answers. A local and a shared `tech/_about` are not a collision.
- No `_meta/`. The schema and constants are this skill and `ledgerlib/constants.py`; a copy inside the ledger drifts.
- One slug, one home. A slug in both ledgers is an error, not a first-match: the lookup refuses and `lint` reports `TWO-HOMES`.
- `OVERSIZE` fires past 50 direct entries; `REGROUP` from 25 up to the cap, where three or more entries share a word. Both advisory, no `--fix`.

## Entry format

```markdown
# tech/stack/package-manager
Q: Which package manager does this repo use?

## a1 · pnpm for all installs              conf 0.63 · checked 2026-03-05
Because: workspaces performance; ~10x smaller installs than npm.
Evidence: cat pnpm-workspace.yaml
    ✓ bob   2026-03-02  h=7f3a92  e=1
    ✓ alice 2026-03-04  h=7f3a92  e=1
    ✗ carol 2026-03-05  h=7f3a92  e=2
    > cat: pnpm-workspace.yaml: No such file or directory
```

One question, one or more answers. Each answer: claim + `Because:` + one or more `Evidence:` +
optional `Repo:` + optional `Ref:` + sig lines, each with its recorded output beneath it.

- `h=` covers claim + `Because:` + `Ref:`. Editing any of those voids every signature on that answer; `Evidence:` and `Repo:` are outside it. `lint` reports voided sigs, and restoring the bytes restores them.
- `e=N` is how many checks the answer carried when that signature was cast. `show` marks a shallower one `[ran 1 of 3 checks]`.
- Link entries as `[[tech/<folder>/<slug>]]` — the full slug, anywhere in a claim or `Because:` line.
- `Ref:` is for a code-scoped claim only, and is the branch name, never a SHA — a name survives rebases. `new`/`rival` fill `Repo:` in from the current checkout whenever `--ref` is given; set it later with `set-repo`, never by hand. Without a `Repo:` the ref resolves in whatever repo the reader stands in, and when it resolves nowhere `lint` says `REF-UNSCOPED` and declines to advise deletion.
- `conf`: `<0.45` unconfirmed · `0.45–0.75` confirmed · `>0.75` well-confirmed. Anchors: author alone `0.30` · one independent ✓ `0.61` · two `0.79` · 2✓+1✗ `0.63` · 6✓+1✗ `0.78`. Counted confidence caps at `0.99`; `1.00` is only ever `asserted`.
- `Asserted: <who> <date> — <why>` records a human's ruling. Outside `h=`, like `Evidence:` and `Repo:`.

## Resolver output

Run it identically for read and write. It produces identity; you paste it verbatim.

```
ledger.py resolve "which package manager do we install with"
```

Order: `EXACT` (slug hit, following any `USE:` redirect) → `UNKNOWN` (query terms in no entry) →
`FOLDER` blocks of candidates, the top one's answers inline → `MINT`. An `EXACT` hit stops there
and prints nothing else; otherwise `MINT` prints even alongside candidates. The candidate list is
cut at the largest score gap and always keeps at least two.
