"""CLI contract tests for host and Bootgear task-type state machines."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"
REPO_ROOT = PLUGIN_DIR.parents[1]
TASK_TYPES = ("ticket-writing", "ticket-to-pr", "triage", "change-review", "design-doc")
# design-doc has no Bootgear override.
OVERRIDE_TYPES = ("change-review", "ticket-to-pr", "triage", "ticket-writing")
# Machines whose review node runs spec-review: (review node, drafting node, debate node, exit).
# A ready review with `inline` patches leaves the drafting node by the exit.
SPEC_REVIEW_GRAPHS = {
    "ticket-to-pr": ("spec-review", "spec", "spec-debate", "impl"),
    "design-doc": ("spec-review", "spec", "spec-debate", "succeeded"),
    "ticket-writing": ("ticket-review", "ticket", "ticket-debate", "succeeded"),
}
SKILL_TOKEN = re.compile(r"(?:/|\$)(spec|test|review)\b")


class BuiltInStateMachineTest(unittest.TestCase):
    def _task(self, *args):
        return subprocess.run(
            [str(TASK_BIN), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_every_v1_task_type_has_a_valid_diagrammable_machine(self):
        for task_type in TASK_TYPES:
            path = PLUGIN_DIR / "state-machines" / f"{task_type}.yaml"
            self.assertTrue(path.is_file(), path)

            validated = self._task("state", "validate", str(path))
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn(": ok", validated.stdout)

            diagram = self._task("state", "diagram", str(path))
            self.assertEqual(diagram.returncode, 0, diagram.stderr)
            self.assertTrue(diagram.stdout.startswith("stateDiagram-v2\n"))
            self.assertIn("[*] --> clarify", diagram.stdout)
            self.assertIn("succeeded --> [*]", diagram.stdout)

    def test_every_v1_task_type_has_a_valid_bootgear_override(self):
        for task_type in OVERRIDE_TYPES:
            path = REPO_ROOT / ".bootgear" / "config" / f"state-machine-{task_type}.yaml"
            self.assertTrue(path.is_file(), path)

            validated = self._task("state", "validate", str(path))
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertIn(": ok", validated.stdout)

            diagram = self._task("state", "diagram", str(path))
            self.assertEqual(diagram.returncode, 0, diagram.stderr)
            self.assertTrue(diagram.stdout.startswith("stateDiagram-v2\n"))
            self.assertIn("[*] --> clarify", diagram.stdout)
            self.assertIn("succeeded --> [*]", diagram.stdout)

    def test_claude_generic_graphs_match_codex_after_skill_normalization(self):
        for task_type in TASK_TYPES:
            claude = yaml.safe_load(
                (
                    REPO_ROOT
                    / "plugins"
                    / "engine"
                    / "state-machines"
                    / f"{task_type}.yaml"
                ).read_text()
            )
            codex = yaml.safe_load(
                (PLUGIN_DIR / "state-machines" / f"{task_type}.yaml").read_text()
            )
            self.assertEqual(
                self._normalize(claude),
                self._normalize(codex),
                task_type,
            )

    def test_spec_review_is_the_only_gate_before_the_exit(self):
        for machine_path, (review_name, draft, debate, exit_node) in self._spec_review_machines():
            with self.subTest(machine=str(machine_path)):
                nodes = yaml.safe_load(machine_path.read_text())["nodes"]
                review = nodes[review_name]
                self.assertEqual(nodes[draft]["next"], [review_name, exit_node])
                self.assertEqual(review["max_visits"], 5)
                self.assertIn(exit_node, review["next"])
                for name, node in nodes.items():
                    if name not in (draft, review_name):
                        self.assertNotIn(exit_node, node.get("next", []), f"node '{name}'")
                branch = nodes[draft]["reminder"]["branches"][exit_node]
                self.assertIn(f"ready {review_name}", branch)
                self.assertIn("`inline`", branch)
                self.assertEqual(nodes[debate]["next"], [draft])
                self.assertIn("leave_check", review["reminder"])
        for machine_path in self._ticket_writing_machines():
            nodes = yaml.safe_load(machine_path.read_text())["nodes"]
            for name in ("spec", "spec-review", "spec-debate"):
                self.assertNotIn(name, nodes, machine_path)

    def test_triage_and_ticket_writing_overrides_keep_the_builtin_graph(self):
        for task_type in ("ticket-writing",):
            with self.subTest(task_type=task_type):
                builtin = yaml.safe_load(
                    (PLUGIN_DIR / "state-machines" / f"{task_type}.yaml").read_text())["nodes"]
                override = yaml.safe_load(
                    (REPO_ROOT / ".bootgear" / "config" / f"state-machine-{task_type}.yaml")
                    .read_text())["nodes"]
                self.assertEqual(set(override), set(builtin))
                self.assertEqual(self._edges(override), self._edges(builtin))
                for name, node in builtin.items():
                    reminder = node.get("reminder") or {}
                    self.assertEqual((override[name].get("reminder") or {}).get("leave_check"),
                                     reminder.get("leave_check"), f"node '{name}'")
        builtin = yaml.safe_load((PLUGIN_DIR / "state-machines" / "triage.yaml").read_text())
        override = yaml.safe_load(
            (REPO_ROOT / ".bootgear" / "config" / "state-machine-triage.yaml").read_text())
        # The bootgear triage override adds only `disposition`, after the gate.
        self.assertEqual(set(override["nodes"]), set(builtin["nodes"]) | {"disposition"})
        for name in ("triage", "triage-review"):
            self.assertEqual(override["nodes"][name], builtin["nodes"][name], f"node '{name}'")
        self.assertEqual(override["nodes"]["triage-gate"]["reminder"]["leave_check"],
                         builtin["nodes"]["triage-gate"]["reminder"]["leave_check"])
        self.assertEqual(override["nodes"]["triage-gate"]["next"], ["disposition"])
        self.assertEqual(override["nodes"]["disposition"]["next"], ["succeeded"])

    def test_no_machine_states_the_handback_precedence_line(self):
        for machine_dir in self._machine_dirs():
            for machine_path in machine_dir.glob("*.yaml"):
                self.assertNotIn("blocked > revise > choices > ready", machine_path.read_text(), machine_path)

    @staticmethod
    def _machine_dirs():
        return [
            REPO_ROOT / "plugins" / "engine" / "state-machines",
            REPO_ROOT / "codex-plugins" / "engine" / "state-machines",
            REPO_ROOT / ".bootgear" / "config",
        ]

    def _spec_review_machines(self):
        """(path, graph) for each machine whose review node runs spec-review."""
        return [
            (machine_dir / f"{prefix}{task_type}.yaml", graph)
            for machine_dir, prefix in zip(self._machine_dirs(), ("", "", "state-machine-"))
            for task_type, graph in SPEC_REVIEW_GRAPHS.items()
            if prefix == "" or task_type in OVERRIDE_TYPES
        ]

    @staticmethod
    def _edges(nodes):
        return {(name, dest) for name, node in nodes.items() for dest in node.get("next", [])}

    def _ticket_writing_machines(self):
        return [
            machine_dir / f"{prefix}ticket-writing.yaml"
            for machine_dir, prefix in zip(self._machine_dirs(), ("", "", "state-machine-"))
        ]

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
            PLUGIN_DIR / "state-machines" / "change-review.yaml",
            REPO_ROOT / ".bootgear" / "config" / "state-machine-change-review.yaml",
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
            with tempfile.TemporaryDirectory(prefix="engine-change-review-no-fix-") as tmp:
                stripped = Path(tmp) / "change-review.yaml"
                stripped.write_text(yaml.safe_dump(machine, sort_keys=False))
                result = self._task("state", "validate", str(stripped))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_project_override_can_replace_a_builtin_before_settlement(self):
        with tempfile.TemporaryDirectory(prefix="engine-state-override-") as tmp:
            project_root = Path(tmp)
            override = project_root / ".bootgear" / "config" / "state-machine-triage.yaml"
            override.parent.mkdir(parents=True)
            override.write_text(
                "name: project-triage\n"
                "nodes:\n"
                "  clarify:\n"
                "    next: [succeeded]\n"
                "  succeeded:\n"
                "    terminal: true\n"
                "  failed:\n"
                "    terminal: true\n"
            )

            result = self._task("state", "validate", str(override))
            self.assertEqual(result.returncode, 0, result.stderr)

            diagram = self._task("state", "diagram", str(override))
            self.assertEqual(diagram.returncode, 0, diagram.stderr)
            self.assertIn("clarify --> succeeded", diagram.stdout)

    def test_no_machine_carries_reminder_skill(self):
        paths = [
            REPO_ROOT / host / "engine" / "state-machines" / f"{task_type}.yaml"
            for host in ("plugins", "codex-plugins") for task_type in TASK_TYPES
        ] + [
            REPO_ROOT / ".bootgear" / "config" / f"state-machine-{task_type}.yaml"
            for task_type in OVERRIDE_TYPES
        ]
        self.assertEqual(len(paths), 14)
        for path in paths:
            machine = yaml.safe_load(path.read_text())
            for name, node in machine["nodes"].items():
                reminder = (node or {}).get("reminder") or {}
                self.assertNotIn("skill", reminder, f"{path} node '{name}'")

    def test_every_non_terminal_node_has_a_reminder_leave(self):
        paths = [
            REPO_ROOT / host / "engine" / "state-machines" / f"{task_type}.yaml"
            for host in ("plugins", "codex-plugins") for task_type in TASK_TYPES
        ] + [
            REPO_ROOT / ".bootgear" / "config" / f"state-machine-{task_type}.yaml"
            for task_type in OVERRIDE_TYPES
        ]
        self.assertEqual(len(paths), 14)
        for path in paths:
            machine = yaml.safe_load(path.read_text())
            for name, node in machine["nodes"].items():
                if (node or {}).get("terminal"):
                    continue
                leave = ((node or {}).get("reminder") or {}).get("leave")
                self.assertTrue(
                    isinstance(leave, str) and leave.strip(),
                    f"{path} node '{name}' has no reminder.leave",
                )

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
