"""Refute closure when attack angles run out, stale cuts, parking and follow-up results."""
from __future__ import annotations

from conftest import add_claim, add_cut, add_refute, make_slate
from converge import model


def test_legacy_refute_state_ignores_exhaustion() -> None:
    slate = make_slate(attack=2, legacy=True)
    claim = add_claim(slate)
    add_refute(slate, claim, 1, "boundary", "downgraded")
    add_refute(slate, claim, 1, "reachability")
    assert not slate.v2
    assert slate.refute_state(claim) == "open"
    assert model.refute_state(claim, 5) == "open"


def test_no_round_and_every_angle_not_applicable_is_unconverged() -> None:
    slate = make_slate(attack=2)
    claim = add_claim(slate)
    assert slate.refute_state(claim) == "open"
    claim.na_angles.update({"boundary", "reachability"})
    assert slate.refute_state(claim) == "unconverged"


def test_incomplete_last_round_closes_when_angles_run_out() -> None:
    slate = make_slate(attack=3)
    claim = add_claim(slate)
    add_refute(slate, claim, 1, "boundary", "downgraded")
    add_refute(slate, claim, 1, "reachability")
    add_refute(slate, claim, 2, "provenance")
    assert slate.refute_state(claim) == "unconverged"
    assert model.refute_state(claim, 5, attack_total=4) == "open"


def test_complete_quiet_round_converges_even_when_exhausted() -> None:
    slate = make_slate(attack=2)
    claim = add_claim(slate)
    add_refute(slate, claim, 1, "boundary")
    add_refute(slate, claim, 1, "reachability", "inconclusive")
    assert slate.refute_state(claim) == "inconclusive"


def test_round_cap_still_closes_and_dead_claims_stay_dead() -> None:
    slate = make_slate(refute_rounds=1)
    claim = add_claim(slate)
    add_refute(slate, claim, 1, "boundary", "downgraded")
    add_refute(slate, claim, 1, "reachability")
    assert slate.refute_state(claim) == "unconverged"
    dead = add_claim(slate)
    add_refute(slate, dead, 1, "boundary", "killed")
    assert slate.refute_state(dead) == "killed"


def test_downgrade_after_cut_makes_it_stale() -> None:
    slate = make_slate(cut_rounds=2)
    claim = add_claim(slate)
    add_cut(slate, claim)
    assert slate.cut_state(claim) == "converged"
    add_refute(slate, claim, 1, "boundary", "downgraded")
    assert slate.cut_state(claim) == "open"
    assert model.cut_state(claim, 2) == "converged"   # legacy rule: no staleness
    add_cut(slate, claim)
    assert slate.cut_state(claim) == "converged"
    claim.stale_seq = 99
    assert slate.cut_state(claim) == "capped"


def test_parked_needs_a_done_cosmetic_cut_and_open_refute() -> None:
    slate = make_slate()
    claim = add_claim(slate)
    add_cut(slate, claim, "cosmetic", fix="rename the label")
    assert slate.parked(claim) and slate.phase(claim) is None
    assert claim not in [c for c, _ in slate.open_claims()]
    claim.rule = "R001"
    slate.config["cutoff"]["report_rules"] = ["R001"]
    assert not slate.parked(claim) and slate.phase(claim) == "refute"
    other = add_claim(slate)
    add_cut(slate, other, "cosmetic", accept=False)
    assert not slate.parked(other)
    legacy = make_slate(legacy=True)
    old = add_claim(legacy)
    add_cut(legacy, old, "cosmetic")
    assert not legacy.parked(old)


def test_phase_with_early_cut() -> None:
    slate = make_slate()
    claim = add_claim(slate)
    assert slate.phase(claim) == "cut"
    add_cut(slate, claim, accept=False)
    assert slate.phase(claim) == "cut"
    claim.accepted_round = 1
    assert slate.phase(claim) == "refute"
    add_refute(slate, claim, 1, "boundary", "downgraded")
    assert slate.phase(claim) == "refute"           # round 1 holds one event
    add_refute(slate, claim, 1, "reachability")
    assert slate.phase(claim) == "cut"              # the downgrade made the cut stale
    add_cut(slate, claim)
    assert slate.phase(claim) == "refute"
    add_refute(slate, claim, 2, "provenance")
    add_refute(slate, claim, 2, "carve-out")
    assert slate.phase(claim) is None


def test_phase_without_early_cut_and_refute_only() -> None:
    slate = make_slate(steps={"early_cut": False})
    claim = add_claim(slate)
    assert slate.phase(claim) == "refute"
    add_refute(slate, claim, 1, "boundary")
    add_refute(slate, claim, 1, "reachability")
    assert slate.phase(claim) == "cut"
    only = make_slate(mode="refute-only")
    slate_claim = add_claim(only, finder="slate")
    assert only.phase(slate_claim) == "refute"
    add_refute(only, slate_claim, 1, "boundary")
    add_refute(only, slate_claim, 1, "reachability")
    assert only.phase(slate_claim) is None


def test_refute_round_complete() -> None:
    slate = make_slate(attack=2)
    claim = add_claim(slate)
    assert slate.refute_round_complete(claim)
    add_refute(slate, claim, 1, "boundary")
    assert not slate.refute_round_complete(claim)
    claim.na_angles.add("reachability")
    assert slate.refute_round_complete(claim)


def _row(slate: model.Slate, claim: model.Claim) -> tuple[str, str]:
    row = next(r for r in model.compute_cutoff(slate) if r.claim is claim)
    return row.result, row.reason


def test_cutoff_follow_up_rows() -> None:
    slate = make_slate(attack=2)
    parked = add_claim(slate)
    add_cut(slate, parked, "cosmetic", fix="reword")
    quiet = add_claim(slate)
    add_cut(slate, quiet, "degraded", "common")
    add_refute(slate, quiet, 1, "boundary", "downgraded")
    add_refute(slate, quiet, 1, "reachability")
    add_cut(slate, quiet, "degraded", "common")
    blocking = add_claim(slate)
    add_cut(slate, blocking, "data-loss", "common")
    blocking.na_angles.update({"boundary", "reachability"})
    rare = add_claim(slate)
    add_cut(slate, rare, "security", "rare")
    rare.na_angles.update({"boundary", "reachability"})
    assert slate.refute_state(quiet) == "unconverged"
    assert _row(slate, parked) == ("follow-up", "unverified")
    assert _row(slate, quiet) == ("follow-up", "unconverged")
    assert _row(slate, blocking) == ("reported", "unconverged")
    assert _row(slate, rare) == ("follow-up", "unconverged")


def test_legacy_cutoff_keeps_unconverged_reported() -> None:
    slate = make_slate(refute_rounds=1, legacy=True)
    claim = add_claim(slate)
    add_refute(slate, claim, 1, "boundary", "downgraded")
    add_refute(slate, claim, 1, "reachability")
    add_cut(slate, claim, "cosmetic", "rare")
    assert _row(slate, claim) == ("reported", "unconverged")


def test_rule_tagged_unconverged_claim_stays_reported() -> None:
    slate = make_slate(attack=2)
    slate.config["cutoff"]["report_rules"] = ["R001"]
    claim = add_claim(slate)
    claim.rule = "R001"
    add_cut(slate, claim, "cosmetic", "rare", fix="reword")
    assert not slate.parked(claim)
    claim.na_angles.update({"boundary", "reachability"})
    assert slate.refute_state(claim) == "unconverged"
    assert not slate.parked(claim)
    assert _row(slate, claim) == ("reported", "unconverged")
