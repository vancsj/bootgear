# Ledger judgement

## What the tool refuses

- Editing an answer body or its `aN` id. There is no `amend`: other answers cite ids, and signatures sign bytes.
- A claim over 40 words, unless `--force`.
- A re-`sign` that would change nothing — same verdict, same depth. Correcting your own vote is allowed; refreshing its date alone is not.
- `refute` against your own signature — `sign` again instead.
- Signing an answer with no `Because:` or `Evidence:` — there is no hash to sign.
- A `new` whose question scores `0.85` or above against an existing one, unless `--anyway`.
- Removing or editing a committed `Evidence:` line — `lint` reports `EVIDENCE-REWRITTEN`. Checks are append-only; `add-evidence` adds one, and to *replace* one, write a rival with `--keep-evidence`.
- Promoting a branch answer whose check names the branch outright — write a `rival` instead.
- An `assert` with no `--why`, or on an answer already asserted — `--clear` first.

---

# Judgement

Everything below needs a decision from you, or names a trap that generalises past its example.

## Which ledger

Each ledger's `WHAT-BELONGS.txt` (`ledger.py rules`) is the authority on what it holds; the points below are the defaults it starts from and lose to it.

1. **Shared holds what stays true; local holds what drifts.** Shared: anything a teammate could re-check about the codebase, the product, the business, a third-party contract. Local: true of this machine only — shell profile, tool config, scratch paths, locally-bound services — or true but perishable — a count, a cohort size, a snapshot of moving state. Never an open-ended count in shared: the next session re-runs the check, gets a different number, signs `✗`, and the tally records a refutation that never happened.
2. **The test is whether the claim pins to a ref**: mainline code, a locked dependency version, an applied migration, a *closed* date window. Production counts, PR and branch status, a runtime flag, an issue tracker pin to nothing.
3. **Mutability is not the test.** A pinned dependency moves only when someone bumps it; what rots is the vendor's live state, not their code.
4. **Three shapes rot fastest** — someone is actively working to make each false:
   - in-flight work state (which PRs are open, what a branch holds, what blocks what);
   - "not yet" negatives under active development — a negative following from a *design decision* is durable, one meaning "nobody has done it" is a countdown;
   - open-ended production counts.
5. **Date the claim, never the question** — "as of 2026-09-02, …". A dated answer becomes historical rather than wrong; a dated question never matches the session asking in a later month.
6. **Prefer the question that outlives the number.** Where a tally has a reusable method inside it, the method is the shared entry and the number is the local one.
7. **Judge the destination yourself and write.** A codebase, product or business fact goes to shared without ceremony. Ask the human only when you cannot place it — it reads general but leans on this machine, or it is about a person. Shared is append-only and published under their name.
8. **Read both ledgers even when you write to one.** `--only` narrows and is never the default: a read covering one ledger lets you mint a question the other already answers.
9. **Which ledger an entry belongs in has no heuristic.** `audit` asserts one thing only — an `Evidence:` line hardcoding a home path. `audit --json` dumps every answer that has a check, skipping `_about` entries, and you ask of each: could someone else, on their own machine, run this and get the same answer?

## Retrieving

1. **Read `(n/m terms)` before acting on a score** — `n` is how many of your query's terms *that entry* matched, `m` how many you asked. `1.00 (2/5 terms)` and `1.00 (5/5 terms)` are not the same claim. The separate `UNKNOWN` line names the terms no entry contains at all.
2. **A fuzzy hit is a decision, not an answer**: same question → run its checks and sign or rival; different question → take the `MINT` slug.
3. **Pass `--in <folder>` only deliberately, and never infer it from the question** — a wrong guess searches a folder that cannot hold the answer.
4. **Never invent a slug the resolver did not emit.** Read with `show`, or `list` for the whole ledger.

## Writing an entry

1. **Run the resolver first.** `new` runs it for you and prints the closest questions; read the entry it names before overriding with `--anyway`.
2. **One falsifiable sentence per claim.** A single ✓/✗ cannot express "first half wrong, second half right"; seven findings are seven entries.
3. **Correct a wrong claim by adding a rival**, never by editing.
4. **Spend real effort on `--alt-terms`** — it is the anti-duplicate mechanism: the phrasings someone would type not knowing this entry exists, including symbol names, error text, and the question backwards. Extra terms only ever help.
5. **Keep claim vocabulary out of `alt_terms`.** Only the question is searched; making content findable there stops the resolver answering "has this been asked?".
6. **Name a slug for its question, not its answer.** Negation words are stopwords, so `no-nested-transactions` reduces to `nested-transactions`.
7. **Choose the folder yourself** — `MINT` gives the leaf only. Read the folder's `_about.md`.
8. **Splitting an oversized folder is a judgement about meaning**, which is why `OVERSIZE` and `REGROUP` have no `--fix`. Propose the split, then `git mv` and fix each `# <slug>` header.
9. **Never put secrets or erasable data in a ledger.** History is append-only.
10. **This is not general note-taking.** A ledger entry is a settled question whose answers each carry a check another session can re-run.

```
ledger.py new tech/stack/package-manager --shared --q "…" --claim "…" --because "…" --evidence "…"
ledger.py rival <slug> --claim "…" --because "…" --evidence "…"        # appends the next aN
ledger.py new <folder>/_about --local --q "What belongs here?" …       # new folder, same commit
```

## Writing a check

1. **Write it for the repo the question is about, without naming it.** Whoever asks next is already working there.
2. **Prefer a check that *discovers* its subject over one that names it**, and guard a check needing live state so it exits loudly. Silence reads as refutation.
3. **Cover the clause that carries the decision.** A two-part claim checked on one half passes, and the untested half gains a corroboration nothing looked at.
4. **Never chain checks with `;`** — a chain exits 0 on a partial run, so a failure in the middle reads as success. Repeat `--evidence` instead.
5. **Anchor any `;`-chained line** with `cd <repo> &&` or `git -C <repo>`: with the failing part anywhere but last, the chain exits 0.
6. **Never hardcode a path into a home directory**; use a repo-relative path, or `--repo <name>` to name the checkout. A tool's conventional directory, such as a package manager's cache (`~/.gradle/`, `~/.m2/`, `~/.npm/`), is the exception: it has the same shape on every machine with that tool. `/Users/someone/…` fails for everyone else and is tallied as a refutation; `~/<checkout>` assumes every checkout sits in the same place.
7. **Use `-E` with `git grep`.** Basic regex makes `'fun a|fun b'` match nothing and exit 1 — indistinguishable from a proven absence.
8. **A branch claim's check must name the ref** (`git grep … origin/<branch> …`), or a session on mainline records a `✗` that is only a ref mismatch.

## Verifying, on every retrieve you act on

1. Read the answer you intend to use.
2. Run **every** one of its `Evidence:` lines with your tools — a signature covers all of them. A connector check runs with the tool it names, not a shell.
3. **Zoom out — cover broader than the checks.** They were chosen because they pass, so re-running them confirms the *checks*, never the *claim*. Name the observation that would be false if the claim were wrong, and run that.
4. Record the verdict:
   - pass → `ledger.py sign <slug> a1`
   - fail → `ledger.py sign <slug> a1 --fail --output "<what it actually printed>"`
   - contradicting a standing signature → `ledger.py refute <slug> a1 <their-id> --output "<yours>"`
5. **Leave the zoom-out behind.** If the broader check is worth re-running, `add-evidence` it — that voids no signature. A claim that turned out narrower than its checks suggested still needs a rival.
6. Commit in the ledger in the same working stretch. No batching.

### Checks that under-determine their claim

Each asserts something narrower than the claim above it.

1. **A grep that matches nothing.** Asserts the pattern is absent, not the thing. Check other spellings, a dynamically built name, config rather than code, the call site rather than the definition.
2. **A grep that matches something.** Asserts a string exists, not that it runs. Check whether the hit is reachable at all — dead code, a test fixture, a comment, a branch behind a disabled flag.
3. **A path-scoped search** (`-- <dir>`, one module, one repo). Asserts about that path only. Widen to the whole tree, then to sibling services that deploy the same thing.
4. **A count.** Asserts what the query returned, not that the query captured the population. Check what it silently excludes — an inner join, soft deletes, a status filter, an open-ended window.
5. **A definition read.** A default, a config key, an annotation asserts what is *declared*. Check the effective value: overrides, profiles, environment, anything set at startup.
6. **A doc or vendor page.** Asserts what the page says, not what the system does. Check the runtime.
7. **A check that exits 0 with no output.** Cannot tell "passed" from "matched nothing" from "never ran". Make it fail once, deliberately, before trusting a pass.

### Signing

1. **The signatory is the AI session, never the human** — `sign` takes it from `CLAUDE_CODE_SESSION_ID`. Never type a name, sign as the user, or invent members: one human across a hundred sessions is one vote.
2. **A subagent is not a second session.** It inherits its parent's session id and framing, so report the delegated verdict up and let the parent sign once. Never `--as` a made-up id.
3. **Changed your mind, or ran checks added after you signed?** Run them yourself, then `sign` again — it rewrites *your own* line in place: verdict, `e=`, date, and any recorded output. Still one session, one vote, so `conf` moves only if your verdict flipped. It refuses a re-sign that would change nothing, and refuses outright if your recorded output has drifted away from your signature. **`sign` never runs the checks for you** — it records your verdict, so a re-sign claims you re-ran the current set, and `e=` is the number of checks that existed, never proof any of them passed. `refute` is for other sessions' signatures and is barred against your own.
4. **Do sign an earlier session's seed** — re-deriving the check without that session's context is the consensus forming.
5. **`refute` casts an opposing vote; it never strikes one.** The other vote stands and the tally decides.
6. **Pass `--output` on any `✗`**, with what the run actually printed. It is the only thing that lets the next session tell a real refutation from a wrong branch or a missing build.
7. **Read `e=N` as verification depth.** An early signer never saw the checks appended later.
8. **A present but broken check is not refused.** That call is yours, and it is worth a rival.

## Reading confidence

1. **`conf` is an indicator, never a gate.** Nothing is hidden at any level; the checks decide.
2. **A `✗` is a vote, never a veto.** A lone bad run — wrong branch, missing build, no network — must not erase a well-corroborated answer.
3. **A `SPLIT`** (✓ and ✗ on one body) **is a finding about the check, not the claim.** Answer it with a rival whose check names what the split turned on, not with an edit.
4. **`1.00` is a human's ruling, never a tally.** Counted confidence stops at `0.99` however many sessions agree. A `conf 1.00 · asserted` header carries an `Asserted:` line saying who ruled and what settles it, and `show` still prints what the signatures count beside it.

## Asserting

`assert` pins an answer at `1.00` on a human's ruling; `--clear` hands it back to the tally. Command syntax: `references/mechanics.md`.

1. **Only for a question no check can settle** — an intent, a decision, a system that no longer exists to be queried. Current behaviour has a check, and the check decides.
2. **It is the human's ruling, not yours.** Ask before asserting. `--by` defaults to `git config user.name`; this is the one place the ledger records a person rather than a session.
3. **A pin is not a veto.** Signatures keep accumulating underneath it, and `lint` reports `ASSERTED-CONTESTED` for as long as a `✗` stands.
4. **Never hand-edit a header to 1.00.** `lint` reports `ASSERT-UNRECORDED` for one carrying no `Asserted:` line.

## When answers disagree

An answer that contradicts, narrows or corrects an existing one is a **rival**, written with
`rival` like any other. `rival` prints the existing answers and their checks before it writes.

1. **State the difference in the claim itself**, citing the answer it argues with by id — `a1 counts only the first of three paths`.
2. **It starts at `0.30 unconfirmed`, inheriting no votes**, and the answer it corrects keeps what it earned.
3. **Carry forward the checks you still agree with** via `--keep-evidence a1`, but expect new signatures — a check re-homed onto a different claim is a different assertion.
4. **There is no `Superseded-by:` and no ordering between answers.** Which answer is right is a judgement the reader makes by running the checks.
5. **Promote when `lint` reports `REF-LANDED`**; the new mainline answer earns its own votes. `REF-GONE` means abandoned — drop the entry.
6. **Invert a proven-false answer with the two commands, never a header.** `sign <slug> aN --fail --output "<what it printed>"` records the disproof under the original; `rival` adds the flipped claim carrying the proof as its own `Evidence:`. The flipped answer starts at `0.30` and earns its votes like any other.
