#!/usr/bin/env python3
"""Expose the Codex session identity and nudge toward `recall` after compaction.

Codex supplies the current session identity to every command hook on stdin.
This hook always prints that identity so `clarify` can use it as the ledger
run-id instead of inventing one.

The rest is added only when the session has an active engine ledger:
`~/.bootgear/session/<session_id>.md` exists, is readable and has no
`## closed` heading. Then, on `source: compact`, the recall nudge is
prepended; the run's `goal` text from the ledger's settlement (parsed as
real YAML; a legacy string or a mapping with `succeeded` and `failed`
conditions) and the merged principles follow. Malformed YAML or a missing
`goal` drops only the goal.

Principles merge from all 3 levels: task (the settlement's `principles`),
project (`.bootgear/config/principles.md`) and user
(`~/.codex/principles.md`, a dedicated file, not `~/.codex/AGENTS.md`), per
`skills/execute/SKILL.md`'s "Reading and merging principles". A missing,
empty, or unreadable file drops only that source.
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
    ledger = _active(hook_input)
    if ledger is not None:
        if hook_input.get("source") == "compact":
            message = f"{NUDGE_MESSAGE}\n\n{message}"
        settlement = _settlement(ledger)
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
