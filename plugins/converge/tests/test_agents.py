"""Agent budget: at most caps.agents distinct ids per slate, and the allocations it serves."""
from __future__ import annotations

from conftest import CUTTER, FINDER, MAIN, R1, R2, Converge


def test_fifth_agent_allowed_sixth_refused(cv: Converge) -> None:
    cv.init(agent=MAIN)                                   # 1
    cv.file(agent=FINDER)                                 # 2
    cv.refute("F001", 1, "boundary", R1)                  # 3
    cv.refute("F001", 1, "reachability", R2)              # 4
    cv.cut("F001", 1, CUTTER)                             # 5
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
    task = cv.root / "task.yaml"
    task.write_text("caps: {agents: 3}\n")
    cv.init("s1", "full", "correctness", MAIN, "--config", str(task))
    cv.file(agent=FINDER)
    cv.refute("F001", 1, "boundary", R1)
    err = cv.refute("F001", 1, "reachability", R2, code=2).stderr
    assert "r2 would be agent 4 on this slate; caps.agents is 3" in err
    cv.refute("F001", 1, "reachability", R1)
    assert cv.status()["by_id"]["F001"]["refute"] == "converged"


def test_cap_above_five_refused_at_init(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("caps: {agents: 6}\n")
    err = cv.refused("init", "s1", "--as", MAIN, "--mode", "full", "--lenses", "correctness",
                     "--project-root", str(cv.project), "--config", str(task))
    assert "caps.agents must be at most 5" in err
    assert not cv.path().exists()


def test_reserved_ids_do_not_count(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("caps: {agents: 3}\n")
    cv.init("s1", "refute-only", "", MAIN, "--config", str(task))
    cv.file(agent="slate", lens="", angle="", origin="slate")
    cv.refute("F001", 1, "boundary", R1)
    cv.refute("F001", 1, "reachability", R2)
    assert cv.status()["agents"] == [MAIN, R1, R2]


def test_full_depth_allocation_with_gap_hunt(cv: Converge) -> None:
    """main, F (all lenses), R1, R2, C; gap hunt filed by R2 and refuted by R1."""
    cv.init(agent=MAIN)
    cv.cover()
    lens_claim = cv.file(agent=FINDER, claim="None crashes the parser")
    cv.refute(lens_claim, 1, "boundary", R1)
    cv.refute(lens_claim, 1, "reachability", R2)
    cv.ok("converged", "s1", "--phase", "refute")
    gap = cv.file(agent=R2, lens="gap-hunt", origin="gap-hunt", claim="ticket asks for retries")
    assert "r2 filed F002 and may not refute it" in cv.refute(gap, 1, "boundary", R2, code=2).stderr
    cv.refute(gap, 1, "boundary", R1)
    cv.refute(gap, 1, "provenance", R1)
    cv.ok("converged", "s1", "--phase", "refute")
    cv.cut(lens_claim, 1, CUTTER, "common", "wrong-behavior")
    cv.cut(gap, 1, CUTTER, "common", "degraded")
    assert "only F002's finder r2 may accept" in cv.accept(gap, 1, FINDER, code=2).stderr
    cv.accept(lens_claim, 1, FINDER)
    cv.rebut_cut(gap, "every retry path is hit on deploy", R2)
    cv.cut(gap, 2, CUTTER, "common", "degraded")
    cv.ok("converged", "s1", "--phase", "cut")
    cv.ok("cutoff", "s1")
    assert "GATE ok s1" in cv("gate", "s1", "--dir", str(cv.dir)).stdout
    assert cv.status()["agents"] == [MAIN, FINDER, R1, R2, CUTTER]


def test_quick_depth_shape(cv: Converge) -> None:
    """main, F, R1, C: one refuter writes both refutes of a round."""
    cv.init(lenses="correctness,tests", agent=MAIN)
    cv.cover(lenses=("correctness", "tests"))
    cid = cv.file(agent=FINDER)
    cv.refute(cid, 1, "boundary", R1)
    cv.refute(cid, 1, "reachability", R1)
    cv.cut_converge(cid)
    cv.ok("cutoff", "s1")
    assert "GATE ok s1" in cv("gate", "s1", "--dir", str(cv.dir)).stdout
    assert cv.status()["agents"] == [MAIN, FINDER, R1, CUTTER]
