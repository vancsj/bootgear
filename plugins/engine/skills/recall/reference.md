# recall reference

`engine` runs long, single-session tasks. Compaction can rewrite or omit earlier turns, including the `clarify`-stage settlement that later decisions depend on. Context reconstruction is lossy; the session ledger is the authority. See SKILL.md § When to run it.

`SessionStart` with source `compact` is the platform signal that compaction occurred; `PostCompact` cannot add context for the model. The hooks read only `~/.bootgear/session/<session_id>.md`, so a run started with `init --dir <custom-path>` gets no hook reminders. `Stop` only adds a context reminder and does not block stopping. The next turn must read the ledger before trusting the previous turn's state.

`${CLAUDE_SESSION_ID}` is a platform-supplied substitution, not a value carried through model context, so compaction cannot remove it. v1 has one `engine` run per session, which makes `~/.bootgear/session/${CLAUDE_SESSION_ID}.md` the only default-directory candidate.

`recall` cannot discover `session_dir` itself. It needs `--dir` before it can read anything, including the settlement that records `session_dir`. The caller must carry the path through its handoff. `session_dir` is always present in the settlement, so a caller with no path has lost the pointer entirely.

There is no reliable default fallback. `init --dir <custom-path>` is a supported call shape, and that run has no ledger under the default `~/.bootgear/session` directory. A missing default-directory match therefore does not prove that no run exists. The direct user question is the one documented work-question exception because the caller has no remaining source naming the ledger directory. Recovery resumes the existing `init` ledger; it does not create a new `clarify` or `init` run. See SKILL.md § When `<session-dir>` is lost.

A filename match is not proof of ledger identity. `${CLAUDE_SESSION_ID}.md` names the file by run-id alone, and `session.py` never checks whether the same run-id also exists under another directory. Duplicate `init` calls with different `--dir` values are not a normal `clarify` flow, but `session.py` does not forbid them. The settlement's `session_dir` line and user confirmation establish the intended ledger.

The script provides the ledger's consistent read interface. The settlement contains the task type, approach and principles, per-domain sources of truth, debate threshold and convergence policy, autonomy scope, `goal`, and run manifest. `--open-only` returns unchecked todos. `--last N` returns recent decisions and pitches. A no-flag read returns more state than normal iteration needs and is reserved for whole-run audits.

`--last N` is enough for ordinary recent history, but not for debate recovery. Four parties after two rounds may have eight recorded positions. Recovery therefore reads the full `decisions` section, uses the last `[qN]` tag to identify the current question, and then selects each party's latest `[debate]` entry for that question. A party's position cannot identify the question by itself. See SKILL.md § What to read.

Amendments can be arbitrarily far back in the decisions section. Recent-history reads and open-todo reads cannot establish that no amendment exists. Every settlement consumer therefore needs the full decisions scan.

`spec_skill`, `test_skill`, and `review_skill` record the general defaults in the run manifest. The engine invokes `spec:spec`, `test:test`, and `review:review` by plugin-qualified name and dispatches only from `spec_override`, `test_override`, and `review_override`. The parallel `_skill` fields are never runtime dispatch targets. An amendment to `spec_skill`, `test_skill`, or `review_skill` can pass shape validation while having no runtime effect. The override fields are the values that change runtime behavior. See SKILL.md § Amendments override the settlement.

An amendment must name a real settlement field, pass the field's shape/value check, and preserve cross-field invariants. A typo or invented field is not a value to apply. An invalid value cannot replace the last valid value. See SKILL.md § Amendments override the settlement.

`debate_roster` and `debate_parties` form one invariant pair. Extending one requires a matching amendment to the other, but `record-decision` has no transaction spanning two entries. The first entry is therefore rejected until its counterpart exists. Both entries apply together once the pair is complete. An incomplete pair is an unfinished change, not ledger corruption, because the previous fully-valid pair remains usable. See SKILL.md § Amendments override the settlement.

`session_dir` is the ledger's addressing information and cannot be changed safely mid-run. `record-decision` refuses `AMENDMENT session_dir`. A directly written `AMENDMENT session_dir` indicates a broken ledger.

The run manifest describes permitted skills, agents, and capabilities. Compacted summaries can omit a capability without proving that the manifest omits it. Only the freshly read manifest establishes permission. There is no separate manifest flag because the manifest fields are returned under `--section settlement`.

An unlisted debate party or direct-call admission is not permitted. The missing admission is a capability gap to pitch, not permission that can be inferred from earlier context.

A valid `AMENDMENT spec_override`, `AMENDMENT test_override`, or `AMENDMENT review_override` is sufficient authorization for that skill. Requiring the parallel `spec_skill`, `test_skill`, or `review_skill` field to be updated would make the override mechanism unable to change the skill it exists to override. See SKILL.md § Run manifest after compaction.

`recall` only restores state. Decisions belong to `execute`; disagreement handling belongs to `resolve` or `debate`. Nothing changing is a valid result.
