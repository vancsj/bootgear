#!/usr/bin/env python3
"""Nudge toward `recall` immediately after a compaction.

Runs on `SessionStart` with matcher `compact`, which fires after compaction
and, unlike `PostCompact`, can return `additionalContext` to the model.

The nudge and the run's `/goal` are printed only when the session has an
active engine ledger: `~/.bootgear/session/<session_id>.md` exists, is
readable and has no `## closed` heading. The goal comes from the ledger's
settlement section, parsed as real YAML; `goal` may be a legacy string or a
mapping with `succeeded` and `failed` conditions. Malformed YAML or a missing
`goal` still prints the base NUDGE_MESSAGE.

Merged principles are printed with or without an active ledger, from all 3
levels — user (`~/.claude/principles.md`), project
(`{cwd}/.bootgear/config/principles.md`), task (the settlement's
`principles`, active ledger only) — per `skills/execute/SKILL.md`'s "Reading
and merging principles". A missing, empty, or unreadable file drops only that
source. With no active ledger and no principles it prints nothing.
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
_CLOSED_HEADING_RE = re.compile(r"(?m)^## closed\s*$")


def _active(hook_input: dict) -> str | None:
    run_id = hook_input.get("session_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    ledger_path = Path.home() / ".bootgear" / "session" / f"{run_id}.md"
    try:
        text = ledger_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if _CLOSED_HEADING_RE.search(text):
        return None
    return text


def _settlement(text: str) -> dict | None:
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
    if isinstance(goal, str):
        return goal.strip() or None
    if isinstance(goal, dict):
        succeeded = goal.get("succeeded")
        failed = goal.get("failed")
        if (isinstance(succeeded, str) and succeeded.strip()
                and isinstance(failed, str) and failed.strip()):
            return f"succeeded when {succeeded.strip()}\nfailed when {failed.strip()}"
    return None


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
    ledger = _active(hook_input)
    parts = [NUDGE_MESSAGE] if ledger is not None else []
    settlement = _settlement(ledger) if ledger is not None else None
    goal = _goal_text(settlement)
    if goal:
        parts.append(f"This run's /goal:\n{goal}")
    principles = _principles_text(hook_input, settlement)
    if principles:
        parts.append(f"Merged principles (user/project/task):\n{principles}")
    if not parts:
        return
    message = "\n\n".join(parts)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()
