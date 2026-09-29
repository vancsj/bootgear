# review-standard

severities: [must, should]
cutoff: must

## R001 [must]
Every skill's `SKILL.md` states what it hands back and to whom — a
finding, a decision, a report — not just what it does internally. A
skill whose output shape another skill depends on (e.g. `test`/`review`
feeding `execute`'s goal-check) must make that shape explicit in its own
file, not leave it to be inferred from a caller.

## R002 [must]
A script that owns a shared, mutable file (the session ledger, a
project-wide config) rejects structurally invalid input rather than
writing it and hoping a later reader copes — see `session.py`'s
`_check_structure`. A new owning script follows the same discipline:
validate before writing, exit clearly on a violation, never a partial
write.

## R003 [must]
A design decision recorded anywhere in this repo (a doc, a skill's
prose, a commit message) that states a fact about the platform (a hook
event, a tool's real behavior, a CLI flag) is checked against the
official docs or the actual CLI output before being written down as
settled — not asserted from memory or a plausible-sounding guess.

## R004 [should]
A skill that can end in more than one distinct outcome (converged vs.
capped vs. degraded; clean vs. blocked vs. capped) names every outcome
explicitly in its own file, rather than describing only the success
path and leaving the others implicit.

## R005 [must]
A `SKILL.md` contains instructions — how to work — not design rationale.
Justification for why a rule exists (why unanimity instead of majority,
why a field is shaped the way it is) belongs in a reference doc the
skill points to, not inline in the instruction itself. A skill may point
to more than one reference doc as needed (progressive disclosure) rather
than one large design doc for everything. Edge-case handling that
changes what to actually do stays inline — only pure justification moves
out.

## R006 [must]
A file the Codex plugin carries as a copy of a Claude-side source (bundled
code, a synced skill or reference) is covered by a drift test that fails
when the copy and its source differ — see `test_bundle_drift.py`.

## R007 [must]
A shipped plugin that calls another plugin's skill or command either
declares that plugin in `dependencies` (Claude) or bundles a copy guarded
by R006 (Codex).

## R008 [must]
Built-in state machines, angle files and skills name no skill, path or
convention specific to one project; project specifics go in
`.bootgear/config/`.

## R009 [must]
A value substituted into a command's argv (a placeholder, a `--leave-arg`)
is refused when it could be read as an option (starts with `-`), so an
input can never change which flags the checked program sees.

## R010 [must]
A CLI subcommand that refuses its arguments prints, alongside the error,
one correct example invocation of that subcommand and a concise list of
the CLI's other subcommands (names only, plus an example for the
frequently used ones), not only the usage line or the bare error.

## R011 [must]
A CLI that finds several problems of the same kind (e.g. bad entries in
a list) reports them in one grouped message naming every offending item,
not one repeated message per item, and still lists every problem in one
run rather than stopping at the first.

## R012 [must]
A CLI's default output format is concise prose for every stdout sink.
`--json` and `--prose` override the default, followed by
`BOOTGEAR_OUTPUT=json|prose` when no flag is present. A Codex wrapper script
passes prose unless the caller asked for JSON.

## R013 [must]
A shipped CLI or script has a `[commands]` entry in its plugin's
`gear.toml`, and when `GEAR_CALLER_CWD` is set it resolves the caller's
relative paths against it (`gear.py` runs the child from the plugin
root).

## R014 [must]
A subcommand that completes a workflow step ends its output with the
next step — the next command or the decision to make — in one line, and
as a `next` field in JSON. The reminder appears only when it changes what
the caller does next; a skill line that repeats it is removed.
