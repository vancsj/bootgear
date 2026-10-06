# review-standard

severities: [must, should]
cutoff: must

## R001 [must]
Every skill's `SKILL.md` must state what it hands back and to whom: a
finding, a decision, a report. A skill whose output shape another skill
depends on must make that shape explicit in its own file. A skill that can
end in more than one outcome names every one.

## R002 [must]
A skill doc (`SKILL.md` or a reference doc) must contain instructions, not
rationale, and never maintainer rationale. A required action may carry a
short why, a clause at most. Detail needed only on some paths goes in a
focused reference doc that `SKILL.md` points to; a skill may have several.
Edge-case handling that changes what to do stays in the skill.

## R003 [must]
A `SKILL.md` points to its own reference docs by file name, where the
detail applies and with the condition for reading it. It never names
another skill's file, section or heading, writes another skill's name with
`/` or `$`, or opens with an H1 that repeats its own name.

## R004 [must]
A `SKILL.md` orders its sections: when to invoke, inputs and handback
outcomes; procedure, including the overall workflow; judgment rules and
safety boundaries; fallbacks, such as the owning CLI being unavailable; and
`## Host mechanics` last.

## R005 [must]
A shipped plugin that calls another bootgear plugin's skill or command
within this repo must declare that plugin in `dependencies` (Claude) or
bundle a copy (Codex).

## R006 [must]
A behavior shared by the Claude and Codex plugins is covered by test cases
on both hosts, and a change to that behavior updates both hosts' tests in
the same change. Review compares the two hosts' test cases for the same
behavior.

## R007 [must]
Built-in state machines, angle files and skills must name no skill, path
or convention specific to one project; project specifics go in
`.bootgear/config/`.

## R008 [must]
A script that owns a shared, mutable file (the session ledger, a
project-wide config) must reject structurally invalid input before
writing: validate, exit clearly on a violation, never a partial write.

## R009 [must]
A value substituted into a command's argv (a placeholder, a `--leave-arg`)
must be refused when it could be read as an option (starts with `-`), so an
input can never change which flags the checked program sees.

## R010 [must]
When an AI caller gets the usage wrong (unknown subcommand, missing
required option, value outside a fixed set such as role or kind), the
subcommand must print, alongside the error, one correct example of that
subcommand and a concise list of the other subcommands.
Out of scope: made-up or edge-case values (malformed numbers, odd flag
orders, abbreviations, hand-edited state). A claim that needs one is not
reported.

## R011 [must]
A CLI that finds several problems of the same kind (e.g. bad entries in a
list) must report them in one grouped message naming every offending item,
and list every problem in one run rather than stopping at the first.

## R012 [must]
A CLI's default output format must be concise prose for every stdout sink.
`--json` and `--prose` override the default, followed by
`BOOTGEAR_OUTPUT=json|prose` when no flag is present. A Codex wrapper
script passes prose unless the caller asked for JSON.

## R013 [must]
A subcommand that completes a workflow step must end its output with the
next step — the next command or the decision to make — in one line, and as
a `next` field in JSON. The reminder appears only when it changes what the
caller does next; a skill line that repeats the per-step detail the CLI
prints (command, branches, gates) is removed; the skill's overall workflow
outline stays.

## R014 [must]
A statement of fact about the platform (a hook event, a tool's real
behavior, a CLI flag) in code, docs, skill prose, a commit message or a PR
must be checked against the official docs or the actual CLI output before
it is written down as settled, not asserted from memory.

## R015 [must]
No personal info, company info or local paths in the repo tree.
`quality/check_content.py` flags home and scratchpad paths and denylisted
terms. Personal or company info it cannot match is flagged in review.

## R016 [must]
Code and skills never point to `docs/`. Comments, docstrings, messages and
skill prose state the rule themselves. `quality/check_content.py` flags the
pointers.
