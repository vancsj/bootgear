"""Tests for plugins/deputy/hooks/deputy_hook.py: the reminder per event, and the hook driven
like a host, with JSON on stdin and the hook output on stdout."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
HOOK = PLUGIN / "hooks" / "deputy_hook.py"
CLAUDE_PROMPT = {"session_id": "s1", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp",
                 "permission_mode": "default", "hook_event_name": "UserPromptSubmit", "prompt": "go on"}
CLAUDE_ANSWER = {"session_id": "s1", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp",
                 "permission_mode": "default", "hook_event_name": "PostToolUse",
                 "tool_name": "AskUserQuestion", "tool_input": {"questions": []}, "tool_response": {},
                 "tool_use_id": "toolu_1"}
CODEX_ANSWER = {"session_id": "s1", "turn_id": "t1", "transcript_path": None, "cwd": "/tmp",
                "hook_event_name": "PostToolUse", "model": "gpt-5", "permission_mode": "default",
                "tool_name": "request_user_input", "tool_input": {"questions": []},
                "tool_response": {}, "tool_use_id": "call_1"}


def load_hook():
    spec = importlib.util.spec_from_file_location("deputy_hook", HOOK)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {HOOK}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hook = load_hook()

    def test_user_prompt_gets_the_ask_reminder(self) -> None:
        self.assertEqual(self.hook.reminder({"hook_event_name": "UserPromptSubmit"}), self.hook.ASK)

    def test_an_answered_question_tool_gets_the_record_reminder(self) -> None:
        for tool in ("AskUserQuestion", "request_user_input"):
            with self.subTest(tool=tool):
                payload = {"hook_event_name": "PostToolUse", "tool_name": tool}
                self.assertEqual(self.hook.reminder(payload), self.hook.RECORD)

    def test_other_tools_get_no_reminder(self) -> None:
        for tool in ("request_user_input_async", "Bash"):
            with self.subTest(tool=tool):
                self.assertIsNone(self.hook.reminder({"hook_event_name": "PostToolUse", "tool_name": tool}))

    def test_both_reminders_gate_the_record_call_on_a_session_ledger_file(self) -> None:
        for text in (self.hook.ASK, self.hook.RECORD):
            with self.subTest(text=text[:40]):
                self.assertIn("session ledger file", text)


class HookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "deputy"
        self.root.mkdir()
        self.env = {**os.environ, "LEDGER_DEPUTY_ROOT": str(self.root)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_hook(self, payload: object, raw: str | None = None) -> str:
        result = subprocess.run([sys.executable, str(HOOK)],
                                input=raw if raw is not None else json.dumps(payload),
                                capture_output=True, text=True, check=False, env=self.env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout

    def context(self, payload: dict) -> str:
        output = json.loads(self.run_hook(payload))["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], payload["hook_event_name"])
        return output["additionalContext"]

    def test_claude_prompt_prints_the_ask_reminder(self) -> None:
        self.assertEqual(self.context(CLAUDE_PROMPT), load_hook().ASK)

    def test_claude_answered_question_prints_the_record_reminder(self) -> None:
        self.assertEqual(self.context(CLAUDE_ANSWER), load_hook().RECORD)

    def test_codex_answered_question_prints_the_record_reminder(self) -> None:
        self.assertEqual(self.context(CODEX_ANSWER), load_hook().RECORD)

    def test_the_envelope_is_compact_json_on_one_line(self) -> None:
        out = self.run_hook(CLAUDE_PROMPT)
        self.assertEqual(out.count("\n"), 1)
        self.assertNotIn('": ', out)

    def test_input_that_is_not_an_object_prints_nothing(self) -> None:
        for raw in ("[]", '"UserPromptSubmit"', "not json", ""):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_hook(None, raw=raw), "")

    def test_a_subagent_payload_prints_nothing(self) -> None:
        self.assertEqual(self.run_hook({**CLAUDE_ANSWER, "agent_id": "a1"}), "")

    def test_a_missing_deputy_root_prints_nothing(self) -> None:
        self.root.rmdir()
        for payload in (CLAUDE_PROMPT, CLAUDE_ANSWER, CODEX_ANSWER):
            with self.subTest(event=payload["hook_event_name"], tool=payload.get("tool_name")):
                self.assertEqual(self.run_hook(payload), "")

    def test_an_exception_prints_nothing_and_exits_0(self) -> None:
        hook = load_hook()
        out = io.StringIO()
        with unittest.mock.patch.object(hook, "reminder", side_effect=RuntimeError("boom")), \
                unittest.mock.patch.object(sys, "stdin", io.StringIO(json.dumps(CLAUDE_PROMPT))), \
                unittest.mock.patch.dict(os.environ, {"LEDGER_DEPUTY_ROOT": str(self.root)}), \
                redirect_stdout(out):
            self.assertEqual(hook.main(), 0)
        self.assertEqual(out.getvalue(), "")


class HookFileTests(unittest.TestCase):
    def groups(self, name: str) -> dict[str, list[dict]]:
        return json.loads((PLUGIN / "hooks" / name).read_text(encoding="utf-8"))["hooks"]

    def assert_registers(self, name: str, matcher: str, command: str) -> None:
        groups = self.groups(name)
        self.assertEqual(set(groups), {"UserPromptSubmit", "PostToolUse"})
        prompt, = groups["UserPromptSubmit"]
        answer, = groups["PostToolUse"]
        self.assertNotIn("matcher", prompt)
        self.assertEqual(answer["matcher"], matcher)
        for group in (prompt, answer):
            self.assertEqual(group["hooks"], [{"type": "command", "command": command}])

    def test_claude_hooks_register_the_prompt_and_the_question_tool(self) -> None:
        self.assert_registers("hooks.json", "AskUserQuestion",
                              "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/deputy_hook.py")

    def test_codex_hooks_register_the_prompt_and_the_question_tool(self) -> None:
        self.assert_registers("codex-hooks.json", "request_user_input",
                              "python3 ${PLUGIN_ROOT}/hooks/deputy_hook.py")

    def test_both_hosts_run_the_same_script(self) -> None:
        scripts = set()
        for name in ("hooks.json", "codex-hooks.json"):
            for groups in self.groups(name).values():
                for group in groups:
                    scripts.update(hook["command"].split("}/", 1)[1] for hook in group["hooks"])
        self.assertEqual(scripts, {"hooks/deputy_hook.py"})
        self.assertTrue(HOOK.is_file())


if __name__ == "__main__":
    unittest.main()
