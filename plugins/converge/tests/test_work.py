"""Public role work and structured actions use the saved slate and current validators."""
from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from converge import ledger
from converge import work as work_model
from test_clean import checks, clean

from conftest import (
    BATCH_1,
    CUT_EVIDENCE_MAP,
    DISABLED,
    GEAR_ARGS,
    MAIN,
    R1,
    R2,
    Converge,
)


def work(cv: Converge, actor: str = R1, host: str = "claude",
         role: str | None = None) -> dict:
    return work_model.package(ledger.read(cv.path(), "s1"), actor, host, requested=role)


def action(package: dict[str, Any], kind: str, claim: str = "F001") -> dict[str, Any]:
    return next(row["input"] for row in package["actions"]
                if row["input"]["action"] == kind and row["input"].get("claim") == claim)


def submit(cv: Converge, value: dict[str, Any], *, code: int = 0,
           command: str = "act") -> subprocess.CompletedProcess[str]:
    path = cv.root / "action.json"
    path.write_text(json.dumps(value))
    return cv.ok(command, "s1", "--as", value["role"], "--input", str(path), code=code)


def test_work_scopes_current_batches_and_saved_angle_definitions(cv: Converge) -> None:
    # Test standard R004: generated work must replace manual status assembly.
    cv.ready(claims=2)
    package = work(cv)
    assert package["role"] == R1
    assert package["role_host"] == "claude"
    assert package["phase"] == "attack"
    assert [item["id"] for item in package["items"]] == ["F001", "F002"]
    assert {row["id"] for row in package["definitions"]} == set(BATCH_1)
    value = action(package, "clean")
    assert [row["angle"] for row in value["checks"]] == list(BATCH_1)
    assert all(row["evidence"] == "" for row in value["checks"])
    assert value["source_seq"] == len(cv.events())


def test_saved_clean_action_submits_one_event_and_keeps_evidence(cv: Converge) -> None:
    cv.ready()
    value = action(work(cv), "clean")
    value["checks"] = checks(*BATCH_1)
    before = len(cv.events())
    submit(cv, value)
    assert len(cv.events()) == before + 1
    assert cv.events()[-1]["checks"] == checks(*BATCH_1)
    assert work(cv)["state"] == "waiting"


def test_direct_clean_accepts_the_generated_envelope(cv: Converge) -> None:
    cv.ready()
    value = action(work(cv), "clean")
    value["checks"] = checks(*BATCH_1)
    submit(cv, value, command="clean")
    assert cv.events()[-1]["event"] == "clean"


def test_action_accepts_stdin(cv: Converge) -> None:
    cv.ready()
    value = action(work(cv), "clean")
    value["checks"] = checks(*BATCH_1)
    result = subprocess.run([*GEAR_ARGS, "act", "s1", "--dir", str(cv.dir), "--as", R1,
                             "--input", "-"], input=json.dumps(value), text=True,
                            capture_output=True, env=cv.env, cwd=cv.project, check=False)
    assert result.returncode == 0, result.stderr
    assert cv.events()[-1]["event"] == "clean"


def test_action_accepts_unrelated_writes_but_rejects_stale_batch(cv: Converge) -> None:
    cv.ready(claims=2)
    value = action(work(cv), "clean")
    value["checks"] = checks(*BATCH_1)
    assert cv.append("clean", R1, claim="F002", batch=1, checks=checks(*BATCH_1)) == []
    submit(cv, value)
    before = cv.path().read_bytes()
    result = submit(cv, value, code=2)
    assert "open batch" in result.stderr or "stale" in result.stderr
    assert "work" in result.stderr.splitlines()[-1]
    assert cv.path().read_bytes() == before


def test_action_rejects_role_context_and_missing_evidence_together(cv: Converge) -> None:
    cv.ready()
    value = action(work(cv), "clean")
    value["role"] = R2
    value["checks"][0]["evidence"] = ""
    before = cv.path().read_bytes()
    result = submit(cv, value, code=2)
    assert "evidence" in result.stderr
    assert cv.path().read_bytes() == before


def test_action_rejects_role_mismatch_with_complete_evidence(cv: Converge) -> None:
    cv.ready()
    value = action(work(cv), "clean")
    value["checks"] = checks(*BATCH_1)
    value["role"] = R2
    path = cv.root / "role-action.json"
    path.write_text(json.dumps(value))
    before = cv.path().read_bytes()
    result = cv.ok("act", "s1", "--as", R1, "--input", str(path), code=2)
    assert "role must match --as r1" in result.stderr
    assert cv.path().read_bytes() == before


def test_repeated_file_action_refuses_after_an_unrelated_write(cv: Converge) -> None:
    cv.init()
    value = next(row["input"] for row in work(cv, actor="finder")["actions"]
                 if row["input"]["action"] == "file")
    value.update(loc="a.py:1", claim="a valid claim", trigger="a normal caller",
                 evidence="a.py:1 reaches it", tier="traced")
    submit(cv, value)
    cv.file(claim="a distinct claim")
    value["source_seq"] = len(cv.events())
    value["depends"] = []
    value["context"]["note"] = "refreshed envelope metadata"
    before = cv.path().read_bytes()
    result = submit(cv, value, code=2)
    assert "F001" in result.stderr and "seq=2" in result.stderr
    assert "refresh" in result.stderr and "work" in result.stderr
    assert cv.path().read_bytes() == before
    value["claim"] = "another distinct claim"
    submit(cv, value)


@pytest.mark.parametrize("field,value", [("depends", None), ("rule", None)])
def test_file_action_keeps_optional_field_validation(cv: Converge, field: str, value: Any) -> None:
    cv.init()
    payload = next(row["input"] for row in work(cv, actor="finder")["actions"]
                   if row["input"]["action"] == "file")
    payload.update(loc="a.py:1", claim="a valid claim", trigger="a normal caller",
                   evidence="a.py:1 reaches it", tier="traced")
    submit(cv, payload)
    payload[field] = value
    before = cv.path().read_bytes()
    result = submit(cv, payload, code=2)
    assert field in result.stderr
    assert "unchanged content" not in result.stderr
    assert cv.path().read_bytes() == before


def test_fresh_eye_work_keeps_free_names_and_used_checks_separate(cv: Converge) -> None:
    cv.ready()
    assert clean(cv, *BATCH_1) == []
    package = work(cv, actor=R2)
    assert package["items"][0]["used"] == list(BATCH_1)
    assert package["items"][0]["angles"] == []
    assert "fixed list is not a menu" in package["items"][0]["rule"]
    assert action(package, "clean")["checks"][0]["angle"] == ""


def test_reply_work_includes_the_refutation_and_only_its_owners_claim(cv: Converge) -> None:
    cv.ready()
    assert cv.append("attack", R1, claim="F001", batch=1, **checks(BATCH_1[0])[0]) == []
    assert clean(cv, *BATCH_1[1:]) == []
    package = work(cv, actor="finder")
    assert package["items"][0]["attacks"][0]["evidence"] == checks(BATCH_1[0])[0]["evidence"]
    assert {row["input"]["action"] for row in package["actions"]} == {"reply"}
    assert {row["input"]["stance"] for row in package["actions"]} == {"rebut", "decline"}
    rebuttal = next(row["input"] for row in package["actions"] if row["input"]["stance"] == "rebut")
    rebuttal["evidence"] = "b.py:12 calls the protected route"
    submit(cv, rebuttal)
    verdict = next(row["input"] for row in work(cv)["actions"] if row["input"].get("verdict") == "agree")
    submit(cv, verdict)


def test_post_attack_cut_work_keeps_only_its_claims_dispute_evidence(cv: Converge) -> None:
    cv.ready(cut="after", claims=2)
    first = {**checks(BATCH_1[0])[0], "evidence": "first claim refutation"}
    assert cv.append("attack", R1, claim="F001", batch=1, **first) == []
    assert clean(cv, *BATCH_1[1:]) == []
    assert cv.append("reply", "finder", claim="F001", batch=1, stance="rebut",
                     evidence="first claim finder response",
                     evidence_sha256=ledger.evidence_hash("first claim finder response")) == []
    assert cv.append("verdict", R1, claim="F001", batch=1, verdict="disagree",
                     evidence="first claim refuter response") == []
    assert cv.append("reply", "finder", claim="F001", batch=1, stance="rebut",
                     evidence="first claim second finder response",
                     evidence_sha256=ledger.evidence_hash("first claim second finder response")) == []
    fresh = {**checks("new route")[0], "evidence": "fresh-eye refutation"}
    assert cv.append("attack", R2, claim="F001", batch="fresh-eye", last=True, **fresh) == []
    assert cv.append("reply", "finder", claim="F001", batch="fresh-eye", stance="rebut",
                     evidence="fresh-eye finder response",
                     evidence_sha256=ledger.evidence_hash("fresh-eye finder response")) == []
    assert cv.append("verdict", R2, claim="F001", batch="fresh-eye", verdict="agree") == []
    other = {**checks(BATCH_1[0])[0], "evidence": "other claim refutation"}
    assert cv.append("attack", R1, claim="F002", batch=1, **other) == []
    assert cv.append("clean", R1, claim="F002", batch=1, checks=checks(*BATCH_1[1:])) == []
    assert cv.append("reply", "finder", claim="F002", batch=1, stance="rebut",
                     evidence="other claim finder response",
                     evidence_sha256=ledger.evidence_hash("other claim finder response")) == []
    assert cv.append("verdict", R1, claim="F002", batch=1, verdict="agree") == []
    assert cv.append("clean", R2, claim="F002", batch="fresh-eye", last=True,
                     checks=checks("other new route")) == []

    package = work(cv, actor="cutter")
    item = next(item for item in package["items"] if item["id"] == "F001")
    assert [row["evidence"] for row in item["attacks"]] == [
        "first claim refutation", "fresh-eye refutation"]
    assert [row["evidence"] for row in item["replies"]] == [
        "first claim finder response", "first claim second finder response", "fresh-eye finder response"]
    assert [row["verdict"] for row in item["verdicts"]] == ["disagree", "agree"]
    assert all(row["outcome"] == "refuted" for row in item["attacks"])
    assert all(row["claim"] == "F001" for field in ("attacks", "replies", "verdicts") for row in item[field])
    assert item["status"] == "disputed"


def test_gap_work_exposes_the_required_find_coordinates(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "none", "gap_hunt": True, "escalate": True}})
    cv.cover()
    package = work(cv, actor=R2)
    value = next(row["input"] for row in package["actions"] if row["input"]["action"] == "file")
    assert "lens" in value and "angle" in value
    value.update(lens="gap-hunt", angle="changed-contract", loc="a.py:1", claim="an omitted contract",
                 trigger="a normal caller", evidence="a.py:1 reaches the missing check", tier="traced")
    submit(cv, value)


def test_empty_slate_requires_gap_hunt_before_completion(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "none", "gap_hunt": True, "escalate": True}})
    cv.cover()
    assert work(cv, actor=R2)["state"] == "ready"
    assert cv.status()["phase"] == "gap-hunt"
    assert "gap-hunt" in cv.refused("cutoff", "s1")
    package = work(cv, actor=R2)
    finish = next(row["input"] for row in package["actions"] if row["input"]["action"] == "gap-hunt-done")
    submit(cv, finish)
    cv.ok("cutoff", "s1")
    package = work(cv, actor=R2)
    assert package["phase"] == "done"
    assert package["state"] == "complete"
    assert package["actions"] == []


def test_generated_actions_cover_find_escalation_cuts_and_cutoff(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "both", "gap_hunt": False, "escalate": True},
                    "angles": {"disable": DISABLED}})
    package = work(cv, actor="finder")
    value = next(row["input"] for row in package["actions"] if row["input"]["action"] == "file")
    value.update(loc="a.py:1", claim="a valid claim", trigger="a normal caller",
                 evidence="a.py:1 reaches it", tier="traced")
    submit(cv, value)
    cv.cover()
    value = next(row["input"] for row in work(cv, actor="finder")["actions"]
                 if row["input"]["action"] == "escalate" and "wider" not in row["input"])
    submit(cv, value)
    for when in ("before", "after"):
        cut_work = work(cv, actor="cutter")
        assert cut_work["items"][0]["status"] == "survived"
        cut = action(cut_work, "cut")
        cut.update(impact="wrong-output", size="one", reach="normal", evidence=CUT_EVIDENCE_MAP)
        if when == "after":
            assert all(key in cut for key in ("patch", "callers", "migration", "choice"))
            cut.update(difficulty="cross-cutting", choice="patch the caller or move the check",
                       callers="none", migration="none")
        submit(cv, cut)
        accept = action(work(cv, actor="finder"), "accept")
        submit(cv, accept)
        if when == "before":
            clean_action = action(work(cv), "clean")
            clean_action["checks"] = checks(*BATCH_1)
            submit(cv, clean_action)
            fresh = action(work(cv, actor=R2), "clean")
            fresh.update(checks=checks("new route"), last=True)
            submit(cv, fresh)
    package = work(cv, actor=MAIN)
    cutoff = next(row["input"] for row in package["actions"] if row["input"]["action"] == "cutoff")
    submit(cv, cutoff)
    assert work(cv, actor=MAIN)["state"] == "complete"


def test_work_does_not_offer_judgment_on_the_actors_own_claim(cv: Converge) -> None:
    cv.ready(cut="before")
    package = work(cv, actor="finder", role="cutter")
    assert package["actions"] == []
    assert package["items"] == []


def test_structured_fix_check_keeps_the_review_slate_gate(cv: Converge) -> None:
    from test_effort import cheap, patch
    from test_fix_check import _fix_now, _review

    _fix_now(cv, cheap(patch(lines=4)))
    package = work(cv, actor=MAIN)
    assert any(item.get("patch") == patch(lines=4) for item in package["items"])
    value = next(row["input"] for row in package["actions"] if row["input"]["outcome"] == "pass")
    value.update(evidence="focused checks passed", review_slate="missing-review")
    before = cv.path().read_bytes()
    result = submit(cv, value, code=2)
    assert "no slate 'missing-review'" in result.stderr
    assert cv.path().read_bytes() == before
    _review(cv, "clean-review")
    value["review_slate"] = "clean-review"
    submit(cv, value)
    assert cv.events()[-1]["event"] == "fix-check"
