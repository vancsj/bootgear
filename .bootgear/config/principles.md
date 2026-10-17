0. Principles do not conflict. If two principles conflict, the earlier one wins. List the winner first. The engine resolves a conflict in this order.

## Plugins and skills

- Each plugin must install and work on its own. A Claude plugin that needs another plugin declares it in `dependencies`. Codex has no dependencies. A Codex skill that calls a sibling skill states what to do if the sibling is missing. A plugin never assumes that a sibling is installed.
- Reference only these items: the skills, plugins, and tools of bootgear; host built-ins; and well-known skills or plugins from outside this repo. Never name a local personal skill or plugin. The local denylist can carry those names.
- Skills call each other only through the public interface. The public interface is the skill name, its modes, its handbacks, and its `settings` subcommand. A caller learns the settings of a callee when it runs `settings`. It never reads the files of the callee.
- Built-in defaults (state machines, angles, skills) are project-free. Keep anything that is specific to one project in the `.bootgear/config/` of that project.
- Host parity: when the Claude and Codex plugins share a behavior, change it on both hosts in the same change.
- Shared sections of the Claude and Codex plugins and skills use host-neutral references, terms, paths, and invocation names. Put host-specific adapters in explicit host sections.

## CLI and enforcement

- Every plugin script is a `gear` command. Register it under `[commands]` in the `gear.toml` of its plugin. It runs as `gear.py <plugin> <command>` and also on its own. When `GEAR_CALLER_CWD` is set, the script resolves the relative paths of the caller against it.
- Design the CLI output for an LLM reader. Keep the retries and tokens of the reader to a minimum.
- Put the most important information last in the CLI output. The result, the errors, and the next step are the final lines. Readers often use `tail` on the output.
- Write the CLI output, and each `next` line, for the role that sees it: the user, the main agent, or a role agent. Name only commands that this role can run.
- A skill states the overall workflow. The model then knows where each step leads and can use its judgment. The CLI prints deterministic detail at the step where it matters (the next command, legal branches, gates, argument tables). That detail comes from validated CLI-owned state or configuration. Do not repeat it in skill text. Skills keep judgment, safety, orchestration, fallbacks, and public handbacks.
- A script enforces a rule about data or behavior that the script can check (CLI validation, a gate, a cap). Do not state such a rule in text only. The review standard enforces rules about doc content. Tests and scripts do not, except mechanical repo hygiene such as `check_content.py`.

## Docs and repo content

- Skill docs (`SKILL.md` and its reference docs) say what to do. They contain no rationale. They never contain maintainer rationale. A required action can carry a short reason of one clause at most. Put detail that only some paths need in focused reference docs. `SKILL.md` points to them. Token efficiency matters in all docs.
- Do not keep a development diary anywhere in the repo: not in comments, docstrings, tests, or docs. State the current behavior. Where needed, add a short reason. Do not state how the behavior came about (fixes, earlier versions, review findings, incidents). Put history and design rationale in tickets, PR bodies, and PR comments.
- `docs/` holds only the up-to-date design, with no detail. It contains no history, alternatives, open questions, task lists, or procedures.
- Do not put private information in the repo.
- Write spec docs (`requirements.md`, `design.md`, `task.md`) and skill docs (`SKILL.md` and its reference docs) in ASD-STE100 format.

## Run behavior

- If an advisor from a different vendor is available, it takes the refuter or adversarial role by default. The user can say no.
- Reviews (including spec reviews), refutations, and tests cover only what an LLM caller can produce. Do not report a claim that needs a made-up value, an edge-case value, hand-edited state, or an environment that the run never uses.
- The main agent keeps reviewers, refuters, cutters, gap hunters, and other judging roles independent. It gives each role only the context that the task needs: the request, the artifacts, the evidence, the applicable principles and standards, and the role brief. It never gives a role its own conclusions, hypotheses, preferred answers, or the reasoning of another role.
- Give each role that judges or writes the principles and the standards that apply to its task. Name the files in the role brief. The role reads them. They are context, not the conclusions of another role.
