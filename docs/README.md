# bootgear design

bootgear is a set of host-native plugins that sit between a coding agent and a
project's own skills, tools and conventions. Framework plugins carry no
project-specific knowledge; each project customizes them through
`.bootgear/config/` and by registering its own skills as overrides.

## Glossary

| Term | Meaning |
|---|---|
| Gear | Shared CLI that discovers and runs registered plugin commands. |
| run | One engine task from `clarify` to `succeeded` or `failed`, recorded in its own session ledger. |
| settlement | What `clarify` settles with the user before a run starts: task type, approach, principles, sources of truth, autonomy, `goal`, and the state machine. Written once. |
| `goal` | The settlement's done condition: when the run has `succeeded`, and when it has `failed` because the task cannot be done. |
| pitch | A progress report to the user, recorded in the session ledger. |
| slate | One set of claims that `converge` tests together: find, attack, cut. Each claim ends `survived`, `disputed`, `unverified` or `killed`, with a separate `cut` field. |
| lens | A review perspective, such as `correctness` or `security`, with its own finder brief. |
| find angle | One specific question a finder asks under a lens. |

## Plugins

| Plugin | What it is | Durable state |
|---|---|---|
| `cli` | Shared Gear CLI, plugin discovery and Python runtime setup. | shared runtime under `~/.bootgear/runtimes/`; host plugin store under `~/.bootgear/host-plugins/` |
| `engine` | Autonomous task loop: clarify once, then execute a state machine to `succeeded`/`failed`. | `~/.bootgear/session/<run-id>.md` |
| `converge` | Settles facts behind a claim slate: find, attack, cut by separate agents; computes which claims are findings. | `~/.bootgear/converge/` |
| `review` | Review domain skill: lens finders plus converge attack and cut, and applying accepted feedback. | via converge |
| `spec` | Requirements domain skill: requirements, design, sign-off, task breakdown. | none |
| `test` | Testing domain skill: write, run, and triage test results. | none |
| `memory-ledger` | Append-only ledger of settled questions, each with a runnable evidence check and per-session signatures. | shared team ledger, a machine-local ledger and a deputy ledger |
| `advisor` | Pairs Claude Code and Codex CLI through a file mailbox, or sends a one-shot prompt to either CLI. | mailbox files |
| `deputy` | Answers a judgement question from the user's recorded decisions, or escalates it; hooks remind the AI to ask it and to record the user's answer. | deputy ledger |

Dependencies:

```
Each Claude plugin that uses Gear declares `cli` as a dependency.
engine ──needs──> cli, converge, spec, test, review, advisor, memory-ledger, deputy
review ──needs──> cli, converge, deputy
converge ──needs──> cli, memory-ledger, advisor, deputy
spec ──needs──> cli, converge, review
test ──needs──> cli
advisor ──needs──> cli
memory-ledger ──needs──> cli
deputy ──needs──> cli, memory-ledger
```

`spec`, `test` and `review` each work standalone. Each first checks the active
engine run's `*_override` settlement field and hands off to a project skill
when one is set.

## Shared sources and host mechanics

```text
plugins/<name>/
  .claude-plugin/plugin.json       Claude manifest and dependency declarations
  .codex-plugin/plugin.json        Codex manifest
  skills/                          shared instructions with explicit host sections
  src/                             shared providers
.claude-plugin/marketplace.json     Claude marketplace
.agents/plugins/marketplace.json    Codex marketplace
```

Both marketplaces load the same directory for every plugin.
Native manifests use the same release version for each plugin.
Claude resolves declared dependencies. Explicit Codex setup reads those declarations and installs missing peers.
Normal commands and hooks never install dependencies.

Host mechanics retain native hook registrations, output envelopes, identity delivery, configuration paths, and advisor dispatch.
Claude debate advisors use direct Codex calls. Claude Converge advisors use Codex listeners.
Codex uses separate Claude listeners for debate and Converge.
Both hosts accept `native_subagent` and `advisor` mechanisms.
Shared session recall, state machines, CLI routing, and provider code have one implementation.
Shared provider suites run for each host. Native adapter tests retain each host's payload and lifecycle contracts.

## Gear CLI

`plugins/cli/bin/gear` routes commands and lifecycle events to plugins. It
discovers registrations from `gear.toml` and does not use a fixed plugin list.

- **Registration.** Each plugin declares a `gear.toml` file. The file has a
  `[plugin] name`, `[commands.<name>] exec = [...]`, and optional
  `[reminders.<event>]` with `exec`, `severity` (`reminder` | `gate`), `order`
  and `dedupe`.
- **Discovery.** Discovery reads `plugins/*/gear.toml` under the repository root. Two registrations with
  the same plugin name are an error.
- **Routing.** `<gear> --host <host> <plugin> <command> [args]` runs the declared
  executable. Gear preserves caller paths and provider roots. The child's exit
  code is returned unchanged.
- **Host.** Gear takes the host from `--host`, else `BOOTGEAR_HOST`, else the
  host whose session variable is set. With both variables set, it takes the
  nearest `claude` or `codex` ancestor process, else `claude`.
- **Runtime.** Python commands use the prepared shared interpreter and imports.
  `cli:setup` prepares selected plugins and their dependencies. It records the managed Python path.
  Codex setup installs missing peers through the native CLI and refreshes enabled installed roots.
- **Events.** `<gear> --host <host> event <event>` runs every matching reminder in
  (`order`, plugin name, `dedupe`) order, skipping repeated `dedupe` keys. A
  failing `gate` reminder stops the run and returns its code. A failing
  `reminder` is reported on stderr and routing continues.
- **Reconciliation.** Gear reads the prepared inventory to route installed plugins.
  A repository-local registration wins over an installed one with the same name.
  Outside hooks, `gear reconcile` refreshes the inventory through the host CLI.
  A host session must have an inventory from `SessionStart` before it can refresh it.
- **Host plugin store.** The store lives under `host-plugins` in the Bootgear data directory.
  Gear and the hook loaders share entries by host, host profile, and session id.
  Setup and explicit reconcile outside a host session prepare an entry for the project directory.
- **Session-start refresh.** The first startup or fork hook builds the session inventory.
  Resume, clear, and compact refresh it. Routine hooks read the prepared inventory.
  After setup, restart open sessions to pick up plugin changes.
  Codex runs the hook after the user grants trust.
- **Built-ins.** `list` prints commands and `@event` reminders. `doctor`
  prints the root and the plugin names. `reconcile` runs a reconciliation and
  exits 1 when it produced warnings.
- **Host sandbox.** Bootgear supports Claude Code and Codex only without the
  host sandbox. Bootgear code has no fallback for an operation that a sandbox
  denies. A denied operation is an environment fault.

The shared CLI owns `clikit`. Provider commands import it through Gear's
prepared runtime and resolve caller-relative paths through `GEAR_CALLER_CWD`.

## Project config: `.bootgear/config/`

Project config files are human-owned and committed with the project. When a
file is absent, the built-in default applies.

| File | Read by | Meaning |
|---|---|---|
| `principles.md` | engine (clarify, execute, session-start hook), spec; named in the role briefs of spec-review, review, test, and execute sub-agents | Project principles, merged `[user]` → `[project]` → `[task]`; task wins a real conflict. |
| `test-standard.md`, `review-standard.md` | test, review, spec, engine (clarify, execute after a compaction, session-start hook lists rule IDs); named in the role briefs of spec-review, review, test, debate, and execute sub-agents | Rules `## R### [severity]` with `severities:`, `cutoff:`, `iteration_cap:`; checked by `validate_standard.py`. |
| `state-machine-<task_type>.yaml` | engine clarify | Wholly replaces the built-in machine for that task type. |
| `<name>.yaml` (e.g. `debate-parties.yaml`, `converge-seats.yaml`, `converge.yaml`) | `task config resolve`, converge | Layered config: user file in the host config dir, then this project file, then an optional task file. Mappings merge recursively; scalars and lists replace. `converge.yaml` rule lists follow "Config layers" in [converge.md](converge.md). |

## Docs index

- [decisions.md](decisions.md): how facts, choices, the deputy, resolve and
  debate fit together.
- [engine.md](engine.md): the engine loop, settlement, resolve/debate,
  delegation, hooks.
- [artefact-review.md](artefact-review.md): general output review, rubric configuration and evidence gates.
- [state-machine.md](state-machine.md): machine schema, override tiers,
  transitions and the leave gate.
- [session-ledger.md](session-ledger.md): the per-run ledger file and the
  `task session` commands.
- [converge.md](converge.md): the claims ledger, angles, cutoff and gate.
- [memory-ledger.md](memory-ledger.md): the durable cross-session fact
  ledger.
- [advisor.md](advisor.md): the Claude–Codex mailbox and one-shot calls.
- [skill-authoring.md](skill-authoring.md): rules for writing skills in this
  repository.
