from __future__ import annotations

from converge import model
from events_test_support import _claim, _cut, _rating, _rebut, _reply, _state, _verdict

from conftest import BATCH_1, CUTTER, FINDER, R1, Converge

# -- cut, accept and rebut -----------------------------------------------------------


def test_cut_accept_and_rebut_need_when(cv: Converge) -> None:
    cv.ready(cut="before")
    assert "cut: missing required field `when`" in _cut(cv, None)
    assert "`when` must be one of before, after; got 'during'" in _cut(cv, "during")
    assert _cut(cv, "before") == []
    problems = cv.append("accept", FINDER, claim="F001", round=1)
    assert any(("accept: missing required field `when`") in problem for problem in problems)
    assert "rebut: missing required field `when`" in _rebut(cv, "e", when=None)


def test_cut_values_and_evidence(cv: Converge) -> None:
    cv.ready(cut="before")
    assert "`impact` must be one of" in " ".join(_cut(cv, "before", impact="huge"))
    assert "`reach` must be one of" in " ".join(_cut(cv, "before", reach="far"))
    assert "cut: no evidence for `size`" in " ".join(
        _cut(cv, "before", evidence={"entry-points": "x", "blast-radius": "y",
                                     "files-touched": "z"}))
    assert _cut(cv, "before", choice="split or patch") == []


def test_finder_answers_a_cut_round_before_the_next(cv: Converge) -> None:
    cv.ready(cut="before")
    assert _cut(cv, "before") == []
    assert ("cut: F001 before round 1 awaits its finder; the finder must accept or rebut it "
            "first") in _cut(cv, "before", rnd=2)
    assert ("accept: only F001's finder finder may accept"
            in cv.append("accept", R1, claim="F001", round=1, when="before"))
    assert ("accept: F001 latest before cut round is 1, got 2"
            in cv.append("accept", FINDER, claim="F001", round=2, when="before"))
    assert ("accept: F001 has no after cut round to accept"
            in cv.append("accept", FINDER, claim="F001", round=1, when="after"))
    assert "rebut: F001 has no after cut round to rebut" in _rebut(cv, "e", when="after")
    assert "rebut: only F001's finder finder may rebut" in _rebut(cv, "e", agent=R1)
    assert _rebut(cv, "e") == []
    assert ("accept: F001 before cut round 1 was rebutted; answer the next cut round"
            in cv.append("accept", FINDER, claim="F001", round=1, when="before"))
    assert "cut: F001 next before cut round is 2, got 3" in _cut(cv, "before", rnd=3)
    assert _cut(cv, "before", rnd=2, impact="cosmetic") == []
    assert cv.append("accept", FINDER, claim="F001", round=2, when="before") == []
    assert ("accept: F001 before cut round 2 is already accepted"
            in cv.append("accept", FINDER, claim="F001", round=2, when="before"))


def test_cut_rounds_and_cap_count_per_when(cv: Converge) -> None:
    cv.ready(cut="both", cut_rounds=2)
    assert _cut(cv, "before") == []
    assert _rebut(cv, "e1") == []
    assert _cut(cv, "before", rnd=2, impact="data-loss") == []
    assert "cut: round 3 exceeds caps.cut_rounds 2" in _cut(cv, "before", rnd=3)
    assert _rating(cv)["impact"] == "data-loss"
    assert model.rank_key(_claim(cv))[0] == model.IMPACT.index("data-loss")
    cv.batch_1()
    cv.fresh_eye()
    assert "cut: F001 next after cut round is 1, got 2" in _cut(cv, "after", rnd=2)
    assert _cut(cv, "after", impact="security") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="after") == []
    state = _state(cv)
    assert sorted(state.cuts["before"].rounds) == [1, 2]
    assert sorted(state.cuts["after"].rounds) == [1]
    assert state.cuts["after"].accepted == 1
    assert _rating(cv)["impact"] == "security" and state.cutters == {CUTTER}
    assert model.rank_key(_claim(cv))[0] == model.IMPACT.index("security")


def test_rebut_needs_new_evidence(cv: Converge) -> None:
    cv.ready(cut="before", cut_rounds=3)
    assert _cut(cv, "before") == []
    assert _rebut(cv, "e1") == []
    assert _cut(cv, "before", rnd=2, impact="cosmetic") == []
    assert ("rebut: this evidence was already given for F001; a rebut needs new evidence"
            in _rebut(cv, "e1"))


def test_cut_commands_take_when(cv: Converge) -> None:
    cv.ready(cut="before")
    out = cv.cut("F001", 1, when="before").stdout
    assert out.startswith("CUT seq=") and out.splitlines()[0].endswith("F001 when=before round=1")
    out = cv.rebut_cut("F001", "the retry path reaches it", when="before").stdout
    assert out.startswith("REBUT seq=") and out.splitlines()[0].endswith("F001 when=before")
    cv.cut("F001", 2, when="before", impact="cosmetic")
    out = cv.accept("F001", 2, when="before").stdout
    assert out.startswith("ACCEPT seq=") and out.splitlines()[0].endswith("F001 when=before round=2")
    err = cv.refused("rebut", "s1", "--as", FINDER, "--claim", "F001", "--evidence", "x")
    assert "the following arguments are required: --when" in err


# -- the phase gate ------------------------------------------------------------------


def test_gate_escalate_needs_the_escalate_phase(cv: Converge) -> None:
    cv.init()
    cv.file()
    assert ("escalate: the slate is in phase find; escalate needs phase escalate"
            in cv.append("escalate", FINDER, claim="F001"))


def test_gate_before_cut_needs_the_cut_before_phase(cv: Converge) -> None:
    cv.ready(cut="both")
    assert _cut(cv, "before") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="before") == []
    assert ("cut: the slate is in phase attack; cut needs phase cut-before"
            in _cut(cv, "before", rnd=2))
    assert ("rebut: the slate is in phase attack; rebut needs phase cut-before"
            in _rebut(cv, "e1"))


def test_gate_before_cut_is_refused_when_steps_cut_excludes_it(cv: Converge) -> None:
    cv.ready(cut="after")
    assert ("cut: the slate is in phase attack; cut needs phase cut-before"
            in _cut(cv, "before"))


def test_gate_attack_needs_the_attack_phase(cv: Converge) -> None:
    cv.ready(cut="before")
    assert (any(("attack: the slate is in phase cut-before; attack needs phase attack") in problem for problem in cv.check("F001", BATCH_1[0])))
    assert ("angle-na: the slate is in phase cut-before; angle-na needs phase attack"
            in cv.append("angle-na", R1, phase="attack", angle=BATCH_1[0], claim="F001",
                         reason="r"))
    assert ("reply: the slate is in phase cut-before; reply needs phase attack"
            in _reply(cv))
    assert ("verdict: the slate is in phase cut-before; verdict needs phase attack"
            in _verdict(cv, "agree"))


def test_gate_after_cut_needs_the_cut_after_phase(cv: Converge) -> None:
    cv.ready(cut="after", claims=2)
    cv.batch_1("F001")
    cv.fresh_eye("F001")
    assert ("cut: the slate is in phase attack; cut needs phase cut-after"
            in _cut(cv, "after"))
    assert ("accept: the slate is in phase attack; accept needs phase cut-after"
            in cv.append("accept", FINDER, claim="F001", round=1, when="after"))


def test_gate_after_cut_is_refused_when_steps_cut_excludes_it(cv: Converge) -> None:
    cv.ready(cut="before")
    assert _cut(cv, "before") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="before") == []
    cv.batch_1()
    cv.fresh_eye()
    assert ("cut: the slate is in phase cutoff; cut needs phase cut-after"
            in _cut(cv, "after"))


def test_gate_claim_needs_an_open_item_of_the_phase(cv: Converge) -> None:
    cv.ready(cut="before", claims=2)
    assert _cut(cv, "before") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="before") == []
    assert "cut: F001 before cut is converged; it takes no more cut" in _cut(cv, "before",
                                                                             rnd=2)
    assert "accept: F001 before cut is converged; it takes no more accept" in cv.append(
        "accept", FINDER, claim="F001", round=1, when="before")
