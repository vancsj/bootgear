# review-standard

severities: [must, should]
cutoff: must

## R001 [must]
Each `SKILL.md` must state what it hands back and to whom. The handback can be a finding, a decision, or a report.
If another skill depends on the output shape, the skill must state that shape in its own file.
If a skill can end in more than one outcome, the skill must name each outcome.

## R002 [must]
A skill doc (`SKILL.md` or a reference doc) must contain instructions. It must not contain rationale. It must never contain maintainer rationale.
A required action can have a short reason. The reason must be one clause or less.
If a detail applies on some paths only, put it in a reference doc. `SKILL.md` must point to that reference doc. A skill can have more than one reference doc.
If an edge case changes what to do, keep the instruction in the skill.

## R003 [must]
A `SKILL.md` must point to its own reference docs by file name. The pointer must be where the detail applies. The pointer must give the condition for reading the doc.
A `SKILL.md` must not name the file, section, or heading of another skill.
A `SKILL.md` must not write the name of another skill with `/` or `$`.
A `SKILL.md` must not open with an H1 that repeats its own name.

## R004 [must]
A `SKILL.md` must have its sections in this order:
1. When to invoke, inputs, and handback outcomes.
2. Procedure, with the overall workflow.
3. Judgment rules and safety boundaries.
4. Fallbacks, for example when the owning CLI is not available.
5. `## Host mechanics`, as the last section.

## R005 [must]
A Claude plugin in this repo can call a skill or command of another bootgear plugin. If it does, it must declare that plugin in `dependencies`.
Codex has no dependency mechanism. A Codex skill can call a skill of a sibling plugin without bundling it. If it does, it must state what to do when that skill is missing.

## R006 [must]
Test cases must cover each behavior that the Claude plugins and the Codex plugins share. The test cases must be on both hosts.
When a change affects such a behavior, the same change must update the test cases on both hosts.
The reviewer must compare the test cases of the two hosts for the same behavior.

## R007 [must]
Built-in state machines, angle files, and skills must not name a skill, path, or convention that is specific to one project.
Put project-specific items in `.bootgear/config/`.

## R008 [must]
A script can own a shared file that can change, such as the session ledger or a project-wide config. That script must reject input with an invalid structure before it writes.
The script must validate the input. On a violation, it must exit with a clear message. It must never write part of the data.

## R009 [must]
A command argv can contain a substituted value, such as a placeholder or a `--leave-arg`. The script must refuse the value if it can be read as an option. This is the case when the value starts with `-`.
An input then cannot change the flags that the checked program sees.

## R010 [must]
An AI caller can use a subcommand incorrectly. The usage errors are: an unknown subcommand, a missing required option, or a value outside a fixed set (for example a role or a kind).
In these cases, the subcommand must print the error. It must also print one correct example of that subcommand and a short list of the other subcommands.
Out of scope: made-up values and edge-case values. Examples are malformed numbers, odd flag orders, abbreviations, and hand-edited state. Do not report a claim that needs one of these.

## R011 [must]
A CLI can find more than one problem of the same kind, for example bad entries in a list. The CLI must report all of them in one grouped message. The message must name each offending item.
The CLI must list every problem in one run. It must not stop at the first problem.

## R012 [must]
The default output format of a CLI must be short prose for each stdout sink.
`--json` and `--prose` override the default. If no flag is present, `BOOTGEAR_OUTPUT=json|prose` applies.
A Codex wrapper script must pass prose, unless the caller asked for JSON.

## R013 [must]
A subcommand that completes a workflow step must end its output with the next step. The next step is the next command or the decision to make. Write it on one line. In JSON, write it as a `next` field.
You must write the `next` line for the role that the subcommand is designed for: the user, the main agent, or a role agent. The `next` line must name only a step that this role can do. The script does not have to detect who runs it.
If the next step belongs to another role, the `next` line must tell the caller to hand that step to that role. Example: a subcommand for a role agent tells the role agent to report the next step to the main agent. It does not give the main agent a command.
Show the reminder only when it changes what the caller does next.
Remove a skill line that repeats the per-step detail that the CLI prints (command, branches, gates).
Keep the overall workflow outline in the skill.

## R014 [must]
Code, docs, skill prose, commit messages, and PRs can state a fact about the platform. Examples are a hook event, the real behavior of a tool, or a CLI flag.
Before you write such a fact as settled, check it against the official docs or the actual CLI output. Do not state it from memory.

## R015 [must]
The repo tree must not contain personal info, company info, or local paths.
`quality/check_content.py` flags home paths, scratchpad paths, and denylisted terms.
The reviewer must flag personal or company info that the script cannot match.

## R016 [must]
Code and skills must never point to `docs/`.
Comments, docstrings, messages, and skill prose must state the rule themselves.
`quality/check_content.py` flags the pointers.
