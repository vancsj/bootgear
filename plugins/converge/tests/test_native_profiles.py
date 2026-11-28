"""Public native judging profile cases cover test-standard R001, R004, and R006."""
from __future__ import annotations

import json

from converge import ledger
from converge import work as work_model

from conftest import HOST, MAIN, Converge


def _profile() -> dict:
    return {"model": "gpt-5.6-luna" if HOST == "codex" else "haiku", "effort": "xhigh"}


def _work(cv: Converge, actor: str = MAIN, host: str = HOST,
         role: str | None = None) -> dict:
    return work_model.package(ledger.read(cv.path(), "s1"), actor, host, requested=role)


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


def test_unused_judges_do_not_block_empty_review(cv: Converge) -> None:
    cv.init(config={"steps": {"gap_hunt": False},
                    "native_profiles": {seat: _profile() for seat in ("r1", "r2", "cutter")}})
    workers = {row["id"]: row for row in _work(cv)["workers"]}
    assert workers["finder"]["ready"]
    assert all(not workers[actor]["ready"] for actor in ("r1", "r2", "cutter"))
    cv.cover()
    assert cv.status()["phase"] == "cutoff"
    cv.ok("cutoff", "s1")
    cv.ok("gate", "s1")
