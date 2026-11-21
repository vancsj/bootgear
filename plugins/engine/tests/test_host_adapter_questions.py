import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from host_adapter_test_support import (
    PLUGIN_DIR,
    HostContext,
    host_adapter,
    normalize_event,
    policy,
    session_paths,
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
        self.ledgers = {}
        for host in ("claude", "codex"):
            session_id = f"question-run-{host}"
            ledger = self.custom_dir / f"{session_id}.md"
            ledger.write_text(
                f"# session: {session_id}\n\n"
                "## settlement\n"
                "autonomy:\n  no_further_questions: true\n  permitted_mutations: [tests]\n\n"
                "## state\ncurrent: inspect\nstarted: 2026-11-15 00:00\n",
                encoding="utf-8",
            )
            self.ledgers[host] = ledger
            session_paths.register_session_path(session_id, self.custom_dir, self.default_dir)
            self.addCleanup(session_paths.unregister_session_path, session_id,
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
            "session_id": self.ledgers[host].stem,
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
            session_id=event.session_id,
            event=event.hook_event_name,
            matcher_pattern=event.manifest_matcher_pattern,
            matcher_value=event.matcher_value,
            handler_kind=event.handler_kind,
        )

    def _ask(self, host, *, record_prompt=False):
        event = self._event(host, record_prompt=record_prompt)
        intent = host_adapter.dispatch_and_apply(event, self._context(event))
        return host_adapter.render(intent, event)

    def test_question_reminds_then_allows_one_revised_retry_on_both_hosts(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                with patch.object(Path, "home", return_value=self.home):
                    first = self._ask(host)
                    retry = self._ask(host, record_prompt=True)
                    after_retry = self._ask(host)
                self.assertEqual((first.kind, retry.kind, after_retry.kind), ("deny", "observe", "deny"))
                reason = json.loads(first.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("Engine run", reason)
                self.assertIn("no_further_questions", reason)
                self.assertIn("30 seconds", reason)

    def test_expired_retry_opens_a_fresh_window_on_both_hosts(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host), patch.object(Path, "home", return_value=self.home), patch.object(
                policy.time, "monotonic", side_effect=[100.0, 131.0, 161.0]
            ):
                decisions = [self._ask(host).kind for _ in range(3)]
                self.assertEqual(decisions, ["deny", "deny", "observe"])

    def test_overlapping_calls_share_one_retry_on_both_hosts(self):
        def ask(host, barrier):
            barrier.wait(timeout=5)
            return self._ask(host).kind

        for host in ("claude", "codex"):
            with self.subTest(host=host), patch.object(Path, "home", return_value=self.home):
                self.assertEqual(self._ask(host).kind, "deny")
                barrier = threading.Barrier(2)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    decisions = list(pool.map(ask, (host, host), (barrier, barrier)))
                self.assertCountEqual(decisions, ["observe", "deny"])

    def test_previous_record_exception_cannot_allow_questions_on_either_host(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                marker = self.custom_dir / f".{self.ledgers[host].stem}.question_state"
                marker.write_text('{"kind":"canonical_record","phase":"execute"}', encoding="utf-8")

                event = self._event(host, record_prompt=True)
                with patch.object(Path, "home", return_value=self.home):
                    intent = host_adapter.dispatch_and_apply(event, self._context(event))

                self.assertEqual(host_adapter.render(intent, event).kind, "deny")

    def test_question_before_cutoff_is_allowed_on_both_hosts(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                ledger = self.ledgers[host]
                session_paths.unregister_session_path(ledger.stem, self.custom_dir, self.default_dir)
                ledger.unlink()
                event = self._event(host, record_prompt=True)
                with patch.object(Path, "home", return_value=self.home):
                    intent = host_adapter.dispatch_and_apply(event, self._context(event))
                self.assertEqual(intent.kind, "observe")

    def test_question_without_an_active_run_is_allowed_on_both_hosts(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                ledger = self.ledgers[host]
                ledger.write_text(
                    f"# session: {ledger.stem}\n\n## closed\noutcome: succeeded\n",
                    encoding="utf-8",
                )
                event = self._event(host)
                with patch.object(Path, "home", return_value=self.home):
                    intent = host_adapter.dispatch_and_apply(event, self._context(event))
                self.assertEqual(intent.kind, "observe")

    def test_missing_registered_ledger_fails_closed(self):
        self.ledgers["codex"].unlink()
        event = self._event("codex")

        with patch.object(Path, "home", return_value=self.home):
            intent = host_adapter.dispatch_and_apply(event, self._context(event))

        self.assertEqual(host_adapter.render(intent, event).kind, "deny")
