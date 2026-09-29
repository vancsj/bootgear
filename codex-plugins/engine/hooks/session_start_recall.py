#!/usr/bin/env python3
"""Nudge toward `recall` immediately after a compaction.

Codex supplies the current session identity to every command hook on stdin.
This hook exposes that identity to the engine skills so `clarify` can use it
as the ledger run-id instead of inventing one. Compaction rewrites the model's
own memory of the clarify-stage settlement
with a lossy summary. The one moment that matters most for `recall` is
right after that happens — the confirmed `SessionStart` hook event with
`source: compact` is the real signal, not a guess, so this always fires
rather than needing a search-shaped heuristic the way memory-ledger's
`nudge.py` does for its own trigger.

Also loads the run's actual `goal` text, when a ledger for this session
exists, and appends it to the nudge — a compaction summary of the goal is
lossy in exactly the way the settlement itself is, so recall's own re-read
should not be the first time the real goal text reappears. `goal:` is a
YAML ">" folded scalar (line breaks fold to spaces unless a line is blank),
a different scalar type from state.py's `state_machine: |` literal block —
folding it with the same dedent-and-join trick used there would produce
the wrong text, so this parses the whole settlement section as real YAML.
Every failure path here (missing ledger, malformed YAML, missing `goal`
field) still prints the base NUDGE_MESSAGE — recall's own reminder to
re-read from disk must never be silently dropped because the goal-loading
extra failed.

Also loads and merges principles from all 3 levels — task (the same
settlement YAML `_goal_text` already parsed), project
(`.bootgear/config/principles.md`), user (`~/.codex/principles.md`,
a dedicated file — not `~/.codex/AGENTS.md`, which carries general
instructions, not principles) — per `skills/execute/SKILL.md`'s "Reading
and merging principles". Each of the 2 file sources is read
independently: a missing, empty, or unreadable file only drops that
source's text, never the whole function's result, matching the
fail-safe shape above.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

NUDGE_MESSAGE = (
    "This session just compacted. If an engine run is active, run "
    "`<plugin-root>/scripts/task session recall <run-id> --dir "
    "<session-dir>` outside the sandbox with host-level access before "
    "anything else — re-read the session ledger's settlement from disk "
    "rather than trusting whatever this compaction summarized."
)

SESSION_ID_MISSING_MESSAGE = (
    "Codex did not provide a session_id. Do not start or resume an engine run "
    "with a generated UUID; obtain the host session identity first."
)

_SETTLEMENT_RE = re.compile(r"(?m)^## settlement\n(.*?)(?=\n## |\Z)", re.DOTALL)


def _settlement(hook_input: dict) -> dict | None:
    run_id = hook_input.get("session_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    ledger_path = Path.home() / ".bootgear" / "session" / f"{run_id}.md"
    try:
        text = ledger_path.read_text()
    except OSError:
        return None
    m = _SETTLEMENT_RE.search(text)
    if not m:
        return None
    try:
        settlement = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return settlement if isinstance(settlement, dict) else None


def _goal_text(settlement: dict | None) -> str | None:
    if not settlement:
        return None
    goal = settlement.get("goal")
    return goal.strip() if isinstance(goal, str) and goal.strip() else None


def _read_file_text(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    text = text.strip()
    return text if text else None


def _principles_text(hook_input: dict, settlement: dict | None) -> str | None:
    cwd = hook_input.get("cwd")
    base = Path(cwd) if cwd else Path.cwd()
    sections = []

    user_text = _read_file_text(Path.home() / ".codex" / "principles.md")
    if user_text:
        sections.append(f"[user]\n{user_text}")

    project_text = _read_file_text(base / ".bootgear" / "config" / "principles.md")
    if project_text:
        sections.append(f"[project]\n{project_text}")

    if settlement:
        task = settlement.get("principles")
        if isinstance(task, str) and task.strip():
            sections.append(f"[task]\n{task.strip()}")

    return "\n\n".join(sections) if sections else None


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        hook_input = {}
    run_id = hook_input.get("session_id")
    if isinstance(run_id, str) and run_id:
        identity = (
            f"Codex session_id: `{run_id}`. Use this exact value as the engine "
            "run-id; do not generate a UUID or other replacement."
        )
    else:
        identity = SESSION_ID_MISSING_MESSAGE
    message = identity
    if hook_input.get("source") == "compact":
        message = f"{NUDGE_MESSAGE}\n\n{message}"
    settlement = _settlement(hook_input)
    goal = _goal_text(settlement)
    if goal:
        message = f"{message}\n\nThis run's goal:\n{goal}"
    principles = _principles_text(hook_input, settlement)
    if principles:
        message = f"{message}\n\nMerged principles (user/project/task):\n{principles}"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()
