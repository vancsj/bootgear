"""Public feedback validation and read-only helper boundaries."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
GEAR = REPO / "plugins" / "cli" / "bin" / "gear"


@dataclass
class FeedbackRunner:
    prefix: list[str]
    env: dict[str, str]
    root: Path
    task: Path

    def __call__(self, command: str, *args: object, **overrides: str) -> tuple[
        subprocess.CompletedProcess[str], dict[str, Any]
    ]:
        result = subprocess.run(
            [*self.prefix, command, "--task-folder", str(self.task), "--json", *map(str, args)],
            env={**self.env, **overrides}, cwd=self.task.parent,
            text=True, capture_output=True, check=False,
        )
        assert result.stdout, result.stderr
        return result, json.loads(result.stdout)


@pytest.fixture
def feedback(tmp_path: Path) -> tuple[Path, Path, Path, FeedbackRunner, Path]:
    task = tmp_path / "task"
    task.mkdir()
    evidence = tmp_path / "raw.txt"
    evidence.write_text("required output differs from observed output")
    inventory = tmp_path / "observations.json"
    inventory.write_text(json.dumps({"observations": [{"id": "O1", "evidence_paths": [str(evidence)]}]}))
    checks = tmp_path / "checks.json"
    checks.write_text(json.dumps({"slate": "s1", "checks": [{"id": "O1", "state": "checked",
        "evidence_refs": ["independent trace:1"], "disposition": "The required output holds on the traced path.",
        "claim_ids": []}]}))
    gear_root = tmp_path / "gear-root"
    engine = gear_root / "codex-plugins" / "engine"
    engine.mkdir(parents=True)
    source_package = PLUGIN / "src" / "spec_feedback"
    shutil.copytree(source_package, engine / "src" / "spec_feedback")
    (engine / "gear.toml").write_text(
        '[plugin]\nname = "engine"\n\n'
        '[commands.spec-feedback]\nexec = ["python3", "-m", "spec_feedback.cli"]\n',
        encoding="utf-8",
    )
    helper_source = '''import json, os, sys
from pathlib import Path
name = os.environ["GEAR_PLUGIN"]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "self-review":
    print(json.dumps({"outcome": "ready", "record_exists": False,
                      "checkpoints": json.loads(os.environ.get("HISTORY", "[]"))}))
elif sys.argv[1] == "status":
    print(json.dumps({"slate": "s1", "claims": [{"id": "F001"}]}))
else:
    ok = os.environ.get("GATE_OPEN") != "1"
    print(json.dumps({"slate": "s1", "ok": ok,
                      "problems": [] if ok else ["F001 is open in attack"]}))
    sys.exit(0 if ok else 1)
'''
    for name, command in (("self-review", "self-review"), ("converge", "converge")):
        plugin = gear_root / "plugins" / name
        plugin.mkdir(parents=True)
        (plugin / "gear.toml").write_text(
            f'[plugin]\nname = "{name}"\n\n'
            f'[commands.{command}]\nexec = ["python3", "provider.py"]\n',
            encoding="utf-8",
        )
        (plugin / "provider.py").write_text(helper_source, encoding="utf-8")

    log = tmp_path / "calls.jsonl"
    safe_path = os.pathsep.join((str(Path(sys.executable).parent), "/bin:/usr/bin"))
    env = {**os.environ, "PATH": safe_path, "CALL_LOG": str(log),
           "BOOTGEAR_HOST": "codex", "BOOTGEAR_OUTPUT": "prose",
           "SPEC_FEEDBACK_TEST_UNUSED": "1"}
    env.pop("GEAR_CALLER_CWD", None)
    prefix = [str(GEAR), "--host", "codex", "--root", str(gear_root), "engine", "spec-feedback"]

    run = FeedbackRunner(prefix=prefix, env=env, root=gear_root, task=task)
    return task, inventory, checks, run, log


def test_intake_package_routes_and_no_writes(feedback):
    task, inventory, _, run, log = feedback
    before = sorted(p.name for p in task.iterdir())
    result, data = run("intake", "--observations", inventory, "--destination", "spec")
    assert result.returncode == 0 and data["destination"] == "spec"
    assert data["design_path"] is None
    assert sorted(p.name for p in task.iterdir()) == before
    assert json.loads(log.read_text().splitlines()[0]) == ["self-review", "status", "--task-folder", str(task.resolve()), "--stage", "spec", "--json"]
    (task / "requirements.md").write_text("required contract")
    result, data = run("intake", "--observations", inventory, "--destination", "spec-review")
    assert result.returncode == 0 and data["design_path"] is None
    (task / "design.md").write_text("design contract")
    result, data = run("intake", "--observations", inventory, "--destination", "spec-review")
    assert result.returncode == 0 and data["design_path"] == str(task / "design.md")
    result, data = run("intake", "--observations", inventory, "--destination", "spec")
    assert result.returncode != 0 and data["outcome"] == "refused"


def test_checkpoint_and_orphan_design_refuse_bootstrap(feedback):
    task, inventory, _, run, _ = feedback
    result, data = run("intake", "--observations", inventory, "--destination", "spec", HISTORY='[{"stage":"spec","visit":1}]')
    assert result.returncode != 0 and any("checkpoint" in p for p in data["problems"])
    assert list(task.iterdir()) == []
    (task / "design.md").write_text("orphan")
    result, data = run("intake", "--observations", inventory, "--destination", "spec")
    assert result.returncode != 0 and any("requirements" in p for p in data["problems"])


def test_gate_requires_coverage_and_normal_converge(feedback, tmp_path):
    task, inventory, checks, run, log = feedback
    args = ("--slate", "s1", "--converge-dir", tmp_path, "--observations", inventory, "--checks", checks)
    result, data = run("gate", *args)
    assert result.returncode == 0 and data["outcome"] == "passed"
    assert data["checks"][0]["claim_ids"] == []
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls == [["converge", "status", "s1", "--dir", str(tmp_path), "--json"],
                     ["converge", "gate", "s1", "--dir", str(tmp_path), "--json"]]
    result, data = run("gate", *args, GATE_OPEN="1")
    assert result.returncode != 0 and "F001 is open in attack" in data["problems"]
    checks.write_text(json.dumps({"slate": "s1", "checks": []}))
    result, data = run("gate", *args)
    assert result.returncode != 0 and any("O1" in p and "missing" in p for p in data["problems"])
    assert list(task.iterdir()) == []


def test_gate_groups_invalid_entries_and_fields(feedback, tmp_path):
    _, inventory, checks, run, _ = feedback
    inventory.write_text(json.dumps({"observations": [
        {"id": "O1", "evidence_paths": [str(tmp_path / "missing.txt")]},
        {"id": "O1", "evidence_paths": []}, {"id": "O2"}, {"id": "O3"}]}))
    checks.write_text(json.dumps({"slate": "s1", "checks": [
        {"id": "O1", "state": "checked", "evidence_refs": [], "disposition": "", "claim_ids": ["F999"]},
        {"id": "O1", "state": "unassessed", "evidence_refs": [], "disposition": "", "claim_ids": []},
        {"id": "O9", "state": "checked", "evidence_refs": ["trace:1"], "disposition": "checked", "claim_ids": []}]}))
    result, data = run("gate", "--slate", "s1", "--converge-dir", tmp_path,
                       "--observations", inventory, "--checks", checks)
    assert result.returncode != 0
    text = "\n".join(data["problems"])
    for fragment in ("duplicate observation O1", "duplicate check O1", "unknown observation O9",
                     "O2: missing check", "O3: missing check", "unassessed", "evidence_refs",
                     "disposition", "F999", "missing.txt", "evidence_paths"):
        assert fragment in text


def test_prior_slate_and_unknown_claim_refuse(feedback, tmp_path):
    _, inventory, checks, run, _ = feedback
    report = json.loads(checks.read_text())
    report["slate"] = "s0"
    report["checks"][0]["claim_ids"] = ["F001"]
    checks.write_text(json.dumps(report))
    result, data = run("gate", "--slate", "s1", "--converge-dir", tmp_path,
                       "--observations", inventory, "--checks", checks)
    assert result.returncode != 0 and any("slate" in p for p in data["problems"])


def test_missing_helpers_return_actual_diagnostic(feedback, tmp_path):
    _, inventory, checks, run, _ = feedback
    self_review = run.root / "plugins" / "self-review" / "gear.toml"
    self_review.unlink()
    result, data = run("intake", "--observations", inventory, "--destination", "spec")
    assert result.returncode != 0 and data["outcome"] == "unavailable"
    assert "self-review" in data["diagnostic"] and "No such file" in data["diagnostic"]
    self_review.write_text(
        '[plugin]\nname = "self-review"\n\n'
        '[commands.self-review]\nexec = ["python3", "provider.py"]\n',
        encoding="utf-8",
    )
    converge = run.root / "plugins" / "converge" / "gear.toml"
    converge.unlink()
    result, data = run("gate", "--slate", "s1", "--converge-dir", tmp_path,
                       "--observations", inventory, "--checks", checks)
    assert result.returncode != 0 and data["outcome"] == "unavailable"
    assert "converge" in data["diagnostic"]


def test_usage_and_prose_default(feedback):
    _, inventory, _, run, _ = feedback
    result, data = run("intake", "--observations", inventory)
    assert result.returncode != 0 and data["outcome"] == "refused"
    assert "example:" in result.stderr and "settings, intake, gate" in result.stderr
    assert f"example: {shlex.join(run.prefix)} intake" in result.stderr
    env = dict(run.env)
    env.pop("BOOTGEAR_OUTPUT", None)
    result = subprocess.run([*run.prefix, "settings", "--task-folder", str(run.task)], env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert not result.stdout.lstrip().startswith("{")
    assert result.stdout.splitlines()[-1].startswith("next:")


@pytest.mark.parametrize("mode,flag,wants_json", [
    ("json", None, True),
    ("prose", None, False),
    ("json", "--prose", False),
    ("prose", "--json", True),
])
def test_gear_route_honors_output_environment_and_explicit_flags(feedback, tmp_path, mode, flag, wants_json):
    _, _, _, run, _ = feedback
    args = [*run.prefix, "settings", "--task-folder", str(tmp_path)]
    if flag is not None:
        args.append(flag)
    result = subprocess.run(args, env={**run.env, "BOOTGEAR_OUTPUT": mode},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    if wants_json:
        assert json.loads(result.stdout)["outcome"] == "ready"
    else:
        assert not result.stdout.lstrip().startswith("{")
        assert result.stdout.splitlines()[-1].startswith("next:")


def test_explicit_empty_inventory_and_checks(feedback, tmp_path):
    _, inventory, checks, run, _ = feedback
    inventory.write_text('{"observations": []}')
    checks.write_text('{"slate": "s1", "checks": []}')
    result, data = run("gate", "--slate", "s1", "--converge-dir", tmp_path,
                       "--observations", inventory, "--checks", checks)
    assert result.returncode == 0 and data["outcome"] == "passed"


def test_relative_paths_use_caller_folder(feedback, tmp_path):
    _, inventory, checks, run, _ = feedback
    inventory.write_text('{"observations": [{"id":"O1","evidence_paths":["raw.txt"]}]}')
    result, data = run("gate", "--slate", "s1", "--converge-dir", tmp_path,
                       "--observations", inventory.name, "--checks", checks.name,
                       GEAR_CALLER_CWD=str(tmp_path))
    assert result.returncode == 0 and data["observations_path"] == str(inventory.resolve())


def test_option_like_values_refuse_before_public_calls(feedback, tmp_path):
    _, inventory, checks, run, log = feedback
    result, data = run("gate", "--slate=-s1", "--converge-dir", tmp_path,
                       "--observations", inventory, "--checks", checks)
    assert result.returncode != 0 and any("slate" in p for p in data["problems"])
    assert not log.exists()


def test_codex_routes_feedback_settings_through_gear(feedback):
    _, _, _, run, _ = feedback
    result, data = run("settings")
    assert result.returncode == 0, result.stdout + result.stderr
    assert data["outcome"] == "ready"
