# bootgear design

bootgear is a set of host-native plugins that sit between a coding agent and a
project's own skills, tools and conventions. Framework plugins carry no
project-specific knowledge; each project customizes them through
`.bootgear/config/` and by registering its own skills as overrides.

## Plugins

| Plugin | What it is | Durable state |
|---|---|---|
| `engine` | Autonomous task loop: clarify once, then execute a state machine to `succeeded`/`failed`. | `~/.bootgear/session/<run-id>.md` |
| `converge` | Settles facts behind a claim slate: find, refute, cut by separate agents; computes what is reported. | `~/.bootgear/converge/` |
| `review` | Review domain skill: lens finders plus converge refute/cut, and applying accepted feedback. | via converge |
| `spec` | Requirements domain skill: requirements, design, sign-off, task breakdown. | none |
| `test` | Testing domain skill: write, run, and triage test results. | none |
| `memory-ledger` | Append-only ledger of settled questions, each with a runnable evidence check and per-session signatures. | shared team ledger and a machine-local ledger |
| `advisor` | Pairs Claude Code and Codex CLI through a file mailbox, or makes a one-shot Codex call. | mailbox files |

Dependencies:

```
engine ──needs──> converge, spec, test, review, advisor, memory-ledger   (declared dependencies, Claude Code)
review ──needs──> converge                       (declared dependency)
```

`spec`, `test` and `review` each work standalone. Each first checks the active
engine run's `*_override` settlement field and hands off to a project skill
when one is set.

## Host split

```
plugins/<name>/            one source tree per plugin
  .claude-plugin/          Claude Code manifest (all plugins)
  .codex-plugin/           Codex manifest (memory-ledger, advisor)
codex-plugins/engine/      Codex engine: engine skills + bundled spec, test,
                           review, converge
.claude-plugin/marketplace.json   Claude marketplace: all seven plugins
.agents/plugins/marketplace.json  Codex marketplace: memory-ledger, advisor, engine
```

- `memory-ledger` and `advisor` serve both hosts from one directory with two
  manifests.
- `engine` has a separate Codex package that bundles the skills and code it
  needs, because Codex has no cross-plugin dependency mechanism. Converge and
  review therefore have no separate Codex install.
- Host-specific parts: manifests, hook registrations and output envelopes,
  wrapper paths (`bin/<cmd>` on Claude, `scripts/<cmd>` on Codex), session
  identity delivery, user config directory (`~/.claude` vs `~/.codex`),
  debate-party dispatch (Claude Code: `independent-reviewer` is a sub-agent
  and `adversarial-reviewer` calls `advisor`, and a party mechanism is
  `native_subagent` or `advisor`; Codex: every reviewer is a native subagent
  and `native_subagent` is the only mechanism), and the Codex-only
  `task session recall` command.
- Shared parts: the ledger formats, the `task` and `converge` CLIs apart
  from `session recall`, and the built-in state machines. The converge,
  resolve and review skill bodies above `## Host mechanics` are identical on
  both hosts; the clarify, debate, execute, recall, spec and test bodies, and
  start, carry host-specific wording in their shared sections too.

Parity is kept by two rules. First, a behavior shared by both hosts changes
on both in the same change. Second, drift tests in the Codex engine package
fail when a copy diverges from its Claude source. The tests check that the
converge package, converge reference, review references and `clikit.py`
copies are byte-identical. They check that the converge skill body above
`## Host mechanics` is identical; no other skill body is drift-tested. They
check that the state-nudge hook differs only by an explicit allowlist of
adaptations.

## `gear.py` CLI

`cli/gear.py` routes commands and lifecycle events to plugins. It never imports
plugin code.

- **Registration.** Each plugin declares a `gear.toml` file. The file has a
  `[plugin] name`, `[commands.<name>] exec = [...]`, and optional
  `[reminders.<event>]` with `exec`, `severity` (`reminder` | `gate`), `order`
  and `dedupe`.
- **Discovery.** Discovery reads `plugins/*/gear.toml` and
  `codex-plugins/*/gear.toml` under the repository root. Two registrations with
  the same plugin name are an error.
- **Routing.** `gear.py <plugin> <command> [args]` runs the declared
  executable. The working directory is the plugin root. The environment gets
  `GEAR_CALLER_CWD`, `GEAR_ROOT`, `GEAR_PLUGIN_ROOT`, `GEAR_PLUGIN` and
  `GEAR_COMMAND`. An executable starting with `./` or `../` resolves from the
  plugin root and must stay inside it; any other executable runs as given.
  The child's exit code is returned unchanged.
- **Events.** `gear.py event <event>` runs every matching reminder in
  (`order`, plugin name, `dedupe`) order, skipping repeated `dedupe` keys. A
  failing `gate` reminder stops the run and returns its code. A failing
  `reminder` is reported on stderr and routing continues.
- **Reconcile on route miss.** Reconciliation runs when a plugin or command is
  unknown, or when an event has no reminders. It adds enabled host-installed
  plugin roots from `claude plugin list --json` and `codex plugin list --json`.
  A repository-local registration wins over an installed one with the same
  name. gear.py then retries the original route exactly once. A second miss
  on a plugin or command is a final error; an event that still has no
  reminders exits 0 silently. Reconciliation only reads host metadata. It never
  installs, enables or trusts anything. Host query failures are warnings on
  stderr.
- **Built-ins.** `list` prints commands and `@event` reminders. `doctor`
  prints the root and the plugin names. `reconcile` runs a reconciliation and
  exits 1 when it produced warnings.

The engine, converge and memory-ledger CLIs each carry a copy of one
`clikit.py`. It resolves relative path arguments against `GEAR_CALLER_CWD` and
chooses prose or JSON output from `--json`/`--prose`, then `BOOTGEAR_OUTPUT`.

## Project config: `.bootgear/config/`

Project config files are human-owned and committed with the project. When a
file is absent, the built-in default applies.

| File | Read by | Meaning |
|---|---|---|
| `principles.md` | engine (execute, session-start hook) | Project principles, merged `[user]` → `[project]` → `[task]`; task wins a real conflict. |
| `test-standard.md`, `review-standard.md` | test, review | Rules `## R### [severity]` with `severities:`, `cutoff:`, `iteration_cap:`; checked by `validate_standard.py`. |
| `state-machine-<task_type>.yaml` | engine clarify | Wholly replaces the built-in machine for that task type. |
| `<name>.yaml` (e.g. `debate-parties.yaml`, `converge.yaml`) | `task config resolve`, converge | Layered config: user file in the host config dir, then this project file, then an optional task file. Mappings merge recursively; scalars and lists replace. |

## Docs index

- [engine.md](engine.md): the engine loop, settlement, resolve/debate,
  delegation, hooks.
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
