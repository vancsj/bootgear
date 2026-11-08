"""Public feedback validation and read-only helper boundaries."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
GEAR = REPO / "plugins" / "cli" / "bin" / "gear"
sys.path.insert(0, str(REPO / "plugins" / "cli" / "src"))
sys.path.insert(0, str(PLUGIN / "src"))
from spec_feedback import cli as spec_cli


@pytest.fixture
def feedback(tmp_path: Path):
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
    commands = tmp_path / "commands"
    commands.mkdir()
    helper = commands / "public-helper"
    helper.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name in {"self-review", "engine-self-review"}:
    print(json.dumps({"outcome": "ready", "record_exists": False, "checkpoints": json.loads(os.environ.get("HISTORY", "[]"))}))
elif sys.argv[1] == "status":
    print(json.dumps({"slate": "s1", "claims": [{"id": "F001"}]}))
else:
    ok = os.environ.get("GATE_OPEN") != "1"
    print(json.dumps({"slate": "s1", "ok": ok, "problems": [] if ok else ["F001 is open in attack"]}))
    sys.exit(0 if ok else 1)
''')
    helper.chmod(0o755)
    for name in ("self-review", "converge", "engine-self-review", "engine-converge"):
        (commands / name).symlink_to(helper)
    registry = tmp_path / "registry"
    spec_plugin = registry / "plugins" / "spec"
    spec_plugin.mkdir(parents=True)
    shutil.copyfile(PLUGIN / "gear.toml", spec_plugin / "gear.toml")
    (spec_plugin / "src").symlink_to(PLUGIN / "src", target_is_directory=True)

    def register(base: Path, name: str, entries: dict[str, list[str]]) -> Path:
        plugin_root = base / name
        plugin_root.mkdir(parents=True)
        lines = ["[plugin]", f'name = "{name}"', ""]
        for command, executable in entries.items():
            lines.extend((f"[commands.{command}]", "exec = [" + ", ".join(
                json.dumps(item) for item in executable) + "]", ""))
        (plugin_root / "gear.toml").write_text("\n".join(lines))
        return plugin_root

    register(registry / "plugins", "review", {
        "self-review": ["python3", str(commands / "self-review")],
    })
    register(registry / "plugins", "converge", {
        "converge": ["python3", str(commands / "converge")],
    })
    engine = register(registry / "codex-plugins", "engine", {
        "self-review": ["python3", str(commands / "engine-self-review")],
        "converge": ["python3", str(commands / "engine-converge")],
        "spec-feedback": ["python3", "-m", "spec_feedback.cli"],
    })
    (engine / "src").symlink_to(PLUGIN / "src", target_is_directory=True)
    log = tmp_path / "calls.jsonl"
    env = {**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"],
           "CALL_LOG": str(log), "BOOTGEAR_HOST": "claude", "BOOTGEAR_OUTPUT": "prose",
           "SPEC_FEEDBACK_TEST_UNUSED": "1"}
    env.pop("GEAR_CALLER_CWD", None)

    def run(command, *args, **overrides):
        host = overrides.get("BOOTGEAR_HOST", "claude")
        plugin = "engine" if host == "codex" else "spec"
        result = subprocess.run([str(GEAR), "--host", host, "--root", str(registry),
            plugin, "spec-feedback", command, "--task-folder", str(task),
            "--json", *map(str, args)], env={**env, **overrides}, cwd=tmp_path,
            text=True, capture_output=True, check=False)
        assert result.stdout, result.stderr
        return result, json.loads(result.stdout)

    return task, inventory, checks, run, log


def test_intake_package_routes_and_no_writes(feedback):
    task, inventory, _, run, log = feedback
    before = sorted(p.name for p in task.iterdir())
    result, data = run("intake", "--observations", inventory, "--destination", "spec")
    assert result.returncode == 0 and data["destination"] == "spec"
    assert data["design_path"] is None
    assert json.loads(log.read_text().splitlines()[0]) == ["self-review", "status", "--task-folder", str(task.resolve()), "--stage", "spec", "--json"]
    assert sorted(p.name for p in task.iterdir()) == before
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


def test_missing_helpers_return_actual_diagnostic(feedback, tmp_path, monkeypatch):
    task, inventory, checks, _, _ = feedback

    def without_helpers(*args):
        output = io.StringIO()
        errors = io.StringIO()
        with monkeypatch.context() as patch:
            patch.setattr(spec_cli, "resolve_command", lambda _name: None)
            patch.setattr(spec_cli.shutil, "which", lambda _name: None)
            with redirect_stdout(output), redirect_stderr(errors):
                code = spec_cli.main([*args, "--json"])
        return code, json.loads(output.getvalue()), errors.getvalue()

    code, data, _ = without_helpers("intake", "--task-folder", str(task),
                                    "--observations", str(inventory), "--destination", "spec")
    assert code != 0 and data["outcome"] == "unavailable"
    assert "self-review public command" in data["diagnostic"]
    assert "No such file" in data["diagnostic"]
    code, data, _ = without_helpers("gate", "--task-folder", str(task),
                                    "--slate", "s1", "--converge-dir", str(tmp_path),
                                    "--observations", str(inventory), "--checks", str(checks))
    assert code != 0 and data["outcome"] == "unavailable"
    assert "converge public command" in data["diagnostic"]


def test_usage_and_prose_default(feedback):
    _, inventory, _, run, _ = feedback
    result, data = run("intake", "--observations", inventory)
    assert result.returncode != 0 and data["outcome"] == "refused"
    assert "example:" in result.stderr and "settings, intake, gate" in result.stderr
    env = dict(os.environ)
    env.pop("BOOTGEAR_OUTPUT", None)
    result = subprocess.run([str(GEAR), "--host", "claude", "--root", str(REPO),
                            "spec", "spec-feedback", "settings"], env=env,
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
def test_gear_honors_output_environment_and_explicit_flags(tmp_path, mode, flag, wants_json):
    args = [str(GEAR), "--host", "claude", "--root", str(REPO), "spec", "spec-feedback",
            "settings", "--task-folder", str(tmp_path)]
    if flag is not None:
        args.append(flag)
    result = subprocess.run(args, env={**os.environ, "BOOTGEAR_OUTPUT": mode},
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


def test_codex_prefers_bundled_public_helper(feedback):
    _, inventory, _, run, log = feedback
    result, data = run("intake", "--observations", inventory, "--destination", "spec",
                       BOOTGEAR_HOST="codex")
    assert result.returncode == 0, result.stdout + result.stderr
    assert data["outcome"] == "ready"
    assert [json.loads(line)[0] for line in log.read_text().splitlines()] == ["engine-self-review"]
