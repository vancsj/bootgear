# memory-ledger

memory-ledger is an append-only store of settled questions. Each entry is keyed by the
question it answers, and each answer carries the checks that re-establish it. AI sessions
re-run those checks and sign the result; confidence is computed from the signatures. It is
a cache for facts that are expensive to derive, not a note store.

## Components

| Part | Role |
|---|---|
| `plugins/memory-ledger/scripts/ledger.py` | CLI: `resolve`, `show`, `list`, `new`, `rival`, `add-evidence`, `sign`, `refute`, `assert`, `promote`, `set-repo`, `hash`, `lint`, `save`, `audit`, `doctor`, `resolve-roots`, `selftest` |
| `scripts/ledgerlib/` | `config` (roots), `context`/`identity` (host, signer), `model` (hash, confidence, refs), `store` (parsing, identity cache), `scoring` (resolver), `read`, `write`, `gates` (write-time checks), `lint`, `gitops` (save), `audit`, `doctor`, `nudge` |
| `scripts/ledger` | Codex wrapper; defaults output to prose |
| `skills/ledger/` | Usage skill; `references/mechanics.md` (commands, formats), `references/judgement.md` (choosing, verifying, contesting) |
| `skills/setup/` | Checks dependencies, creates both ledgers, wires the config; asks before any write outside the ledgers |
| `hooks/` | `nudge.py` (Claude) and `codex_nudge.py` (Codex), thin adapters over `ledgerlib.nudge` |

## Roots and config

The **shared** ledger has a remote and reaches the team; the **local** ledger never leaves
the machine. They are separate git repositories, not folders in one, because history is
append-only: a local fact committed to a repo that later gains a remote cannot be removed.

- **Roots.** First set wins, per ledger: `--root`/`--local-root`, then
  `$LEDGER_ROOT`/`$LEDGER_LOCAL_ROOT`, then `memory.root`/`memory.local_root` in the config
  file, then `~/.memory-ledger/shared` and `~/.memory-ledger/local`. Relative paths resolve
  from the caller's cwd.
- **Config file.** The first that exists of `./.memory-ledger/config.yaml`,
  `./.bootgear/config.yaml`, `~/.memory-ledger/config.yaml`, `~/.bootgear/config.yaml`. Flat
  YAML, one level of nesting; it may also set `repo` and `ref`.
- **Invariants.** The two roots must differ, or the CLI refuses. A root missing on disk is
  skipped. When both ledgers exist, `new` requires exactly one of `--shared` or `--local`,
  with no default; with only one ledger, it writes there. Slug commands look in
  both ledgers, and a slug in both is an error (`TWO-HOMES`), never a first match.
- **Capability status** (`doctor --json`): `configured` when the shared root is a git repo,
  the local root is absent or a git repo, and the roots differ; `unconfigured` when there is
  no config file and no root exists; `broken` otherwise.

## Entry model

An entry is one Markdown file, `<root>/<folder>/<slug>.md`. Every folder has an
`_about.md`, an ordinary entry answering "What belongs here?".

```markdown
# example/area/topic
Q: Does the example project ship an example config file?
alt_terms: sample config

## a1 · yes, example.cfg at the root       conf 0.49 · checked <date>
Because: the example loader reads it.
Evidence: test -f example.cfg
    ✓ aaaa1111    <date>  h=abc123  e=1  (author)
    ✓ codex:bbbb2222  <date>  h=abc123  e=1
    ✗ cccc3333    <date>  h=abc123  e=1
    > example.cfg: No such file or directory
```

- **Identity** is the question. The resolver scores only `Q:`, the slug and `alt_terms`;
  `USE:` redirects to a canonical slug.
- **Answer** `aN`: a one-sentence claim, `Because:`, one or more `Evidence:` lines (a shell
  command or `<Tool>: <query>`), optional `Repo:` (the checkout the checks run in), optional
  `Ref:` (a branch, for code-scoped claims), optional `Asserted:`. The body is immutable and
  ids are never reused (max + 1), because answers cite each other by id.
- **Hash.** `h=` is the first 6 hex characters of sha256 over claim, `Because:` and `Ref:`.
  Editing any of them voids every signature on the answer; restoring the bytes restores
  them. `Evidence:`, `Repo:` and `Asserted:` are outside it, so `add-evidence` voids nothing;
  `lint` reports a replaced check as `EVIDENCE-REWRITTEN`. `e=N` is how many checks the
  answer had when signed, and a `>` block is that run's recorded output.
- **Signer** is the AI session, never the human. Claude: the first segment of
  `CLAUDE_CODE_SESSION_ID`, overridable by `--as`. Codex: exactly `codex:<session_id>`; `--as`
  may be omitted, and an unsafe session id or a conflicting `--as` is rejected. Standalone or gear: `--as`, else
  `--session-id` or `$MEMORY_LEDGER_SESSION_ID`. The host is `--host`, else
  `$MEMORY_LEDGER_HOST`, else Claude when `CLAUDE_CODE_SESSION_ID` is set, else standalone.
- **Write gates.** `new` and `rival` run each shell check (180 s timeout) and report the
  result without refusing on it, then record the author's `✓ (author)`. They refuse a claim
  over 40 words and (on `new`) a blatant restatement of an existing question. `new`,
  `rival`, `add-evidence` and `promote` refuse, on any write not to the local ledger, an
  evidence path that is absolute or `~`-relative, except fixed system paths (`/usr/`,
  `/etc/`, …) and tool caches (`~/.cache/`, `~/.m2/`, …). `--force` / `--anyway` override.

## Confidence

```
conf = min(round((1 − 0.70 × 0.55^yes) × 0.80^no, 2), 0.99)
```

- `yes` counts valid `✓` from sessions other than the author; `no` counts valid `✗`. Valid
  means the `h=` matches the current body.
- One session, one vote per body: signing again from the live session rewrites its own
  line, and `refute <signer>` casts an opposing vote with its output, never striking one.
- Anchors: author alone 0.30, one independent `✓` 0.61, two 0.79. Bands (unconfirmed
  < 0.45 ≤ confirmed ≤ 0.75 < well-confirmed) describe corroboration; nothing is hidden.
- `✓` and `✗` on one body is `SPLIT`: the check depends on something it does not name. It
  is a finding about the check, not a veto.
- `1.00` comes only from `assert`, a human's ruling on a question no check can settle. It
  writes `Asserted: <git user.name> <date> — <why>` and pins the header while signatures
  keep counting; `--clear` lifts it.
- The `conf`/`checked` header is a cache that `sign`/`refute` rewrite and `lint --fix`
  recomputes.

## Rivals and scope

- **Rival.** An answer that contradicts, narrows or corrects another is a new answer on the
  same question, starting at 0.30 with no inherited votes. `--keep-evidence aN` copies the
  disputed answer's checks. Nothing supersedes anything; the reader runs the checks.
- **Branch claims.** `Ref:` state is `live`, `merged`, `missing` or `unknown`, measured
  against the mainline: `origin/HEAD`, else the first of `origin/main`, `origin/master`,
  `main`, `master`; `ref`/`$LEDGER_REF` override. `promote` re-scopes a landed branch claim
  by adding a mainline answer and leaves the original intact.

## Retrieval

`resolve` lowercases, drops stopwords (negations included, since polarity belongs to the
answer) and stems the query, then scores entries by rarity-weighted query coverage. Output
order: `EXACT` (stops there), `UNKNOWN` terms, candidate `FOLDER` blocks cut at the largest
score gap (at least two kept), then a `MINT` slug. Scoring reads `.ledger-cache.json` in each
root: identity only (slug, question, tokens), validated by a filesystem stamp rather than
git, replaced atomically, never committed.

## Save and commit

`save` owns all git work. It runs `lint --fix`, then commits each ledger separately (never
one commit spanning both; a failure in one does not skip the other). It stages every entry
with `git add -f` so no ignore rule can hide one, plus `add -u` for deletions. After
committing it fails if any `.md` on disk is missing from the commit or the cache was
committed. With a remote it pushes; on rejection it runs `pull --rebase` and retries once,
otherwise the commit stays local. No branches, no force-push. It warns when the shared
ledger has no remote or carries unportable evidence paths.

## Nudge hook

A `PostToolUse` hook fires on every tool call and `ledgerlib.nudge.evaluate` decides. If
capability status is not `configured`, it emits `memory-ledger: <status>`. A Bash command
invoking `ledger`/`ledger.py`, or the `ledger` skill, records `ledger-used` silently. Any
other call emits one fixed, never-escalating reminder to check and record in the ledger,
unless a nudge fired in the last 300 s; a ledger use clears that cooldown. State is per
session in `~/.memory-ledger/.nudge-state/<session>.last`, under a `flock`.

## Host differences

| | Claude | Codex |
|---|---|---|
| Entry point | `${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py` | `${PLUGIN_ROOT}/scripts/ledger` (prose output by default) |
| Signer | first segment of `CLAUDE_CODE_SESSION_ID`, or `--as` | `codex:<id>` from `--host codex --session-id <id>`; `--as`, if given, must equal it |
| Manifest | `.claude-plugin`, `hooks/hooks.json` | `.codex-plugin`, `hooks/codex-hooks.json` |
| Hook status output | `additionalContext` | `systemMessage`; the hook first validates the session id and stays silent if it is invalid |

`gear.toml` also exposes the CLI as the gear command `ledger`. Ledger files, formats and
computations are identical on every host.
