"""Public native judging profile cases cover test-standard R001, R004, and R006."""
from __future__ import annotations

import json

import pytest

from conftest import BATCH_1, DISABLED, HOST, MAIN, Converge


def _profile() -> dict:
    return {"model": "gpt-5.6-luna" if HOST == "codex" else "haiku", "effort": "xhigh"}


def _work(cv: Converge, actor: str = MAIN) -> dict:
    return json.loads(cv.ok("work", "s1", "--as", actor, "--role-host", HOST, "--json").stdout)


def _call(cv: Converge, command: str, entries: list[dict], code: int = 0, actor: str = MAIN):
    path = cv.root / "native-request.json"
    path.write_text(json.dumps({"launches" if command == "launch" else "outcomes": entries}))
    return cv.ok(command, "s1", "--as", actor, "--input", str(path), "--json", code=code)


def _reserve(cv: Converge, actor: str) -> dict:
    return json.loads(_call(cv, "launch", [{"id": actor, "host": HOST, **_profile()}]).stdout)


def _finish(cv: Converge, actor: str, effective: dict | None = None, handle: str | None = None, code: int = 0):
    return _call(cv, "launch-result", [{"id": actor, "state": "finished", "handle": handle or actor + "-task",
                                       "receipt_worker": actor, "effective": effective or {}}], code=code)


def test_serial_cutter_profile_reservation_receipt_and_reuse(cv: Converge) -> None:
    cv.ready(cut="both", config={"native_profiles": {"cutter": _profile()}})
    workers = {row["id"]: row for row in _work(cv)["workers"]}
    assert workers["cutter"]["profile"] == {"host": HOST, **_profile()}
    assert workers["cutter"]["ready"]
    before = cv.path().read_bytes()
    cv.cut("F001", 1, when="before", code=2)
    _call(cv, "launch", [{"id": "cutter", "host": HOST, **_profile()}], code=2, actor="cutter")
    assert cv.path().read_bytes() == before
    accepted = _reserve(cv, "cutter")["accepted"][0]
    effort = "reasoning_effort" if HOST == "codex" else "effort"
    assert accepted["arguments"] == {"model": _profile()["model"], effort: "xhigh"}
    cv.cut("F001", 1, when="before")
    _finish(cv, "cutter", {"effort": "xhigh"})
    assert _work(cv, "cutter")["launch"]["evidence"] == "unverified"
    cv.accept("F001", 1, when="before")
    cv.clean()
    assert _work(cv, "cutter")["actions"]
    cv.cut("F001", 1)
    assert _work(cv, "cutter")["launch"]["handle"] == "cutter-task"
    before = cv.path().read_bytes()
    _reserve_again = [{"id": "cutter", "host": HOST, **_profile()}]
    _call(cv, "launch", _reserve_again, code=2)
    _finish(cv, "cutter", {"effort": "low"}, handle="replacement", code=2)
    assert cv.path().read_bytes() == before
    _finish(cv, "cutter", {"effort": "low"})
    assert _work(cv)["state"] == "blocked"
    assert "effort" in cv.ok("gate", "s1", code=1).stdout


@pytest.mark.parametrize("profiles", [{"r1": {"model": "bad model", "effort": "bad", "extra": 1},
                                        "other": {}}, {"cutter": {"effort": "high"}}])
def test_invalid_profiles_group_errors_before_writes(cv: Converge, profiles: dict) -> None:
    path = cv.root / "invalid.json"
    path.write_text(json.dumps({"native_profiles": profiles}))
    error = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness", "--config", str(path))
    assert "native_profiles" in error
    if "r1" in profiles:
        assert all(word in error for word in ("model", "effort", "extra", "other"))
    else:
        assert "model is missing" in error
    assert not cv.path().exists()


def test_profile_layers_null_clear_and_saved_host(cv: Converge) -> None:
    personal = cv.home / f".{HOST}" / "converge.yaml"
    personal.parent.mkdir()
    personal.write_text(json.dumps({"native_profiles": {"cutter": _profile(), "r1": _profile()}}))
    cv.init(config={"native_profiles": {"cutter": {"effort": "high"}, "r1": None}})
    assert cv.events()[0]["native_host"] == HOST
    assert cv.events()[0]["config"]["native_profiles"]["cutter"] == {**_profile(), "effort": "high"}
    personal.write_text('{"native_profiles":null}')
    assert _work(cv, "cutter")["profile"] == {"host": HOST, **_profile(), "effort": "high"}
    cv.init("s2")
    assert "native_host" not in cv.events("s2")[0]
    other = "claude" if HOST == "codex" else "codex"
    request = cv.root / "host-request.json"
    request.write_text(json.dumps({"launches": [{"id": "cutter", "host": HOST, **_profile(), "effort": "high"}]}))
    error = cv(*cv.with_dir("launch", "s1", "--as", MAIN, "--input", str(request)),
               env={"BOOTGEAR_HOST": other}, code=2).stderr
    assert "native host" in error


def test_unused_judges_do_not_block_empty_review(cv: Converge) -> None:
    cv.init(config={"native_profiles": {seat: _profile() for seat in ("r1", "r2", "cutter")}})
    workers = {row["id"]: row for row in _work(cv)["workers"]}
    assert workers["finder"]["ready"]
    assert all(not workers[actor]["ready"] for actor in ("r1", "r2", "cutter"))
    cv.cover()
    assert cv.status()["phase"] == "cutoff"
    cv.ok("cutoff", "s1")
    cv.ok("gate", "s1")


def test_parallel_refuter_profiles_and_atomic_receipt_admission(cv: Converge) -> None:
    cv.ready(claims=2, config={"native_profiles": {"r1": _profile(), "r2": _profile()},
                              "parallelism": {"r1": 2, "r2": 2}})
    workers = {row["id"]: row for row in _work(cv)["workers"]}
    assert all(workers[actor]["profile"] == {"host": HOST, **_profile()}
               for actor in ("r1", "r1-2", "r2", "r2-2"))
    before = cv.path().read_bytes()
    cv.check_cli("F001", "cited-but-unread", code=2)
    invalid = [{"id": "r1", "host": "other", **_profile()},
               {"id": "r1-2", "host": HOST, "model": "wrong", "effort": "wrong"}]
    error = _call(cv, "launch", invalid, code=2).stderr
    assert all(word in error for word in ("r1", "r1-2", "host", "model", "effort"))
    assert cv.path().read_bytes() == before
    for actor in ("r1", "r1-2", "r2", "r2-2"):
        _reserve(cv, actor)
    cv.batch_1("F001")
    cv.batch_1("F002", agent="r1-2")
    cv.fresh_eye("F001")
    cv.fresh_eye("F002", agent="r2-2")
    assert cv.status()["phase"] == "cutoff"
    assert "finished native turn" in cv.ok("gate", "s1", code=1).stdout
    assert "r1 needs a finished native turn" in json.loads(cv.ok("coverage", "s1", "--json").stdout)["native_turns_pending"]
    cv.ok("cutoff", "s1", code=2)
    assert not json.loads(cv.ok("converged", "s1", "--json", code=1).stdout)["converged"]
    before = cv.path().read_bytes()
    _call(cv, "launch-result", [{"id": "r1", "state": "finished", "handle": "shared", "receipt_worker": "r1"},
                                 {"id": "r1-2", "state": "finished", "handle": "shared", "receipt_worker": "r1"}], code=2)
    assert cv.path().read_bytes() == before
    observed_model = "claude-haiku-5-5" if HOST == "claude" else _profile()["model"]
    for actor in ("r1", "r1-2", "r2", "r2-2"):
        _finish(cv, actor, {"model": observed_model, "effort": "xhigh"})
        assert _work(cv, actor)["launch"]["evidence"] == "verified"
    cv.ok("cutoff", "s1")
    cv.ok("gate", "s1")


def test_native_r2_keeps_gap_hunt_claim_and_refuter_identity(cv: Converge) -> None:
    cv.init(config={"native_profiles": {"r2": _profile()}, "parallelism": {"finder": 2},
                    "steps": {"cut": "none"}})
    for index, angle in enumerate(("changed-contract", "failure-path")):
        for lens in ("correctness", "security"):
            # The saved allocation alternates each lens's two find angles.
            actor = "finder" if index == 0 else "finder-2"
            cv.ok("angle-na", "s1", "--as", actor, "--phase", "find", "--lens", lens,
                  "--angle", angle, "--reason", "tell absent")
    assert cv.status()["phase"] == "gap-hunt"
    before = cv.path().read_bytes()
    cv.ok("gap-hunt-done", "s1", "--as", "r2", code=2)
    assert cv.path().read_bytes() == before
    _reserve(cv, "r2")
    cid = cv.file(agent="r2", origin="gap-hunt")
    cv.ok("gap-hunt-done", "s1", "--as", "r2")
    _finish(cv, "r2")
    assert _work(cv, "r2")["launch"]["handle"] == "r2-task"
    cv.ok("escalate", "s1", "--as", "r2", "--claim", cid)
    cv.check_cli(cid, "cited-but-unread", outcome="refuted")
    for angle in BATCH_1[1:]:
        cv.check_cli(cid, angle)
    cv.ok("reply", "s1", "--as", "r2", "--claim", cid, "--batch", "1", "--stance", "rebut",
          "--evidence", "the saved caller reaches this path")
    assert _work(cv, "r2")["launch"]["handle"] == "r2-task"


def test_advisor_r2_ignores_native_profile_and_reservations(cv: Converge) -> None:
    settlement = cv.root / "advisor.yaml"
    settlement.write_text("converge_seats:\n  r2: advisor\nadvisor_roles:\n"
                          "  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n  startup: early\n")
    cv.init("s1", "correctness,security", MAIN, "--settlement", str(settlement),
            config={"native_profiles": {"r2": _profile()}, "parallelism": {"r1": 2}})
    cv.file()
    cv.cover()
    worker = next(row for row in _work(cv)["workers"] if row["id"] == "r2")
    assert worker["mechanism"] == "advisor"
    assert "profile" not in worker and "launch" not in worker
    before = cv.path().read_bytes()
    error = _call(cv, "launch", [{"id": "r2", "host": HOST, **_profile()}], code=2).stderr
    assert "no configured native assignment" in error
    assert cv.path().read_bytes() == before


def test_parallel_review_hands_off_one_serial_cutter(cv: Converge) -> None:
    cv.ready(cut="both", config={"native_profiles": {"cutter": _profile()}, "parallelism": {"r1": 2}})
    cutters = [row for row in _work(cv)["workers"] if row["seat"] == "cutter"]
    assert len(cutters) == 1
    assert cutters[0]["id"] == "cutter" and cutters[0]["ready"]


@pytest.mark.parametrize("kind", ["advisor-only", "null-only", "omitted", "native-cutter"])
def test_serial_find_guidance_uses_active_native_profiles(cv: Converge, kind: str) -> None:
    settlement = cv.root / "serial-advisor.yaml"
    settlement.write_text("converge_seats:\n  r2: advisor\nadvisor_roles:\n"
                          "  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n  startup: early\n")
    policy = {
        "advisor-only": {"native_profiles": {"r2": _profile()}},
        "null-only": {"native_profiles": {seat: None for seat in ("r1", "r2", "cutter")}},
        "omitted": {},
        "native-cutter": {"native_profiles": {"cutter": _profile()}},
    }[kind]
    cv.init("s1", "correctness", MAIN, "--settlement", str(settlement), config=policy)
    assert cv.events()[0].get("native_host") == (None if kind == "omitted" else HOST)
    before = cv.path().read_bytes()
    main = _work(cv)
    status = cv.status()
    if kind == "native-cutter":
        cutter = next(row for row in main["workers"] if row["id"] == "cutter")
        assert cutter["profile"] == {"host": HOST, **_profile()}
        assert "work s1" in status["next"] and f"--as {MAIN}" in status["next"]
    else:
        assert "workers" not in main and main["actions"] == []
        for package in (main, status):
            assert package["next"].startswith("continue the finder with the missing angles, then ")
            assert "coverage s1" in package["next"]
    assert _work(cv, "finder")["state"] == "ready"
    assert cv.path().read_bytes() == before
    cv.cover(lenses=("correctness",))
    assert cv.status()["phase"] == "cutoff"


@pytest.mark.parametrize("profiled", [True, False])
def test_cutter_work_respects_configured_native_identity(cv: Converge, profiled: bool) -> None:
    policy = {"native_profiles": {"cutter": _profile()}} if profiled else None
    cv.ready(cut="both", config=policy)
    if profiled:
        for reserved in (False, True):
            if reserved:
                _reserve(cv, "cutter")
            before = cv.path().read_bytes()
            canonical = _work(cv, "cutter")
            assert bool(canonical["actions"]) is reserved
            assert canonical["profile"] == {"host": HOST, **_profile()}
            error = cv.ok("work", "s1", "--as", "custom-cutter", "--role", "cutter",
                          "--role-host", HOST, "--json", code=2).stderr
            assert "work: cutter belongs to native identity cutter" in error
            cv.cut("F001", 1, agent="custom-cutter", when="before", code=2)
            assert cv.path().read_bytes() == before
        cv.cut("F001", 1, when="before")
    else:
        before = cv.path().read_bytes()
        legacy = json.loads(cv.ok("work", "s1", "--as", "custom-cutter", "--role", "cutter",
                                  "--role-host", HOST, "--json").stdout)
        assert legacy["state"] == "ready"
        assert any(row["input"]["action"] == "cut" for row in legacy["actions"])
        assert "profile" not in legacy and "launch" not in legacy
        assert cv.path().read_bytes() == before
        cv.cut("F001", 1, agent="custom-cutter", when="before")


@pytest.mark.parametrize("role,profiled,advisor", [
    ("r1", True, False), ("r2", True, False),
    ("r1", False, False), ("r2", False, False), ("r2", True, True),
])
def test_serial_refuter_work_respects_native_identity(
        cv: Converge, role: str, profiled: bool, advisor: bool) -> None:
    policy = {"steps": {"cut": "none", "gap_hunt": False, "escalate": False},
              "angles": {"disable": DISABLED}}
    if profiled:
        policy["native_profiles"] = {role: _profile()}
    extra = ()
    if advisor:
        settlement = cv.root / "serial-refuter-advisor.yaml"
        settlement.write_text("converge_seats:\n  r2: advisor\nadvisor_roles:\n"
                              "  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n  startup: early\n")
        extra = ("--settlement", str(settlement))
    cv.init("s1", "correctness,security", MAIN, *extra, config=policy)
    cv.file()
    cv.cover()
    if role == "r2":
        for angle in BATCH_1:
            cv.check_cli("F001", angle)
    batch = 1 if role == "r1" else "fresh-eye"
    angle = "cited-but-unread" if role == "r1" else "unused caller route"
    alias = f"custom-{role}"
    if profiled and not advisor:
        for reserved in (False, True):
            if reserved:
                _reserve(cv, role)
            before = cv.path().read_bytes()
            canonical = _work(cv, role)
            assert bool(canonical["actions"]) is reserved
            assert canonical["profile"] == {"host": HOST, **_profile()}
            error = cv.ok("work", "s1", "--as", alias, "--role", role,
                          "--role-host", HOST, "--json", code=2).stderr
            assert f"work: {role} belongs to native identity {role}" in error
            cv.check_cli("F001", angle, agent=alias, batch=batch, code=2)
            assert cv.path().read_bytes() == before
        cv.check_cli("F001", angle, agent=role, batch=batch)
    else:
        before = cv.path().read_bytes()
        legacy = json.loads(cv.ok("work", "s1", "--as", alias, "--role", role,
                                  "--role-host", HOST, "--json").stdout)
        assert legacy["state"] == "ready" and legacy["actions"]
        assert "profile" not in legacy and "launch" not in legacy
        assert cv.path().read_bytes() == before
        cv.check_cli("F001", angle, agent=alias, batch=batch)
