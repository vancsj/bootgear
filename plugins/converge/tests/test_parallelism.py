"""Public configuration and assignment coverage (test-standard R006)."""

from concurrent.futures import ThreadPoolExecutor

from converge import ledger
from converge import work as work_model

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


def _work(cv: Converge, actor: str, host: str = HOST,
         role: str | None = None) -> dict:
    return work_model.package(ledger.read(cv.path(), "s1"), actor, host, requested=role)


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
    cv.check_cli("F001", BATCH_1[0], outcome="refuted")
    for angle in BATCH_1[1:]:
        cv.check_cli("F001", angle)
    actor = _work(cv, "r1")
    assert actor["state"] == "ready"
    assert [item["id"] for item in actor["items"]] == ["F003"]

    for angle in BATCH_1:
        cv.check_cli("F003", angle)
    dispute = _work(cv, "r1")
    assert dispute["waiting_for_reply"] == ["F001"]
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

    waiting = _work(cv, "r2")
    assert waiting["state"] == "waiting"
    assert waiting["assignment"]["fresh_eye"] == ["F001"]

    for angle in BATCH_1:
        cv.check_cli("F001", angle)
    assert _work(cv, "r1")["state"] == "complete"
    assert _work(cv, "r2")["state"] == "ready"
    assert _work(cv, "r1-2")["items"][0]["id"] == "F002"
