"""Not-applicable attack angles on one claim (R5): a refuter records them, and a claim with
no attack angle left closes `unconverged`."""
from __future__ import annotations

from conftest import CUTTER, FINDER, MAIN, R1, R2, Converge
from converge import ledger

ATTACK = ("cited-but-unread", "point-in-time", "provenance", "reachability", "absent-vs-default",
          "downstream-consumer", "inverse-reading", "carve-out", "boundary", "dependents",
          "positive-control", "inherited-bounds", "guarded-elsewhere", "deliberate", "real-referent")
# Three attack angles left: boundary, reachability, provenance.
THREE_ATTACK = {"angles": {"disable": [a for a in ATTACK
                                       if a not in ("boundary", "reachability", "provenance")]}}


def _na(cv: Converge, agent: str, angle: str, claim: str | None = "F001", **extra: str
        ) -> list[str]:
    fields = {"phase": "refute", "angle": angle, "reason": "no such path here", **extra}
    if claim is not None:
        fields["claim"] = claim
    return cv.append("angle-na", agent, **fields)


def _ready(cv: Converge, config: dict | None = None) -> None:
    """A steps slate whose F001 is escalated and has a converged cut."""
    cv.init(defaults=True, config=config)
    cv.file()
    assert cv.append("escalate", FINDER, claim="F001") == []
    cv.cut_converge("F001")


def test_refuter_records_a_not_applicable_angle(cv: Converge) -> None:
    _ready(cv)
    assert _na(cv, R1, "boundary") == []
    claim = ledger.read(cv.path(), "s1").claims["F001"]
    assert claim.na_angles == {"boundary"}
    assert "boundary" not in cv.status()["by_id"]["F001"]["unused_attack_angles"]
    err = cv.refute("F001", 1, "boundary", R2, code=2).stderr
    assert "angle 'boundary' is recorded not applicable to F001" in err


def test_roles_and_shape(cv: Converge) -> None:
    _ready(cv)
    assert "refute: finder filed F001 and may not refute it" in _na(cv, FINDER, "boundary")
    assert "refute: orch wrote init; the orchestrator never writes refute" in _na(
        cv, MAIN, "boundary")
    assert "refute: cutter cut F001; refuters and cutters are disjoint" in _na(
        cv, CUTTER, "boundary")
    assert "angle-na: phase refute needs `claim`" in _na(cv, R1, "boundary", claim=None)
    assert "unknown claim 'F009'" in _na(cv, R1, "boundary", claim="F009")
    assert "`lens` is only recorded for phase find" in _na(cv, R1, "boundary",
                                                           lens="correctness")
    cv.refute("F001", 1, "reachability", R1)
    assert "angle-na: angle 'reachability' was already used on F001" in _na(cv, R2, "reachability")
    assert _na(cv, R1, "boundary") == []
    assert "angle-na: angle 'boundary' is already recorded not applicable to F001" in _na(
        cv, R2, "boundary")
    problems = cv.append("angle-na", FINDER, phase="find", angle="failure-path",
                         lens="correctness", reason="no I/O", claim="F001")
    assert "angle-na: `claim` is only recorded for phase refute" in problems


def test_legacy_slate_refuses_claim(cv: Converge) -> None:
    cv.init(legacy=True)
    cv.file()
    assert _na(cv, R1, "boundary", claim=None) == []
    assert "angle-na: `claim` is recorded only on slates with a steps config" in _na(
        cv, R1, "boundary")


def test_exhausted_claim_is_unconverged_and_can_be_cut(cv: Converge) -> None:
    _ready(cv, THREE_ATTACK)
    cv.refute("F001", 1, "boundary", R1, "downgraded", "--narrowed", "only on retry")
    cv.refute("F001", 1, "reachability", R2)
    assert cv.status()["by_id"]["F001"]["refute"] == "open"
    assert _na(cv, R1, "provenance") == []
    assert cv.status()["by_id"]["F001"]["refute"] == "unconverged"
    cv.cut("F001", 2, CUTTER, "rare", "degraded")
    cv.accept("F001", 2)
    cv.cover()
    rows = cv.ok("cutoff", "s1").stdout
    assert "F001 follow-up rank=1 reason=unconverged" in rows


def test_angle_na_command_takes_a_claim(cv: Converge) -> None:
    _ready(cv)
    out = cv.ok("angle-na", "s1", "--as", R1, "--phase", "refute", "--claim", "F001",
                "--angle", "boundary", "--reason", "no boundary in a constant").stdout
    assert out.startswith("ANGLE-NA seq=") and "phase=refute angle=boundary" in out
    assert "boundary" not in cv.status()["by_id"]["F001"]["unused_attack_angles"]


def test_refusal_without_claim_shows_the_refute_example(cv: Converge) -> None:
    _ready(cv)
    err = cv.refused("angle-na", "s1", "--as", R1, "--phase", "refute", "--angle", "boundary",
                     "--reason", "no boundary in a constant")
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--phase refute --claim" in example


def test_refusal_without_lens_shows_the_find_example(cv: Converge) -> None:
    _ready(cv)
    err = cv.refused("angle-na", "s1", "--as", FINDER, "--phase", "find",
                     "--angle", "failure-path", "--reason", "no I/O")
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--phase find --lens" in example


def test_usage_refusal_follows_the_phase(cv: Converge) -> None:
    _ready(cv)
    err = cv.refused("angle-na", "s1", "--as", FINDER, "--phase", "find", "--lens", "correctness",
                     "--angle", "failure-path")
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--reason" in err and "--phase find --lens" in example
    err = cv.refused("angle-na", "s1", "--as", R1, "--phase", "refute", "--claim", "F001",
                     "--angle", "boundary")
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--phase refute --claim" in example
