"""Public help explains valid calls without running their handlers."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GEAR = ROOT / "plugins/cli/bin/gear"
LEAVES = [
    ("cli", "setup"),
    *(("cli", "coordination", name) for name in
      ("init", "reserve", "join", "replace", "release",
       "heartbeat", "send", "poll", "complete", "blocked")),
    *(("deputy", "deputy", name) for name in ("candidates", "record", "assert")),
    *(("engine", "task", "session", name) for name in
      ("init", "validate", "read", "recall", "record-decision", "update-todo", "next-question-id", "record-pitch", "close", "write-ticket")),
    *(("engine", "task", "state", name) for name in ("transition", "current", "amend", "show", "validate", "diagram")),
    ("engine", "task", "config", "resolve"),
    *(("engine", "task", "artefact", name) for name in ("settings", "prepare", "record", "gate", "report")),
    *(("memory-ledger", "ledger", name) for name in
      ("resolve", "new", "rival", "show", "list", "refute", "hash", "sign", "lint", "promote", "vote", "add-evidence", "assert", "set-repo", "save", "rules", "resolve-roots", "audit", "doctor", "selftest")),
    *(("review", "self-review", name) for name in ("settings", "status", "open", "configure", "pass", "check")),
    *(("spec", "spec-feedback", name) for name in ("settings", "intake", "gate")),
]


def help_for(host: str, *route: str) -> str:
    result = subprocess.run(
        [str(GEAR), "--host", host, "--root", str(ROOT), *route, "--help"],
        env={**os.environ, "BOOTGEAR_OUTPUT": "prose"},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    assert "example:" in result.stdout.lower()
    return result.stdout


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("route", LEAVES)
def test_provider_help_has_a_working_call_shape(host, route):
    output = help_for(host, *route)
    assert f"--host {host}" in output


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("route", [
    ("cli", "session-start"),
    ("cli", "coordination-hook"),
    ("advisor", "hook"),
    ("deputy", "hook"),
    ("engine", "adapter"),
    ("memory-ledger", "hook"),
    ("memory-ledger", "codex-hook"),
])
def test_event_routes_explain_their_event_input(host, route):
    output = help_for(host, *route)
    assert "event" in output.lower()


@pytest.mark.parametrize("command", ["list", "doctor", "reconcile", "event"])
def test_gear_builtin_help_is_guidance(command):
    help_for("codex", command)


def test_coordination_help_exposes_message_acknowledgement():
    output = help_for("codex", "cli", "coordination", "poll")
    assert "--ack" in output
    assert "message ID" in output


def test_engine_force_help_names_the_preserved_boundary():
    output = help_for("codex", "engine", "task", "state", "transition")
    for value in ("--force", "--reason", "ledger", "destination"):
        assert value in output


def test_gear_refusal_keeps_the_error_after_recovery_guidance():
    result = subprocess.run([str(GEAR), "--host", "codex", "--root", str(ROOT), "doctor", "--unknown"],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 2
    assert "example:" in result.stderr
    assert result.stderr.splitlines()[-1].startswith("gear:")
