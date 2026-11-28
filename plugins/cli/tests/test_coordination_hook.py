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
