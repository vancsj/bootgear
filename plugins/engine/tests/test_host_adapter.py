import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins" / "engine"
sys.path.insert(0, str(PLUGIN_DIR / "src"))

host_adapter = import_module("engine.host_adapter")
policy = import_module("engine.policy")
session_paths = import_module("engine.session_paths")
AdapterError = host_adapter.AdapterError
HostContext = host_adapter.HostContext
normalize_event = host_adapter.normalize_event

RUNNER = Path(__file__).resolve().parent / "run_host_adapter_fixture.py"


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
                with patch.object(policy, "_ledger_path", return_value=ledger), \
                        patch.object(policy.subprocess, "run", return_value=response) as run, \
                        patch.object(policy, "gear_argv", wraps=policy.gear_argv) as route:
                    self.assertEqual(policy._run_state(context), {"current": "clarify"})
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


class QuestionBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-question-boundary-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.default_dir = self.home / ".bootgear" / "session"
        self.custom_dir = self.tmp / "task" / "session"
        self.custom_dir.mkdir(parents=True)
        self.session_id = "question-run"
        self.ledger = self.custom_dir / f"{self.session_id}.md"
        self.ledger.write_text(
            f"# session: {self.session_id}\n\n"
            "## settlement\n"
            "autonomy:\n  no_further_questions: true\n  permitted_mutations: [tests]\n\n"
            "## state\ncurrent: inspect\nstarted: 2026-11-15 00:00\n",
            encoding="utf-8",
        )
        session_paths.register_session_path(self.session_id, self.custom_dir, self.default_dir)
        self.addCleanup(session_paths.unregister_session_path, self.session_id,
                        self.custom_dir, self.default_dir)

    def _event(self, host, *, record_prompt=False):
        tool_name, matcher = ("AskUserQuestion", "^AskUserQuestion$") if host == "claude" else (
            "request_user_input", "^request_user_input$")
        questions = [{
            "header": "Record" if record_prompt else "Question",
            "question": ("Confirm the canonical record shown above?" if record_prompt
                         else "Should scripts run with uv?"),
            "options": [
                {"label": "Confirm (Recommended)", "description": "Write this record."},
                {"label": "Correct", "description": "Show a new preview."},
            ],
        }]
        if host == "codex":
            questions[0]["id"] = "question"
        payload = {
            "session_id": self.session_id,
            "cwd": str(self.tmp),
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"questions": questions},
            "tool_use_id": "tool-use-1",
        }
        if host == "codex":
            payload["turn_id"] = "turn-1"
            payload["permission_mode"] = "default"
        return normalize_event(host, payload, matcher, "question_boundary")

    def _context(self, event):
        return HostContext(
            host=event.host,
            plugin_root=PLUGIN_DIR,
            source_dir=PLUGIN_DIR / "src",
            hook_dir=PLUGIN_DIR / "hooks",
            cwd=str(self.tmp),
            session_id=self.session_id,
            event=event.hook_event_name,
            matcher_pattern=event.manifest_matcher_pattern,
            matcher_value=event.matcher_value,
            handler_kind=event.handler_kind,
        )

    def test_question_after_cutoff_is_denied_on_both_hosts(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                event = self._event(host)
                with patch.object(Path, "home", return_value=self.home):
                    intent = host_adapter.dispatch_and_apply(event, self._context(event))
                self.assertEqual(host_adapter.render(intent, event).kind, "deny")

    def test_previous_record_exception_cannot_allow_questions_on_either_host(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                marker = self.custom_dir / f".{self.session_id}.question_state"
                marker.write_text('{"kind":"canonical_record","phase":"execute"}', encoding="utf-8")

                event = self._event(host, record_prompt=True)
                with patch.object(Path, "home", return_value=self.home):
                    intent = host_adapter.dispatch_and_apply(event, self._context(event))

                self.assertEqual(host_adapter.render(intent, event).kind, "deny")

    def test_question_before_cutoff_is_allowed_on_both_hosts(self):
        session_paths.unregister_session_path(self.session_id, self.custom_dir, self.default_dir)
        self.ledger.unlink()
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                event = self._event(host, record_prompt=True)
                with patch.object(Path, "home", return_value=self.home):
                    intent = host_adapter.dispatch_and_apply(event, self._context(event))
                self.assertEqual(intent.kind, "observe")

    def test_question_without_an_active_run_is_allowed_on_both_hosts(self):
        self.ledger.write_text(
            f"# session: {self.session_id}\n\n## closed\noutcome: succeeded\n",
            encoding="utf-8",
        )

        for host in ("claude", "codex"):
            with self.subTest(host=host):
                event = self._event(host)
                with patch.object(Path, "home", return_value=self.home):
                    intent = host_adapter.dispatch_and_apply(event, self._context(event))
                self.assertEqual(intent.kind, "observe")

    def test_missing_registered_ledger_fails_closed(self):
        self.ledger.unlink()
        event = self._event("codex")

        with patch.object(Path, "home", return_value=self.home):
            intent = host_adapter.dispatch_and_apply(event, self._context(event))

        self.assertEqual(host_adapter.render(intent, event).kind, "deny")


class SessionRecallAdapterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="host-adapter-session-recall-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.cwd = Path(tmp.name) / "project"
        self.session_dir = self.home / ".bootgear" / "session"
        self.session_dir.mkdir(parents=True)
        (self.cwd / ".bootgear" / "config").mkdir(parents=True)
        (self.cwd / ".bootgear" / "config" / "principles.md").write_text("- project rule\n")
        self.ledger = self.session_dir / "fixture-claude.md"

    def _invoke(self, source: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(PLUGIN_DIR / "hooks" / "adapter.py"),
                "--handler",
                "session_recall",
                "--matcher-pattern",
                "startup|clear|compact",
            ],
            input=json.dumps({
                "session_id": "fixture-claude",
                "cwd": str(cwd or self.cwd),
                "hook_event_name": "SessionStart",
                "source": source,
            }),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.home), "CLAUDE_PLUGIN_ROOT": str(PLUGIN_DIR), "BOOTGEAR_HOST": "claude"},
            check=False,
        )

    def _run(self, source: str = "compact") -> str:
        result = self._invoke(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _context(self, source: str = "compact") -> str:
        return json.loads(self._run(source))["hookSpecificOutput"]["additionalContext"]

    ACTIVE_LEDGER = "## settlement\ngoal: the goal text\n"
    GOAL_AND_PRINCIPLES = (
        "This run's /goal:\nthe goal text\n\n"
        "Merged principles (user/project/task):\n[project]\n- project rule"
    )
    STANDARDS_BLOCK = (
        "Standards (read each file in full before you judge or write):\n"
        "[review-standard] .bootgear/config/review-standard.md: R001 [must], R002 [should]\n"
        "[test-standard] .bootgear/config/test-standard.md: R001 [must]"
    )

    def _write_standards(self):
        config = self.cwd / ".bootgear" / "config"
        (config / "review-standard.md").write_text(
            "    ```text\n    Literal code example.\n    ```\n\n"
            "# review-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst review rule.\n\n## R002 [should]\nSecond review rule.\n"
            "\n```md\n## R003 [must]\nExample rule.\n```\n"
            "\n<!--\n## R004 [must]\nCommented rule.\n-->\n"
        )
        (config / "test-standard.md").write_text(
            "# test-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst test rule.\n"
        )

    def test_active_ledger_adds_recall_context(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        context = self._context()
        self.assertIn("This session just compacted", context)
        self.assertTrue(context.endswith(self.GOAL_AND_PRINCIPLES), context)

    def test_startup_and_clear_sources_are_accepted(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        for source in ("startup", "clear"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), self.GOAL_AND_PRINCIPLES)

    def test_resume_source_is_refused(self):
        result = self._invoke("resume")
        self.assertEqual(result.stdout, "")
        self.assertIn("engine hook adapter: ", result.stderr)

    def test_standard_files_add_the_standards_block_after_the_principles(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        self._write_standards()
        expected = f"{self.GOAL_AND_PRINCIPLES}\n\n{self.STANDARDS_BLOCK}"
        for source in ("startup", "clear"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), expected)
        self.assertTrue(self._context("compact").endswith(expected))

    def test_no_standard_file_omits_the_standards_block(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        for source in ("startup", "clear", "compact"):
            with self.subTest(source=source):
                self.assertNotIn("Standards", self._context(source))

    def test_partial_standard_files_list_only_the_files_with_rules(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        config = self.cwd / ".bootgear" / "config"
        cases = {
            "only review": ("test-standard.md", None, self.STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "only test": (
                "review-standard.md",
                None,
                self.STANDARDS_BLOCK.split("\n", 1)[0] + "\n" + self.STANDARDS_BLOCK.rsplit("\n", 1)[1],
            ),
            "empty file": ("test-standard.md", "", self.STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "unreadable file": ("test-standard.md", b"\xff\xfe", self.STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "no rule heading": (
                "test-standard.md",
                "# test-standard\n",
                self.STANDARDS_BLOCK.rsplit("\n", 1)[0]
                + "\n[test-standard] .bootgear/config/test-standard.md",
            ),
        }
        for name, (file, text, block) in cases.items():
            with self.subTest(case=name):
                self._write_standards()
                if text is None:
                    (config / file).unlink()
                elif isinstance(text, bytes):
                    (config / file).write_bytes(text)
                else:
                    (config / file).write_text(text)
                self.assertEqual(self._context("startup"), f"{self.GOAL_AND_PRINCIPLES}\n\n{block}")

    def test_active_ledger_adds_the_nudge_on_compact_only(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        for source in ("startup", "clear"):
            with self.subTest(source=source):
                context = self._context(source)
                self.assertNotIn("This session just compacted", context)
                self.assertIn("the goal text", context)
        self.assertIn("This session just compacted", self._context("compact"))

    def test_repo_hook_output_fits_the_limit(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        result = self._invoke("startup", cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Standards (read each file in full before you judge or write):", context)
        self.assertLess(len(context), 10000)

    def test_no_ledger_prints_nothing(self):
        self._write_standards()
        for source in ("startup", "clear", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._run(source), "")

    def test_closed_ledger_prints_nothing(self):
        self._write_standards()
        self.ledger.write_text(f"{self.ACTIVE_LEDGER}\n## closed\nsucceeded\n")
        self.assertEqual(self._run(), "")

    def test_closed_text_that_is_not_a_heading_keeps_the_ledger_active(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n\n## notes\nnot ## closed yet\n## closed-loop notes\n")
        context = self._context()
        self.assertIn("This session just compacted", context)
        self.assertIn("the goal text", context)

    def test_unreadable_ledger_prints_nothing(self):
        self.ledger.write_bytes(b"\xff\xfe\x00bad-utf8")
        self.assertEqual(self._run(), "")
