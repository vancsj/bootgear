"""Gear command prefixes for Codex Engine tests."""
from __future__ import annotations

import shlex
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GEAR = REPOSITORY_ROOT / "plugins" / "cli" / "bin" / "gear"
HOST = "codex"


def command(plugin: str, name: str, host: str = HOST) -> list[str]:
    return [str(GEAR), "--host", host, plugin, name]


def display(plugin: str, name: str, host: str = HOST) -> str:
    return shlex.join(command(plugin, name, host))


TASK = command("engine", "task")
CONVERGE = command("engine", "converge")
SELF_REVIEW = command("engine", "self-review")
SPEC_FEEDBACK = command("engine", "spec-feedback")
