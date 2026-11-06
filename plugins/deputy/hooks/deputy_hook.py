#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML>=6.0.3"]
# ///
"""Main-agent deputy reminders: paced ASK completions and immediate RECORD events."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shlex
import sys
import time
from pathlib import Path
from typing import NoReturn

import yaml

ASK = ("deputy: before you ask the user a work question, call `deputy:ask` with the question, its options "
       "and its stakes. Ask the user only if it returns `escalate`. Never send a production change, outward "
       "send, irreversible action, goal sign-off or permitted mutations to the deputy.")
RECORD = ("deputy: if `deputy:ask` returned `escalate` for the question the user just answered, and the answer "
          "is written in a session ledger file, call `deputy:record` with the question, the answer, the reason, "
          "the options and the stakes. Without a session ledger file, do not call it.")
QUESTION_TOOLS = ("AskUserQuestion", "request_user_input", "request_user_input_async")
DEFAULTS = {"tool_calls": 10, "cooldown_seconds": 300}


class ConfigError(ValueError):
    """The reminder configuration cannot be applied."""


class HookParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        script = shlex.quote(str(Path(__file__).resolve()))
        print(f"example: uv run --quiet --script {script} --host codex < event.json", file=sys.stderr)
        print("commands: deputy, hook", file=sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def caller_path(value: str) -> Path:
    path = Path(value).expanduser()
    base = Path(os.environ.get("GEAR_CALLER_CWD", os.getcwd()))
    return (path if path.is_absolute() else base / path).resolve()


def project_config(cwd: Path) -> Path | None:
    for directory in (cwd, *cwd.parents):
        path = directory / ".bootgear" / "config" / "deputy.yaml"
        if path.exists():
            return path
        if (directory / ".git").exists():
            break
    return None


def reminder_settings(host: str, cwd: Path) -> dict[str, int]:
    settings = DEFAULTS.copy()
    problems = []
    for path in (Path.home() / f".{host}" / "deputy.yaml", project_config(cwd)):
        if path is None or not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            problems.append(f"{path}: cannot read config: {exc}")
            continue
        if data is None:
            continue
        if not isinstance(data, dict):
            problems.append(f"{path}: config must be a mapping")
            continue
        for key in data:
            if key != "ask_reminder":
                problems.append(f"{path}: unknown setting {key!r}")
        values = data.get("ask_reminder", {})
        if not isinstance(values, dict):
            problems.append(f"{path}: ask_reminder must be a mapping")
            continue
        for key, value in values.items():
            if key not in DEFAULTS:
                problems.append(f"{path}: unknown ask_reminder setting {key!r}")
            elif type(value) is not int or value < 1:
                problems.append(f"{path}: ask_reminder.{key} must be a positive integer")
            else:
                settings[key] = value
    if problems:
        raise ConfigError("invalid reminder config:\n" + "\n".join(f"  - {problem}" for problem in problems))
    return settings


def ask_due(payload: dict, root: Path, host: str) -> bool:
    session = payload.get("session_id") or os.environ.get("BOOTGEAR_SESSION_ID")
    if not isinstance(session, str) or not session:
        return False
    cwd = caller_path(payload.get("cwd") or os.environ.get("GEAR_CALLER_CWD", os.getcwd()))
    settings = reminder_settings(host, cwd)
    directory = root.parent / ".deputy-reminder-state"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps([str(root), host, session]).encode()).hexdigest()
    path = directory / f"{key}.json"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            marker = json.load(handle)
        except json.JSONDecodeError:
            marker = {}
        if not isinstance(marker, dict):
            raise TypeError("invalid reminder state")
        calls, last = marker.get("calls", 0), marker.get("last_ask")
        if type(calls) is not int or calls < 0 or (last is not None and type(last) not in (int, float)):
            raise ValueError("invalid reminder state")
        calls += 1
        now = time.time()
        due = calls >= settings["tool_calls"] and (last is None or now - last >= settings["cooldown_seconds"])
        marker = {"calls": 0 if due else calls, "last_ask": now if due else last}
        handle.seek(0)
        handle.truncate()
        json.dump(marker, handle, separators=(",", ":"))
    return due


def reminder(payload: dict) -> str | None:
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        return RECORD
    if event == "PostToolUse" and payload.get("tool_name") in QUESTION_TOOLS:
        return RECORD
    return None


def remind(host: str) -> None:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict) or payload.get("agent_id"):
        return
    root = caller_path(os.environ.get("LEDGER_DEPUTY_ROOT", "~/.memory-ledger/deputy"))
    if not root.is_dir():
        return
    text = reminder(payload)
    completion = payload.get("hook_event_name") == "PostToolUse" or (
        host == "claude" and payload.get("hook_event_name") == "PostToolUseFailure")
    if completion:
        try:
            if ask_due(payload, root, host):
                text = "\n".join(filter(None, (ASK, text)))
        except ConfigError as exc:
            print(f"deputy: {exc}", file=sys.stderr)
        except (OSError, ValueError, TypeError):
            pass
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": payload["hook_event_name"],
                                                 "additionalContext": text}}, separators=(",", ":")))


def main(host: str | None = None) -> int:
    """Emit main-agent context; config errors report diagnostics without blocking the host."""
    with contextlib.suppress(BaseException):
        remind(host or os.environ.get("BOOTGEAR_HOST", "claude"))
    return 0


if __name__ == "__main__":
    parser = HookParser(description=__doc__)
    parser.add_argument("--host", choices=("claude", "codex"), default=os.environ.get("BOOTGEAR_HOST", "claude"))
    sys.exit(main(parser.parse_args().host))
