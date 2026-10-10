"""The result: computed cutoff rows (status, cut, result, rank, reason), the cutoff table,
the `cutoff` event and its recompute on replay, and `converged`."""
from __future__ import annotations

import json
from typing import Any

from conftest import BATCH_1, DISABLED, FINDER, MAIN, R1, R2, Converge
from converge import ledger, model, protocol


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _build(cv: Converge, *specs: dict[str, Any], cut: str = "after",
           config: dict[str, Any] | None = None, extra: tuple[str, ...] = ()) -> list[str]:
    """One claim per spec, every batch clean, rated after the attack with the spec's values.

    A spec may carry `lens`, `origin` and `rule`; the rest are cut values."""
    task = {"steps": {"cut": cut, "gap_hunt": False, "escalate": False},
            "angles": {"disable": DISABLED}, **(config or {})}
    cv.init("s1", "correctness,security", MAIN, *extra, config=task)
    rows = [dict(spec) for spec in specs]
    ids: dict[int, str] = {}
    for index, spec in enumerate(rows):
        if spec.get("origin", "lens") == "lens":
            rule = spec.pop("rule", None)
            ids[index] = cv.file(lens=spec.pop("lens", "correctness"), claim=f"claim {index}",
                                 extra=("--rule", rule) if rule else ())
    cv.cover()
    for index, spec in enumerate(rows):
        if spec.get("origin") == "gap-hunt":
            ids[index] = cv.file(agent=R2, origin="gap-hunt", lens=spec.pop("lens", "correctness"),
                                 claim=f"gap claim {index}")
    gaps = [spec.pop("origin", "lens") == "gap-hunt" for spec in rows]
    for index, gap in enumerate(gaps):
        cv.clean(ids[index], fresh_eye_agent=R1 if gap else R2)
    if cut != "none":
        for index, gap in enumerate(gaps):
            cv.rate(ids[index], finder=R2 if gap else FINDER, **rows[index])
    return [ids[i] for i in range(len(rows))]


def _rows(cv: Converge) -> dict[str, dict[str, Any]]:
    return {row["claim"]: row
            for row in protocol.cutoff_results(protocol.compute_cutoff(_slate(cv)))}


def _write_cutoff(cv: Converge) -> list[str]:
    results = protocol.cutoff_results(protocol.compute_cutoff(_slate(cv)))
    return cv.append("cutoff", model.CONVERGE_AGENT, results=results)


def _results(cv: Converge) -> dict[str, tuple[str, str]]:
    return {cid: (row["result"], row["reason"]) for cid, row in _rows(cv).items()}


# -- rows --------------------------------------------------------------------------


def test_default_rules_and_rank(cv: Converge) -> None:
    a, b, c, d, e, f, g = _build(
        cv,
        {"frequency": "rare", "severity": "security"},
        {"frequency": "common", "severity": "wrong-behavior"},
        {"frequency": "rare", "severity": "wrong-behavior"},
        {"frequency": "contrived", "severity": "degraded", "confidence": "reproduced"},
        {"frequency": "every-call", "severity": "cosmetic", "confidence": "reproduced"},
        {"frequency": "contrived", "severity": "data-loss"},
        {"frequency": "rare", "severity": "degraded", "confidence": "reproduced"},
    )
    rows = _rows(cv)
    assert {cid: (rows[cid]["result"], rows[cid]["reason"]) for cid in (a, b, g)} == {
        a: ("finding", "report_if[0]"), b: ("finding", "report_if[1]"),
        g: ("finding", "report_if[2]")}
    assert {rows[cid]["result"] for cid in (c, d, e, f)} == {"follow-up"}
    assert {rows[cid]["reason"] for cid in (c, d, e, f)} == {"no rule matched"}
    assert [rows[cid]["rank"] for cid in (a, f, b, c, g, d, e)] == [1, 2, 3, 4, 5, 6, 7]
    assert rows[a] == {"claim": a, "status": "survived", "cut": "no", "result": "finding",
                       "rank": 1, "reason": "report_if[0]"}
    assert rows[c]["cut"] == "yes"


def test_gap_hunt_rules(cv: Converge) -> None:
    a, b, c = _build(
        cv,
        {"origin": "gap-hunt", "frequency": "rare", "severity": "wrong-behavior",
         "confidence": "reproduced"},
        {"origin": "gap-hunt", "frequency": "common", "severity": "cosmetic"},
        {"origin": "gap-hunt", "frequency": "rare", "severity": "data-loss"},
    )
    assert _results(cv) == {a: ("follow-up", "no rule matched"),
                            b: ("finding", "report_if_gap_hunt[0]"),
                            c: ("finding", "report_if_gap_hunt[1]")}


def test_rereview_pass_rules(cv: Converge) -> None:
    degraded, wrong = _build(
        cv,
        {"frequency": "rare", "severity": "degraded", "confidence": "reproduced"},
        {"frequency": "rare", "severity": "wrong-behavior", "confidence": "reproduced"},
        extra=("--pass", "2"))
    assert _results(cv) == {degraded: ("follow-up", "no rule matched"),
                            wrong: ("finding", "report_if[2]")}


def test_report_rules_report_a_claim_below_the_rules(cv: Converge) -> None:
    tagged, other, plain = _build(
        cv,
        {"rule": "R002", "frequency": "contrived", "severity": "degraded"},
        {"rule": "R003", "frequency": "contrived", "severity": "degraded"},
        {"frequency": "contrived", "severity": "degraded"},
        config={"cutoff": {"report_rules": ["R002"]}})
    assert _results(cv) == {tagged: ("finding", "report_rules[R002]"),
                            other: ("follow-up", "no rule matched"),
                            plain: ("follow-up", "no rule matched")}


def test_report_rules_default_empty(cv: Converge) -> None:
    (tagged,) = _build(cv, {"rule": "R002", "frequency": "contrived", "severity": "degraded"})
    assert _results(cv) == {tagged: ("follow-up", "no rule matched")}


def test_report_rules_claim_is_exempt_from_the_per_lens_cap(cv: Converge) -> None:
    top, tagged, past = _build(
        cv,
        {"frequency": "common", "severity": "security"},
        {"rule": "R002", "frequency": "contrived", "severity": "degraded"},
        {"frequency": "common", "severity": "wrong-behavior"},
        config={"cutoff": {"report_rules": ["R002"]}, "caps": {"per_lens": {"default": 1}}})
    assert _results(cv) == {top: ("finding", "report_if[0]"),
                            tagged: ("finding", "report_rules[R002]"),
                            past: ("follow-up", "per-lens cap 1 (correctness)")}


def test_report_rules_claims_take_no_cap_slot(cv: Converge) -> None:
    ids = _build(
        cv,
        *({"rule": "R002", "frequency": "common", "severity": "security"} for _ in range(2)),
        *({"frequency": "common", "severity": "wrong-behavior"} for _ in range(2)),
        config={"cutoff": {"report_rules": ["R002"]}, "caps": {"per_lens": {"default": 2}}})
    results = _results(cv)
    assert [results[cid] for cid in ids] == [("finding", "report_rules[R002]")] * 2 + [
        ("finding", "report_if[1]")] * 2


def test_per_lens_cap_ranks_within_the_lens(cv: Converge) -> None:
    ids = _build(
        cv,
        *({"frequency": "common", "severity": sev}
          for sev in ("wrong-behavior", "security", "data-loss", "security")),
        {"lens": "security", "frequency": "common", "severity": "wrong-behavior"},
        config={"caps": {"per_lens": {"default": 3}}})
    results = _results(cv)
    assert results[ids[0]] == ("follow-up", "per-lens cap 3 (correctness)")
    assert {results[cid][0] for cid in ids[1:]} == {"finding"}


def test_killed_unverified_and_cut_none_rows(cv: Converge) -> None:
    cv.ready(cut="before", claims=3)
    cv.rate("F001", "before", frequency="common", severity="wrong-behavior")
    cv.rate("F002", "before", frequency="common", severity="wrong-behavior")
    cv.rate("F003", "before", frequency="rare", severity="wrong-behavior")
    cv.batch_1("F001", refuted=(BATCH_1[0],))
    assert cv.append("reply", FINDER, claim="F001", batch=1, stance="decline") == []
    cv.clean("F002")
    rows = _rows(cv)
    assert rows["F001"] == {"claim": "F001", "status": "killed", "cut": "no",
                            "result": "killed", "rank": 3, "reason": "killed"}
    assert rows["F002"]["result"] == "finding"
    assert rows["F003"] == {"claim": "F003", "status": "unverified", "cut": "yes",
                            "result": "follow-up", "rank": 2, "reason": "unverified"}


def test_cut_none_rows_are_findings(cv: Converge) -> None:
    cv.ready(cut="none")
    cv.clean()
    assert _rows(cv)["F001"] == {"claim": "F001", "status": "survived", "cut": "no",
                                 "result": "finding", "rank": 1, "reason": "cut none"}


# -- the cutoff event ---------------------------------------------------------------


def test_cutoff_closes_the_slate(cv: Converge) -> None:
    _build(cv, {"frequency": "common", "severity": "security"})
    assert protocol.slate_phase(_slate(cv)) == "cutoff"
    assert _write_cutoff(cv) == []
    slate = _slate(cv)
    assert protocol.slate_phase(slate) == "done" and slate.cutoff_valid
    assert slate.cutoff is not None and slate.cutoff["results"] == list(_rows(cv).values())
    assert "cutoff: the slate is in phase done; cutoff needs phase cutoff" in _write_cutoff(cv)


def test_cutoff_is_invalid_after_a_later_event(cv: Converge) -> None:
    _build(cv, {"frequency": "common", "severity": "security"})
    assert _write_cutoff(cv) == []
    assert cv.append("find-run", FINDER, lens="correctness", angle="failure-path", tell="t",
                     searches="s", positive_control="p", result="none") == []
    slate = _slate(cv)
    assert not slate.cutoff_valid and protocol.slate_phase(slate) == "cutoff"
    assert _write_cutoff(cv) == []


def test_cutoff_refused_with_open_claims(cv: Converge) -> None:
    cv.ready(claims=2)
    cv.clean("F001")
    problems = _write_cutoff(cv)
    assert "cutoff: the slate is in phase attack; cutoff needs phase cutoff" in problems
    assert "cutoff: open claims remain: F002 (attack)" in problems


def test_cutoff_refused_from_an_agent(cv: Converge) -> None:
    _build(cv, {"frequency": "common", "severity": "security"})
    results = protocol.cutoff_results(protocol.compute_cutoff(_slate(cv)))
    problems = cv.append("cutoff", MAIN, results=results)
    assert "cutoff is computed by `converge cutoff` only; it is rejected from --as input" in problems


def test_cutoff_results_must_match_the_recompute(cv: Converge) -> None:
    _build(cv, {"frequency": "common", "severity": "security"})
    results = protocol.cutoff_results(protocol.compute_cutoff(_slate(cv)))
    results[0]["result"] = "follow-up"
    problems = cv.append("cutoff", model.CONVERGE_AGENT, results=results)
    assert "cutoff: results differ from the computed cutoff" in problems


def test_hand_edited_cutoff_is_refused_on_replay(cv: Converge) -> None:
    _build(cv, {"frequency": "rare", "severity": "wrong-behavior"})
    assert _write_cutoff(cv) == []
    lines = cv.path().read_text().splitlines()
    event = json.loads(lines[-1])
    event["results"][0]["result"] = "finding"
    lines[-1] = json.dumps(event)
    cv.path().write_text("\n".join(lines) + "\n")
    assert "results differ from the computed cutoff" in cv.refused("status", "s1")


# -- converged -----------------------------------------------------------------------


def _dispute(cv: Converge) -> None:
    cv.batch_1("F001", refuted=(BATCH_1[0],))
    for n, (kind, fields) in enumerate((("reply", {"stance": "rebut"}),
                                        ("verdict", {"verdict": "disagree", "evidence": "b"}),
                                        ("reply", {"stance": "rebut"}))):
        agent = R1 if kind == "verdict" else FINDER
        if kind == "reply":
            fields = {**fields, "evidence": f"e{n}", "evidence_sha256": ledger.evidence_hash(f"e{n}")}
        assert cv.append(kind, agent, claim="F001", batch=1, **fields) == []
    cv.fresh_eye("F001")


def test_converged_needs_the_cutoff(cv: Converge) -> None:
    cv.ready()
    cv.clean()
    assert not protocol.converged(_slate(cv))
    assert _write_cutoff(cv) == []
    assert protocol.converged(_slate(cv))


def test_a_disputed_finding_is_not_converged(cv: Converge) -> None:
    cv.ready(cut="after")
    _dispute(cv)
    cv.rate("F001", frequency="common", severity="security")
    assert _write_cutoff(cv) == []
    assert _rows(cv)["F001"]["status"] == "disputed"
    assert not protocol.converged(_slate(cv))


def test_a_disputed_follow_up_is_converged(cv: Converge) -> None:
    cv.ready(cut="after")
    _dispute(cv)
    cv.rate("F001", frequency="rare", severity="cosmetic")
    assert _write_cutoff(cv) == []
    assert (_rows(cv)["F001"]["status"], _rows(cv)["F001"]["cut"]) == ("disputed", "yes")
    assert protocol.converged(_slate(cv))
