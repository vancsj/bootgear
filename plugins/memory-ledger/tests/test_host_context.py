"""Host hooks supply the identity used by the registered ledger command."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]


@pytest.mark.parametrize("host", ("claude", "codex"))
def test_hook_context_reaches_the_registered_ledger(host: str, tmp_path: Path) -> None:
    engine = REPO / ("codex-plugins" if host == "codex" else "plugins") / "engine"
    for name in ("shared", "local"):
        subprocess.run(["git", "init", "-q", str(tmp_path / name)], check=True)
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "BOOTGEAR_HOST": "standalone",
           "BOOTGEAR_SESSION_ID": "inherited-session", "CLAUDE_CODE_SESSION_ID": "native-session",
           "PLUGIN_ROOT": str(engine), "CLAUDE_PLUGIN_ROOT": str(engine)}
    command = shlex.join([
        str(PLUGIN / "bin" / "ledger"), "--root", str(tmp_path / "shared"),
        "--local-root", str(tmp_path / "local"), "new", "tech/context", "--local",
        "--q", "Which session signed the entry?", "--claim", "The active host session signs.",
        "--because", "The hook supplies shared context.", "--evidence", "true",
    ])
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "session_id": "active-session-full", "cwd": str(tmp_path),
               "tool_input": {"command": command}}
    hook = subprocess.run(
        [sys.executable, str(engine / "hooks" / "pre_tool_use_task_identity.py"), "--host", host],
        input=json.dumps(payload), capture_output=True, text=True, env=env, check=True,
    )
    updated = json.loads(hook.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
    result = subprocess.run(["bash", "-c", updated], cwd=tmp_path, env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    entry = (tmp_path / "local" / "tech" / "context.md").read_text()
    signer = "codex:active-session-full" if host == "codex" else "active"
    assert re.findall(r"^\s+✓\s+(\S+)", entry, re.MULTILINE) == [signer]
    assert result.stdout.splitlines()[-1] == f"next: {PLUGIN / 'bin' / 'ledger'} save"
