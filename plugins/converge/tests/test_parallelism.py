"""Public configuration and assignment coverage (test-standard R006)."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from converge import cli, cli_actions

from conftest import BATCH_1, DISABLED, HOST, MAIN, Converge


def test_parallelism_defaults_and_effective_budget_are_saved(cv: Converge) -> None:
    cv.init("serial")
    assert cv.events("serial")[0]["config"]["parallelism"] == {
        "finder": 1, "r1": 1, "r2": 1, "max_workers": 4,
    }
    assert cv.status("serial")["agent_cap"] == 5

    cv.init("parallel", config={"parallelism": {"finder": 4, "r1": 4, "r2": 4}})
    parallelism = {"finder": 4, "r1": 4, "r2": 4, "max_workers": 4}
    assert cv.events("parallel")[0]["config"]["parallelism"] == parallelism
    assert cv.status("parallel")["parallelism"] == parallelism
    assert cv.status("parallel")["agent_cap"] == 14


def test_parallelism_uses_the_effective_ceiling(cv: Converge) -> None:
    project_config = cv.project / ".bootgear" / "config"
    project_config.mkdir(parents=True)
    (project_config / "converge.yaml").write_text("parallelism: {r2: 5}\n")

    error = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness")
    assert "parallelism.r2" in error and "max_workers 4" in error
    assert not cv.path().exists()

    cv.init(config={"parallelism": {"max_workers": 5}})
    assert cv.status()["parallelism"] == {"finder": 1, "r1": 1, "r2": 5, "max_workers": 5}
    assert cv.status()["agent_cap"] == 9


def test_parallelism_reports_every_invalid_count_without_writing(cv: Converge) -> None:
    task = cv.root / "invalid.yaml"
    task.write_text("parallelism: {finder: 0, r1: true, r2: -2, max_workers: 0}\n")
    error = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness",
                       "--config", str(task))
    for key in ("finder", "r1", "r2", "max_workers"):
        assert f"parallelism.{key} must be a positive integer" in error
    assert not cv.path().exists()


def _work(cv: Converge, actor: str, *options: str) -> dict[str, Any]:
    return json.loads(cv.ok("work", "s1", "--as", actor, "--role-host", HOST,
                            "--json", *options).stdout)


def _main_wait(cv: Converge, source_seq: int, *active: str, seconds: str = "1") -> dict[str, Any]:
    workers = [arg for actor in active for arg in ("--active-worker", actor)]
    return _work(cv, MAIN, "--wait", seconds, "--after-seq", str(source_seq), *workers)


def _find_run(cv: Converge, actor: str, angle: str, claim: str) -> None:
    cv.ok("find-run", "s1", "--as", actor, "--lens", "correctness", "--angle", angle,
          "--tell", "caller uses changed path", "--searches", "rg caller",
          "--positive-control", "caller found", "--result", claim)


def _init_workers(cv: Converge, *, gap_hunt: bool) -> None:
    cv.init("s1", "correctness", config={
        "parallelism": {"finder": 2, "r1": 2, "r2": 2},
        "steps": {"cut": "none", "gap_hunt": gap_hunt, "escalate": gap_hunt},
        "angles": {"disable": DISABLED},
    })


def test_workers_share_seats_and_own_distinct_assignments(cv: Converge) -> None:
    _init_workers(cv, gap_hunt=False)
    assert _work(cv, "finder")["assignment"]["find"] == [["correctness", "changed-contract"]]
    second = _work(cv, "finder-2")
    assert second["seat"] == "finder"
    assert second["assignment"]["find"] == [["correctness", "failure-path"]]
    assert [item["id"] for item in _work(cv, MAIN)["workers"] if item["ready"]] == [
        "finder", "finder-2",
    ]

    before = cv.path().read_bytes()
    err = cv.refused("angle-na", "s1", "--as", "finder", "--phase", "find",
                     "--lens", "correctness", "--angle", "failure-path", "--reason", "no I/O")
    assert "assigned to finder-2" in err
    assert cv.path().read_bytes() == before

    assert cv.file(claim="first claim") == "F001"
    assert cv.file(agent="finder-2", angle="failure-path", claim="second claim") == "F002"
    _find_run(cv, "finder-2", "failure-path", "F002")
    _find_run(cv, "finder", "changed-contract", "F001")

    assert _work(cv, "r1")["assignment"]["fixed"] == ["F001"]
    assert _work(cv, "r1-2")["assignment"]["fixed"] == ["F002"]
    assert _work(cv, "r2-2")["assignment"]["fresh_eye"] == ["F002"]

    before = cv.path().read_bytes()
    assert "assigned to r1-2" in cv.check_cli("F002", BATCH_1[0], code=2).stderr
    assert cv.path().read_bytes() == before
    for angle in BATCH_1:
        cv.check_cli("F002", angle, agent="r1-2")
        cv.check_cli("F001", angle, agent="r1")
    cv.check_cli("F001", "first fresh angle", "--last", agent="r2", batch="fresh-eye")
    cv.check_cli("F002", "second fresh angle", "--last", agent="r2-2", batch="fresh-eye")

    events = cv.events()
    assert [row["as"] for row in events if row["event"] == "file"] == ["finder", "finder-2"]
    assert _work(cv, "r1-2")["assignment"]["fixed"] == ["F002"]
    assert cv.ok("cutoff", "s1").returncode == 0


def test_parallel_gap_hunt_requires_completion_even_without_claims(cv: Converge) -> None:
    _init_workers(cv, gap_hunt=True)
    assert cv.file(claim="first claim") == "F001"
    _find_run(cv, "finder", "changed-contract", "F001")
    _find_run(cv, "finder-2", "failure-path", "none")

    assert cv.status()["phase"] == "gap-hunt"
    assert _work(cv, "r2")["assignment"]["gap_hunt"] is True
    assert _work(cv, "r2-2")["items"] == []
    before = cv.path().read_bytes()
    err = cv.refused("escalate", "s1", "--as", "finder", "--claim", "F001")
    assert "phase gap-hunt" in err
    assert "r2" in cv.refused("gap-hunt-done", "s1", "--as", "r2-2")
    assert cv.path().read_bytes() == before

    cv.ok("gap-hunt-done", "s1", "--as", "r2")
    assert cv.events()[-1]["event"] == "gap-hunt-done"
    cv.ok("escalate", "s1", "--as", "finder", "--claim", "F001")
    assert cv.status()["phase"] == "attack"


def test_main_wait_ignores_find_and_active_workers_in_a_new_phase(cv: Converge) -> None:
    _init_workers(cv, gap_hunt=False)
    baseline = _work(cv, MAIN)
    assert "--wait 300" in baseline["wait"]

    claim = cv.file()
    filed = _main_wait(cv, baseline["source_seq"], "finder", "finder-2")
    assert (filed["wait_result"], filed["phase"]) == ("timeout", "find")
    assert filed["source_seq"] == cv.events()[-1]["seq"]

    _find_run(cv, "finder", "changed-contract", claim)
    _find_run(cv, "finder-2", "failure-path", "none")
    before = cv.path().read_bytes()
    started = time.monotonic()
    advanced = _main_wait(cv, filed["source_seq"], "finder", "finder-2", "r1")
    assert (advanced["wait_result"], advanced["phase"]) == ("timeout", "attack")
    assert advanced["source_seq"] == cv.events()[-1]["seq"]
    assert "--wait 1 " in advanced["wait"]
    assert time.monotonic() - started >= 1
    assert cv.path().read_bytes() == before


def test_main_wait_dispatches_idle_fresh_eye_worker_in_same_phase(cv: Converge) -> None:
    cv.ready(claims=2, config={"parallelism": {"r1": 2, "r2": 2}})
    baseline = _work(cv, MAIN)["source_seq"]
    for angle in BATCH_1[:-1]:
        cv.check_cli("F002", angle, agent="r1-2")
    partial = _main_wait(cv, baseline, "r1", "r1-2")
    assert partial["wait_result"] == "timeout"
    assert partial["source_seq"] == cv.events()[-1]["seq"]

    cv.check_cli("F002", BATCH_1[-1], agent="r1-2")
    before = cv.path().read_bytes()
    dispatched = _main_wait(cv, partial["source_seq"], "r1", "r1-2", seconds="300")
    assert (dispatched["wait_result"], dispatched["phase"]) == ("dispatch", "attack")
    assert [row["id"] for row in dispatched["workers"] if row["ready"]] == ["r2-2"]
    fresh_eyes = [item for item in dispatched["items"] if item["batch"] == "fresh-eye"]
    assert [(item["claim"], item["agent"]) for item in fresh_eyes] == [("F002", "r2-2")]
    assert cv.path().read_bytes() == before


def test_main_wait_refuses_invalid_options_without_writing(cv: Converge) -> None:
    _init_workers(cv, gap_hunt=False)
    before = cv.path().read_bytes()
    main = ("--as", MAIN, "--role-host", HOST)
    missing = cv.refused("work", "s1", *main, "--after-seq", "1")
    assert "--wait" in missing and "positive" in missing
    combined = cv.refused("work", "s1", *main, "--wait", "0", "--after-seq", "2",
                          "--active-worker", "r2-8", "--active-worker", "r1-9", "--active-worker", "cutter")
    assert "--wait requires positive seconds" in combined
    assert "--after-seq must be an existing source_seq" in combined
    assert "unknown --active-worker IDs: cutter, r1-9, r2-8" in combined
    no_cursor = cv.refused("work", "s1", *main, "--wait", "1")
    assert "--after-seq" in no_cursor
    wrong_actor = cv.refused("work", "s1", "--as", "finder", "--role-host", HOST,
                             "--wait", "1", "--after-seq", "1")
    assert "main" in wrong_actor and "--after-seq" in wrong_actor
    assert cv.path().read_bytes() == before


def test_main_wait_keeps_manual_cutter_valid_until_its_turn_returns(cv: Converge) -> None:
    cv.ready(cut="before", config={"parallelism": {"r1": 2}})
    plan = _work(cv, MAIN)
    assert plan["phase"] == "cut-before"
    assert any(item["agent_role"] == "cutter" for item in plan["items"])
    assert _main_wait(cv, plan["source_seq"], "cutter")["wait_result"] == "timeout"

    cv.cut("F001", 1, when="before")
    cv.ok("accept", "s1", "--as", "finder", "--claim", "F001", "--when", "before", "--round", "1")
    waited = _main_wait(cv, cv.events()[-1]["seq"], "cutter", "r1")
    assert (waited["wait_result"], waited["phase"]) == ("timeout", "attack")


def test_main_wait_returns_done_with_existing_next_step(cv: Converge) -> None:
    _init_workers(cv, gap_hunt=False)
    _find_run(cv, "finder", "changed-contract", "none")
    _find_run(cv, "finder-2", "failure-path", "none")
    cv.ok("cutoff", "s1")
    done = _work(cv, MAIN)
    waited = _main_wait(cv, done["source_seq"], seconds="300")
    assert (waited["wait_result"], waited["phase"]) == ("state", "done")
    assert waited["next"] == done["next"]


def test_parallel_finders_append_distinct_claim_ids(cv: Converge) -> None:
    _init_workers(cv, gap_hunt=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cv.file, claim="first claim")
        second = pool.submit(cv.file, agent="finder-2", angle="failure-path", claim="second claim")
        assert {first.result(), second.result()} == {"F001", "F002"}

    files = cv.events()[1:]
    assert [row["id"] for row in files] == ["F001", "F002"]
    assert {row["as"]: row["angle"] for row in files} == {
        "finder": "changed-contract", "finder-2": "failure-path",
    }


def test_refuter_continues_other_assigned_claims_during_a_dispute(cv: Converge) -> None:
    cv.ready(claims=3, config={"parallelism": {"r1": 2}})
    before_refutation = cv.events()[-1]["seq"]
    cv.check_cli("F001", BATCH_1[0], outcome="refuted")
    for angle in BATCH_1[1:]:
        cv.check_cli("F001", angle)
    actor = _work(cv, "r1")
    assert actor["state"] == "ready"
    assert [item["id"] for item in actor["items"]] == ["F003"]

    for angle in BATCH_1:
        cv.check_cli("F003", angle)
    dispute = _work(cv, "r1", "--wait", "1")
    assert dispute["waiting_for_reply"] == ["F001"]
    handed_off = _main_wait(cv, before_refutation, "r1", "r1-2")
    assert handed_off["wait_result"] == "dispatch"
    assert any(item["claim"] == "F001" and item["action"] == "reply" for item in handed_off["items"])
    cv.ok("reply", "s1", "--as", "finder", "--claim", "F001", "--batch", "1",
          "--stance", "rebut", "--evidence", "new counterexample evidence")
    cv.ok("verdict", "s1", "--as", "r1", "--claim", "F001", "--batch", "1", "--verdict", "agree")
    assert _work(cv, "r1")["state"] == "complete"


def test_parallel_work_waits_for_ordinary_prerequisites_and_reports_worker_completion(
    cv: Converge,
) -> None:
    _init_workers(cv, gap_hunt=False)
    cv.file(claim="first claim")
    cv.file(agent="finder-2", angle="failure-path", claim="second claim")
    _find_run(cv, "finder", "changed-contract", "F001")
    _find_run(cv, "finder-2", "failure-path", "F002")

    started = time.monotonic()
    waiting = _work(cv, "r2", "--wait", "1")
    assert waiting["state"] == "waiting"
    assert time.monotonic() - started >= 1
    assert waiting["assignment"]["fresh_eye"] == ["F001"]
    assert waiting["next"].endswith("--wait 1")
    assert _work(cv, "r2")["next"].endswith("--wait 300")

    for angle in BATCH_1:
        cv.check_cli("F001", angle)
    assert _work(cv, "r1", "--wait", "1")["state"] == "complete"
    assert _work(cv, "r2", "--wait", "1")["state"] == "ready"
    assert _work(cv, "r1-2")["items"][0]["id"] == "F002"


@pytest.mark.parametrize("actor", ["r2", MAIN])
def test_wait_replays_only_when_the_slate_changes(
    cv: Converge, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], actor: str,
) -> None:
    cv.ready(config={"parallelism": {"r1": 2}})
    options = ["--after-seq", str(cv.events()[-1]["seq"]), "--active-worker", "r1"] if actor == MAIN else []
    read = cli_actions._read
    read_count = 0
    polls = 0
    elapsed = 0.0

    def count_read(args: Any) -> Any:
        nonlocal read_count
        read_count += 1
        return read(args)

    def advance(seconds: float) -> None:
        nonlocal polls, elapsed
        polls += 1
        elapsed += seconds
        if polls == 3:
            for angle in BATCH_1:
                cv.check_cli("F001", angle)

    monkeypatch.setattr(cli_actions, "_read", count_read)
    monkeypatch.setattr(cli_actions, "time", SimpleNamespace(monotonic=lambda: elapsed, sleep=advance))
    cli.main(["work", "s1", "--dir", str(cv.dir), "--as", actor, "--role-host", HOST, "--wait", "1", "--json", *options])
    package = json.loads(capsys.readouterr().out)
    if actor == MAIN:
        assert package["wait_result"] == "dispatch"
    else:
        assert package["state"] == "ready"
    assert read_count == 2


def test_standalone_review_group_follows_predecessor_and_checks_project(cv: Converge) -> None:
    cv.init("first")
    cv.init("second", "correctness", MAIN, "--continue-from", "first")
    cv.init("unrelated")
    group = str(cv.path("first").resolve())
    assert cv.status("first")["review_group"] == group
    assert cv.status("second")["review_group"] == group
    assert cv.status("unrelated")["review_group"] != group

    error = cv.refused("init", "foreign", "--as", MAIN, "--lenses", "correctness",
                       "--project-root", str(cv.root / "other-project"), "--continue-from", "first")
    assert "different project" in error
    assert not cv.path("foreign").exists()


def test_parallel_advisor_launcher_and_worker_commands(cv: Converge) -> None:
    settlement = cv.root / "settlement.yaml"
    roles = {"roles": ["refuter"], "brief": "review the claim", "startup": "deferred",
             "launcher": "start-listener"}
    task = cv.root / "task.yaml"
    task.write_text("parallelism: {finder: 3, r1: 3, r2: 3}\ncutoff: {report_rules: [R004]}\n")
    options = ("--as", MAIN, "--lenses", "correctness", "--settlement", str(settlement),
               "--review-group", "engine-run", "--config", str(task))
    for template in ("start-listener", "start-listener {group} --worker={worker} {invitation}",
                     "start-listener {group} {worker} {worker} {invitation}"):
        roles["launcher"] = template
        settlement.write_text(json.dumps({"converge_seats": {"r2": "advisor"}, "advisor_roles": roles}))
        error = cv.refused("init", "s1", *options)
        assert "launcher template" in error
        assert "parallelism.r2 only" in error and "Preserve finder and r1" in error
        assert "--r2-only-retry 3 3" in error
        assert not cv.path().exists()

    roles["launcher"] = "start-listener {group} {worker} {invitation}"
    settlement.write_text(json.dumps({"converge_seats": {"r2": "advisor"}, "advisor_roles": roles}))
    output = cv.ok("init", "s1", *options, "--json")
    assert json.loads(output.stdout)["parallelism"] == {"finder": 3, "r1": 3, "r2": 3, "max_workers": 4}
    data = cv.status()
    assert data["review_group"] == "engine-run"
    assert [driver["worker"] for driver in data["drivers"]] == ["r2", "r2-2", "r2-3"]
    second = data["drivers"][1]
    assert "reserve --group engine-run --worker r2-2" in second["reserve"]
    assert "wait-listener --group engine-run --worker r2-2" in second["wait_listener"]
    assert "--as r2-2 --role-host claude" in second["work_claude"]
    assert "--as r2-2 --role-host codex" in second["work_codex"]

    error = cv.refused("init", "still-parallel", *options, "--r2-only-retry", "3", "3")
    assert "parallelism.r2 is 3, expected 1 for this r2-only retry" in error
    assert not cv.path("still-parallel").exists()

    roles["launcher"] = "start-listener"
    settlement.write_text(json.dumps({"converge_seats": {"r2": "advisor"}, "advisor_roles": roles}))
    original = task.read_text()
    task.write_text("parallelism: {finder: 1, r1: 1, r2: 1}\n")
    error = cv.refused("init", "downgraded", *options, "--r2-only-retry", "3", "3")
    for seat in ("finder", "r1"):
        assert f"parallelism.{seat} is 1, expected 3 for this r2-only retry" in error
    assert not cv.path("downgraded").exists()
    task.write_text(original.replace("r2: 3", "r2: 1"))
    retry = cv.ok("init", "retry", *options, "--r2-only-retry", "3", "3", "--prose")
    assert "finder=3 r1=3 r2=1" in retry.stdout
    assert cv.events("retry")[0]["config"]["cutoff"]["report_rules"] == ["R004"]
