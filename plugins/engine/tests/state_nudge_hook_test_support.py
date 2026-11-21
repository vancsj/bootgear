"""Tests the registered state-nudge hook through public Gear.

Drives the hook as a subprocess against a real scratch ledger built with
Gear `engine task` route, then manipulates the hook's own marker file directly to force the
elapsed-time and history conditions each test needs, rather than sleeping.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from bootgear_cli import runtime
from gear_commands import HOST
from gear_commands import TASK as TASK_COMMAND
from settlement_fixture import valid_settlement

PLUGIN_DIR = Path(__file__).resolve().parents[1]
HANDLER = PLUGIN_DIR / "hooks" / "state_nudge_reminder.py"
HOOK = PLUGIN_DIR / "hooks" / "gear"

_spec = importlib.util.spec_from_file_location("state_nudge_reminder", HANDLER)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"could not load {HOOK}")
state_nudge_reminder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(state_nudge_reminder)

MACHINE = """\
name: smoke
nodes:
  clarify:
    next: [impl]
  impl:
    next: [fix, succeeded]
  fix:
    next: [impl]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""

SETTLEMENT = valid_settlement(MACHINE)


class StateNudgeHookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="state-nudge-hook-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.data = self.tmp / "data"
        runtimes = self.data / "bootgear" / "runtimes"
        runtimes.parent.mkdir(parents=True)
        runtimes.symlink_to(runtime.environment_path().parent, target_is_directory=True)
        self.session_dir = self.home / ".bootgear" / "session"
        self.session_dir.mkdir(parents=True)
        settlement_file = self.session_dir / "settlement.txt"
        settlement_file.write_text(SETTLEMENT)
        self.run_id = "test-run"
        env = {**os.environ, "HOME": str(self.home), "XDG_DATA_HOME": str(self.data)}
        subprocess.run(
            [*TASK_COMMAND, "session", "init", self.run_id,
             "--settlement-file", str(settlement_file), "--dir", str(self.session_dir)],
            capture_output=True, text=True, check=True, env=env,
        )
        self.marker_path = self.session_dir / f".{self.run_id}.state_nudge_state"

    def _hook_env(self, home: Path | None = None) -> dict:
        env = os.environ.copy()
        env["BOOTGEAR_HOST"] = HOST
        env.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
        env["HOME"] = str(home or self.home)
        env["XDG_DATA_HOME"] = str(self.data)
        return env

    def _hook_argv(self):
        return [str(HOOK), "--host", HOST, "adapter", "--handler", "state_nudge",
                "--matcher-pattern", ".*"]

    def _hook_input(self, cwd: str | None = None, **extra) -> dict:
        payload = {
            "session_id": self.run_id,
            "cwd": cwd or str(self.session_dir),
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "tool_response": {"exit": 0},
            **extra,
        }
        if HOST == "codex":
            payload.update(turn_id="fixture-turn", tool_use_id="fixture-tool")
        return payload

    def _run_hook(self, cwd: str | None = None, home: Path | None = None,
                  extra: dict | None = None) -> dict:
        payload = self._hook_input(cwd, **(extra or {}))
        result = subprocess.run(
            self._hook_argv(),
            input=json.dumps(payload),
            capture_output=True, text=True,
            env=self._hook_env(home),
            check=False,
        )
        self.last_hook_result = result
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return {}
        return json.loads(result.stdout)

    def _force_stale(self):
        """Backdate the marker so the hook treats last activity as stale,
        without waiting 5 real minutes."""
        marker = json.loads(self.marker_path.read_text()) if self.marker_path.exists() else {}
        marker["last_checked_at"] = 0.0
        self.marker_path.write_text(json.dumps(marker))

    def _setup_home_ledger(self):
        home_session_dir = self.home / ".bootgear" / "session"
        home_session_dir.mkdir(parents=True, exist_ok=True)
        ledger_src = self.session_dir / f"{self.run_id}.md"
        (home_session_dir / f"{self.run_id}.md").write_text(ledger_src.read_text())
        return (home_session_dir / f"{self.run_id}.md",
                home_session_dir / f".{self.run_id}.state_nudge_state")

    def _backdate_started(self, ledger_path: Path, old_ts: str) -> None:
        text = re.sub(r"(?m)^started: .*$", f"started: {old_ts}",
                       ledger_path.read_text())
        ledger_path.write_text(text)

    def _backdate_transitions(self, ledger_path: Path, old_ts: str) -> None:
        text = ledger_path.read_text()
        text = re.sub(r"(?m)^(- \d{4}-\d{2}-\d{2} \d{2}:\d{2}) (\S+ -> \S+ )",
                       lambda m: f"- {old_ts} {m.group(2)}", text)
        ledger_path.write_text(text)
