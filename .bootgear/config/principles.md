0. Principles do not conflict. Where two must, the earlier one wins, so list the winner first; the engine resolves a conflict by that order.

## Plugins and skills

- Each plugin installs and works on its own. A Claude plugin that needs another declares it in `dependencies`; Codex has no dependencies, so a Codex skill that calls a sibling states what to do if the sibling is missing. A plugin never assumes a sibling is installed.
- Reference only bootgear's own skills, plugins and tools, host built-ins, and well-known skills or plugins from outside this repo. Never name local personal skills or plugins. The local denylist can carry those names.
- Skills call each other only through the public interface: the skill name, its modes, its handbacks, and its `settings` subcommand. A caller learns a callee's settings by running `settings`, never by reading the callee's files.
- Built-in defaults (state machines, angles, skills) are project-free. Anything specific to one project lives in that project's `.bootgear/config/`.
- Host parity: a behavior shared by the Claude and Codex plugins changes on both hosts in the same change.
- Shared Claude/Codex plugin and skill sections use host-neutral references, terms, paths, and invocation names; host-specific adapters belong in explicit host sections.

## CLI and enforcement

- Every plugin script is a `gear` command: registered under `[commands]` in its plugin's `gear.toml`, runnable as `gear.py <plugin> <command>` as well as on its own, and resolving the caller's relative paths against `GEAR_CALLER_CWD` when it is set.
- CLI output is designed for an LLM reader: minimize its retries and tokens. The last few lines carry all the key information (result, errors, next step), because readers often `tail` the output.
- A skill states the overall workflow, so the model knows where each step leads and can use its judgment. Deterministic detail derivable from validated CLI-owned state or configuration (the next command, legal branches, gates, argument tables) is printed by the CLI at the step where it matters, not repeated in skill prose. Skills keep judgment, safety, orchestration, fallbacks and public handbacks.
- A rule about data or behavior that a script can check is enforced by the script (CLI validation, a gate, a cap), not stated only in prose. Rules about doc content are enforced by the review standard, not by tests or scripts, except mechanical repo hygiene such as `check_content.py`.

## Docs and repo content

- Skill docs (`SKILL.md` and its reference docs) say what to do. No rationale, and absolutely no maintainer rationale. A required action may carry a short why, a clause at most. Detail needed only on some paths goes in focused reference docs that `SKILL.md` points to. Token efficiency matters throughout.
- No development diary anywhere in the repo: comments, docstrings, tests and docs state current behavior and, where needed, a short why, never how it got there (fixes, earlier versions, review findings, incidents). History and design rationale belong in tickets, PR bodies and PR comments.
- `docs/` holds only the up-to-date design, with no details: no history, alternatives, open questions, task lists, or procedure.
- No private information in the repo.

## Run behavior

- When an advisor from a different vendor is available, it takes the refuter or adversarial role by default, unless the user says no.
- Reviews (including spec reviews), refutations and tests cover only what an LLM caller can produce. A claim that needs a made-up or edge-case value, hand-edited state, or an environment the run never uses is not reported.
