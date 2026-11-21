import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gear_commands import command as gear_command
from gear_commands import display as shared_display


def display(plugin: str, name: str) -> str:
    return shared_display(plugin, name, host="codex")


TASK = gear_command("engine", "task", host="codex")
CONVERGE = gear_command("converge", "converge", host="codex")

PLUGIN_DIR = Path(__file__).resolve().parents[1]
MANIFEST = PLUGIN_DIR / ".codex-plugin" / "plugin.json"
HOOKS = PLUGIN_DIR / "hooks" / "codex-hooks.json"
TASK_DISPLAY = display("engine", "task")
ROSTER = "[main-agent, independent-reviewer, adversarial-reviewer, critic]"
ADVISOR_PARTY = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                 "      mechanism: advisor\n")
ALL_NATIVE = ("converge_seats: {main: native_subagent, finder: native_subagent, "
              "r1: native_subagent, r2: native_subagent, cutter: native_subagent}\n")
EXPECTED_SKILLS = {"clarify", "debate", "execute", "recall", "resolve", "start"}


def _roles(*roles: str) -> str:
    return f"advisor_roles:\n  roles: [{', '.join(roles)}]\n  brief: Act only in these roles.\n  startup: early\n"


class CodexPackageContractTestCase(unittest.TestCase):

    def _settlement(self, extra: str, roster: str = ROSTER, *, task_folder: Path) -> str:
        return (
            "task_type: ticket-to-pr\napproach: fixture\nprinciples: none\n"
            f"task_folder: {task_folder.resolve()}\n"
            "goal:\n  succeeded: done\n  failed: never\n"
            "state_machine: |\n  name: smoke\n  nodes:\n    clarify:\n"
            "      next: [succeeded]\n    succeeded:\n      terminal: true\n"
            "    failed:\n      terminal: true\n"
            "request_assessment: fixture\nsource_of_truth:\n  scope: fixture\n"
            "debate_threshold: fixture\ndebate_round_cap: 1\n"
            "convergence_policy: unanimous\nconsented_stop_allowed: true\n"
            "spec_skill: spec\ntest_skill: test\nreview_skill: review\n"
            "review_fix_mode: accepted_only\n"
            "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
            f"debate_roster: {roster}\n"
            + extra
        )

    def _validate(self, extra: str, roster: str = ROSTER):
        with tempfile.TemporaryDirectory(prefix="engine-debate-mechanism-") as tmp:
            path = Path(tmp) / "settlement.txt"
            settlement = self._settlement(extra, roster, task_folder=Path(tmp) / "task")
            path.write_text(f"{settlement}session_dir: {Path(tmp).resolve()}\n")
            return subprocess.run(
                [*TASK, "session", "validate", "mech-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )

    def _machine_validate(self, nodes: str, skills: str):
        settlement = (
            "task_type: change-review\napproach: fixture\nprinciples: none\n"
            "goal:\n  succeeded: done\n  failed: never\n"
            f"state_machine: |\n  name: fixture\n  nodes:\n{nodes}"
            "request_assessment: fixture\nsource_of_truth:\n  scope: fixture\n"
            "debate_threshold: fixture\ndebate_round_cap: 1\n"
            "convergence_policy: unanimous\nconsented_stop_allowed: true\n"
            "debate_party_config: {}\n"
            f"{skills}"
            "review_fix_mode: accepted_only\n"
            "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
            f"debate_roster: {ROSTER}\n"
        )
        with tempfile.TemporaryDirectory(prefix="engine-skill-fields-") as tmp:
            path = Path(tmp) / "settlement.txt"
            path.write_text(f"{settlement}session_dir: {Path(tmp).resolve()}\n"
                            f"task_folder: {(Path(tmp) / 'task').resolve()}\n")
            return subprocess.run(
                [*TASK, "session", "validate", "skill-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )

    def _resolve_seats_output(self, user: str | None, project: str | None,
                              task: str | None, *extra: str) -> str:
        with tempfile.TemporaryDirectory(prefix="engine-seat-config-") as tmp:
            root = Path(tmp)
            args = [*TASK, "config", "resolve", "--name", "converge-seats",
                    "--project-root", str(root)]
            for flag, text in (("--user-config", user), ("--project-config", project),
                               ("--task-config-file", task)):
                path = root / f"{flag.strip('-')}.yaml"
                if text is not None:
                    path.write_text(text)
                args += [flag, str(path)]
            return subprocess.run([*args, *extra], capture_output=True, text=True,
                                  check=True).stdout

    def _resolve_seats(self, *, user: str | None = None, project: str | None = None,
                       task: str | None = None) -> dict:
        return json.loads(self._resolve_seats_output(user, project, task, "--json"))
