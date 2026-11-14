import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
RUNNER = PLUGIN_DIR / "tests" / "run_host_adapter_fixture.py"
sys.path.insert(0, str(PLUGIN_DIR / "src"))

host_adapter = import_module("engine.host_adapter")
policy = import_module("engine.policy")

HostContext = host_adapter.HostContext


class CodexHostAdapterFixtureTest(unittest.TestCase):
    def test_codex_fixture_corpus_is_collected_and_runs(self):
        with tempfile.TemporaryDirectory(prefix="codex-host-adapter-test-home-") as home:
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--host", "codex"],
                capture_output=True,
                text=True,
                env={**os.environ, "HOME": home},
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("host-adapter fixtures passed: codex", result.stdout)


IDENTITY = (
    "Codex session_id: fixture-codex. It is the engine run id. Engine commands read it "
    "from the session environment; omit <run-id> and never generate a replacement."
)
ACTIVE_LEDGER = "## settlement\ngoal: the goal text\n"
GOAL_AND_PRINCIPLES = (
    "This run's goal:\nthe goal text\n\n"
    "Merged principles (user/project/task):\n[project]\n- project rule"
)
RECALL = f"{IDENTITY}\n\n{GOAL_AND_PRINCIPLES}"
STANDARDS_BLOCK = (
    "Standards (read each file in full before you judge or write):\n"
    "[review-standard] .bootgear/config/review-standard.md: R001 [must], R002 [should]\n"
    "[test-standard] .bootgear/config/test-standard.md: R001 [must]"
)


class CodexSessionRecallAdapterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="codex-host-adapter-session-recall-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.cwd = Path(tmp.name) / "project"
        self.session_dir = self.home / ".bootgear" / "session"
        self.session_dir.mkdir(parents=True)
        (self.cwd / ".bootgear" / "config").mkdir(parents=True)
        (self.cwd / ".bootgear" / "config" / "principles.md").write_text("- project rule\n")
        self.ledger = self.session_dir / "fixture-codex.md"

    def _context(self, source: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            [
                sys.executable,
                str(PLUGIN_DIR / "hooks" / "adapter.py"),
                "--handler",
                "session_recall",
                "--matcher-pattern",
                "^(startup|resume|clear|compact|fork)$",
            ],
            input=json.dumps({
                "session_id": "fixture-codex",
                "cwd": str(cwd or self.cwd),
                "hook_event_name": "SessionStart",
                "source": source,
            }),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.home), "PLUGIN_ROOT": str(PLUGIN_DIR)},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def _write_standards(self):
        config = self.cwd / ".bootgear" / "config"
        (config / "review-standard.md").write_text(
            "# review-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst review rule.\n\n## R002 [should]\nSecond review rule.\n"
        )
        (config / "test-standard.md").write_text(
            "# test-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst test rule.\n"
        )

    def test_standard_files_add_the_standards_block_after_the_principles(self):
        self.ledger.write_text(ACTIVE_LEDGER)
        self._write_standards()
        for source in ("startup", "resume"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), f"{RECALL}\n\n{STANDARDS_BLOCK}")
        self.assertTrue(
            self._context("compact").endswith(f"{RECALL}\n\n{STANDARDS_BLOCK}")
        )

    def test_no_standard_file_omits_the_standards_block(self):
        self.ledger.write_text(ACTIVE_LEDGER)
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertNotIn("Standards", self._context(source))

    def test_partial_standard_files_list_only_the_files_with_rules(self):
        self.ledger.write_text(ACTIVE_LEDGER)
        config = self.cwd / ".bootgear" / "config"
        cases = {
            "only review": ("test-standard.md", None, STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "only test": (
                "review-standard.md",
                None,
                STANDARDS_BLOCK.split("\n", 1)[0] + "\n" + STANDARDS_BLOCK.rsplit("\n", 1)[1],
            ),
            "empty file": ("test-standard.md", "", STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "unreadable file": ("test-standard.md", b"\xff\xfe", STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "no rule heading": (
                "test-standard.md",
                "# test-standard\n",
                STANDARDS_BLOCK.rsplit("\n", 1)[0]
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
                self.assertEqual(self._context("startup"), f"{RECALL}\n\n{block}")

    def test_repo_hook_output_fits_the_limit(self):
        self.ledger.write_text(ACTIVE_LEDGER)
        context = self._context("startup", cwd=REPO_ROOT)
        self.assertIn("Standards (read each file in full before you judge or write):", context)
        self.assertLess(len(context), 10000)

    def test_active_ledger_adds_nudge_on_compact_with_goal_and_principles(self):
        self.ledger.write_text(ACTIVE_LEDGER)
        context = self._context("compact")
        self.assertIn("This session just compacted", context)
        self.assertIn(" session recall --dir <session-dir> before anything else", context)
        self.assertTrue(context.endswith(RECALL), context)

    def test_no_ledger_emits_identity_only(self):
        self._write_standards()
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), IDENTITY)

    def test_closed_ledger_emits_identity_only(self):
        self._write_standards()
        self.ledger.write_text(f"{ACTIVE_LEDGER}\n## closed\nsucceeded\n")
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), IDENTITY)

    def test_active_ledger_on_startup_and_resume_adds_goal_without_the_nudge(self):
        self.ledger.write_text(ACTIVE_LEDGER)
        for source in ("startup", "resume"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), RECALL)

    def test_closed_text_that_is_not_a_heading_keeps_the_ledger_active(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n\n## notes\nnot ## closed yet\n## closed-loop notes\n")
        context = self._context("compact")
        self.assertIn("This session just compacted", context)
        self.assertIn("the goal text", context)

    def test_unreadable_ledger_emits_identity_only(self):
        self.ledger.write_bytes(b"\xff\xfe\x00bad-utf8")
        self.assertEqual(self._context("compact"), IDENTITY)


class ActiveStatePolicyRoutingTest(unittest.TestCase):
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
