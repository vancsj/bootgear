import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


class SubagentStopGuardTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="engine-subagent-stop-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.session_dir = self.home / ".bootgear" / "session"
        self.session_dir.mkdir(parents=True)
        self.session_id = "fixture-subagent-stop"
        (self.session_dir / f"{self.session_id}.md").write_text("## state\ncurrent: inspect\n")

    def _claude_stop(self, tasks):
        return self._hook("claude", "stop_reminder", "", {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "background_tasks": tasks,
        })

    def _hook(self, host, handler, matcher, fields):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; from engine.host_adapter import run; raise SystemExit(run('{host}', sys.argv[1:]))",
                "--handler", handler,
                "--matcher-pattern", matcher,
            ],
            input=json.dumps({
                "session_id": self.session_id,
                "cwd": str(self.home),
                **fields,
            }),
            env={
                **os.environ,
                "HOME": str(self.home),
                "CLAUDE_PLUGIN_ROOT": str(PLUGIN_DIR),
                "PLUGIN_ROOT": str(PLUGIN_DIR),
                "CODEX_HOME": str(self.home / ".codex"),
                "PYTHONPATH": os.pathsep.join((str(PLUGIN_DIR / "src"), os.environ.get("PYTHONPATH", ""))),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_running_subagent_suppresses_stop_without_consuming_the_next_reminder(self):
        task = {"id": "task-agent", "type": "subagent", "status": "running", "agent_type": "Explore"}

        self.assertEqual(self._claude_stop([task]), {})
        self.assertFalse((self.session_dir / f".{self.session_id}.stop_reminder_state").exists())
        self.assertIn("additionalContext", self._claude_stop([])["hookSpecificOutput"])

    def test_background_shell_keeps_the_stop_reminder(self):
        task = {"id": "task-shell", "type": "shell", "status": "running", "command": "tail -f build.log"}

        self.assertIn("additionalContext", self._claude_stop([task])["hookSpecificOutput"])

    def test_pending_subagent_keeps_the_stop_reminder(self):
        self.assertIn("additionalContext", self._claude_stop([
            {"type": "subagent", "status": "pending"},
        ])["hookSpecificOutput"])

    def test_running_subagent_suppresses_a_mixed_task_list(self):
        self.assertEqual(self._claude_stop([
            {"type": "shell", "status": "running"},
            {"type": "subagent", "status": "running"},
        ]), {})

    def test_absent_task_list_keeps_the_stop_reminder(self):
        output = self._hook("claude", "stop_reminder", "", {
            "hook_event_name": "Stop", "stop_hook_active": False,
        })
        self.assertIn("additionalContext", output["hookSpecificOutput"])

    def _codex_start(self, source="startup"):
        self._hook("codex", "session_recall", "^(startup|resume|clear|compact|fork)$", {
            "hook_event_name": "SessionStart", "source": source,
        })

    def _codex_reminder(self, event, turn):
        fields = {"hook_event_name": event, "turn_id": turn}
        if event == "Stop":
            fields["stop_hook_active"] = False
        else:
            fields.update(tool_name="exec_command", tool_use_id="fixture-tool", tool_input={}, tool_response={})
        return self._hook("codex", "stop_reminder", "" if event == "Stop" else ".*", fields)

    def _running_codex_child(self, parent=None, identifier="child"):
        storage = self.home / ".codex"
        storage.mkdir(exist_ok=True)
        rollout = storage / f"{identifier}.jsonl"
        self._write_lifecycle(rollout, "task_started")
        with sqlite3.connect(storage / "state_5.sqlite") as connection:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, rollout_path TEXT);"
                "CREATE TABLE IF NOT EXISTS thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT, status TEXT);"
            )
            connection.execute("INSERT INTO threads VALUES (?, ?)", (identifier, str(rollout)))
            connection.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, 'open')", (parent or self.session_id, identifier))
        return rollout

    def _write_lifecycle(self, rollout, kind):
        with rollout.open("a") as output:
            output.write(json.dumps({
                "timestamp": datetime.now(UTC).isoformat(),
                "type": "event_msg",
                "payload": {"type": kind, "turn_id": "child-turn"},
            }) + "\n")

    def test_codex_stop_suppresses_running_child_and_resumes_after_completion(self):
        self._codex_start()
        rollout = self._running_codex_child()
        marker = self.session_dir / f".{self.session_id}.stop_reminder_state"
        before = marker.read_bytes() if marker.exists() else None

        self.assertEqual(self._codex_reminder("Stop", "parent-turn"), {})
        self.assertEqual(marker.read_bytes() if marker.exists() else None, before)
        self._write_lifecycle(rollout, "task_complete")
        self.assertTrue(self._codex_reminder("Stop", "parent-turn"))

    def test_codex_fallback_suppresses_running_child_without_consuming_the_reminder(self):
        self._codex_start()
        self.assertEqual(self._codex_reminder("PostToolUse", "parent-first"), {})
        rollout = self._running_codex_child()
        marker = self.session_dir / f".{self.session_id}.stop_reminder_state"
        before = marker.read_bytes()

        self.assertEqual(self._codex_reminder("PostToolUse", "parent-second"), {})
        self.assertEqual(marker.read_bytes(), before)
        self._write_lifecycle(rollout, "turn_aborted")
        self.assertTrue(self._codex_reminder("PostToolUse", "parent-second"))

    def test_codex_completed_child_keeps_the_stop_reminder(self):
        self._codex_start()
        rollout = self._running_codex_child()
        self._write_lifecycle(rollout, "task_complete")

        self.assertTrue(self._codex_reminder("Stop", "parent-turn"))

    def test_codex_reused_running_child_suppresses_stop(self):
        self._codex_start()
        rollout = self._running_codex_child()
        self._write_lifecycle(rollout, "task_complete")
        self._write_lifecycle(rollout, "task_started")

        self.assertEqual(self._codex_reminder("Stop", "parent-turn"), {})

    def test_codex_fork_can_start_a_guarded_runtime(self):
        self._codex_start("fork")
        self._running_codex_child()

        self.assertEqual(self._codex_reminder("Stop", "parent-turn"), {})

    def test_codex_clear_can_start_a_guarded_runtime(self):
        self._codex_start("clear")
        self._running_codex_child()

        self.assertEqual(self._codex_reminder("Stop", "parent-turn"), {})

    def test_codex_resume_excludes_starts_from_the_previous_runtime(self):
        self._codex_start()
        self._running_codex_child()
        self._codex_start("resume")

        self.assertTrue(self._codex_reminder("Stop", "parent-turn"))

    def test_codex_compaction_preserves_a_running_child_and_the_runtime_boundary(self):
        self._codex_start()
        self._running_codex_child()
        marker = self.session_dir / f".{self.session_id}.stop_reminder_state"
        before = marker.read_bytes() if marker.exists() else None
        self._codex_start("compact")

        self.assertEqual(marker.read_bytes() if marker.exists() else None, before)
        self.assertEqual(self._codex_reminder("Stop", "parent-turn"), {})

    def test_codex_closed_child_keeps_the_reminder_without_a_terminal_rollout_record(self):
        self._codex_start()
        self._running_codex_child()
        with sqlite3.connect(self.home / ".codex" / "state_5.sqlite") as connection:
            connection.execute("UPDATE thread_spawn_edges SET status = 'closed'")

        self.assertTrue(self._codex_reminder("Stop", "parent-turn"))

    def test_codex_unrelated_running_child_keeps_the_reminder(self):
        self._codex_start()
        self._running_codex_child(parent="unrelated-root")

        self.assertTrue(self._codex_reminder("Stop", "parent-turn"))

    def test_codex_running_grandchild_suppresses_stop_after_its_parent_finishes(self):
        self._codex_start()
        parent_rollout = self._running_codex_child()
        self._write_lifecycle(parent_rollout, "task_complete")
        self._running_codex_child(parent="child", identifier="grandchild")

        self.assertEqual(self._codex_reminder("Stop", "parent-turn"), {})

    def test_codex_partial_tail_preserves_the_latest_complete_running_record(self):
        self._codex_start()
        rollout = self._running_codex_child()
        with rollout.open("ab") as output:
            output.write(b'{"type":"event_msg","payload":')

        self.assertEqual(self._codex_reminder("Stop", "parent-turn"), {})

    def test_codex_root_activity_does_not_suppress_the_reminder(self):
        self._codex_start()
        child_rollout = self._running_codex_child()
        self._write_lifecycle(child_rollout, "task_complete")
        root_rollout = self.home / ".codex" / "root.jsonl"
        self._write_lifecycle(root_rollout, "task_started")
        with sqlite3.connect(self.home / ".codex" / "state_5.sqlite") as connection:
            connection.execute("INSERT INTO threads VALUES (?, ?)", (self.session_id, str(root_rollout)))

        self.assertTrue(self._codex_reminder("Stop", "parent-turn"))
