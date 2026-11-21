"""Exercise writing checks and author records through the public executable."""
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
HOST = os.environ.get("BOOTGEAR_TEST_HOST", "claude")
COMMAND = [str(REPO / "plugins" / "cli" / "bin" / "gear"), "--host", HOST,
           "--root", str(REPO), "review", "self-review"]
PROGRAM = shlex.join([COMMAND[0], "--host", HOST, "review", "self-review"])


class SelfReviewTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.task = self.root / "task"
        self.project = self.root / "project"
        self.project.mkdir()

    def call(self, command, data=None, stage="spec", expected=0):
        argv = [*COMMAND, command, "--task-folder", str(self.task),
                "--project-root", str(self.project), "--stage", stage, "--json"]
        if data is not None:
            argv += ["--input", "-"]
        result = subprocess.run(argv, input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def open(self, data=None, stage="spec"):
        return self.call("open", data if data is not None else {"candidates": [], "selections": []}, stage)

    def record(self, number, result="found", stage="spec", refs=None, expected=0):
        return self.call("pass", {"expected_pass": number, "result": result,
                                 "unresolved_refs": refs or []}, stage, expected)

    def source(self, name, mode="absorb", scope="selected phases: authoring; orchestration"):
        return {"name": name, "mode": mode, "scope": scope, "coverage": "Applies to this artifact.",
                "confirmation": {"kind": "user-message", "ref": "conversation:choice-1"}}

    def writing_file(self, text, name="guide.md"):
        source = self.root / name
        source.write_text(text)
        return source

    def writing_check(self, files, kind="procedure", expected=0):
        result = subprocess.run([*COMMAND, "check", "--kind", kind, "--files",
                                 *map(str, files), "--json"],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["check_kind"], "mechanical-writing")
        self.assertEqual(report["kind"], kind)
        self.assertTrue(report["next"])
        return report
