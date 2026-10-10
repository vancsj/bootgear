"""The cut: cut rounds per `when`, the cut modes of `steps.cut`, unverified claims, and the
per-lens cap map."""
from __future__ import annotations

from typing import Any

import pytest
from conftest import BATCH_1, CUTTER, DISABLED, FINDER, Converge
from converge import ledger, model, protocol

KEPT = {"frequency": "common", "severity": "wrong-behavior"}        # report_if[1]
BELOW = {"frequency": "rare", "severity": "wrong-behavior"}         # no rule matches


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _cuts(cv: Converge) -> dict[str, tuple[bool, str]]:
    return protocol.cut_reasons(_slate(cv))


def _status(cv: Converge, cid: str) -> str:
    slate = _slate(cv)
    return protocol.status(slate, slate.claims[cid])


# -- cut rounds --------------------------------------------------------------------


def _round(rnd: int, severity: str = "degraded") -> dict[str, Any]:
    return {"round": rnd, "frequency": "common", "severity": severity, "confidence": "traced",
            "difficulty": "local"}


@pytest.mark.parametrize(("rounds", "pending", "accepted", "state"), [
    ((), 0, 0, "open"),
    (("degraded",), 0, 0, "open"),
    (("degraded",), 0, 1, "converged"),
    (("degraded",), 1, 1, "open"),
    (("degraded", "degraded"), 1, 0, "converged"),
    (("degraded", "security"), 1, 0, "open"),
    (("degraded", "degraded"), 0, 0, "open"),
    (("degraded", "security", "cosmetic"), 2, 0, "capped"),
    (("degraded", "security", "security"), 2, 0, "converged"),
])
def test_cut_track_state(rounds: tuple[str, ...], pending: int, accepted: int,
                         state: str) -> None:
    track = protocol.CutTrack({n: _round(n, sev) for n, sev in enumerate(rounds, start=1)},
                              pending, accepted)
    assert protocol.cut_track_state(track, 3) == state


def test_rebut_reopens_a_converged_cut_in_its_phase(cv: Converge) -> None:
    cv.ready(cut="before", claims=2)
    cv.rate("F001", "before", **KEPT)
    assert protocol.cut_track_state(_slate(cv).claims["F001"].state.cuts["before"], 5) == "converged"
    assert cv.append("rebut", FINDER, claim="F001", when="before", evidence="prod shows more",
                     evidence_sha256=ledger.evidence_hash("prod shows more")) == []
    assert cv.append("cut", CUTTER, claim="F001", round=2, when="before", confidence="inferred",
                     frequency="every-call") == []


def test_capped_cut_takes_no_rebut(cv: Converge) -> None:
    cv.ready(cut="before", claims=2, cut_rounds=1)
    assert cv.append("cut", CUTTER, claim="F001", round=1, when="before",
                     confidence="inferred") == []
    assert ("rebut: F001 before cut is capped; it takes no more rebut"
            in cv.append("rebut", FINDER, claim="F001", when="before", evidence="e",
                         evidence_sha256=ledger.evidence_hash("e")))


def test_cut_budget_counts_per_when(cv: Converge) -> None:
    cv.ready(cut="both", cut_rounds=1)
    assert cv.append("cut", CUTTER, claim="F001", round=1, when="before",
                     confidence="inferred", **KEPT) == []
    cv.clean()
    assert cv.append("cut", CUTTER, claim="F001", round=1, when="after", **KEPT) == []
    assert protocol.slate_phase(_slate(cv)) == "cutoff"


# -- cut modes -------------------------------------------------------------------------


def test_before_cut_claims_are_unverified_and_never_attacked(cv: Converge) -> None:
    cv.ready(cut="before", claims=2)
    cv.rate("F001", "before", **KEPT)
    cv.rate("F002", "before", **BELOW)
    assert protocol.unverified_ids(_slate(cv)) == {"F002"}
    assert _status(cv, "F002") == "unverified"
    assert ("attack: F002 is unverified (cut before the attack); it takes no attack"
            in cv.attack("F002", BATCH_1[0]))
    cv.clean("F001")
    assert protocol.slate_phase(_slate(cv)) == "cutoff"
    assert _cuts(cv) == {"F001": (False, "report_if[1]"), "F002": (True, "unverified")}


def test_after_cut_rates_attacked_claims(cv: Converge) -> None:
    cv.ready(cut="after", claims=2)
    for cid in ("F001", "F002"):
        cv.clean(cid)
    assert protocol.slate_phase(_slate(cv)) == "cut-after"
    cv.rate("F001", **KEPT)
    cv.rate("F002", **BELOW)
    assert protocol.unverified_ids(_slate(cv)) == set()
    assert _cuts(cv) == {"F001": (False, "report_if[1]"), "F002": (True, "no rule matched")}
    assert _status(cv, "F002") == "survived"


def test_both_rerates_and_may_cut_a_claim_the_first_cut_kept(cv: Converge) -> None:
    cv.ready(cut="both", claims=2)
    cv.rate("F001", "before", **KEPT)
    cv.rate("F002", "before", **BELOW)
    cv.clean("F001")
    assert ("cut: F002 is unverified; it takes no after cut"
            in cv.append("cut", CUTTER, claim="F002", round=1, when="after"))
    cv.rate("F001", **BELOW)
    slate = _slate(cv)
    assert slate.claims["F001"].state.rating is not None
    assert slate.claims["F001"].state.rating["frequency"] == "rare"
    assert _cuts(cv) == {"F001": (True, "no rule matched"), "F002": (True, "unverified")}
    assert _status(cv, "F001") == "survived"


def test_none_rates_nothing(cv: Converge) -> None:
    cv.ready(cut="none")
    assert ("cut: the slate is in phase attack; cut needs phase cut-before"
            in cv.append("cut", CUTTER, claim="F001", round=1, when="before",
                         confidence="inferred"))
    cv.clean()
    assert protocol.slate_phase(_slate(cv)) == "cutoff"
    assert _cuts(cv) == {"F001": (False, "cut none")}


# -- the per-lens cap ----------------------------------------------------------------


def test_per_lens_cap_is_a_map_with_a_default(cv: Converge) -> None:
    cv.ready(per_lens={"default": 2, "security": 1})
    slate = _slate(cv)
    assert (slate.lens_cap("security"), slate.lens_cap("correctness")) == (1, 2)


def test_the_finder_is_never_capped(cv: Converge) -> None:
    ids = cv.ready(claims=3, per_lens={"default": 1})
    assert ids == ["F001", "F002", "F003"]


def test_unverified_ratings_count_in_the_per_lens_ranking(cv: Converge) -> None:
    cv.ready(cut="both", claims=2, per_lens={"default": 1})
    cv.rate("F001", "before", frequency="common", severity="security")
    cv.rate("F002", "before", frequency="common", severity="data-loss")
    cv.clean("F001")
    cv.rate("F001", **KEPT)
    assert _cuts(cv) == {"F001": (True, "per-lens cap 1 (correctness)"),
                         "F002": (True, "unverified")}


def test_unverified_set_holds_after_a_kill(cv: Converge) -> None:
    cv.ready(cut="before", claims=2, per_lens={"default": 1})
    cv.rate("F001", "before", frequency="common", severity="security")
    cv.rate("F002", "before", frequency="common", severity="data-loss")
    cv.batch_1("F001", refuted=(BATCH_1[0],))
    assert cv.append("reply", FINDER, claim="F001", batch=1, stance="decline") == []
    assert protocol.unverified_ids(_slate(cv)) == {"F002"}
    assert protocol.slate_phase(_slate(cv)) == "cutoff"


def test_per_lens_cap_applies_per_lens(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "after", "gap_hunt": False, "escalate": False},
                    "angles": {"disable": DISABLED},
                    "caps": {"per_lens": {"default": 1, "security": 2}}})
    for lens in ("correctness", "correctness", "security", "security"):
        cv.file(lens=lens)
    cv.cover()
    for cid in ("F001", "F002", "F003", "F004"):
        cv.clean(cid)
    for cid in ("F001", "F002", "F003", "F004"):
        cv.rate(cid, **KEPT)
    assert _cuts(cv) == {"F001": (False, "report_if[1]"),
                         "F002": (True, "per-lens cap 1 (correctness)"),
                         "F003": (False, "report_if[1]"), "F004": (False, "report_if[1]")}
