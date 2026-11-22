"""Exercise finder profiles through the public Converge commands on both host routes."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

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
    output = cv.ok("work", "s1", "--as", MAIN, "--role-host", HOST, "--json")
    return {item["id"]: item for item in json.loads(output.stdout)["workers"] if item["seat"] == "finder"}


def _call(cv: Converge, command: str, entries: list[dict], *, code: int = 0, actor: str = MAIN):
    name = "launches" if command == "launch" else "outcomes"
    request = cv.root / "request.json"
    request.write_text(json.dumps({name: entries}))
    return cv.ok(command, "s1", "--as", actor, "--input", str(request), "--json", code=code)


def _angle(cv: Converge, actor: str, angle: str, *, code: int = 0):
    return cv.ok("angle-na", "s1", "--as", actor, "--phase", "find", "--lens", "correctness",
                 "--angle", angle, "--reason", "trigger absent: no public caller changed", code=code)


def test_routed_finders_use_the_saved_host_policy(cv: Converge) -> None:
    policy = _policy()
    personal = cv.home / f".{HOST}" / "converge.yaml"
    personal.parent.mkdir()
    personal.write_text(json.dumps(policy))
    cv.init(lenses="correctness,security,architecture,architecture-fit")

    personal.write_text('{"parallelism":{"finder":1},"finder_routing":null}')
    assert cv.events()[0]["finder_host"] == HOST
    workers = _finders(cv)
    assert list(workers) == ["finder", "finder-2", "finder-3"]
    specialist = policy["finder_routing"]["groups"][0]
    for index, item in enumerate(workers.values()):
        expected = specialist if index == 0 else policy["finder_routing"]["default"]
        assert item["profile"] == {"host": HOST, "model": expected["model"], "effort": expected["effort"]}
    assert {lens for lens, _ in workers["finder"]["assignment"]["find"]} == set(specialist["lenses"])
    assert workers["finder-2"]["assignment"]["find"] == [["correctness", "changed-contract"]]
    assert workers["finder-3"]["assignment"]["find"] == [["correctness", "failure-path"]]
    other = "claude" if HOST == "codex" else "codex"
    replay = cv(*cv.with_dir("work", "s1", "--as", MAIN, "--role-host", other, "--json"),
                env={"BOOTGEAR_HOST": other})
    first = json.loads(replay.stdout)["workers"][0]
    assert first["profile"] == workers["finder"]["profile"]
    assert f"--role-host {HOST}" in first["work"]


def test_main_launch_and_refusal_use_the_saved_host(cv: Converge) -> None:
    cv.init(lenses="security", config=_policy())
    saved = _finders(cv)["finder"]["profile"]
    other = "claude" if HOST == "codex" else "codex"
    caller = {"BOOTGEAR_HOST": other}
    wrong_host_work = cv(*cv.with_dir("work", "s1", "--as", MAIN, "--role-host", other, "--json"),
                         env=caller)
    proposal = cv.root / "launch.json"
    proposal.write_text(json.dumps({"launches": [{"id": "finder", **saved}]}))
    before = cv.path().read_bytes()
    refusal = cv(*cv.with_dir("launch", "s1", "--as", MAIN, "--input", str(proposal), "--json"),
                 env=caller, code=2)
    assert cv.path().read_bytes() == before
    assert f"use the slate's finder host {HOST}" in refusal.stderr
    assert f"--host {HOST} " in json.loads(wrong_host_work.stdout)["next"]
    retry = json.loads(refusal.stderr)["error"]["next"]
    assert f"--host {HOST} " in retry and retry.endswith(f"--role-host {HOST}")


def test_standalone_continuation_uses_saved_config_and_appends_report_rules(cv: Converge) -> None:
    original = cv.root / "approved-source.yaml"
    original.write_text("parallelism: {finder: 3, r1: 3, r2: 1}\ncutoff: {report_rules: [R004]}\n")
    approved = cv.root / "first.task.yaml"
    approved.write_bytes(original.read_bytes())
    cv.init("first", "correctness", MAIN, "--config", str(approved), "--report-rule", "R008",
            "--report-rule", "R004", "--report-rule", "R006")
    assert cv.status("first")["task_config"] == str(approved)
    first = cv.events("first")[0]
    assert first["config"]["cutoff"]["report_rules"] == ["R004", "R008", "R006"]
    original.write_text("parallelism: {finder: 1, r1: 1, r2: 1}\n")
    cv.init("second", "correctness", MAIN, "--continue-from", "first", "--report-rule", "R006")
    second = cv.events("second")[0]
    assert second["task_config"] == str(approved)
    assert second["config"]["parallelism"] == {"finder": 3, "r1": 3, "r2": 1, "max_workers": 4}
    assert second["config"]["cutoff"]["report_rules"] == ["R004", "R006"]
    replacement = cv.root / "replacement.task.yaml"
    replacement.write_bytes(original.read_bytes())
    cv.init("replacement", "correctness", MAIN, "--continue-from", "second", "--config", str(replacement))
    cv.init("after-replacement", "correctness", MAIN, "--continue-from", "replacement")
    assert cv.status("after-replacement")["task_config"] == str(replacement)
    assert cv.status("after-replacement")["parallelism"]["finder"] == 1
    approved.unlink()
    error = cv.refused("init", "third", "--as", MAIN, "--lenses", "correctness", "--continue-from", "second")
    assert str(approved) in error
    assert not cv.path("third").exists()


def test_launch_reserves_full_batches_and_blocks_on_native_mismatch(cv: Converge) -> None:
    cv.init(lenses="correctness", config=_policy())
    workers = _finders(cv)
    launches = [{"id": actor, **worker["profile"]} for actor, worker in workers.items()]
    assert len(launches) == 2
    before = cv.path().read_bytes()
    invalid = [{**launches[0], "host": "other"}, {**launches[1], "model": "wrong", "effort": "wrong"}]
    error = _call(cv, "launch", invalid, code=2).stderr
    for field in ("finder", "finder-2", "host", "model", "effort"):
        assert field in error
    _call(cv, "launch", launches, code=2, actor="finder")
    _call(cv, "launch-result", [{"id": "finder", "state": "blocked", "reason": "host refused"}], code=2)
    _angle(cv, "finder", "changed-contract", code=2)
    assert cv.path().read_bytes() == before

    accepted = json.loads(_call(cv, "launch", launches[:1]).stdout)["accepted"][0]
    effort_arg = "reasoning_effort" if HOST == "codex" else "effort"
    assert accepted["arguments"] == {"model": launches[0]["model"], effort_arg: "xhigh"}
    assert _finders(cv)["finder-2"]["ready"]
    _call(cv, "launch", launches[:1], code=2)
    _angle(cv, "finder-2", "changed-contract", code=2)
    _angle(cv, "finder", "changed-contract")
    _call(cv, "launch-result", [{"id": "finder", "state": "finished", "handle": "worker-a",
                                "receipt_worker": "finder", "effective": {"effort": "xhigh"}}])
    assert _finders(cv)["finder"]["launch"]["evidence"] == "unverified"
    assert cv.status()["phase"] == "find"
    _call(cv, "launch", launches[1:])
    _angle(cv, "finder-2", "failure-path")

    before_outcome = cv.path().read_bytes()
    wrong = {"id": "finder-2", "state": "blocked", "handle": "worker-b", "receipt_worker": "finder",
             "effective": {"effort": "medium"}, "reason": "unexpected effort"}
    _call(cv, "launch-result", [wrong], code=2)
    _call(cv, "launch-result", [{**wrong, "receipt_worker": "finder-2", "handle": "worker-a"}], code=2)
    assert cv.path().read_bytes() == before_outcome
    _call(cv, "launch-result", [{"id": "finder-2", "state": "finished", "handle": "worker-b",
                                "receipt_worker": "finder-2", "effective": {"effort": "medium"}}])
    saved = _finders(cv)["finder-2"]["launch"]
    assert saved["state"] == "blocked"
    assert saved["handle"] == "worker-b"
    assert saved["effective"] == {"effort": "medium"}
    assert "effort" in saved["reason"]
    blocked = json.loads(cv.ok("work", "s1", "--as", "finder-2", "--role-host", HOST, "--json").stdout)
    assert blocked["state"] == "blocked"
    assert blocked["next"] == "report the blocked finder assignment and its reason to main"
    coverage = json.loads(cv.ok("coverage", "s1", "--json").stdout)
    assert coverage["lenses"]["correctness"]["missing"] == []
    assert "finder-2 blocked" in coverage["finder_turns_pending"][0]
    gate = cv.ok("gate", "s1", code=1).stdout
    assert "finder-2" in gate and "effort" in gate


@pytest.mark.parametrize("count", [1, 3])
def test_only_assigned_routed_finders_take_slots_and_keep_existing_gap_hunt(cv: Converge, count: int) -> None:
    policy = _policy()
    policy["parallelism"]["finder"] = count
    cv.init(lenses="security", config=policy)
    workers = _finders(cv)
    assert list(workers) == ["finder"]
    cv.file(lens="security", code=2)
    _call(cv, "launch", [{"id": "finder", **workers["finder"]["profile"]}])
    cv.file(lens="security", agent="finder-2", code=2)
    cv.cover(lenses=("security",))
    assert cv.status()["phase"] == "find"
    actual_model = "claude-opus-5-5" if HOST == "claude" else workers["finder"]["profile"]["model"]
    outcome = {"id": "finder", "state": "finished", "handle": "finder-task", "receipt_worker": "finder",
               "effective": {"model": actual_model, "effort": "high"}}
    _call(cv, "launch-result", [outcome])
    assert _finders(cv)["finder"]["launch"]["evidence"] == "verified"
    if count == 3:
        assert cv.status()["phase"] == "gap-hunt"
        cv.ok("gap-hunt-done", "s1", "--as", "r2")
    assert cv.status()["phase"] == "cutoff"
    cv.ok("cutoff", "s1")
    cv.ok("gate", "s1")
    _call(cv, "launch-result", [{**outcome, "handle": "different", "effective": {"effort": "low"}}], code=2)
    _call(cv, "launch-result", [{**outcome, "effective": {"effort": "low"}}])
    assert cv.status()["phase"] == "find"
    assert cv.ok("gate", "s1", code=1).returncode == 1
    results = [event for event in cv.events() if event["event"] == "launch-result"]
    assert results[0]["outcomes"][0] == outcome


def test_routing_capacity_is_checked_before_snapshots_or_slate_writes(cv: Converge) -> None:
    policy = _policy()
    policy["parallelism"]["finder"] = 1
    task = cv.root / "capacity.yaml"
    task.write_text(json.dumps(policy))
    error = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness,security",
                       "--angles", str(cv.angles), "--config", str(task), "--snapshot", "--pass", "1")
    assert "default angles need a worker within finder budget 1" in error
    assert not cv.path().exists()


def test_racing_main_calls_reserve_the_worker_once(cv: Converge) -> None:
    cv.init(lenses="correctness", config=_policy())
    worker = _finders(cv)["finder"]
    request = cv.root / "one-launch.json"
    request.write_text(json.dumps({"launches": [{"id": "finder", **worker["profile"]}]}))
    args = cv.with_dir("launch", "s1", "--as", MAIN, "--input", str(request), "--json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(cv.run, *args) for _ in range(2)]
        results = [attempt.result(timeout=20) for attempt in attempts]
    assert sorted(result.returncode for result in results) == [0, 2]
    refusal = next(result.stderr for result in results if result.returncode == 2)
    assert "worker already has a launch attempt" in refusal
    assert [event["event"] for event in cv.events()] == ["init", "launch"]
