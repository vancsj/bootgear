# review-standard

severities: [must, should]
cutoff: must

## R001 [must]
Every skill's `SKILL.md` must state what it hands back and to whom — a
finding, a decision, a report — not just what it does internally. A skill
whose output shape another skill depends on (e.g. `test`/`review` feeding
`execute`'s goal-check) must make that shape explicit in its own file.

## R002 [must]
A script that owns a shared, mutable file (the session ledger, a
project-wide config) must reject structurally invalid input before
writing: validate, exit clearly on a violation, never a partial write (see
`session.py`'s `_check_structure`).

## R003 [must]
A design decision recorded anywhere in this repo (a doc, a skill's prose, a
commit message) that states a fact about the platform (a hook event, a
tool's real behavior, a CLI flag) must be checked against the official docs
or the actual CLI output before it is written down as settled, not asserted
from memory.

## R004 [should]
A skill that can end in more than one distinct outcome (converged vs.
capped vs. degraded; clean vs. blocked vs. capped) should name every
outcome explicitly in its own file.

## R005 [must]
A `SKILL.md` must contain instructions — how to work — not design
rationale. Justification for why a rule exists goes in a reference doc the
skill points to; a skill may point to more than one. Edge-case handling
that changes what to actually do stays inline; only pure justification
moves out.

## R006 [must]
A file the Codex plugin carries as a copy of a Claude-side source (bundled
code, a synced skill or reference) must be covered by a drift test that
fails when the copy and its source differ — see `test_bundle_drift.py`.

## R007 [must]
A shipped plugin that calls another bootgear plugin's skill or command
within this repo must declare that plugin in `dependencies` (Claude) or
bundle a copy guarded by R006 (Codex).

## R008 [must]
Built-in state machines, angle files and skills must name no skill, path
or convention specific to one project; project specifics go in
`.bootgear/config/`.

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
A shipped CLI or script must have a `[commands]` entry in its plugin's
`gear.toml`, and when `GEAR_CALLER_CWD` is set it must resolve the
caller's relative paths against it (`gear.py` runs the child from the
plugin root).

## R014 [must]
A subcommand that completes a workflow step must end its output with the
next step — the next command or the decision to make — in one line, and as
a `next` field in JSON. The reminder appears only when it changes what the
caller does next; a skill line that repeats it is removed.
