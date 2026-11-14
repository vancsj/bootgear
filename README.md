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
bootgear puts you inside a productive loop, not inside a black box. You always see which gear is engaged and can amend the run or stop it at any point.

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
| Claude Code | **cli, engine, converge, spec, test, review, advisor, memory-ledger, and deputy**, as plugins |
| opencode | Not shipped |
| Codex | The same plugins, skills, and command sources, with native manifests and hooks |

Both marketplaces load the same `plugins/<name>` directories.
Each shared skill selects its host mechanics explicitly.

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

## Use case: software engineering

Bootgear can connect spec authoring, implementation and review in one engineering workflow.
The user supplies intent, resolves escalated questions and grants required permissions.
Project context supplies the domain rules and conventions.

![Software-engineering workflow with the user, engine, memory-ledger, converge and deputy](assets/software-engineering-use-case.png)

Spec review checks the design. Code review checks the implementation, tests and contracts.
Shared support works across these stages:

| Gear | Role |
|---|---|
| [memory-ledger](plugins/memory-ledger) | Reuse settled answers after rerunning their evidence. Record durable findings. |
| [converge](plugins/converge) | Check factual claims through independent attacks, finder replies and verdicts. |
| [deputy](plugins/deputy) | Advise on judgment questions from recorded user decisions, or escalate them to the user. |

Factual agreement and deputy advice do not grant action permission.
The [SVG version](assets/software-engineering-use-case.svg) keeps the diagram editable.

## Repository layout

```
bootgear/
├── plugins/         # one authored source directory per plugin, with both native manifests
├── .claude-plugin/  # Claude Code marketplace
├── .agents/         # Codex marketplace
├── .bootgear/       # project workflow configuration
├── docs/            # current design
└── quality/         # repository validation and quality checks
```

Each plugin has `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`.
Both hosts use its shared skills and providers. Hook registrations retain each host's native contract.

## Install

Prerequisites: `git`, Python 3.12, and [`uv`](https://docs.astral.sh/uv/).
Python plugins use the shared CLI runtime. An engine run's advisor roles (a debate
reviewer, or the converge refuter and gap hunter) go to the other vendor's host through
`advisor`: on Claude Code they need the Codex CLI installed and signed in; on Codex, a
Claude Code session listening through `advisor`.

Each plugin installs on its own — you do not need the rest of bootgear. The table's
"installs … with it" notes describe Claude Code's declared dependencies.
Codex uses explicit setup to install the same dependencies (see [Codex CLI](#codex-cli)).

After installation, call `cli:setup` once to prepare the shared runtime.
Call `cli:gear` to get the literal Gear path.

```
/plugin marketplace add vancsj/bootgear
/plugin install memory-ledger@bootgear
```

| gear | what it does |
|---|---|
| [cli](plugins/cli) | owns Gear, the shared Python runtime, clikit, discovery, and the public Gear-path skill |
| [memory-ledger](plugins/memory-ledger) | a ledger of settled questions, where confidence counts independent verifications instead of asserting itself |
| [engine](plugins/engine) | an autonomous task-execution loop — start a run with `/engine:start` (Codex: `$engine:start`); installs `converge`, `spec`, `test`, `review`, `advisor` and `memory-ledger` with it |
| [converge](plugins/converge) | settles the facts behind a findings slate: find, refute, and cut each claim with separate agents, then compute what is reported; installs `memory-ledger` and `advisor` with it, and is installed automatically with `engine` and `review` |
| [review](plugins/review) | PR review: lens finders and a gap hunt, with every finding settled through `converge`; installs `converge` with it |
| [spec](plugins/spec) | requirements and design for `engine`'s design-doc and ticket-to-pr runs. It works on its own too. |
| [test](plugins/test) | test writing, running, and failure triage for `engine`'s triage and ticket-to-pr runs; works on its own too |
| [advisor](plugins/advisor) | pairs Claude Code and Codex CLI through a shared mailbox, or makes a one-shot call to Codex |
| [deputy](plugins/deputy) | answers a judgement question from your recorded decisions, or escalates it to you, and reminds the AI to ask it before it asks you; installs `memory-ledger` with it on Claude Code, and needs `memory-ledger` installed on Codex |

### Codex CLI

Both marketplaces contain every plugin and point to the same source directories.
Codex does not install transitive dependencies. Install the target and CLI first:

```sh
codex plugin marketplace add vancsj/bootgear
codex plugin add cli@bootgear
codex plugin add engine@bootgear
```

Call `cli:setup` with target `engine`. It runs `<gear> --host codex cli setup --plugin engine`.
Setup reads the installed target's declared dependencies, installs missing peers, and verifies their enabled installed roots.
Choose another installed plugin as the target for a standalone workflow.
Normal commands and hooks never install dependencies.

Start an engine run with `$engine:start`. Set up the ledger with `$memory-ledger:setup`.
Trust plugin hooks through the native `/hooks` interface when Codex requests it.

`advisor` pairs a Codex session with a Claude Code listener through a shared mailbox.
Claude Code can also send direct requests to Codex.

## Status

bootgear ships as native Claude Code and Codex CLI plugins. The shared CLI
plugin routes registered commands through Gear: `<gear> --host <host> <plugin>
<command> [arguments]`.

## License

[Apache License 2.0](LICENSE). Contributions require a DCO sign-off — see
[CONTRIBUTING.md](CONTRIBUTING.md).
