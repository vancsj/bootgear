# Advisor — rationale

`channel.py` is co-located under this skill for both hosts, so neither host resolves a path into another plugin.

Mode is a required, explicit argument on every invocation rather than inferred from which host is running, because either host may run either mode (see `references/channel.md`'s pairing algorithm) — nothing about being "the Claude Code skill" or "the Codex CLI skill" fixes a mode.
