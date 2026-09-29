"""Layered converge.yaml: defaults, host user path, project, task; validation."""
from __future__ import annotations

import json

from conftest import Converge


def _effective(cv: Converge, *args: str, env: dict[str, str] | None = None) -> dict:
    out = cv("config", "resolve", "--project-root", str(cv.project), *args, env=env).stdout
    return json.loads(out)["effective"]


def test_defaults(cv: Converge) -> None:
    eff = _effective(cv)
    assert eff["caps"] == {"refute_rounds": 5, "cut_rounds": 3, "per_lens": 3, "agents": 5}
    assert eff["cutoff"]["report_if"][0] == {"severity": ["security", "data-loss"],
                                             "frequency": ["every-call", "common", "rare"]}
    assert eff["cutoff"]["report_if"][2] == {
        "confidence": ["reproduced"],
        "severity": ["security", "data-loss", "wrong-behavior", "degraded"],
        "frequency": ["every-call", "common", "rare"]}
    assert eff["cutoff"]["report_if_gap_hunt"] == [
        {"frequency": ["every-call", "common"]},
        {"frequency": ["rare"], "severity": ["security", "data-loss"]}]
    assert eff["cutoff"]["report_rules"] == []
    assert "CONFIG valid" in cv("config", "validate", "--project-root", str(cv.project)).stdout


def test_layers_merge_later_wins(cv: Converge) -> None:
    (cv.home / ".claude").mkdir()
    (cv.home / ".claude" / "converge.yaml").write_text("caps: {per_lens: 5, cut_rounds: 4}\n")
    project_cfg = cv.project / ".bootgear" / "config"
    project_cfg.mkdir(parents=True)
    (project_cfg / "converge.yaml").write_text("caps: {per_lens: 2}\n")
    task = cv.root / "task.yaml"
    task.write_text("caps: {refute_rounds: 2}\ncutoff: {report_if: [{severity: [security]}]}\n")
    eff = _effective(cv, "--config", str(task))
    assert eff["caps"] == {"refute_rounds": 2, "cut_rounds": 4, "per_lens": 2, "agents": 5}
    assert eff["cutoff"]["report_if"] == [{"severity": ["security"]}]
    assert len(eff["cutoff"]["report_if_gap_hunt"]) == 2


def test_codex_host_reads_codex_user_path(cv: Converge) -> None:
    (cv.home / ".claude").mkdir()
    (cv.home / ".claude" / "converge.yaml").write_text("caps: {per_lens: 7}\n")
    (cv.home / ".codex").mkdir()
    (cv.home / ".codex" / "converge.yaml").write_text("caps: {per_lens: 9}\n")
    assert _effective(cv)["caps"]["per_lens"] == 7
    assert _effective(cv, env={"CONVERGE_HOST": "codex"})["caps"]["per_lens"] == 9


def test_validate_lists_every_problem(cv: Converge) -> None:
    bad = cv.root / "bad.yaml"
    bad.write_text(
        "colour: blue\n"
        "caps: {refute_rounds: 0, per_lens: true, extra: 1, agents: 6}\n"
        "cutoff: {report_if: [{severity: [catastrophic]}, {speed: [fast]}], report_if_gap_hunt: [], report_rules: [R001, '']}\n"
        "angles: {files: [1], disable: [x]}\n")
    err = cv("config", "validate", "--project-root", str(cv.project), "--config", str(bad), code=2).stderr
    for fragment in ("unknown key 'colour'", "caps.refute_rounds must be a positive integer",
                     "caps.per_lens must be a positive integer", "unknown key caps.extra",
                     "caps.agents must be at most 5",
                     "bad value 'catastrophic'", "unknown field 'speed'",
                     "angles.files must be a list of non-empty strings",
                     "cutoff.report_rules must be a list of non-empty strings"):
        assert fragment in err


def test_missing_task_config_refused(cv: Converge) -> None:
    err = cv("config", "validate", "--project-root", str(cv.project), "--config",
             str(cv.root / "nope.yaml"), code=2).stderr
    assert "task config does not exist" in err


def test_init_snapshot_ignores_later_config_edits(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("caps: {refute_rounds: 1}\n")
    cv.init("s1", "full", "correctness", "orch", "--config", str(task))
    task.write_text("caps: {refute_rounds: 5}\n")
    cv.file()
    cv.refute("F001", 1, "boundary", "r1", "downgraded", "--narrowed", "narrower")
    cv.refute("F001", 1, "reachability", "r2")
    assert cv.status()["by_id"]["F001"]["refute"] == "unconverged"
    assert "exceeds caps.refute_rounds 1" in cv.refute("F001", 2, "provenance", "r3", code=2).stderr


def test_agents_cap_must_be_positive(cv: Converge) -> None:
    bad = cv.root / "bad.yaml"
    for value in ("0", "true", "-1"):
        bad.write_text(f"caps: {{agents: {value}}}\n")
        err = cv("config", "validate", "--project-root", str(cv.project), "--config", str(bad),
                 code=2).stderr
        assert "caps.agents must be a positive integer" in err
    bad.write_text("caps: {agents: 3}\n")
    assert "CONFIG valid" in cv("config", "validate", "--project-root", str(cv.project),
                                "--config", str(bad)).stdout


def test_snapshot_without_report_rules_still_replays(cv: Converge) -> None:
    cv.init()
    path = cv.path()
    events = [json.loads(line) for line in path.read_text().splitlines()]
    del events[0]["config"]["cutoff"]["report_rules"]
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    cv.ok("status", "s1")
