# bootgear

> An agent harness framework — the gear between the LLM motor and your skills, tools, configs, and docs.

## What is bootgear?

bootgear is a curated collection of general-purpose, extensible **skills**, **agents**, and **hooks** for coding-agent workflows.

Think of an LLM as a motor: raw power, no direction. A motor alone doesn't move anything — it needs a transmission that converts spin into motion, mounted on a chassis you can actually load your cargo onto. bootgear is that layer. It sits between the model and your assets, routes work through an opinionated loop, and lets you bolt on your own gear where it matters.

```
your skills / tools / configs / docs      <- what makes each project different
                  ^
                  |   bootgear: routing, invocation, governance
                  v
                   LLM                    <- the motor
```

## Design principles

**General by design.**
Framework-level skills and agents hold no project-specific knowledge. They are reusable across projects, languages, and teams.

**The framework drives (IoC).**
Inspired by Spring Boot: you don't call the framework, the framework calls you. Register your skills, agents, and hooks — bootgear owns the lifecycle and invokes them at the right points in the loop.

**Opinionated defaults, explicit overrides.**
Every component works out of the box with sensible defaults, and every component declares its customization points. Tune preferences, swap steps, or extend behavior without forking the skill.

**Your workflow stays yours.**
bootgear puts you inside a productive loop, not inside a black box. You always see which gear is engaged and can steer at any point.

## How is this different from [superpowers](https://github.com/obra/superpowers)?

superpowers proved that a strong, opinionated skill set makes agents dramatically more capable. But its opinions are take-it-or-leave-it: if a skill's assumptions don't fit your project or taste, your options are to live with it or fork it.

bootgear keeps the opinionated core but treats customizability as a first-class feature. Same idea — harness over raw model power — with the control handed back to you.

| | superpowers | bootgear |
|---|---|---|
| Opinionated defaults | Yes | Yes |
| Extension/customization points | No | Explicit, per component |
| Project-specific knowledge | Baked in where needed | None by design |

## Platforms

| Platform | Status |
|---|---|
| Claude Code | **engine, converge, spec, test, review, advisor, and memory-ledger**, as plugins — see Install |
| opencode | Not shipped |
| Codex | **memory-ledger, engine, and advisor**, as plugins — see Install |

Skill/hook formats differ across platforms; bootgear aims to keep one conceptual gear set with platform-specific adapters.

## Architecture

Bootgear ships **host-native plugins**. The engine provides durable task
execution, state-machine governance, recall and recovery, and project-level
workflow configuration; project-specific skills and conventions stay in the
repository and are invoked natively by the host.

```
project skills / hooks / config
        │
        ▼
engine workflow + session ledger
        │
        ▼
Claude Code / Codex CLI plugins
```

Plugins are authored and loaded in their host's native format.

## Repository layout

```
bootgear/
├── plugins/         # gear that ships today; most plugins are Claude Code-only,
│                    # some (e.g. memory-ledger, advisor) also ship a Codex CLI
│                    # manifest from the same source directory
├── codex-plugins/   # gear that ships as Codex CLI-only plugins, with no
│                    # Claude Code counterpart
├── .agents/         # Codex marketplace
├── .bootgear/       # this repo's own bootgear config; the same place any project puts its config
├── cli/             # gear.py: runs any plugin command as `gear.py <plugin> <command>`
├── docs/            # current design
└── quality/         # repository validation and quality checks
```

A plugin that serves both hosts ships from one source directory under `plugins/`,
with a `.claude-plugin/plugin.json` and a `.codex-plugin/plugin.json` side by
side (see `memory-ledger`, `advisor`). `codex-plugins/` holds plugins with no
Claude Code counterpart at all (e.g. `engine`'s Codex-CLI port). Both retain
platform-native manifests, hooks, wrappers, and invocation contracts.
`converge` is the exception to both: it ships as a Claude Code plugin from
`plugins/converge` and is bundled into the Codex `engine` rather than carrying
its own `.codex-plugin`, so there is no separate Codex install.

## Install

Prerequisites: `git`, Python 3.11 or later, and [`uv`](https://docs.astral.sh/uv/)
(`engine` and `converge` run through it). `engine`'s debate on Claude Code
asks Codex through `advisor`, so it needs the Codex CLI installed and signed in.
`advisor`'s mailbox pairing runs on macOS only.

Each plugin installs on its own — you do not need the rest of bootgear. The table's
"installs … with it" notes describe Claude Code's declared dependencies; Codex CLI packages
differ (see [Codex CLI](#codex-cli)).

```
/plugin marketplace add vancsj/bootgear
/plugin install memory-ledger@bootgear
```

| gear | what it does |
|---|---|
| [memory-ledger](plugins/memory-ledger) | a ledger of settled questions, where confidence counts independent verifications instead of asserting itself |
| [engine](plugins/engine) | an autonomous task-execution loop — start a run with `/engine:start` (Codex: `$engine:start`); installs `converge`, `spec`, `test`, `review`, `advisor` and `memory-ledger` with it |
| [converge](plugins/converge) | settles the facts behind a findings slate: find, refute, and cut each claim with separate agents, then compute what is reported; installed automatically with `engine` and `review` |
| [review](plugins/review) | PR review: lens finders and a gap hunt, with every finding settled through `converge`; installs `converge` with it |
| [spec](plugins/spec) | requirements and design for `engine`'s ticket-writing and ticket-to-pr runs; works on its own too |
| [test](plugins/test) | test writing, running, and failure triage for `engine`'s bug-triage and ticket-to-pr runs; works on its own too |
| [advisor](plugins/advisor) | pairs Claude Code and Codex CLI through a shared mailbox, or makes a one-shot call to Codex |

### Codex CLI

[advisor](plugins/advisor) ships from one source directory serving both hosts
(the same pattern as `memory-ledger`): a `.claude-plugin/plugin.json` and a
`.codex-plugin/plugin.json` side by side, so it's registered in both
`.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json`.
Codex CLI's plugin mechanism only ever sees plugins listed in the latter.
Install:

```
codex plugin marketplace add vancsj/bootgear
codex plugin add memory-ledger@bootgear
codex plugin add advisor@bootgear
codex plugin add engine@bootgear
```

On Codex, start an engine run with `$engine:start`, and set up the ledger with
`$memory-ledger:setup`.

`advisor` pairs a Codex CLI session with a Claude Code session through a
shared mailbox, or answers a one-shot direct call — either host can run
either side of the pair. `channel.py` is co-located under the one shared
skill directory, so no runtime path resolution between hosts is needed.

## Status

bootgear ships as native Claude Code and Codex CLI plugins. `cli/gear.py`
routes each plugin's commands (`gear.py <plugin> <command>`).

## License

[Apache License 2.0](LICENSE). Contributions require a DCO sign-off — see
[CONTRIBUTING.md](CONTRIBUTING.md).
