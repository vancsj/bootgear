0. Project principles must be general, clear, concise, invariant, and unambiguous. They state properties that always hold or an agreed direction. Prefer ASD-STE100 wording.
1. If two principles conflict, the earlier one wins. List the winner first. The engine resolves a conflict in this order.

## Plugins and skills

- Each plugin must install and work on its own. A Claude plugin that needs another plugin declares it in `dependencies`. Codex has no dependencies. A Codex skill that calls a sibling skill states what to do if the sibling is missing. A plugin never assumes that a sibling is installed.
- Reference only these items. They are the skills, plugins and tools of bootgear, host built-ins, and well-known skills or plugins from outside this repo. Never reference a local personal skill or plugin. The local denylist can carry those names.
- Skills use only the public interface of other skills. It includes the skill name, modes, handbacks, and `settings`. Run `settings` to learn the callee's settings. Keep callee file reads out of skills. Skill prose must avoid references to and dependencies on the callee's files, internals, or script flags. A CLI may print a driver step that calls another plugin's script.
- Built-in defaults (state machines, angles, skills) are project-free. Keep anything that is specific to one project in the `.bootgear/config/` of that project.
- Host parity: when the Claude and Codex plugins share a behavior, change it on both hosts in the same change.
- No back compatibility. Do not keep an old version, mode, or format for compatibility or dogfooding. Replace the mechanism in place, delete its paths and tests, and hand-rewrite the run's own old ledgers to the new format.
- Version bump on every plugin change. A commit that touches a file in a plugin's directory bumps that plugin's `.claude-plugin/plugin.json` `version`, in the same commit or the next one. Do not limit this to contract changes.
- Shared sections of the Claude and Codex plugins and skills use host-neutral references, terms, paths, and invocation names. Put host-specific adapters in explicit host sections.

## CLI and enforcement

- The shared CLI plugin owns Gear, the uv runtime, clikit and automatic plugin discovery. Both hosts use the same plugin source.
- Provider plugins keep their command implementations and expose them through gear.toml. Gear discovers them without a fixed built-in plugin list.
- Skills get the Gear executable path from the shared CLI plugin's thin public skill. They then call registered Gear commands.
- Script calls and CLI-printed next commands use Gear. Caller skills do not encode another plugin's installation paths.
- Gear prepares the shared interpreter and import paths. Provider scripts use the shared clikit implementation.
- Reuse a uv environment when Python and locked dependencies match. Plugin version alone never creates an environment.
- Only explicit setup installs or changes dependencies. Normal commands and hooks use the prepared runtime.
- Hooks discover Gear and call their registered handler. If Gear is missing, they emit setup guidance.
- Claude declares plugin dependencies. Codex setup installs missing sibling plugins explicitly.

- Every plugin script is a Gear command. Register it under `[commands]` in its plugin's `gear.toml`. Call it as `gear <plugin> <command>`. When `GEAR_CALLER_CWD` is set, the script resolves the caller's relative paths against it.
- Shared host context: Gear takes the host from `--host`, else `BOOTGEAR_HOST`, else the host whose session variable is set. With both variables set, it takes the nearest `claude` or `codex` ancestor process, else `claude`. Gear sets `BOOTGEAR_HOST` to that host. Gear commands read the session id from `BOOTGEAR_SESSION_ID`, then `CLAUDE_CODE_SESSION_ID` or `CODEX_SESSION_ID` for the declared host, then the other one. Explicit host and session arguments take precedence. Standalone calls can supply the same context explicitly.
- Bootgear supports Claude Code and Codex only without the host sandbox. Bootgear code has no fallback for an operation that a sandbox denies. A denied operation is an environment fault.
- Design the CLI output for an LLM reader. Minimize total task tokens and retries, including instruction reads, discovery, and recovery. Keep enough CLI guidance to complete the task, and keep skill docs brief.
- Put the most important information last in the CLI output. The result, the errors, and the next step are the final lines. Readers often use `tail` on the output.
- Write the CLI output for the role that sees it: the user, the main agent, or a role agent. Write each `next` line for the same role. Name only commands that this role can run.
- Skills describe the overall workflow and keep judgment, safety, orchestration, fallbacks, and public handbacks. The CLI controls normal steps and transitions. It prints deterministic detail from validated CLI-owned state or configuration as needed. Callers can force a transition past workflow gates with a recorded reason. Role checks and ledger validation still apply. Skills may give short examples of common, stable commands. Keep CLI-owned, state-dependent details out of skill text.
- A script enforces a rule about data or behavior that the script can check (CLI validation, a gate, a cap). Do not state such a rule in text only. The review standard enforces rules about doc content. Tests and scripts do not, except mechanical repo hygiene such as `check_content.py`.
- Apply Occam's razor. Use the least restrictive rule that addresses the observed problem.
- Support valid inputs and common mistakes from an LLM caller. Report clear errors and leave the workflow state ready for a corrected call. Invented or very rare cases do not require defensive handling.

## Docs and repo content

- Skill docs (`SKILL.md` and its reference docs) say what to do. They contain no rationale. They never contain maintainer rationale. A required action can carry a short reason of one clause at most. Put detail that only some paths need in focused reference docs. `SKILL.md` points to them. Token efficiency matters in all docs.
- Do not keep a development diary anywhere in the repo: not in comments, docstrings, tests, or docs. State the current behavior. Where needed, add a short reason. Do not state how the behavior came about (fixes, earlier versions, review findings, incidents). Put history and design rationale in tickets, PR bodies, and PR comments.
- `docs/` holds only the up-to-date design, with no detail. It contains no history, alternatives, open questions, task lists, or procedures.
- Do not put private information in the repo.
- Write spec docs (`requirements.md`, `design.md`, `task.md`) and skill docs (`SKILL.md` and its reference docs) in ASD-STE100 format.

## Run behavior

- If an advisor from a different vendor is available, it takes the refuter or adversarial role by default. The user can say no.
- Reviews (including spec reviews), refutations, and tests cover valid inputs and common mistakes from an LLM caller. Exclude invented or very rare cases, hand-edited state, and environments that the run never uses.
- Read-only roles may read and write memory-ledger entries. Their other write limits still apply.
- The main agent keeps reviewers, refuters, cutters, gap hunters, and other judging roles independent. It gives each role only the context that the task needs. That context is: the request, the artifacts, the evidence, the applicable principles and standards, and the role brief. It never gives a role its own conclusions, hypotheses, preferred answers, or the reasoning of another role.
- Give each judging or writing role the principles and standards that apply to its task. Name the files in the role brief. The role reads them. They are context, not the conclusions of another role.
- A claim slate is immutable. Each review or triage visit uses a new slate. To keep a claim from an earlier slate, copy it to the new slate. Never change a claim or its events on an earlier slate.

## Artefacts and review

- Decide the artefact at clarify stage.
- An artefact is what a task produces and refines, such as spec docs, code, or a triage report. An artefact is optional. When a task has one, it is the main object of review.
- A run is authoring when it produces or changes an artefact. It is reviewing when it does not. A state machine lists possible paths, and the path a run takes decides its kind. For example, a `change-review` run is authoring when it passes through `fix`, and reviewing otherwise.
- Converge checks the factual claims about an artefact over several passes, until the facts hold. A factual claim is right or wrong.
- A question with no right answer is a judgement. Decide it with `resolve`, `debate`, or the deputy. Converge does not decide judgements.
- Refine the artefact after each factual pass and after each judgement decision.
- Set a threshold for each loop, so the loop ends. A threshold can change during a run. Work that a loop cannot close becomes a follow-up.
- A solution has two parts. Converge checks its facts. The choice of solution is a judgement.
