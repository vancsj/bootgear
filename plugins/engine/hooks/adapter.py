#!/usr/bin/env python3
"""Installed host adapter entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from bootgear_cli.clikit import event_help, host

HOST = host() or "claude"
_ROOT_ENV = "PLUGIN_ROOT" if HOST == "codex" else "CLAUDE_PLUGIN_ROOT"


def _source_dir() -> Path:
    root = os.environ.get(_ROOT_ENV)
    if root:
        return Path(root).expanduser().resolve(strict=False) / "src"
    return Path(__file__).resolve().parent.parent / "src"


_plugin_root = Path(os.environ.get(_ROOT_ENV, Path(__file__).resolve().parent.parent))
os.environ.setdefault(_ROOT_ENV, str(_plugin_root.resolve(strict=False)))
_source = _source_dir()
if str(_source) not in sys.path:
    sys.path.insert(0, str(_source))

from engine.host_adapter import run

if __name__ == "__main__":
    if event_help("engine", "adapter", "Host event JSON on stdin: session_id, hook_event_name, cwd, and event-specific fields. "
                  "--handler: session_recall, state_nudge, stop_reminder, compaction_observe. --matcher-pattern selects the event matcher.",
                  {"session_id": "00000000-0000-4000-8000-000000000001", "hook_event_name": "SessionStart", "source": "startup", "cwd": "."},
                  "--handler session_recall --matcher-pattern startup"):
        raise SystemExit(0)
    raise SystemExit(run(HOST, sys.argv[1:]))
