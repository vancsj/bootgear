"""Advisor reservation and invitation contracts (test-standard R006)."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest
from channel_test_support import channel_json, run


def _reserve(root: Path, group: str, worker: str, session: str = "asker") -> dict[str, Any]:
    result = run(root, "reserve", "--group", group, "--worker", worker, "--session", session)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_reserved_listener_matches_group_worker_and_invitation(tmp_path: Path, host: str) -> None:
    first = _reserve(tmp_path, "/review group/first-slate", "r2")
    second = _reserve(tmp_path, "/review group/first-slate", "r2-2")
    assert f"heartbeat --channel {second['channel']} --role asker" in second["heartbeat"]
    assert first["channel"] != second["channel"]
    assert first["invitation"] != second["invitation"]
    resumed = _reserve(tmp_path, first["group"], first["worker"])
    assert (resumed["channel"], resumed["invitation"]) == (first["channel"], first["invitation"])

    file = channel_json(tmp_path, second["channel"])
    before = file.read_bytes()
    foreign = run(tmp_path, "reserve", "--group", first["group"], "--worker", "r2-3",
                  "--session", "foreign")
    assert foreign.returncode == 2
    assert json.loads(foreign.stderr)["category"] == "group_owner_mismatch"
    wrong = run(tmp_path, "register", "--role", "listener", "--session", "wrong",
                "--group", first["group"], "--worker", second["worker"],
                "--invitation", first["invitation"])
    assert wrong.returncode == 2
    assert json.loads(wrong.stderr)["category"] == "invitation_mismatch"
    generic = run(tmp_path, "register", "--role", "listener", "--session", "wrong",
                  "--channel", second["channel"])
    assert generic.returncode == 2
    assert file.read_bytes() == before

    spare = run(tmp_path, "register", "--role", "listener", "--session", "spare")
    assert spare.returncode == 0
    waiting = run(tmp_path, "wait-listener", "--group", second["group"], "--worker", second["worker"],
                  "--session", "asker", "--timeout", "0")
    assert waiting.returncode == 1
    assert json.loads(waiting.stdout)["channel"] == second["channel"]

    registered = run(tmp_path, "register", "--role", "listener", "--session", "listener-2",
                     "--group", second["group"], "--worker", second["worker"],
                     "--invitation", second["invitation"], env={"BOOTGEAR_HOST": host})
    assert registered.returncode == 0, registered.stderr
    assert json.loads(registered.stdout)["channel"] == second["channel"]
    waiting = run(tmp_path, "wait-listener", "--group", second["group"], "--worker", second["worker"],
                  "--session", "asker", "--timeout", "0")
    assert waiting.returncode == 1
    assert json.loads(waiting.stdout)["ready"] is False
    heartbeat = run(tmp_path, "heartbeat", "--channel", second["channel"], "--role", "listener",
                    "--session", "listener-2", "--interval", "0.02", "--max-age", "0.1")
    assert heartbeat.returncode == 0, heartbeat.stderr
    ready = run(tmp_path, "wait-listener", "--group", second["group"], "--worker", second["worker"],
                "--session", "asker", "--timeout", "0")
    assert ready.returncode == 0, ready.stderr
    payload = json.loads(ready.stdout)
    assert payload["channel"] == second["channel"]
    assert payload["listener_host"] == host
    assert payload["listener_owner"] == "listener-2"
    assert "invitation" not in payload


def test_reserved_launcher_retries_once_with_exact_argv(tmp_path: Path) -> None:
    reserved = _reserve(tmp_path, "/review group/first-slate", "r2-2")
    received = tmp_path / "received.json"
    script = "import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))"
    template = shlex.join([sys.executable, "-c", script, str(received),
                           "{group}", "{worker}", "{invitation}"])
    arguments = ("launch", "--group", reserved["group"], "--worker", reserved["worker"],
                 "--session", "asker", "--template", template)

    first = run(tmp_path, *arguments)
    assert first.returncode == 0, first.stderr
    assert json.loads(received.read_text()) == [reserved[key] for key in ("group", "worker", "invitation")]
    assert run(tmp_path, *arguments).returncode == 2
    assert run(tmp_path, *arguments, "--retry").returncode == 0
    assert run(tmp_path, *arguments, "--retry").returncode == 2
