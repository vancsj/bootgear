"""Tests for plugins/advisor/hooks/advisor_hook.py, driven like a host: JSON on stdin, hook output on stdout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
HOOK = PLUGIN / "hooks" / "advisor_hook.py"
CHANNEL = PLUGIN / "skills" / "advisor" / "scripts" / "channel.py"
EVENTS = ("SessionStart", "PostToolUse", "UserPromptSubmit", "Stop")


class AdvisorHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="advisor-hook-test-"))
        self.root = self.home / "advisor"
        self.env = {**{k: v for k, v in os.environ.items() if k != "BOOTGEAR_OUTPUT"},
                    "HOME": str(self.home), "BOOTGEAR_ADVISOR_DIR": str(self.root)}

    def channel(self, *args: str) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(CHANNEL), *args, "--json"], capture_output=True, text=True,
                                check=False, env=self.env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def pair(self) -> None:
        self.channel("register", "--role", "listener", "--session", "s1")
        self.channel("register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def record(self) -> dict:
        return json.loads((self.root / "channels" / "0001" / "channel.json").read_text())

    def write_record(self, record: dict) -> None:
        (self.root / "channels" / "0001" / "channel.json").write_text(json.dumps(record))

    def stop_heartbeat(self) -> None:
        record = self.record()
        record["listener_seen_at"] -= 600
        self.write_record(record)

    def hook(self, payload: object, raw: str | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(HOOK)], input=raw if raw is not None else json.dumps(payload),
                                capture_output=True, text=True, check=False, env=self.env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def event(self, name: str, session: str = "s1", **extra: object) -> subprocess.CompletedProcess:
        return self.hook({"session_id": session, "hook_event_name": name, **extra})

    def context(self, result: subprocess.CompletedProcess, event: str) -> str:
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], event)
        return output["additionalContext"]

    def test_compact_injects_the_channel_status(self) -> None:
        self.pair()
        text = self.context(self.event("SessionStart", source="compact"), "SessionStart")
        lines = text.splitlines()
        self.assertIn("channel: 0001", lines)
        self.assertIn("role: listener", lines)
        self.assertTrue(lines[-1].startswith("next: "))
        self.assertIn("receive --channel 0001 --for listener --timeout 300", lines[-1])
        self.assertNotIn("engine run:", text)

    def test_compact_names_the_engine_run_when_its_ledger_exists(self) -> None:
        self.pair()
        ledger = self.home / ".bootgear" / "session" / "s1.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("# run\n")
        text = self.context(self.event("SessionStart", source="compact"), "SessionStart")
        self.assertIn("engine run: s1", text.splitlines())

    def test_compact_restart_line_when_the_heartbeat_stopped(self) -> None:
        self.pair()
        self.stop_heartbeat()
        text = self.context(self.event("SessionStart", source="compact"), "SessionStart")
        self.assertIn("heartbeat --channel 0001 --role listener --session s1", text)
        self.assertTrue(text.splitlines()[-1].startswith("then: "))

    def test_compact_writes_the_hook_stamp(self) -> None:
        self.pair()
        before = time.time()
        self.event("SessionStart", source="compact")
        self.assertGreaterEqual(self.record()["listener_hook_seen_at"], before)

    def test_compact_without_a_channel_prints_nothing(self) -> None:
        self.pair()
        self.assertEqual(self.event("SessionStart", session="other", source="compact").stdout, "")

    def test_other_session_start_sources_print_nothing(self) -> None:
        self.pair()
        for source in ("startup", "resume", "clear"):
            with self.subTest(source=source):
                self.assertEqual(self.event("SessionStart", source=source).stdout, "")

    def test_beating_seat_is_stamped_silently(self) -> None:
        self.pair()
        before = time.time()
        for event in ("PostToolUse", "UserPromptSubmit"):
            with self.subTest(event=event):
                self.assertEqual(self.event(event).stdout, "")
        self.assertGreaterEqual(self.record()["listener_hook_seen_at"], before)

    def test_stopped_heartbeat_gets_one_reminder_per_minute(self) -> None:
        self.pair()
        self.stop_heartbeat()
        text = self.context(self.event("PostToolUse", tool_name="Bash"), "PostToolUse")
        self.assertTrue(text.startswith("advisor: your heartbeat for channel 0001 (listener) is not running; "
                                        "start it in a new background session: python3 "))
        self.assertIn("heartbeat --channel 0001 --role listener --session s1", text)
        self.assertEqual(self.event("PostToolUse", tool_name="Bash").stdout, "")

    def test_user_prompt_submit_reminds_with_its_own_event_name(self) -> None:
        self.pair()
        self.stop_heartbeat()
        text = self.context(self.event("UserPromptSubmit", prompt="hi"), "UserPromptSubmit")
        self.assertIn("heartbeat --channel 0001", text)

    def test_subagent_call_stamps_but_never_injects(self) -> None:
        self.pair()
        self.stop_heartbeat()
        before = time.time()
        for event, extra in (("PostToolUse", {}), ("UserPromptSubmit", {}), ("SessionStart", {"source": "compact"})):
            with self.subTest(event=event):
                self.assertEqual(self.event(event, agent_id="a1", **extra).stdout, "")
        self.assertGreaterEqual(self.record()["listener_hook_seen_at"], before)

    def test_calls_that_cannot_inject_leave_the_reminder_for_the_next_prompt(self) -> None:
        self.pair()
        self.stop_heartbeat()
        self.event("PostToolUse", agent_id="a1")
        self.event("Stop")
        self.event("SessionStart", source="compact")
        self.assertNotIn("listener_hook_nudged_at", self.record())
        text = self.context(self.event("UserPromptSubmit", prompt="hi"), "UserPromptSubmit")
        self.assertIn("heartbeat --channel 0001", text)

    def test_stop_stamps_and_prints_nothing(self) -> None:
        self.pair()
        self.stop_heartbeat()
        before = time.time()
        result = self.event("Stop")
        self.assertEqual((result.stdout, result.stderr), ("", ""))
        self.assertGreaterEqual(self.record()["listener_hook_seen_at"], before)

    def test_hook_never_writes_the_heartbeat_fields(self) -> None:
        self.pair()
        self.stop_heartbeat()
        before = self.record()
        for event in EVENTS:
            self.event(event, source="compact")
        after = self.record()
        for key in ("listener_seen_at", "updated_at"):
            self.assertEqual(after[key], before[key], key)
        self.assertNotIn("listener_restart_until", after)

    def test_unknown_event_prints_nothing(self) -> None:
        self.pair()
        self.stop_heartbeat()
        self.assertEqual(self.event("PreToolUse").stdout, "")

    def test_malformed_input_exits_zero_silently(self) -> None:
        self.pair()
        for raw in ("", "not json", "[]", "{}", json.dumps({"session_id": "", "hook_event_name": "Stop"}),
                    json.dumps({"session_id": "s1"}), json.dumps({"session_id": 5, "hook_event_name": "Stop"})):
            with self.subTest(raw=raw):
                result = self.hook(None, raw=raw)
                self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_unreadable_record_exits_zero_silently(self) -> None:
        self.pair()
        (self.root / "channels" / "0001" / "channel.json").write_text("{bad")
        for event in EVENTS:
            with self.subTest(event=event):
                result = self.event(event, source="compact")
                self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_missing_root_is_not_created(self) -> None:
        result = self.event("PostToolUse")
        self.assertEqual((result.stdout, result.stderr), ("", ""))
        self.assertFalse(self.root.exists())


class HookManifestTests(unittest.TestCase):
    def assert_manifest(self, path: Path, variable: str) -> None:
        hooks = json.loads(path.read_text())["hooks"]
        self.assertEqual(sorted(hooks), sorted(EVENTS))
        for event in EVENTS:
            with self.subTest(manifest=path.name, event=event):
                commands = [hook["command"] for group in hooks[event] for hook in group["hooks"]]
                self.assertEqual(commands, [f"python3 {variable}/hooks/advisor_hook.py"])
        self.assertEqual([group.get("matcher") for group in hooks["SessionStart"]], ["compact"])
        self.assertEqual([group.get("matcher") for group in hooks["PostToolUse"]], [".*"])

    def test_claude_manifest(self) -> None:
        self.assert_manifest(PLUGIN / "hooks" / "hooks.json", "${CLAUDE_PLUGIN_ROOT}")

    def test_codex_manifest(self) -> None:
        self.assert_manifest(PLUGIN / "hooks" / "codex-hooks.json", "${PLUGIN_ROOT}")

    def test_codex_plugin_names_the_hooks_file(self) -> None:
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["hooks"], "./hooks/codex-hooks.json")


if __name__ == "__main__":
    unittest.main()
