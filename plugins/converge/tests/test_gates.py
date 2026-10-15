"""The two gates: gate 1 (attack or skip) from the before cut and the finder's tier, gate 2
(finding or follow-up) from the after cut and the claim's status; the per-lens policy; the
cut schema (`rate` only when the lens policy counts it, `choice` while cheap fixes are on)."""
from __future__ import annotations

from typing import Any

from conftest import BATCH_1, CUTTER, DISABLED, FINDER, MAIN, Converge
from converge import config as config_mod
from converge import ledger, model, protocol

UNREACHABLE = {"impact": "cosmetic", "reach": "unreachable"}
PATCH = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
         "@@ -10,1 +10,3 @@\n-x = None\n+x = load()\n+if x is None:\n+    raise ValueError\n")


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _task(cut: str, **cutoff: Any) -> dict[str, Any]:
    task: dict[str, Any] = {"steps": {"cut": cut, "gap_hunt": False, "escalate": False},
                            "angles": {"disable": DISABLED}}
    if cutoff:
        task["cutoff"] = cutoff
    return task


def _filed(cv: Converge, *tiers: str, cut: str = "before", lens: str = "correctness",
           rules: tuple[str | None, ...] = (), caps: dict[str, Any] | None = None,
           **cutoff: Any) -> list[str]:
    """One claim per tier on `lens`, with find coverage complete on every lens."""
    task = _task(cut, **cutoff)
    if caps:
        task["caps"] = caps
    cv.init("s1", "correctness,security,architecture", MAIN, config=task)
    angle = "god-object" if lens == "architecture" else "changed-contract"
    ids = []
    for index, tier in enumerate(tiers):
        rule = rules[index] if index < len(rules) else None
        ids.append(cv.file(lens=lens, angle=angle, claim=f"claim {index}", tier=tier,
                           extra=("--rule", rule) if rule else ()))
    cv.cover(lenses=("correctness", "security", "architecture"))
    cv.ok("angle-na", "s1", "--as", FINDER, "--phase", "find", "--angle", "god-object",
          "--lens", "architecture", "--reason", "no class in diff")
    return ids


# -- gate 1 --------------------------------------------------------------------------


def test_gate1_uses_finder_tier(cv: Converge) -> None:
    reproduced, traced = _filed(cv, "reproduced", "traced")
    for cid in (reproduced, traced):
        cv.rate(cid, "before", impact="cosmetic", reach="normal")
    slate = _slate(cv)
    assert protocol.gate1(slate, slate.claims[reproduced],
                          slate.claims[reproduced].state.cuts["before"].latest()) == (
        True, "attack_if[1]")
    assert protocol.unverified_ids(slate) == {traced}
    assert protocol.status(slate, slate.claims[traced]) == "unverified"


def test_gate1_no_match_is_unverified(cv: Converge) -> None:
    kept, skipped = _filed(cv, "traced", "reproduced")
    cv.rate(kept, "before", impact="wrong-output", reach="crafted")
    cv.rate(skipped, "before", **UNREACHABLE)
    slate = _slate(cv)
    assert protocol.gate1(slate, slate.claims[kept],
                          slate.claims[kept].state.cuts["before"].latest()) == (
        True, "attack_if[0]")
    assert protocol.unverified_ids(slate) == {skipped}
    assert ("attack: F002 is unverified (cut before the attack); it takes no attack"
            in cv.attack(skipped, BATCH_1[0]))
    cv.clean(kept)
    assert protocol.cut_reasons(_slate(cv))[skipped] == (True, "unverified")


def test_report_rules_claim_always_attacked(cv: Converge) -> None:
    (tagged,) = _filed(cv, "inferred", rules=("R002",), report_rules=["R002"])
    cv.rate(tagged, "before", **UNREACHABLE)
    slate = _slate(cv)
    assert protocol.gate1(slate, slate.claims[tagged],
                          slate.claims[tagged].state.cuts["before"].latest()) == (
        True, "report_rules[R002]")
    assert protocol.unverified_ids(slate) == set()
    cv.clean(tagged)
    assert protocol.cut_reasons(_slate(cv))[tagged] == (False, "report_rules[R002]")


def test_lens_policy_falls_back_to_default(cv: Converge) -> None:
    lenses = {"security": {"attack_if": [{"reach": ["unreachable"]}]}}
    on_security = _filed(cv, "traced", lens="security", lenses=lenses)[0]
    cv.rate(on_security, "before", **UNREACHABLE)
    slate = _slate(cv)
    assert slate.lens_policy("security") == lenses["security"]
    assert slate.lens_policy("correctness") == config_mod.DEFAULTS["cutoff"]["lenses"]["default"]
    assert protocol.unverified_ids(slate) == set()


def test_gate1_reads_rate_at_least(cv: Converge) -> None:
    lenses = {"architecture": {"attack_if": [{"tier": ["traced"], "rate_at_least": 3}],
                               "report_if": [{"tier": ["traced"], "rate_at_least": 3}]}}
    busy, quiet = _filed(cv, "traced", "traced", lens="architecture", lenses=lenses)
    cv.rate(busy, "before", rate=3, evidence={**_evidence(), "call-site-count": "rg x: 3"})
    cv.rate(quiet, "before", rate=2, evidence={**_evidence(), "call-site-count": "rg x: 2"})
    assert protocol.unverified_ids(_slate(cv)) == {quiet}


# -- gate 2 --------------------------------------------------------------------------


def test_gate2_reads_status_tier_and_after_cut(cv: Converge) -> None:
    lenses = {"default": {"report_if": [{"status": ["survived"], "tier": ["reproduced"],
                                         "difficulty": ["cross-cutting"]}]}}
    shown, traced, redesign = _filed(cv, "reproduced", "traced", "reproduced", cut="after",
                                     lenses=lenses)
    for cid in (shown, traced, redesign):
        cv.clean(cid)
    cv.rate(shown)
    cv.rate(traced)
    cv.rate(redesign, difficulty="redesign", choice="split the module or keep it")
    slate = _slate(cv)
    assert protocol.gate2(slate, slate.claims[shown], slate.claims[shown].state.rating) == (
        "finding", "report_if[0]")
    assert protocol.cut_reasons(slate) == {shown: (False, "report_if[0]"),
                                           traced: (True, "no rule matched"),
                                           redesign: (True, "no rule matched")}


def test_per_lens_cap_counts_findings_only(cv: Converge) -> None:
    ids = _filed(cv, "traced", "traced", "traced", cut="after", caps={"per_lens": {"default": 1}})
    for cid in ids:
        cv.clean(cid)
    cv.rate(ids[0], impact="security", reach="unreachable")
    cv.rate(ids[1], impact="data-loss")
    cv.rate(ids[2], impact="wrong-output")
    assert protocol.cut_reasons(_slate(cv)) == {
        ids[0]: (True, "no rule matched"), ids[1]: (False, "report_if[0]"),
        ids[2]: (True, "per-lens cap 1 (correctness)")}


def test_rank_key_orders_rate_descending() -> None:
    def key(tier: str, cid: str, **values: Any) -> tuple[Any, ...]:
        rating = {"impact": "wrong-output", "size": "one", "reach": "normal", **values}
        return model.rating_key(rating, tier, cid)

    ordered = [
        key("inferred", "F009", impact="security"),
        key("inferred", "F008", reach="crafted", impact="data-loss"),
        key("inferred", "F007", size="many"),
        key("inferred", "F006", rate=9),
        key("inferred", "F005", rate=2),
        key("reproduced", "F004"),
        key("traced", "F002"),
        key("traced", "F003"),
        key("inferred", "F001", reach="crafted"),
        model.rating_key(None, "reproduced", "F010"),
    ]
    assert sorted(ordered) == ordered


# -- the cut schema --------------------------------------------------------------------


def _evidence() -> dict[str, str]:
    return {"entry-points": "POST /x reaches it", "blast-radius": "one row per call",
            "affected-count": "one record", "files-touched": "a.py"}


def test_rate_optional_stored_as_zero_and_required_by_rate_at_least(cv: Converge) -> None:
    lenses = {"architecture": {"choice_if": [{"rate_at_least": 3}]}}
    (plain,) = _filed(cv, "traced", lenses=lenses)
    counted = Converge(cv.root / "arch")
    _filed(counted, "traced", lens="architecture", lenses=lenses)
    assert cv.append("cut", CUTTER, claim=plain, round=1, when="before") == []
    assert (_slate(cv).claims[plain].state.rating or {})["rate"] == 0
    problems = counted.append("cut", CUTTER, claim="F001", round=1, when="before")
    assert ("cut: F001's lens architecture has a rate_at_least rule; `rate` is required"
            in problems)
    assert "cut: no evidence for `rate` (give an evaluate angle whose field is rate)" in problems
    problems = counted.append("cut", CUTTER, claim="F001", round=1, when="before", rate=-1,
                              evidence={**_evidence(), "call-site-count": "rg x"})
    assert "`rate` must be a non-negative integer; got -1" in problems
    assert counted.append("cut", CUTTER, claim="F001", round=1, when="before", rate=4,
                          evidence={**_evidence(), "call-site-count": "rg x: 4 hits"}) == []


def test_before_cut_refuses_difficulty_and_patch(cv: Converge) -> None:
    (cid,) = _filed(cv, "traced")
    problems = cv.append("cut", CUTTER, claim=cid, round=1, when="before",
                         difficulty="local", patch="--- a/x\n+++ b/x\n")
    assert "cut: a before cut carries no `difficulty`" in problems
    assert "cut: a before cut carries no `patch`" in problems


def test_after_cut_needs_difficulty_and_its_evidence(cv: Converge) -> None:
    (cid,) = _filed(cv, "traced", cut="after")
    cv.clean(cid)
    evidence = {k: v for k, v in _evidence().items() if k != "files-touched"}
    problems = cv.append("cut", CUTTER, claim=cid, round=1, when="after", difficulty=None,
                         evidence=evidence)
    assert "cut: an after cut needs `difficulty`" in problems
    assert ("cut: no evidence for `difficulty` (give an evaluate angle whose field is "
            "difficulty)") in problems
    problems = cv.append("cut", CUTTER, claim=cid, round=1, when="after",
                         callers="some", migration="maybe")
    assert "`callers` must be one of none, changed; got 'some'" in problems
    assert "`migration` must be one of none, needed; got 'maybe'" in problems


def test_choice_follows_cheap_enabled(cv: Converge) -> None:
    (cid,) = _filed(cv, "traced", cut="after")
    cv.clean(cid)
    assert ("cut: F001 has difficulty redesign; a non-empty `choice` is required"
            in cv.append("cut", CUTTER, claim=cid, round=1, when="after", difficulty="redesign",
                         choice=None))
    other = Converge(cv.root / "spec")
    (cid,) = _filed(other, "traced", cut="after", cheap={"enabled": False})
    other.clean(cid)
    assert other.append("cut", CUTTER, claim=cid, round=1, when="after",
                        difficulty="redesign", choice=None) == []


def test_choice_if_requires_a_choice(cv: Converge) -> None:
    lenses = {"default": {"choice_if": [{"difficulty": ["cross-cutting"],
                                         "status": ["survived"]}]}}
    (cid,) = _filed(cv, "traced", cut="after", lenses=lenses, cheap={"enabled": False})
    cv.clean(cid)
    assert ("cut: F001 matches choice_if[0]; a non-empty `choice` is required"
            in cv.append("cut", CUTTER, claim=cid, round=1, when="after", choice=None))
    assert cv.append("cut", CUTTER, claim=cid, round=1, when="after", choice="a or b") == []


def test_cut_cli_flags(cv: Converge) -> None:
    (cid,) = _filed(cv, "traced", cut="after")
    cv.clean(cid)
    out = cv.ok("cut", "s1", "--as", CUTTER, "--claim", cid, "--when", "after", "--round", "1",
                "--impact", "data-loss", "--size", "many", "--reach", "normal", "--rate", "2",
                "--difficulty", "local", "--callers", "none", "--migration", "none",
                "--patch", PATCH,
                "--evidence", "entry-points=e", "--evidence", "blast-radius=b",
                "--evidence", "affected-count=a", "--evidence", "files-touched=f").stdout
    assert out.startswith("CUT seq=")
    event = cv.events()[-1]
    assert {k: event[k] for k in ("impact", "size", "reach", "rate", "difficulty", "callers",
                                  "migration")} == {
        "impact": "data-loss", "size": "many", "reach": "normal", "rate": 2,
        "difficulty": "local", "callers": "none", "migration": "none"}
    assert cv.status()["by_id"][cid]["rating"] == {
        "impact": "data-loss", "size": "many", "reach": "normal", "rate": 2,
        "difficulty": "local"}
    err = cv.refused("cut", "s1", "--as", CUTTER, "--claim", cid, "--when", "after",
                     "--round", "2", "--impact", "cosmetic", "--size", "one",
                     "--reach", "normal", "--fix", "x")
    assert "unrecognized arguments: --fix x" in err
