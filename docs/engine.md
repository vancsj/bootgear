# engine

`engine` drives one coding task (ticket writing, bug triage, ticket-to-PR, PR
review) from the user's framing to a `succeeded` or `failed` end, unattended
after a single clarification stage. The loop is generic; projects customize it
through configuration and registered skills, never by editing the loop.

## Components

| Component | Role |
|---|---|
| `start` | Explicit-only entry point; hands the request to `clarify`. |
| `clarify` | The only stage that asks the user work questions. Writes the settlement once. |
| `execute` | The autonomous loop: act on the current node, transition, report, check `goal`, close. |
| `recall` | Re-reads settlement, amendments, open todos and current node from disk. Decides nothing. |
| `resolve` | Settles a disagreement from the settled per-domain source of truth, or escalates. |
| `debate` | Multi-party argument for choices `resolve` cannot settle. |
| `task` CLI | `session` (ledger), `state` (state machine), `config` (layered config). The only writer of the ledger. |
| hooks, machines | Three reminder hooks; one built-in state machine per task type. |

## Control flow

```
start -> clarify --(goal confirmed, settlement written)--> execute
                                                         |
     +---------------------- each iteration -------------+
     | recall -> act on node's reminder.do -> transition -> report -> goal check
     |              |
     |              +-> spec / test / review (by public name)
     |              +-> resolve --(no settled source)--> debate
     |              +-> memory-ledger lookup / record
     +--> succeeded | failed  ->  converge prune  ->  session close  ->  final pitch
```

- **clarify** assesses the request, fixes the task type, resolves and validates
  the state machine (built-in, project override, per-run adjustment), shows its
  diagram and every `leave_check` command for approval, and drafts `goal` with
  explicit *succeeded when* and *failed when* conditions. Only after the user
  confirms `goal` does it call `task session init`, once.
- **execute** first runs `task session validate`; a refusal fails the run. Each
  iteration then recalls, resumes any open debate question, does the current
  node's work, and transitions only when a branch destination is reached.
- A run ends `failed` only when the goal is undoable, or when every unit of work
  is exhausted (recorded as a gap in `goal`). A stall is not an outcome.

## Settlement

Written once by `clarify` into the session ledger and never rewritten. It holds:

- `task_type` (one of `ticket-writing`, `bug-triage`, `ticket-to-pr`,
  `pr-review`), `request_assessment`, and the complete resolved `state_machine`;
- `approach` (workflow steps) and `principles` (run-wide constraints);
- `source_of_truth` per domain: scope and outcome, current behavior,
  implementation approach, correctness;
- debate settings: `debate_threshold`, `debate_round_cap` (default 10),
  `convergence_policy` (`unanimous`), `consented_stop_allowed`, custom
  `debate_parties`, and the resolved `debate_party_config` snapshot (party
  `label`/`prompt`/`mechanism`/`enabled` only; model and profile stay in the
  `task config resolve` report);
- `autonomy`: `no_further_questions` and an explicit list of permitted mutations;
- domain overrides `spec_override` / `test_override` / `review_override`, a
  skill name or a `{sub-task-label: skill}` map, and `spec_debate_mode`;
- the run manifest: `spec_skill` / `test_skill` / `review_skill`,
  `debate_roster`, `debate_admission`, `review_fix_mode`;
- `goal` and `session_dir` (written by `init` as the resolved absolute path).

A user-requested change is a `solo` decision `AMENDMENT <field>: <old> -> <new>`;
the latest valid one wins from the next recall. `state_machine` changes only
through `task state amend`; `session_dir` cannot change.

## Resolve and debate

Most decisions are made solo. A decision at or above `debate_threshold`
(reversibility and blast radius by default) goes to `resolve`, which classifies
its domain and applies that domain's settled source. When no source decides
it, `resolve` hands `debate` the decision, domains, full `source_of_truth`,
threshold, `task_type`, `goal` and merged principles.

`debate` argues only choices: factual disputes go back to converge, and a
caller's converge render is briefed as settled fact. It then:

- tags every entry of one question with a stable `[qN]` id, and opens with a
  round 0 on scope, principles and cutoff, closed by `scope-settled`;
- polls the enabled parties in `debate_roster` (default `main-agent`,
  `independent-reviewer`, `adversarial-reviewer`; at most five) using
  `debate_party_config`; round 1 positions are independent, later rounds answer
  each other party. On Claude Code `independent-reviewer` is a fresh sub-agent
  and `adversarial-reviewer` a one-shot `advisor` call asking Codex for
  counterexamples; a party's `mechanism` is `native_subagent` or `advisor`. On
  Codex both reviewers are native subagents and `native_subagent` is the only
  mechanism;
- records unavailable or empty parties as `UNAVAILABLE` / `NO-RESPONSE` and
  owes one retry round per absence episode;
- closes with one of `unanimous_convergence` (only after an angle round that
  changes nothing and keeps `goal`), `consented_stop` (every party votes `CUT`),
  `round_cap`, or `degraded_convergence`. A stuck round calls `resolve` again
  before the cap.

Only skills listed in `debate_admission` may call `debate` directly.

## Delegation

- Each machine node's `reminder.do` names the skill that does its work:
  `spec` for spec nodes, `test` for test and triage nodes, `review` for review
  nodes, `resolve`/`debate` for `*-debate` nodes.
- `execute` invokes domain skills by public name and passes `<run-id>`,
  `<engine-root>`, `<session-dir>`. Each domain skill checks its own
  `*_override` (including amendments) and hands off to a project skill when one
  is set. A missing required domain skill fails the run.
- `review` files every finding through converge; `converge gate`, as the
  review node's `leave_check`, blocks leaving until the slate is complete.
- `memory-ledger:ledger` is asked before investigating an unknown fact and
  after settling a durable one; the decision carries `ledger:<slug>`,
  `ledger-worthy-unrecorded:<why>` or `no-ledger:not-installed`. Its absence
  never blocks `goal`.

## Hooks

All hooks read only `~/.bootgear/session/<session_id>.md`, the ledger's default
directory. A run started with a custom `--dir` gets no hook reminders. No hook
writes the ledger.

| Hook | Fires on | Reads | Emits |
|---|---|---|---|
| session-start recall | session start after compaction (Codex: also startup, resume) | hook `session_id`, `cwd`; the ledger's settlement `goal` and `principles`; user `principles.md` in the host config dir; `.bootgear/config/principles.md` | a recall nudge (Codex: only when `source` is `compact`), the run's `goal` when it is a plain string (a `succeeded`/`failed` mapping is not shown), and merged `[user]`/`[project]`/`[task]` principles; a read failure drops only that part |
| stop reminder | turn stop (Codex: also post-tool fallback) | ledger existence and `## closed`; marker `.<run-id>.stop_reminder_state` | a recall reminder on the 1st, 3rd, 5th … stop while stops keep coming within 30 s of the last reminder; the stops between are silent; silent when `stop_hook_active` |
| state nudge | every tool call by the main agent | `task session read --section state --json`; marker `.<run-id>.state_nudge_state` (flock-guarded) | a transition reminder once the current node has been idle for 5 min, rechecked at most every 60 s; one escalated reminder after 15 more min for the same (node, activity time, transition count); nothing on terminal nodes or closed ledgers |

Host differences: the Claude stop hook adds context and never blocks. The Codex
stop hook returns a one-round `block` continuation, and a `PostToolUse`
fallback reminds when the previous turn never reached `Stop`. The Codex
session-start hook fires on startup, resume and compaction, always hands the
model its host `session_id` to use as the run id, and adds the recall nudge
only after a compaction; Claude skills get the id by substitution.

## State and invariants

All run state is in the session ledger, one file per run keyed by the host
session id ([session-ledger.md](session-ledger.md)); the current node,
transitions and machine amendments are its `## state` and `## machines`
sections ([state-machine.md](state-machine.md)). Hook markers sit beside it.
Project config is under `.bootgear/config/` ([README.md](README.md)).

- No work question after `clarify`, except recovering a lost `session_dir`.
- Skills read the ledger only through `task session` / `task state`, never from
  model memory or by editing the file.
- Engine skills pass `--dir <session-dir>` on every session command. The
  Claude `spec` and `test` skills read the settlement without `--dir`, so
  from the default directory; their Codex copies pass it.
- No mutation outside the settled permitted-mutations list.
- `transition --to succeeded|failed` precedes `close`; `failed` is always a
  legal destination; `close` runs exactly once and is refused while a debate
  question is open.
