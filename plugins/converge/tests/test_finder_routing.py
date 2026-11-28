"""Exercise finder profiles through the public Converge commands on both host routes."""
from __future__ import annotations

import json

from converge import ledger, work

from conftest import HOST, MAIN, Converge


def _policy() -> dict:
    specialist, mechanical = ("gpt-6.2-sol", "gpt-5.6-luna") if HOST == "codex" else ("opus", "haiku")
    return {
        "parallelism": {"finder": 3},
        "finder_routing": {
            "default": {"model": mechanical, "effort": "xhigh"},
            "groups": [{"lenses": ["security", "architecture", "architecture-fit"],
                        "workers": 1, "model": specialist, "effort": "high"}],
        },
    }


def _finders(cv: Converge) -> dict:
    package = work.package(ledger.read(cv.path(), "s1"), MAIN, HOST)
    return {item["id"]: item for item in package["workers"] if item["seat"] == "finder"}


def test_routed_finders_use_the_saved_host_policy(cv: Converge) -> None:
    policy = _policy()
    personal = cv.home / f".{HOST}" / "converge.yaml"
    personal.parent.mkdir()
    personal.write_text(json.dumps(policy))
    cv.init(lenses="correctness,security,architecture,architecture-fit")

    personal.write_text('{"parallelism":{"finder":1},"finder_routing":null}')
    assert cv.events()[0]["native_host"] == HOST
    workers = _finders(cv)
    assert list(workers) == ["finder", "finder-2", "finder-3"]
    specialist = policy["finder_routing"]["groups"][0]
    for index, item in enumerate(workers.values()):
        expected = specialist if index == 0 else policy["finder_routing"]["default"]
        assert item["profile"] == {"host": HOST, "model": expected["model"], "effort": expected["effort"]}
    assert {lens for lens, _ in workers["finder"]["assignment"]["find"]} == set(specialist["lenses"])
    assert workers["finder-2"]["assignment"]["find"] == [["correctness", "changed-contract"]]
    assert workers["finder-3"]["assignment"]["find"] == [["correctness", "failure-path"]]


def test_report_rules_extend_the_task_configuration(cv: Converge) -> None:
    task = cv.root / "rules.yaml"
    task.write_text("parallelism: {finder: 3, r1: 3, r2: 1}\ncutoff: {report_rules: [R004]}\n")
    cv.init("with-rules", "correctness", MAIN, "--config", str(task), "--report-rule", "R006")
    cutoff = cv.events("with-rules")[0]["config"]["cutoff"]
    assert cutoff["report_rules"] == ["R004", "R006"]


def test_routing_capacity_is_checked_before_snapshots_or_slate_writes(cv: Converge) -> None:
    policy = _policy()
    policy["parallelism"]["finder"] = 1
    task = cv.root / "capacity.yaml"
    task.write_text(json.dumps(policy))
    error = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness,security",
                       "--angles", str(cv.angles), "--config", str(task), "--snapshot", "--pass", "1")
    assert "default angles need a worker within finder budget 1" in error
    assert not cv.path().exists()
