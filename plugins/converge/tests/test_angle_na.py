"""Not-applicable attack angles on one claim: a refuter records them in the attack phase."""
from __future__ import annotations

from conftest import BATCH_1, CUTTER, FINDER, MAIN, R1, R2, Converge
from converge import ledger


def _na(cv: Converge, agent: str, angle: str, claim: str | None = "F001", **extra: str
        ) -> list[str]:
    fields = {"phase": "attack", "angle": angle, "reason": "no such path here", **extra}
    if claim is not None:
        fields["claim"] = claim
    return cv.append("angle-na", agent, **fields)


def test_refuter_records_a_not_applicable_angle(cv: Converge) -> None:
    cv.ready()
    assert _na(cv, R1, BATCH_1[0]) == []
    claim = ledger.read(cv.path(), "s1").claims["F001"]
    assert claim.na_angles == {BATCH_1[0]}
    assert BATCH_1[0] not in cv.status()["by_id"]["F001"]["fixed_remaining"]
    assert (f"attack: angle {BATCH_1[0]!r} is recorded not applicable to F001"
            in cv.attack("F001", BATCH_1[0], agent=R2))


def test_status_shows_na_reason_beside_fixed_angle(cv: Converge) -> None:
    cv.ready()
    assert _na(cv, R1, BATCH_1[0], reason="no time window") == []
    claim = cv.status()["by_id"]["F001"]
    assert claim["na_reasons"] == {BATCH_1[0]: "no time window"}
    assert BATCH_1[0] not in claim["fixed_remaining"]
    [line] = [line for line in cv.ok("status", "s1").stdout.splitlines()
              if line.startswith("F001 ")]
    assert line.endswith(f"na[{BATCH_1[0]}]=no time window")


def test_status_shows_a_fresh_eye_attack_on_a_not_applicable_angle(cv: Converge) -> None:
    cv.ready()
    assert _na(cv, R1, BATCH_1[0], reason="no time window") == []
    for angle in BATCH_1[1:]:
        assert cv.attack("F001", angle) == []
    assert cv.attack("F001", BATCH_1[0], agent=R2, batch="fresh-eye") == []
    claim = cv.status()["by_id"]["F001"]
    assert claim["fresh_eye"] == [BATCH_1[0]]
    [line] = [line for line in cv.ok("status", "s1").stdout.splitlines()
              if line.startswith("F001 ")]
    assert f"fresh-eye={BATCH_1[0]} na[{BATCH_1[0]}]=no time window" in line


def test_roles_and_shape(cv: Converge) -> None:
    cv.ready(cut="before")
    assert cv.append("cut", CUTTER, claim="F001", round=1, when="before",
                     confidence="inferred") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="before") == []
    assert "attack: finder filed F001 and may not attack it" in _na(cv, FINDER, BATCH_1[0])
    assert "attack: orch wrote init; the orchestrator never writes attack" in _na(
        cv, MAIN, BATCH_1[0])
    assert "attack: cutter cut F001; refuters and cutters are disjoint" in _na(
        cv, CUTTER, BATCH_1[0])
    assert "angle-na: phase attack needs `claim`" in _na(cv, R1, BATCH_1[0], claim=None)
    assert "unknown claim 'F009'" in _na(cv, R1, BATCH_1[0], claim="F009")
    assert "`lens` is only recorded for phase find" in _na(cv, R1, BATCH_1[0],
                                                           lens="correctness")
    assert "unknown attack angle 'boundary' (not in this slate's init snapshot)" in _na(
        cv, R1, "boundary")
    assert cv.attack("F001", BATCH_1[1]) == []
    assert (f"angle-na: angle {BATCH_1[1]!r} was already used on F001"
            in _na(cv, R2, BATCH_1[1]))
    assert _na(cv, R1, BATCH_1[0]) == []
    assert (f"angle-na: angle {BATCH_1[0]!r} is already recorded not applicable to F001"
            in _na(cv, R2, BATCH_1[0]))
    problems = cv.append("angle-na", FINDER, phase="find", angle="failure-path",
                         lens="correctness", reason="no I/O", claim="F001")
    assert "angle-na: `claim` is only recorded for phase attack" in problems


def test_angle_na_command_takes_a_claim(cv: Converge) -> None:
    cv.ready()
    out = cv.ok("angle-na", "s1", "--as", R1, "--phase", "attack", "--claim", "F001",
                "--angle", BATCH_1[0], "--reason", "no boundary in a constant").stdout
    assert out.startswith("ANGLE-NA seq=") and f"phase=attack angle={BATCH_1[0]}" in out
    assert BATCH_1[0] not in cv.status()["by_id"]["F001"]["fixed_remaining"]


def test_refusal_without_claim_shows_the_attack_example(cv: Converge) -> None:
    cv.ready()
    err = cv.refused("angle-na", "s1", "--as", R1, "--phase", "attack", "--angle", BATCH_1[0],
                     "--reason", "no boundary in a constant")
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--phase attack --claim" in example


def test_refusal_without_lens_shows_the_find_example(cv: Converge) -> None:
    cv.ready()
    err = cv.refused("angle-na", "s1", "--as", FINDER, "--phase", "find",
                     "--angle", "failure-path", "--reason", "no I/O")
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--phase find --lens" in example


def test_usage_refusal_follows_the_phase(cv: Converge) -> None:
    cv.ready()
    err = cv.refused("angle-na", "s1", "--as", FINDER, "--phase", "find", "--lens", "correctness",
                     "--angle", "failure-path")
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--reason" in err and "--phase find --lens" in example
    err = cv.refused("angle-na", "s1", "--as", R1, "--phase", "attack", "--claim", "F001",
                     "--angle", BATCH_1[0])
    example = next(line for line in err.splitlines() if line.startswith("example: "))
    assert "--phase attack --claim" in example
