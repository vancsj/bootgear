"""Repeated filed content is refused without changing valid saved events."""
from __future__ import annotations

import json

import pytest
from conftest import Converge
from converge import ledger


def test_direct_file_refuses_same_actor_content_across_prior_events(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.file(claim="a distinct claim")
    before = cv.path().read_bytes()
    error = cv.file(extra=("--depends", ""), code=2)
    assert "F001" in error and "seq=2" in error
    assert "refresh" in error and "work" in error
    assert cv.path().read_bytes() == before
    cv.file(claim="another distinct claim")
    cv.file(agent="r2")


def test_saved_valid_repeated_claims_remain_readable(cv: Converge) -> None:
    cv.init()
    cv.file()
    prior = cv.events()[-1]
    saved = {**prior, "id": "F002", "seq": prior["seq"] + 1}
    with cv.path().open("a") as stream:
        stream.write(json.dumps(saved) + "\n")
    assert list(ledger.read(cv.path(), "s1").claims) == ["F001", "F002"]
    assert set(cv.status()["by_id"]) == {"F001", "F002"}
    cv.file(claim="a distinct claim")


@pytest.mark.parametrize("extra", [
    ("--loc", "src/b.py:11"),
    ("--trigger", "caller passes an empty list"),
    ("--evidence", "b.py:11 reaches another route"),
    ("--tier", "inferred"),
    ("--lens", "security"),
    ("--angle", "failure-path"),
    ("--depends", "F001"),
    ("--rule", "R001"),
])
def test_distinct_filed_fields_receive_normal_validation(cv: Converge, extra: tuple[str, ...]) -> None:
    cv.init()
    cv.file()
    assert cv.file(extra=extra) == "F002"
