"""Computed cutoff: default rules, gap-hunt rules, per-lens cap, forced reporting, rank."""
from __future__ import annotations

import json

from conftest import Converge


def _results(cv: Converge, slate: str = "s1") -> dict[str, tuple[str, int]]:
    out = cv.ok("cutoff", slate).stdout.splitlines()
    assert out[0].startswith("CUTOFF seq=")
    rows = {}
    for line in out[1:]:
        if line.startswith("next: "):
            continue
        cid, result, rank, _ = line.split(" ", 3)
        rows[cid] = (result, int(rank.removeprefix("rank=")))
    return rows


def _claim(cv: Converge, freq: str, sev: str, conf: str = "traced", diff: str = "local",
           origin: str = "lens", lens: str = "correctness") -> str:
    cid = cv.file(lens=lens, origin=origin, claim=f"{sev} {freq}")
    cv.quiet_round(cid, 1, ("boundary", "reachability"))
    cv.cut_converge(cid, freq, sev, conf, diff)
    return cid


def test_default_rules(cv: Converge) -> None:
    cv.init()
    cv.cover()
    a = _claim(cv, "rare", "security")              # rule 0
    b = _claim(cv, "common", "wrong-behavior")      # rule 1
    c = _claim(cv, "rare", "wrong-behavior")        # no rule
    d = _claim(cv, "contrived", "degraded", "reproduced")  # contrived not in rule 2
    e = _claim(cv, "every-call", "cosmetic", "reproduced")  # cosmetic never matches
    f = _claim(cv, "contrived", "data-loss")        # contrived not in rule 0
    g = _claim(cv, "rare", "degraded", "reproduced")  # rule 2
    res = _results(cv)
    assert res[a][0] == "reported" and res[b][0] == "reported" and res[g][0] == "reported"
    assert res[c][0] == "appendix" and res[e][0] == "appendix" and res[f][0] == "appendix"
    assert res[d][0] == "appendix"
    # rank: severity, then frequency, then confidence
    assert res[a][1] == 1 and res[f][1] == 2 and res[b][1] == 3


def test_gap_hunt_rules(cv: Converge) -> None:
    cv.init()
    cv.cover()
    a = _claim(cv, "rare", "wrong-behavior", "reproduced", origin="gap-hunt")
    b = _claim(cv, "common", "cosmetic", origin="gap-hunt")
    c = _claim(cv, "rare", "data-loss", origin="gap-hunt")
    res = _results(cv)
    assert res[a][0] == "appendix"   # would be reported by default rule 2, not by gap-hunt rules
    assert res[b][0] == "reported"
    assert res[c][0] == "reported"


def test_rereview_pass_rules(cv: Converge) -> None:
    cv.init("s1", "full", "correctness,security", "orch", "--pass", "2")
    cv.cover()
    degraded = _claim(cv, "rare", "degraded", "reproduced")        # default rule 2 reports it
    wrong = _claim(cv, "common", "wrong-behavior")                 # rule 1
    reproduced = _claim(cv, "rare", "wrong-behavior", "reproduced")  # rule 2
    security = _claim(cv, "rare", "security", lens="security")     # rule 0
    res = _results(cv)
    assert res[degraded][0] == "appendix"
    assert res[wrong][0] == "reported"
    assert res[reproduced][0] == "reported"
    assert res[security][0] == "reported"
    assert "reason=no rule matched" in cv.ok("cutoff", "s1").stdout


def test_rereview_gap_hunt_rules(cv: Converge) -> None:
    cv.init("s1", "full", "correctness,security", "orch", "--pass", "2")
    cv.cover()
    cosmetic = _claim(cv, "common", "cosmetic", origin="gap-hunt")          # default reports it
    degraded = _claim(cv, "every-call", "degraded", origin="gap-hunt")      # default reports it
    wrong = _claim(cv, "common", "wrong-behavior", origin="gap-hunt", lens="security")
    rare_wrong = _claim(cv, "rare", "wrong-behavior", "reproduced", origin="gap-hunt")
    rare_loss = _claim(cv, "rare", "data-loss", origin="gap-hunt", lens="security")
    res = _results(cv)
    assert res[cosmetic][0] == "appendix" and res[degraded][0] == "appendix"
    assert res[rare_wrong][0] == "appendix"
    assert res[wrong][0] == "reported" and res[rare_loss][0] == "reported"


def test_rereview_keeps_report_rules_and_first_pass_keeps_defaults(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("cutoff: {report_rules: [R002]}\n")
    cv.init("s1", "full", "correctness,security", "orch", "--pass", "2", "--config", str(task))
    cv.cover()
    tagged = cv.file(claim="partial write", extra=("--rule", "R002"))
    cv.quiet_round(tagged, 1, ("boundary", "reachability"))
    cv.cut_converge(tagged, "contrived", "cosmetic", "inferred", "local")
    assert _results(cv)[tagged][0] == "reported"
    cv.init("s2", "full", "correctness,security", "orch", "--pass", "1")
    first = json.loads(cv.path("s2").read_text().splitlines()[0])
    assert first["pass"] == 1
    assert first["config"]["cutoff"]["report_if"][2]["severity"][-1] == "degraded"


def test_pass_must_be_positive(cv: Converge) -> None:
    err = cv.refused("init", "s1", "--as", "orch", "--mode", "full", "--lenses", "correctness",
                     "--project-root", str(cv.project), "--angles", str(cv.angles),
                     "--pass", "0")
    assert "--pass must be >= 1; got 0" in err
    assert not cv.path().exists()


def test_per_lens_cap_by_rank(cv: Converge) -> None:
    cv.init()
    cv.cover()
    ids = [_claim(cv, "common", sev) for sev in ("wrong-behavior", "security", "data-loss", "security")]
    other = _claim(cv, "common", "wrong-behavior", lens="security")
    res = _results(cv)
    reported = [cid for cid in ids if res[cid][0] == "reported"]
    assert len(reported) == 3
    assert res[ids[0]][0] == "appendix"   # lowest-ranked in the lens
    assert res[other][0] == "reported"
    out = cv.ok("cutoff", "s1").stdout
    assert "per-lens cap 3 (correctness)" in out


def test_inconclusive_and_unconverged_always_reported_and_exempt(cv: Converge) -> None:
    cv.init()
    cv.cover()
    for _ in range(3):
        _claim(cv, "common", "security")
    inc = cv.file(claim="unsure")
    cv.refute(inc, 1, "boundary", "r1", "inconclusive")
    cv.refute(inc, 1, "reachability", "r2")
    cv.cut_converge(inc, "contrived", "cosmetic", "inferred", "trivial")
    res = _results(cv)
    assert res[inc][0] == "reported"
    assert sum(1 for r, _ in res.values() if r == "reported") == 4


def test_cut_capped_reported(cv: Converge) -> None:
    cv.init()
    cv.cover()
    cid = cv.file()
    cv.quiet_round(cid, 1, ("boundary", "reachability"))
    for rnd, freq in ((1, "contrived"), (2, "rare"), (3, "contrived")):
        cv.cut(cid, rnd, "cutter", freq, "cosmetic")
        if rnd < 3:
            cv.rebut_cut(cid, f"rebut {rnd}")
    assert _results(cv)[cid][0] == "reported"
    assert "reason=cut-capped" in cv.ok("cutoff", "s1").stdout


def test_cutoff_refused_with_open_claims(cv: Converge) -> None:
    cv.init()
    cv.cover()
    cv.file()
    assert "F001 is open in refute" in cv.refused("cutoff", "s1")
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    assert "F001 is open in cut" in cv.refused("cutoff", "s1")


def test_after_cutoff_only_rebut_or_refute(cv: Converge) -> None:
    cv.init()
    cv.cover()
    _claim(cv, "common", "security")
    _results(cv)
    assert "a cutoff is current" in cv.file(code=2)
    assert cv.status()["cutoff"] == "current"
    # idempotent: a second cutoff writes nothing
    before = cv.path().read_bytes()
    _results(cv)
    assert cv.path().read_bytes() == before
    cv.ok("rebut", "s1", "--as", "finder", "--claim", "F001", "--stage", "cut",
          "--evidence", "new prod numbers")
    assert cv.status()["cutoff"] == "stale"
    cv.cut("F001", 2, "cutter", "common", "security")
    cv.accept("F001", 2)
    _results(cv)
    assert [e["event"] for e in cv.events()].count("cutoff") == 2


def test_hand_edited_cutoff_results_rejected_on_replay(cv: Converge) -> None:
    cv.init()
    cv.cover()
    _claim(cv, "rare", "wrong-behavior")
    _results(cv)
    lines = cv.path().read_text().splitlines()
    event = json.loads(lines[-1])
    event["results"]["F001"]["result"] = "reported"
    lines[-1] = json.dumps(event)
    cv.path().write_text("\n".join(lines) + "\n")
    assert "results differ from the computed cutoff" in cv.refused("status", "s1")


def test_cutoff_rejected_from_as_input(cv: Converge) -> None:
    cv.init()
    lines = cv.path().read_text().splitlines()
    forged = {"seq": 2, "ts": "2026-01-01T00:00:00Z", "event": "cutoff", "as": "orch", "results": {}}
    cv.path().write_text("\n".join([*lines, json.dumps(forged)]) + "\n")
    assert "rejected from --as input" in cv.refused("status", "s1")


def test_refute_only_has_no_cutoff(cv: Converge) -> None:
    cv.init(mode="refute-only", lenses="")
    assert "refute-only slate has no cut stage" in cv.refused("cutoff", "s1")
    assert "refute-only slate has no cut stage" in cv.refused("converged", "s1", "--phase", "cut")


def test_report_rules_force_reporting_and_exempt_from_cap(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("cutoff:\n  report_rules: [R002]\n")
    cv.init("s1", "full", "correctness,security", "orch", "--config", str(task))
    cv.cover()
    for _ in range(3):
        _claim(cv, "common", "security")
    tagged = cv.file(claim="partial write", extra=("--rule", "R002"))
    cv.quiet_round(tagged, 1, ("boundary", "reachability"))
    cv.cut_converge(tagged, "contrived", "degraded", "inferred", "local")
    other = cv.file(claim="other rule", extra=("--rule", "R003"))
    cv.quiet_round(other, 1, ("boundary", "reachability"))
    cv.cut_converge(other, "contrived", "degraded", "inferred", "local")
    res = _results(cv)
    assert res[tagged][0] == "reported"
    assert res[other][0] == "appendix"
    assert sum(1 for r, _ in res.values() if r == "reported") == 4
    assert f"{tagged} reported" in cv.ok("cutoff", "s1").stdout
    assert "reason=report_rules[R002]" in cv.ok("cutoff", "s1").stdout


def test_report_rules_default_empty(cv: Converge) -> None:
    cv.init()
    cv.cover()
    tagged = cv.file(claim="partial write", extra=("--rule", "R002"))
    cv.quiet_round(tagged, 1, ("boundary", "reachability"))
    cv.cut_converge(tagged, "contrived", "degraded", "inferred", "local")
    assert _results(cv)[tagged][0] == "appendix"
