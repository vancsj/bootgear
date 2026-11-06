"""Behavior checks for both hosts. Test standard: R001 and R004; review standard: R006."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_deputy_hook import HOOK, load_hook


class ReminderCadenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.root = self.base / "deputy"
        self.root.mkdir()
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / ".git").mkdir()
        self.sequence = 0

    def config(self, host: str, text: str, project: Path | None = None) -> Path:
        directory = project / ".bootgear/config" if project else self.home / f".{host}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "deputy.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def event(self, host: str, *, session: str = "s1", event: str = "PostToolUse",
              question: bool = False, cwd: Path | None = None, agent_id: str = "") -> dict:
        self.sequence += 1
        tool = ("AskUserQuestion" if host == "claude" else "request_user_input") if question else "Bash"
        payload = {"hook_event_name": event, "session_id": session,
                   "cwd": str(cwd or self.project), "tool_name": tool,
                   "tool_use_id": f"call_{self.sequence}", "tool_input": {}, "tool_response": {}}
        if agent_id:
            payload["agent_id"] = agent_id
        return payload

    def run_hook(self, host: str, payload: dict, *, now: float = 1000) -> tuple[str, str]:
        output, errors = io.StringIO(), io.StringIO()
        env = {"HOME": str(self.home), "BOOTGEAR_HOST": host, "LEDGER_DEPUTY_ROOT": str(self.root)}
        with patch.dict(os.environ, env), patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                patch.object(time, "time", return_value=now), redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(load_hook().main(), 0)
        raw = output.getvalue()
        if not raw:
            return "", errors.getvalue()
        self.assertEqual(raw.count("\n"), 1)
        envelope = json.loads(raw)["hookSpecificOutput"]
        self.assertEqual(envelope["hookEventName"], payload["hook_event_name"])
        return envelope["additionalContext"], errors.getvalue()

    def context(self, host: str, payload: dict, *, now: float = 1000) -> str:
        context, errors = self.run_hook(host, payload, now=now)
        self.assertEqual(errors, "")
        return context

    def calls(self, host: str, count: int, *, now: float = 1000, session: str = "s1",
              cwd: Path | None = None) -> list[str]:
        return [self.context(host, self.event(host, session=session, cwd=cwd), now=now) for _ in range(count)]

    def assert_ask(self, text: str) -> None:
        self.assertIn("`deputy:ask`", text)

    def assert_record_only(self, text: str) -> None:
        self.assertIn("`deputy:record`", text)
        self.assertNotIn(load_hook().ASK, text)
        self.assertIn("session ledger file", text)

    def test_first_ask_is_on_the_tenth_observed_completion(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.assertEqual(self.calls(host, 9), [""] * 9)
                text = self.calls(host, 1)[0]
                self.assert_ask(text)
                self.assertNotIn("`deputy:record`", text)

    def test_elapsed_time_does_not_replace_the_call_threshold(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.assert_ask(self.calls(host, 10)[-1])
                self.assertEqual(self.calls(host, 9, now=1300), [""] * 9)
                self.assert_ask(self.calls(host, 1, now=1300)[0])

    def test_count_accumulates_until_the_cooldown_boundary(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.assert_ask(self.calls(host, 10)[-1])
                self.assertEqual(self.calls(host, 15, now=1299), [""] * 15)
                self.assert_ask(self.calls(host, 1, now=1300)[0])
                self.assertEqual(self.calls(host, 9, now=1600), [""] * 9)
                self.assert_ask(self.calls(host, 1, now=1600)[0])

    def test_prompts_record_without_counting_or_resetting(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.assertEqual(self.calls(host, 9), [""] * 9)
                prompt = self.event(host, event="UserPromptSubmit")
                self.assert_record_only(self.context(host, prompt))
                self.assert_ask(self.calls(host, 1)[0])
                self.assertEqual(self.calls(host, 9, now=1299), [""] * 9)
                self.assert_record_only(self.context(host, prompt, now=1299))
                self.assert_ask(self.calls(host, 1, now=1300)[0])

    def test_question_returns_record_and_count_once(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                question = self.event(host, question=True)
                self.assert_record_only(self.context(host, question))
                self.assertEqual(self.calls(host, 8), [""] * 8)
                text = self.context(host, self.event(host, question=True))
                self.assert_ask(text)
                self.assertEqual(text.count("`deputy:record`"), 1)
                self.assertEqual(text.count(load_hook().ASK), 1)
                self.assertEqual(self.calls(host, 9, now=1300), [""] * 9)
                self.assert_ask(self.calls(host, 1, now=1300)[0])

    def test_codex_async_question_return_records(self) -> None:
        payload = self.event("codex", question=True)
        payload["tool_name"] = "request_user_input_async"
        self.assert_record_only(self.context("codex", payload))

    def test_sessions_and_hosts_have_independent_counters(self) -> None:
        for host in ("claude", "codex"):
            for session in ("one", "two"):
                with self.subTest(host=host, session=session):
                    self.assertEqual(self.calls(host, 9, session=session), [""] * 9)
        for host in ("claude", "codex"):
            for session in ("one", "two"):
                with self.subTest(host=host, session=session):
                    self.assert_ask(self.calls(host, 1, session=session)[0])

    def test_concurrent_completions_emit_one_ask(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                env = {**os.environ, "HOME": str(self.home), "BOOTGEAR_HOST": host,
                       "LEDGER_DEPUTY_ROOT": str(self.root)}
                payloads = [self.event(host) for _ in range(10)]

                def invoke(payload: dict, selected_host: str = host,
                           selected_env: dict[str, str] = env) -> subprocess.CompletedProcess[str]:
                    return subprocess.run([sys.executable, str(HOOK), "--host", selected_host],
                                          input=json.dumps(payload), capture_output=True,
                                          text=True, check=False, env=selected_env, timeout=10)

                with ThreadPoolExecutor(max_workers=10) as pool:
                    results = list(pool.map(invoke, payloads))
                contexts = []
                for result in results:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    if result.stdout:
                        contexts.append(json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])
                self.assertEqual(contexts, [load_hook().ASK])

    def test_explicit_host_overrides_shared_host_context(self) -> None:
        self.config("claude", "ask_reminder:\n  tool_calls: 20\n")
        self.config("codex", "ask_reminder:\n  tool_calls: 1\n")
        env = {**os.environ, "HOME": str(self.home), "BOOTGEAR_HOST": "claude",
               "LEDGER_DEPUTY_ROOT": str(self.root)}
        result = subprocess.run([sys.executable, str(HOOK), "--host", "codex"],
                                input=json.dumps(self.event("codex")), capture_output=True,
                                text=True, check=False, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assert_ask(text)

    def test_cli_usage_error_shows_a_correct_example_without_touching_state(self) -> None:
        env = {**os.environ, "HOME": str(self.home), "LEDGER_DEPUTY_ROOT": str(self.root)}
        result = subprocess.run([sys.executable, str(HOOK), "--host"], input="{}",
                                capture_output=True, text=True, check=False, env=env, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("example:", result.stderr)
        self.assertIn("commands:", result.stderr)
        self.assertFalse((self.base / ".deputy-reminder-state").exists())

    def test_relative_payload_cwd_uses_gear_caller_directory(self) -> None:
        self.config("claude", "ask_reminder:\n  tool_calls: 1\n", self.project)
        for host in ("claude", "codex"):
            with self.subTest(host=host), patch.dict(os.environ, {"GEAR_CALLER_CWD": str(self.project)}):
                payload = self.event(host)
                payload["cwd"] = "."
                self.assert_ask(self.context(host, payload))

    def test_shared_session_context_is_a_fallback_for_payload_identity(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host), patch.dict(os.environ, {"BOOTGEAR_SESSION_ID": "shared-session"}):
                self.config(host, "ask_reminder:\n  tool_calls: 2\n")
                payload = self.event(host)
                payload.pop("session_id")
                self.assertEqual(self.context(host, payload), "")
                self.assert_ask(self.context(host, payload))
                self.assertEqual(self.calls(host, 1), [""])
                self.assert_ask(self.calls(host, 1)[0])

    def test_subagent_events_neither_emit_nor_count(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                for event in ("PostToolUse", "UserPromptSubmit"):
                    for _ in range(10):
                        payload = self.event(host, event=event, question=True, agent_id="child")
                        self.assertEqual(self.context(host, payload), "")
                self.assertEqual(self.calls(host, 9), [""] * 9)
                self.assert_ask(self.calls(host, 1)[0])

    def test_host_user_config_sets_both_positive_limits(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.config(host, "ask_reminder:\n  tool_calls: 2\n  cooldown_seconds: 20\n")
                self.assertEqual(self.calls(host, 1), [""])
                self.assert_ask(self.calls(host, 1)[0])
                self.assertEqual(self.calls(host, 2, now=1019), [""] * 2)
                self.assert_ask(self.calls(host, 1, now=1020)[0])

    def test_hosts_read_only_their_own_user_config(self) -> None:
        self.config("claude", "ask_reminder:\n  tool_calls: 2\n")
        self.config("codex", "ask_reminder:\n  tool_calls: 3\n")
        self.assertEqual(self.calls("claude", 1), [""])
        self.assert_ask(self.calls("claude", 1)[0])
        self.assertEqual(self.calls("codex", 2), [""] * 2)
        self.assert_ask(self.calls("codex", 1)[0])

    def test_record_does_not_require_session_identity(self) -> None:
        for host in ("claude", "codex"):
            for event in ("PostToolUse", "UserPromptSubmit"):
                with self.subTest(host=host, event=event):
                    payload = self.event(host, event=event, question=True)
                    payload.pop("session_id")
                    self.assert_record_only(self.context(host, payload))

    def test_project_override_keeps_omitted_host_user_value(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.config(host, "ask_reminder:\n  tool_calls: 4\n  cooldown_seconds: 20\n")
                self.config(host, "ask_reminder:\n  tool_calls: 2\n", self.project)
                nested = self.project / "src/deep"
                nested.mkdir(parents=True, exist_ok=True)
                self.assertEqual(self.calls(host, 1, cwd=nested), [""])
                self.assert_ask(self.calls(host, 1, cwd=nested)[0])
                self.assertEqual(self.calls(host, 2, cwd=nested, now=1019), [""] * 2)
                self.assert_ask(self.calls(host, 1, cwd=nested, now=1020)[0])

    def test_nearest_config_wins_without_merging_project_ancestors(self) -> None:
        self.config("claude", "ask_reminder:\n  tool_calls: 8\n  cooldown_seconds: 20\n", self.project)
        nested = self.project / "nested"
        self.config("claude", "ask_reminder:\n  tool_calls: 2\n", nested)
        deeper = nested / "src"
        deeper.mkdir()
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.assertEqual(self.calls(host, 1, cwd=deeper), [""])
                self.assert_ask(self.calls(host, 1, cwd=deeper)[0])
                self.assertEqual(self.calls(host, 2, cwd=deeper, now=1020), [""] * 2)
                self.assert_ask(self.calls(host, 1, cwd=deeper, now=1300)[0])

    def test_git_directory_and_worktree_file_stop_parent_config_search(self) -> None:
        self.config("claude", "ask_reminder:\n  tool_calls: 1\n", self.base)
        for boundary in ("directory", "file"):
            project = self.base / boundary
            project.mkdir()
            if boundary == "directory":
                (project / ".git").mkdir()
            else:
                (project / ".git").write_text("gitdir: /unused\n", encoding="utf-8")
            nested = project / "src"
            nested.mkdir()
            for host in ("claude", "codex"):
                with self.subTest(boundary=boundary, host=host):
                    session = boundary
                    self.assertEqual(self.calls(host, 9, session=session, cwd=nested), [""] * 9)
                    self.assert_ask(self.calls(host, 1, session=session, cwd=nested)[0])

    def test_invalid_config_reports_and_preserves_counter_while_record_survives(self) -> None:
        invalid = ("ask_reminder:\n  tool_calls: 0\n", "ask_reminder:\n  cooldown_seconds: -1\n",
                   "ask_reminder:\n  tool_calls: true\n", "ask_reminder:\n  tool_calls: '2'\n",
                   "ask_reminder: []\n", "ask_reminder: [\n")
        for host in ("claude", "codex"):
            for index, text in enumerate(invalid):
                with self.subTest(host=host, config=text):
                    session = f"invalid-{index}"
                    self.assertEqual(self.calls(host, 9, session=session), [""] * 9)
                    path = self.config(host, text)
                    before = {p.relative_to(self.base): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
                    output, errors = self.run_hook(host, self.event(host, session=session))
                    self.assertEqual(output, "")
                    self.assertIn("deputy", errors.lower())
                    self.assertTrue(errors.strip())
                    output, errors = self.run_hook(host, self.event(host, session=session, question=True))
                    self.assert_record_only(output)
                    self.assertTrue(errors.strip())
                    after = {p.relative_to(self.base): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
                    self.assertEqual(after, before)
                    path.unlink()
                    self.assert_ask(self.calls(host, 1, session=session)[0])

    def test_missing_root_stays_absent_and_silent(self) -> None:
        self.root.rmdir()
        for host in ("claude", "codex"):
            for event in ("PostToolUse", "UserPromptSubmit"):
                with self.subTest(host=host, event=event):
                    self.assertEqual(self.context(host, self.event(host, event=event, question=True)), "")
        self.assertFalse(self.root.exists())
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["home", "project"])

    def test_claude_failures_count_without_recording_failed_questions(self) -> None:
        self.assertEqual(self.calls("claude", 8), [""] * 8)
        failed_question = self.event("claude", event="PostToolUseFailure", question=True)
        failed_question.pop("tool_response")
        failed_question["error"] = "Tool execution failed"
        self.assertEqual(self.context("claude", failed_question), "")
        failure = self.event("claude", event="PostToolUseFailure")
        failure.pop("tool_response")
        failure["error"] = "Tool execution failed"
        text = self.context("claude", failure)
        self.assert_ask(text)
        self.assertNotIn("`deputy:record`", text)


if __name__ == "__main__":
    unittest.main()
