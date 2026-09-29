"""CLI contract tests for Claude built-ins and Bootgear project machines."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
TASK_BIN = PLUGIN_DIR / "bin" / "task"
TASK_TYPES = ("ticket-writing", "bug-triage", "ticket-to-pr", "pr-review")
SKILL_TOKEN = re.compile(r"(?:/|\$)(spec|test|review)\b")


class ClaudeStateMachineTest(unittest.TestCase):
    def _task(self, *args):
        return subprocess.run(
            [str(TASK_BIN), *args],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "BOOTGEAR_OUTPUT": "prose"},
        )

    def _assert_valid_diagram(self, path):
        validated = self._task("state", "validate", str(path))
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertIn(": ok", validated.stdout)

        diagram = self._task("state", "diagram", str(path))
        self.assertEqual(diagram.returncode, 0, diagram.stderr)
        self.assertTrue(diagram.stdout.startswith("stateDiagram-v2\n"))
        self.assertIn("[*] --> clarify", diagram.stdout)
        self.assertIn("succeeded --> [*]", diagram.stdout)

    def test_every_v1_task_type_has_a_valid_claude_builtin(self):
        for task_type in TASK_TYPES:
            self._assert_valid_diagram(
                PLUGIN_DIR / "state-machines" / f"{task_type}.yaml"
            )

    def test_every_v1_task_type_has_a_valid_bootgear_override(self):
        for task_type in TASK_TYPES:
            self._assert_valid_diagram(
                REPO_ROOT / ".bootgear" / "config" / f"state-machine-{task_type}.yaml"
            )

    def test_claude_generic_graphs_match_codex_after_skill_normalization(self):
        for task_type in TASK_TYPES:
            claude = yaml.safe_load(
                (PLUGIN_DIR / "state-machines" / f"{task_type}.yaml").read_text()
            )
            codex = yaml.safe_load(
                (
                    REPO_ROOT
                    / "codex-plugins"
                    / "engine"
                    / "state-machines"
                    / f"{task_type}.yaml"
                ).read_text()
            )
            self.assertEqual(
                self._normalize(claude),
                self._normalize(codex),
                task_type,
            )

    @staticmethod
    def _normalize(machine):
        nodes = {}
        for name, node in machine["nodes"].items():
            normalized = {
                "next": node.get("next", []),
                "terminal": node.get("terminal", False),
                "max_visits": node.get("max_visits"),
            }
            if "reminder" in node:
                reminder = dict(node["reminder"])
                # leave_check names a program resolved per host by state.py,
                # so it is compared verbatim, never token-normalized.
                reminder["leave_check"] = reminder.get("leave_check")
                if "do" in reminder:
                    reminder["do"] = SKILL_TOKEN.sub("<skill>", reminder["do"])
                if "leave" in reminder:
                    reminder["leave"] = SKILL_TOKEN.sub("<skill>", reminder["leave"])
                normalized["reminder"] = reminder
            nodes[name] = normalized
        return {"name": machine["name"], "nodes": nodes}

    def _pr_review_machines(self):
        return [
            PLUGIN_DIR / "state-machines" / "pr-review.yaml",
            REPO_ROOT / ".bootgear" / "config" / "state-machine-pr-review.yaml",
        ]

    def test_pr_review_fixes_in_a_fix_node_with_no_review_self_loop(self):
        for path in self._pr_review_machines():
            nodes = yaml.safe_load(path.read_text())["nodes"]
            self.assertNotIn("review", nodes["review"]["next"], path)
            self.assertIn("fix", nodes["review"]["next"], path)
            self.assertIn("fix", nodes["review-debate"]["next"], path)
            self.assertEqual(nodes["fix"]["next"], ["review"], path)
            self.assertNotIn("max_visits", nodes["review"], path)
            self.assertEqual(nodes["fix"]["max_visits"], 4, path)
            self.assertEqual(nodes["review-debate"]["max_visits"], 3, path)

    def test_pr_review_with_fix_removed_still_validates(self):
        for path in self._pr_review_machines():
            machine = yaml.safe_load(path.read_text())
            nodes = machine["nodes"]
            del nodes["fix"]
            for node in nodes.values():
                if "fix" in (node.get("next") or []):
                    node["next"].remove("fix")
                    node["reminder"]["branches"].pop("fix")
            with tempfile.TemporaryDirectory(prefix="engine-pr-review-no-fix-") as tmp:
                stripped = Path(tmp) / "pr-review.yaml"
                stripped.write_text(yaml.safe_dump(machine, sort_keys=False))
                result = self._task("state", "validate", str(stripped))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_project_override_can_replace_a_builtin_before_settlement(self):
        with tempfile.TemporaryDirectory(prefix="engine-state-override-") as tmp:
            project_root = Path(tmp)
            override = project_root / ".bootgear" / "config" / "state-machine-bug-triage.yaml"
            override.parent.mkdir(parents=True)
            override.write_text(
                "name: project-bug-triage\n"
                "nodes:\n"
                "  clarify:\n"
                "    next: [succeeded]\n"
                "  succeeded:\n"
                "    terminal: true\n"
                "  failed:\n"
                "    terminal: true\n"
            )

            self._assert_valid_diagram(override)

    def test_no_machine_carries_reminder_skill(self):
        paths = [
            REPO_ROOT / host / "engine" / "state-machines" / f"{task_type}.yaml"
            for host in ("plugins", "codex-plugins") for task_type in TASK_TYPES
        ] + [
            REPO_ROOT / ".bootgear" / "config" / f"state-machine-{task_type}.yaml"
            for task_type in TASK_TYPES
        ]
        self.assertEqual(len(paths), 12)
        for path in paths:
            machine = yaml.safe_load(path.read_text())
            for name, node in machine["nodes"].items():
                reminder = (node or {}).get("reminder") or {}
                self.assertNotIn("skill", reminder, f"{path} node '{name}'")

    def test_validate_rejects_removed_reminder_skill(self):
        with tempfile.TemporaryDirectory(prefix="engine-state-skill-") as tmp:
            machine = Path(tmp) / "machine.yaml"
            machine.write_text(
                "name: old-schema\n"
                "nodes:\n"
                "  clarify:\n"
                "    next: [succeeded]\n"
                "    reminder:\n"
                "      do: Draft the spec.\n"
                "      skill: spec\n"
                "  succeeded:\n"
                "    terminal: true\n"
                "  failed:\n"
                "    terminal: true\n"
            )
            result = self._task("state", "validate", str(machine))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                "node 'clarify': `reminder.skill` was removed; name the skill "
                "and how to call it in `reminder.do`",
                result.stdout + result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
