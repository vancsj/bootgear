"""Agent budget: at most caps.agents distinct ids per slate, main included."""
from __future__ import annotations

from conftest import BATCH_1, CUTTER, DISABLED, FINDER, MAIN, R1, R2, Converge


def test_fifth_agent_allowed_sixth_refused(cv: Converge) -> None:
    cv.ready(cut="after")                                 # 1 orch, 2 finder
    cv.batch_1()                                          # 3 r1
    cv.fresh_eye()                                        # 4 r2
    cv.cut("F001", 1, CUTTER)                             # 5 cutter
    before = cv.path().read_bytes()
    err = cv.cut("F001", 2, "cutter-2", code=2).stderr
    assert "agent budget: cutter-2 would be agent 6 on this slate; caps.agents is 5" in err
    assert "(orch, finder, r1, r2, cutter)" in err
    assert cv.path().read_bytes() == before
    cv.accept("F001", 1)                                  # a known id still writes
    status = cv.status()
    assert status["agents"] == [MAIN, FINDER, R1, R2, CUTTER] and status["agent_cap"] == 5
    assert "agents=5/5" in cv.ok("status", "s1").stdout


def test_custom_cap_three(cv: Converge) -> None:
    cv.ready(agents=3)
    assert cv.attack("F001", BATCH_1[0], agent=R1) == []
    problems = cv.attack("F001", BATCH_1[1], agent=R2)
    assert any("r2 would be agent 4 on this slate; caps.agents is 3" in p for p in problems)
    assert cv.attack("F001", BATCH_1[1], agent=R1) == []


def _cut(cv: Converge, cid: str, when: str, rnd: int, impact: str) -> None:
    cv.cut(cid, rnd, CUTTER, when, impact)


def _gate_ok(cv: Converge) -> None:
    assert cv.status()["phase"] == "cutoff"
    cv.ok("cutoff", "s1")
    assert "GATE ok s1" in cv("gate", "s1", "--dir", str(cv.dir)).stdout


def test_full_depth_allocation_with_gap_hunt(cv: Converge) -> None:
    """main, F (all lenses), R1, R2, C; the gap-hunt claim is filed by R2 and attacked by R1
    in every batch."""
    cv.init(config={"steps": {"cut": "both", "gap_hunt": True, "escalate": True},
                    "angles": {"disable": DISABLED}})
    cv.cover()
    lens_claim = cv.file(agent=FINDER, claim="None crashes the parser")
    gap = cv.file(agent=R2, origin="gap-hunt", claim="ticket asks for retries")
    cv.ok("escalate", "s1", "--as", FINDER, "--claim", lens_claim)
    cv.ok("escalate", "s1", "--as", R2, "--claim", gap)
    _cut(cv, lens_claim, "before", 1, "wrong-output")
    _cut(cv, gap, "before", 1, "data-loss")
    assert "only F002's finder r2 may accept" in cv.accept(gap, 1, FINDER, "before",
                                                           code=2).stderr
    cv.accept(lens_claim, 1, FINDER, "before")
    cv.accept(gap, 1, R2, "before")
    for angle in BATCH_1:
        cv.attack_cli(lens_claim, angle)
    assert "r2 filed F002 and may not attack it" in cv.attack_cli(
        gap, BATCH_1[0], agent=R2, code=2).stderr
    for angle in BATCH_1:
        cv.attack_cli(gap, angle)
    cv.attack_cli(lens_claim, "retry timing", "--last", agent=R2, batch="fresh-eye")
    cv.attack_cli(gap, "retry timing", "--last", agent=R1, batch="fresh-eye")
    _cut(cv, lens_claim, "after", 1, "wrong-output")
    _cut(cv, gap, "after", 1, "data-loss")
    cv.accept(lens_claim, 1, FINDER)
    cv.rebut_cut(gap, "every retry path is hit on deploy", R2)
    _cut(cv, gap, "after", 2, "data-loss")
    _gate_ok(cv)
    assert cv.status()["agents"] == [MAIN, FINDER, R2, CUTTER, R1]
    assert cv.ok("converged", "s1").stdout.startswith("CONVERGED\n")


def test_quick_depth_shape(cv: Converge) -> None:
    """main, F, R1, C: one refuter attacks every batch, the fresh-eye batch included."""
    cv.init("s1", "correctness,tests", MAIN, "--refuters", "1",
            config={"steps": {"cut": "both", "gap_hunt": False, "escalate": True},
                    "angles": {"disable": DISABLED}})
    cv.cover(lenses=("correctness", "tests"))
    cid = cv.file(agent=FINDER)
    cv.ok("escalate", "s1", "--as", FINDER, "--claim", cid)
    _cut(cv, cid, "before", 1, "wrong-output")
    cv.accept(cid, 1, FINDER, "before")
    for angle in BATCH_1:
        cv.attack_cli(cid, angle)
    cv.attack_cli(cid, "retry timing", "--last", agent=R1, batch="fresh-eye")
    _cut(cv, cid, "after", 1, "wrong-output")
    cv.accept(cid, 1, FINDER)
    _gate_ok(cv)
    assert cv.status()["agents"] == [MAIN, FINDER, CUTTER, R1]


def test_cap_above_five_refused_at_init(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("caps: {agents: 6}\n")
    err = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness",
                     "--project-root", str(cv.project), "--config", str(task))
    assert "caps.agents must be at most 5" in err
    assert not cv.path().exists()
