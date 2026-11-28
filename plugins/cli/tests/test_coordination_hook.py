from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

import pytest

from .gear_test_support import GEAR, REPO


def _hook(host: str, command: str, participant: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"tool_input": {"command": command}}
    if participant is not None:
        event["agent_id"] = participant
    result = subprocess.run(
        [str(GEAR), "--root", str(REPO), "--host", host, "cli", "coordination-hook"],
        input=json.dumps(event), text=True, capture_output=True, timeout=15, check=True,
    )
    return json.loads(result.stdout).get("hookSpecificOutput", {}) if result.stdout else {}


def _run_native(tmp_path, host, args):
    store = tmp_path / "coordination"
    env = dict(os.environ, BOOTGEAR_COORDINATION_DIR=str(store), BOOTGEAR_SESSION_ID=f"help-{host}")
    command = shlex.join([str(GEAR), "--host", host, *args])
    decision = _hook(host, command, "native")
    assert decision.get("permissionDecision") == "allow", decision
    result = subprocess.run(["bash", "-c", decision["updatedInput"]["command"]], env=env, text=True,
                            capture_output=True, timeout=15, check=False)
    assert not store.exists()
    return result


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("args,usage", [
    (["cli", "coordination", "--help"], "cli coordination"),
    (["cli", "coordination", "reserve", "-h"], "cli coordination reserve"),
    (["cli", "coordination", "poll", "--help"], "cli coordination poll"),
    (["converge", "converge", "--help"], "converge converge"),
    (["converge", "converge", "status", "--help"], "converge converge status"),
    (["converge", "converge", "status", "review-old", "--dir", ".", "-h"], "converge converge status"),
    (["converge", "converge", "act", "--help"], "converge converge act"),
])
def test_native_help_reaches_public_parser(tmp_path, host, args, usage):
    result = _run_native(tmp_path, host, args)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage:")
    assert usage in result.stdout


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("args,hint", [("act --help", True), ("act --input action.json --json", True),
                                       ("typo --help", False)])
def test_native_invalid_coordination_command_reaches_public_parser(tmp_path, host, args, hint):
    result = _run_native(tmp_path, host, ["cli", "coordination", *args.split()])
    assert result.returncode == 2
    message = json.loads(result.stderr)["error"]["message"] if "--json" in args else result.stderr
    assert f"invalid choice: {args.split()[0]!r}" in message
    assert ("converge converge act --input" in message) == hint


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("form", ["plain", "options", "cwd"])
def test_native_hook_binds_public_gear_forms(tmp_path, host, form):
    env = dict(os.environ, BOOTGEAR_COORDINATION_DIR=str(tmp_path / "coordination"),
               BOOTGEAR_SESSION_ID=f"hook-{host}")
    env.pop("BOOTGEAR_COORDINATION_PARTICIPANT", None)
    gear = shlex.join([str(GEAR), "--host", host, "cli", "coordination"])

    def run(command):
        result = subprocess.run(["bash", "-c", command], env=env, text=True, capture_output=True,
                                timeout=15, check=True)
        return json.loads(result.stdout)

    main = _hook(host, f"{gear} init --json")
    assert main["permissionDecision"] == "allow"
    run(main["updatedInput"]["command"])
    reserve = _hook(host, f"{gear} reserve worker finder --json")
    invitation = run(reserve["updatedInput"]["command"])["invitation"]

    prefix = ""
    if form == "options":
        gear = shlex.join([str(GEAR), f"--host={host}", "--root", str(REPO), "--json",
                          "cli", "coordination"])
    if form == "cwd":
        directory = tmp_path / "worker directory"
        directory.mkdir()
        prefix = f"cd -- {shlex.quote(str(directory))} && "
    worker = _hook(host, f"{prefix}{gear} join {shlex.quote(invitation)} --json", "native")
    assert worker.get("permissionDecision") == "allow", worker
    assert run(worker["updatedInput"]["command"])["seat"] == "worker"

    blocked = _hook(host, f"{prefix}{gear} reserve unexpected finder", "native")
    assert blocked["permissionDecision"] == "deny"
    assert _hook(host, f"true && {gear} reserve unexpected finder", "native") == {}
    assert _hook(host, f"cd /tmp '&&' {gear} poll", "native") == {}
    other = shlex.join([str(GEAR), "--root", str(tmp_path / "other root"),
                       "cli", "coordination", "poll"])
    assert _hook(host, other, "native") == {}


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("args", ["cli coordination init", "cli coordination replace worker",
                                  "cli coordination release worker", "cli coordination reserve -- --help finder",
                                  "converge converge status", "converge converge status -- --help",
                                  "converge converge cutoff"])
def test_native_main_controls_remain_denied(host, args):
    command = shlex.join([str(GEAR), "--host", host, *args.split()])
    assert _hook(host, command, "native")["permissionDecision"] == "deny"
