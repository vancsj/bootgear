"""The registered ledger command reads the session identity from the host environment."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
GEAR = REPO / "plugins" / "cli" / "bin" / "gear"
CLI_SOURCE = REPO / "plugins" / "cli" / "src"
SESSION_VARIABLES = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_SESSION_ID"}


@pytest.mark.parametrize("host", ("claude", "codex"))
def test_environment_session_reaches_the_registered_ledger(host: str, tmp_path: Path) -> None:
    for name in ("shared", "local"):
        subprocess.run(["git", "init", "-q", str(tmp_path / name)], check=True)
    home = tmp_path / "home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key not in {"BOOTGEAR_HOST", "BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID",
                          "CODEX_SESSION_ID", "GEAR_CALLER_CWD", "VIRTUAL_ENV"}}
    env.update({"HOME": str(home), SESSION_VARIABLES[host]: "active-session-full",
                "PYTHONPATH": os.pathsep.join([str(CLI_SOURCE), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)})
    argv = [
        str(GEAR), "--host", host, "--root", str(REPO), "memory-ledger", "ledger",
        "--root", str(tmp_path / "shared"), "--local-root", str(tmp_path / "local"),
        "new", "tech/context", "--local",
        "--q", "Which session signed the entry?", "--claim", "The active host session signs.",
        "--because", "The host environment names the session.", "--evidence", "true",
    ]
    result = subprocess.run(argv, cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    entry = (tmp_path / "local" / "tech" / "context.md").read_text()
    signer = "codex:active-session-full" if host == "codex" else "active"
    assert re.findall(r"^\s+✓\s+(\S+)", entry, re.MULTILINE) == [signer]
    expected = shlex.join([str(GEAR), "--host", host, "memory-ledger", "ledger", "save"])
    assert result.stdout.splitlines()[-1] == f"next: {expected}"
