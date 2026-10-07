# Permissions

**Auto-approve the whole CLI, not a read-only subset.** Match on the script name
with no subcommand gate.

Ask where their permission rules live before writing any; setups differ, and a
rule added to the wrong place silently never fires. If they have a
permission-hook plugin, that is the mechanism rather than `settings.json`. Check
first whether a rule already covers it — this may well be done already. Show the
exact pattern you propose and let them decide.
