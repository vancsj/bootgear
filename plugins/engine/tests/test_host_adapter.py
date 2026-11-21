import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from host_adapter_test_support import (
    PLUGIN_DIR,
    REPO_ROOT,
    RUNNER,
    AdapterError,
    HostContext,
    host_adapter,
    normalize_event,
    policy,
    state_nudge,
)


class HostAdapterFixtureTest(unittest.TestCase):
    def _run(self, host: str) -> str:
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--host", host],
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": tempfile.mkdtemp(prefix="host-adapter-test-home-")},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_claude_fixture_corpus(self):
        self.assertIn("host-adapter fixtures passed: claude", self._run("claude"))

    def test_codex_fixture_corpus(self):
        self.assertIn("host-adapter fixtures passed: codex", self._run("codex"))

    def test_canonical_fixture_corpus_has_both_hosts(self):
        cases = json.loads(
            (Path(__file__).resolve().parent / "fixtures" / "host_adapter" / "cases.json").read_text()
        )
        self.assertEqual({case["host"] for case in cases}, {"claude", "codex"})

    def test_fixture_runner_checks_the_expected_decision(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "host_adapter" / "cases.json"
        cases = json.loads(fixture_path.read_text())
        case = next(case for case in cases if case["host"] == "claude")
        case["expected"]["decision"] = "continue"
        with tempfile.TemporaryDirectory(prefix="host-adapter-mutated-fixture-") as tmp:
            altered = Path(tmp) / "cases.json"
            altered.write_text(json.dumps([case]))
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--host", "claude", "--fixture", str(altered)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0, "fixture runner ignored expected.decision")


class HostAdapterBoundaryTest(unittest.TestCase):
    @staticmethod
    def _claude_post_tool_input(tool_input):
        return {
            "session_id": "fixture-claude",
            "cwd": "/tmp/fixture-project",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": tool_input,
            "tool_response": {"exit": 0},
        }

    def test_nested_json_value_is_rejected_with_adapter_error(self):
        value = "leaf"
        for _ in range(2000):
            value = [value]
        with self.assertRaises(AdapterError) as raised:
            normalize_event(
                "claude",
                self._claude_post_tool_input(value),
                ".*",
                "state_nudge",
            )
        self.assertEqual(raised.exception.code, "value_too_deep")

    def test_json_parser_depth_failure_is_a_bounded_adapter_error(self):
        nested = b"[" * 2000 + b"0" + b"]" * 2000
        raw = (
            b'{"session_id":"fixture-claude","cwd":"/tmp/fixture-project",'
            b'"hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":'
            + nested
            + b',"tool_response":{}}'
        )
        parsed = host_adapter._parse_json(raw)
        with self.assertRaises(AdapterError) as raised:
            normalize_event("claude", parsed, ".*", "state_nudge")
        self.assertEqual(raised.exception.code, "value_too_deep")

    def test_unknown_host_fields_are_omitted_from_normalized_payload(self):
        raw = self._claude_post_tool_input({"command": "true"})
        raw["future_host_field"] = {"secret": "not-normalized"}
        event = normalize_event("claude", raw, ".*", "state_nudge")
        self.assertNotIn("future_host_field", event.payload)

    def test_malformed_marker_json_is_reported_instead_of_defaulted(self):
        with tempfile.TemporaryDirectory(prefix="host-adapter-marker-") as tmp:
            marker = Path(tmp) / ".session.stop_reminder_state"
            marker.write_text("{truncated")
            with self.assertRaises(AdapterError) as raised:
                policy._read_json(marker, {"nudge_count": 0})
        self.assertEqual(raised.exception.code, "invalid_marker")

    def test_overflowing_marker_number_is_rejected_as_invalid_json(self):
        with tempfile.TemporaryDirectory(prefix="host-adapter-marker-") as tmp:
            marker = Path(tmp) / ".session.stop_reminder_state"
            marker.write_text('{"last_nudge_at":1e9999}')
            with self.assertRaises(AdapterError) as raised:
                policy._read_json(marker, {"last_nudge_at": 0.0})
        self.assertEqual(raised.exception.code, "invalid_marker")

    def test_marker_lock_is_held_when_run_appears_during_policy_evaluation(self):
        with tempfile.TemporaryDirectory(prefix="host-adapter-marker-race-") as tmp:
            home = Path(tmp)
            session_dir = home / ".bootgear" / "session"
            session_dir.mkdir(parents=True)
            ledger = session_dir / "fixture-codex.md"
            marker = session_dir / ".fixture-codex.stop_reminder_state"
            context = HostContext(
                host="codex",
                plugin_root=PLUGIN_DIR,
                source_dir=PLUGIN_DIR / "src",
                hook_dir=PLUGIN_DIR / "hooks",
                cwd="/tmp/fixture-project",
                session_id="fixture-codex",
                event="Stop",
                matcher_pattern=None,
                matcher_value=None,
                handler_kind="stop_reminder",
            )
            event = normalize_event(
                "codex",
                {
                    "session_id": "fixture-codex",
                    "cwd": "/tmp/fixture-project",
                    "hook_event_name": "Stop",
                    "turn_id": "fixture-turn",
                    "stop_hook_active": False,
                },
                "",
                "stop_reminder",
            )
            original_active_ledger = policy._active_ledger

            def activate_run_and_assert_lock(_context):
                ledger.write_text("active run\n")
                lock_fd = os.open(f"{marker}.lock", os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        self.fail("policy evaluation ran without the marker lock")
                finally:
                    os.close(lock_fd)
                return original_active_ledger(_context)

            with patch.dict(os.environ, {"HOME": str(home)}), patch.object(
                policy, "_active_ledger", side_effect=activate_run_and_assert_lock
            ):
                intent = host_adapter.dispatch_and_apply(event, context)

            self.assertEqual(intent.kind, "continue", intent)
            state = json.loads(marker.read_text())
        self.assertEqual(state["turns"], [
            {"turn_id": "fixture-turn", "stop_seen": True, "fallback_reminded": False}
        ])

    def test_state_policy_reads_through_gear_with_the_event_host(self):
        ledger = PLUGIN_DIR / "fixture-session.md"
        response = subprocess.CompletedProcess([], 0, '{"current":"clarify"}', "")
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                context = HostContext(
                    host=host,
                    plugin_root=PLUGIN_DIR,
                    source_dir=PLUGIN_DIR / "src",
                    hook_dir=PLUGIN_DIR / "hooks",
                    cwd="/tmp/fixture-project",
                    session_id="fixture-session",
                    event="PostToolUse",
                    matcher_pattern=None,
                    matcher_value=None,
                    handler_kind="state_nudge",
                )
                with patch.object(state_nudge, "_ledger_path", return_value=ledger), \
                        patch.object(state_nudge.subprocess, "run", return_value=response) as run, \
                        patch.object(state_nudge, "gear_argv", wraps=state_nudge.gear_argv) as route:
                    self.assertEqual(state_nudge._run_state(context), {"current": "clarify"})
                route.assert_called_once_with("engine", "task", host=host)
                argv = run.call_args.args[0]
                self.assertEqual(argv[:5], [str(REPO_ROOT / "plugins" / "cli" / "bin" / "gear"),
                                            "--host", host, "engine", "task"])
                self.assertEqual(argv[5:], ["session", "read", "fixture-session", "--dir",
                                            str(ledger.parent), "--section", "state", "--json"])

    def test_concurrent_codex_stop_updates_hold_the_lock_through_read_and_write(self):
        count = 8
        with tempfile.TemporaryDirectory(prefix="host-adapter-concurrent-") as tmp:
            home = Path(tmp)
            session_dir = home / ".bootgear" / "session"
            session_dir.mkdir(parents=True)
            (session_dir / "fixture-codex.md").write_text("active run\n")
            marker = session_dir / ".fixture-codex.stop_reminder_state"
            context = HostContext(
                host="codex",
                plugin_root=PLUGIN_DIR,
                source_dir=PLUGIN_DIR / "src",
                hook_dir=PLUGIN_DIR / "hooks",
                cwd="/tmp/fixture-project",
                session_id="fixture-codex",
                event="Stop",
                matcher_pattern=None,
                matcher_value=None,
                handler_kind="stop_reminder",
            )
            events = [
                normalize_event(
                    "codex",
                    {
                        "session_id": "fixture-codex",
                        "cwd": "/tmp/fixture-project",
                        "hook_event_name": "Stop",
                        "turn_id": f"turn-{index}",
                        "stop_hook_active": False,
                    },
                    "",
                    "stop_reminder",
                )
                for index in range(count)
            ]
            original_read = policy._read_json

            def assert_lock_held(path, default):
                if path == marker:
                    lock_fd = os.open(f"{path}.lock", os.O_CREAT | os.O_RDWR, 0o600)
                    try:
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            pass
                        else:
                            fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            self.fail("marker was read without the invocation lock")
                    finally:
                        os.close(lock_fd)
                return original_read(path, default)

            with patch.dict(os.environ, {"HOME": str(home)}), patch.object(
                policy, "_read_json", side_effect=assert_lock_held
            ):
                barrier = threading.Barrier(count)

                def invoke(event):
                    barrier.wait()
                    return host_adapter.dispatch_and_apply(event, context)

                with ThreadPoolExecutor(max_workers=count) as pool:
                    intents = list(pool.map(invoke, events))

            state = json.loads(marker.read_text())
        self.assertEqual(len(state["turns"]), count)
        self.assertEqual(
            {turn["turn_id"] for turn in state["turns"]},
            {f"turn-{index}" for index in range(count)},
        )
        self.assertTrue(
            all(intent.kind in {"observe", "add_context", "continue"} for intent in intents)
        )
