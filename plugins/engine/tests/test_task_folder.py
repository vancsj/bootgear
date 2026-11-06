"""Exercise bound authoring identity through the public task command."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from settlement_fixture import valid_settlement

PLUGIN = Path(__file__).resolve().parents[1]
TASK = PLUGIN / ("bin/task" if (PLUGIN / "bin/task").exists() else "scripts/task")
MACHINE = """name: binding
nodes:
  clarify:
    reminder:
      leave: The folder is bound.
      exit_checks:
        succeeded:
          argv: [python3, "{probe}", "{task_folder}"]
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""


class TaskFolderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sessions = self.root / "sessions"
        self.folder = self.root / "task"
        self.ledger = self.sessions / "bound.md"
        self.env = {k: v for k, v in os.environ.items()
                    if k not in {"GEAR_CALLER_CWD", "PLUGIN_ROOT", "BOOTGEAR_SESSION_ID",
                                 "CLAUDE_CODE_SESSION_ID", "VIRTUAL_ENV"}}

    def command(self, *args):
        return subprocess.run([str(TASK), *args, "--dir", str(self.sessions), "--prose"],
                              cwd=self.root, env=self.env, text=True,
                              capture_output=True, check=False)

    def settlement(self, task_type="ticket-to-pr", folder=None, extra=""):
        text = valid_settlement(MACHINE, extra=extra)
        text = "\n".join(line for line in text.splitlines()
                         if not line.startswith("task_folder:")) + "\n"
        text = text.replace("task_type: ticket-to-pr", f"task_type: {task_type}", 1)
        if folder is not None:
            text += f"\ntask_folder: {json.dumps(str(folder))}\n"
        return text

    def init(self, text=None):
        path = self.root / "settlement.yaml"
        path.write_text(text if text is not None else self.settlement(folder=self.folder))
        return self.command("session", "init", "bound", "--settlement-file", str(path))

    def test_authoring_types_require_the_binding_before_any_write(self):
        for kind in ("ticket-to-pr", "change-review"):
            with self.subTest(kind=kind):
                result = self.init(self.settlement(kind))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("task_folder", result.stderr)
                self.assertFalse(self.ledger.exists())

    def test_init_creates_and_canonicalises_the_folder(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        result = self.init(self.settlement(folder=alias / "task"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.folder.is_dir())
        body = self.ledger.read_text().split("## settlement\n", 1)[1].split("\n## decisions", 1)[0]
        self.assertEqual(yaml.safe_load(body)["task_folder"], str(self.folder))
        self.assertIn("state_machine: |", body)

    def test_other_invalid_fields_prevent_directory_creation(self):
        result = self.init(self.settlement(folder=self.folder, extra="debate_mode: invalid\n"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.folder.exists())
        self.assertFalse(self.ledger.exists())

    def test_invalid_folder_and_other_field_are_reported_together(self):
        result = self.init(self.settlement(folder="relative/task", extra="debate_mode: invalid\n"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task_folder", result.stderr)
        self.assertIn("debate_mode", result.stderr)
        self.assertFalse(self.ledger.exists())

    def test_file_cannot_be_a_task_folder(self):
        self.folder.write_text("keep\n")
        result = self.init()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task_folder", result.stderr)
        self.assertEqual(self.folder.read_text(), "keep\n")

    def test_binding_cannot_be_amended(self):
        result = self.init()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.ledger.read_bytes()
        result = self.command("session", "record-decision", "bound", "--mode", "solo",
                              "--summary", f"AMENDMENT task_folder: {self.folder} -> {self.root / 'other'}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task_folder", result.stderr)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_exit_uses_bound_folder_and_refuses_even_matching_caller_override(self):
        result = self.init()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / "argv.json"
        probe = self.root / "probe.py"
        probe.write_text("import json,sys\nfrom pathlib import Path\n"
                         f"Path({str(output)!r}).write_text(json.dumps(sys.argv[1:]))\n")
        args = ("state", "transition", "bound", "--to", "succeeded", "--reason", "checked",
                "--confirm-leave", "--leave-arg", f"probe={probe}")
        before = self.ledger.read_bytes()
        refused = self.command(*args, "--leave-arg", f"task_folder={self.folder}")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("reserved", refused.stderr)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse(output.exists())
        accepted = self.command(*args)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(output.read_text()), [str(self.folder)])
