#!/usr/bin/env python3
"""Nudge toward `recall` immediately after a compaction.

Runs on `SessionStart` with matcher `compact`, which fires after compaction
and, unlike `PostCompact`, can return `additionalContext` to the model.

Appends the run's `/goal` text when the session ledger
`~/.bootgear/session/<session_id>.md` exists. `goal:` is a YAML ">" folded
scalar, so the settlement section is parsed as real YAML. Every failure path
(missing ledger, malformed YAML, missing `goal`) still prints the base
NUDGE_MESSAGE.

Also merges principles from all 3 levels — user (`~/.claude/principles.md`),
project (`{cwd}/.bootgear/config/principles.md`), task (the settlement's
`principles`) — per `skills/execute/SKILL.md`'s "Reading and merging
principles". A missing, empty, or unreadable file drops only that source.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

NUDGE_MESSAGE = (
    "This session just compacted. If an engine run is active, call "
    "`recall` now, before anything else — re-read the session ledger's "
    "settlement from disk rather than trusting whatever this compaction "
    "summarized it as."
)

_SETTLEMENT_RE = re.compile(r"(?m)^## settlement\n(.*?)(?=\n## |\Z)", re.DOTALL)


def _settlement(hook_input: dict) -> dict | None:
    run_id = hook_input.get("session_id")
    if not run_id:
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

    user_text = _read_file_text(Path.home() / ".claude" / "principles.md")
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
    message = NUDGE_MESSAGE
    settlement = _settlement(hook_input)
    goal = _goal_text(settlement)
    if goal:
        message = f"{message}\n\nThis run's /goal:\n{goal}"
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
