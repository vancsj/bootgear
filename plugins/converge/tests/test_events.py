"""Event shapes and the replayed claim state: `attack`, `reply`, `verdict`, the `when` field
of `cut`, `accept` and `rebut`, the rules of `file`, `escalate` and `angle-na`, the common
checks, and `ClaimState`."""
from __future__ import annotations

from typing import Any

from conftest import BATCH_1, CUTTER, FINDER, MAIN, R1, R2, Converge
from converge import ledger, model, protocol


def _reply(cv: Converge, cid: str = "F001", stance: str = "rebut", batch: Any = 1,
           evidence: str | None = "new evidence", agent: str = FINDER, **extra: Any) -> list[str]:
    fields: dict[str, Any] = {"claim": cid, "batch": batch, "stance": stance, **extra}
    if evidence is not None:
        fields.update(evidence=evidence, evidence_sha256=ledger.evidence_hash(evidence))
    return cv.append("reply", agent, **fields)


def _verdict(cv: Converge, verdict: str, cid: str = "F001", agent: str = R1, batch: Any = 1,
             **extra: Any) -> list[str]:
    return cv.append("verdict", agent, claim=cid, batch=batch, verdict=verdict, **extra)


def _cut(cv: Converge, when: str | None, rnd: int = 1, cid: str = "F001", agent: str = CUTTER,
         **extra: Any) -> list[str]:
    fields: dict[str, Any] = {"claim": cid, "round": rnd, **extra}
    if when is not None:
        fields["when"] = when
    if when == "before":
        fields.setdefault("confidence", "inferred")
    return cv.append("cut", agent, **fields)


def _rebut(cv: Converge, evidence: str, when: str | None = "before", agent: str = FINDER,
           **extra: Any) -> list[str]:
    fields: dict[str, Any] = {"claim": "F001", "evidence": evidence, **extra}
    if when is not None:
        fields["when"] = when
    return cv.append("rebut", agent, **fields)


def _claim(cv: Converge, cid: str = "F001") -> model.Claim:
    return ledger.read(cv.path(), "s1").claims[cid]


def _state(cv: Converge, cid: str = "F001") -> protocol.ClaimState:
    return _claim(cv, cid).state


def _rating(cv: Converge) -> dict[str, Any]:
    rating = _state(cv).rating
    assert rating is not None
    return rating


# -- the event list and the common checks ----------------------------------------


def test_event_kinds() -> None:
    assert model.EVENTS == ("init", "file", "escalate", "find-run", "angle-na", "attack", "reply",
                            "verdict", "cut", "rebut", "accept", "cutoff")


def test_filed_claim_starts_survived(cv: Converge) -> None:
    cv.ready()
    state = _state(cv)
    assert isinstance(state, protocol.ClaimState)
    assert state.status == "survived" and state.rating is None
    assert state.attacks == {} and state.refuters == set() and state.cutters == set()


def test_refute_is_not_an_event(cv: Converge) -> None:
    cv.ready()
    problems = cv.append("refute", R1, claim="F001", round=1, angle=BATCH_1[0], tell="t",
                         outcome="survived", evidence="e", searches="s", positive_control="p")
    assert any(p.startswith("`event` must be one of init, file, ") and p.endswith("got 'refute'")
               for p in problems), problems


def test_rebut_has_no_stage(cv: Converge) -> None:
    cv.ready(cut="before")
    assert _cut(cv, "before") == []
    assert "rebut: unknown field `stage`" in _rebut(cv, "e", stage="cut")


def test_sixth_agent_id_is_refused(cv: Converge) -> None:
    cv.ready(cut="after")
    cv.batch_1()
    cv.fresh_eye()
    assert _cut(cv, "after") == []
    assert ledger.read(cv.path(), "s1").agent_ids() == [MAIN, FINDER, R1, R2, CUTTER]
    problems = cv.append("accept", "r3", claim="F001", round=1, when="after")
    assert any(p.startswith("agent budget: r3 would be agent 6") for p in problems)


def test_reserved_agent_id_is_refused(cv: Converge) -> None:
    cv.ready()
    problems = cv.attack("F001", BATCH_1[0], agent=model.CONVERGE_AGENT)
    assert "agent id 'converge' is reserved for computed cutoff events" in problems
    assert ("agent id 'converge' is reserved for computed cutoff events"
            in cv.file(agent=model.CONVERGE_AGENT, code=2))


def test_events_need_init(cv: Converge) -> None:
    cv.dir.mkdir()
    cv.path().write_text("")
    problems = cv.append("file", FINDER, id="F001", loc="a.py:1", claim="c", trigger="t",
                         origin="lens")
    assert "file: the slate has no init event; run `converge init` first" in problems


# -- file and escalate ------------------------------------------------------------


def test_file_origin_is_lens_or_gap_hunt(cv: Converge) -> None:
    cv.init()
    assert "`origin` must be one of lens, gap-hunt; got 'slate'" in cv.file(origin="slate", code=2)
    assert cv.file(agent="slate") == "F001"


def test_file_is_refused_after_the_first_escalate(cv: Converge) -> None:
    cv.ready()
    assert ("file: claims are filed before the first escalate, cut or attack event"
            in cv.file(code=2))


def test_file_and_escalate_are_refused_after_the_first_attack(cv: Converge) -> None:
    cv.ready(claims=2, escalate=False)
    assert cv.attack("F001", BATCH_1[0]) == []
    assert ("file: claims are filed before the first escalate, cut or attack event"
            in cv.file(code=2))
    assert ("escalate: escalate comes before the first cut or attack event"
            in cv.append("escalate", FINDER, claim="F002"))


def test_escalate_is_refused_after_the_first_cut(cv: Converge) -> None:
    cv.ready(cut="before", claims=2, escalate=False)
    assert _cut(cv, "before") == []
    assert ("escalate: escalate comes before the first cut or attack event"
            in cv.append("escalate", FINDER, claim="F002"))


# -- angle-na ------------------------------------------------------------------------


def test_angle_na_phases(cv: Converge) -> None:
    cv.ready()
    problems = cv.append("angle-na", R1, phase="refute", angle=BATCH_1[0], claim="F001",
                         reason="r")
    assert "`phase` must be one of find, attack; got 'refute'" in problems
    assert cv.append("angle-na", R1, phase="attack", angle=BATCH_1[0], claim="F001",
                     reason="no time window in the claim") == []
    assert _claim(cv).na_angles == {BATCH_1[0]}


# -- attack ------------------------------------------------------------------


def test_attack_fields(cv: Converge) -> None:
    cv.ready()
    for batch in (0, "two", True):
        assert ("`batch` must be a positive integer or fresh-eye; got "
                f"{batch!r}") in cv.attack("F001", BATCH_1[0], batch=batch)
    assert ("`outcome` must be one of clean, refuted; got 'survived'"
            in cv.attack("F001", BATCH_1[0], outcome="survived"))
    assert ("attack: `last` is given only with batch fresh-eye"
            in cv.attack("F001", BATCH_1[0], last=True))
    problems = cv.append("attack", R1, claim="F001", batch=1, angle=BATCH_1[0])
    assert "attack: missing required field `tell`" in problems
    assert "attack: unknown field `round`" in cv.attack("F001", BATCH_1[0], round=1)
    assert "unknown claim 'F009'" in cv.attack("F009", BATCH_1[0])


def test_table_attack_angle_rules(cv: Converge) -> None:
    cv.ready()
    assert ("unknown attack angle 'made-up' (not in this slate's init snapshot)"
            in cv.attack("F001", "made-up"))
    assert "unknown attack angle 'boundary' (not in this slate's init snapshot)" in cv.attack(
        "F001", "boundary")
    assert cv.attack("F001", BATCH_1[0]) == []
    assert (f"attack: angle {BATCH_1[0]!r} was already used on F001"
            in cv.attack("F001", BATCH_1[0]))
    assert cv.append("angle-na", R1, phase="attack", angle=BATCH_1[1], claim="F001",
                     reason="no time window in the claim") == []
    assert (f"attack: angle {BATCH_1[1]!r} is recorded not applicable to F001"
            in cv.attack("F001", BATCH_1[1]))


def test_fresh_eye_angle_is_free_text_not_used_before(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert ("attack: `last` must be true or false; got 'yes'"
            in cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye", last="yes"))
    assert cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye") == []
    assert ("attack: angle 'retry timing' was already used on F001"
            in cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye"))
    assert (f"attack: angle {BATCH_1[2]!r} was already used on F001"
            in cv.attack("F001", BATCH_1[2], agent=R2, batch="fresh-eye"))
    assert "`angle` must be a non-empty string" in cv.attack(
        "F001", " ", agent=R2, batch="fresh-eye")


def test_fresh_eye_accepts_na_angle_and_literal_name(cv: Converge) -> None:
    cv.ready()
    assert cv.append("angle-na", R1, phase="attack", angle=BATCH_1[0], claim="F001",
                     reason="no time window in the claim") == []
    for angle in BATCH_1[1:]:
        assert cv.attack("F001", angle) == []
    assert cv.attack("F001", BATCH_1[0], agent=R2, batch="fresh-eye") == []
    assert cv.attack("F001", "fresh-eye", agent=R2, batch="fresh-eye") == []
    seq = next(event["seq"] for event in cv.events() if event.get("angle") == "fresh-eye")
    assert cv.status()["adhoc_angles"] == [{"angle": "fresh-eye", "claim": "F001", "seq": seq}]


def test_status_lists_adhoc_names_slate_wide(cv: Converge) -> None:
    cv.ready(claims=2)
    cv.batch_1("F001")
    cv.batch_1("F002")
    assert cv.attack("F001", "novel-name", agent=R2, batch="fresh-eye") == []
    assert cv.attack("F002", "novel-name", agent=R2, batch="fresh-eye") == []
    seqs = {event["claim"]: event["seq"] for event in cv.events()
            if event.get("angle") == "novel-name"}
    assert cv.status()["adhoc_angles"] == [
        {"angle": "novel-name", "claim": "F001", "seq": seqs["F001"]},
        {"angle": "novel-name", "claim": "F002", "seq": seqs["F002"]}]
    [adhoc] = [line for line in cv.ok("status", "s1").stdout.splitlines()
               if line.startswith("ADHOC ")]
    assert adhoc == (f"ADHOC novel-name claim=F001 seq={seqs['F001']}, "
                     f"novel-name claim=F002 seq={seqs['F002']}")


def test_attacker_is_not_the_finder_the_orchestrator_or_a_cutter(cv: Converge) -> None:
    cv.ready(cut="before")
    assert _cut(cv, "before") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="before") == []
    assert ("attack: finder filed F001 and may not attack it"
            in cv.attack("F001", BATCH_1[0], agent=FINDER))
    assert ("attack: orch wrote init; the orchestrator never writes attack"
            in cv.attack("F001", BATCH_1[0], agent=MAIN))
    assert ("attack: cutter cut F001; refuters and cutters are disjoint"
            in cv.attack("F001", BATCH_1[0], agent=CUTTER))


def test_cutter_is_not_a_refuter(cv: Converge) -> None:
    cv.ready(cut="after")
    cv.batch_1()
    cv.fresh_eye()
    assert ("cut: r1 attacked F001; refuters and cutters are disjoint"
            in _cut(cv, "after", agent=R1))
    state = _state(cv)
    assert state.refuters == {R1, R2} and state.cutters == set()
    assert _claim(cv).used_angles == {*BATCH_1, "retry timing"}
    assert [e["angle"] for e in state.attacks[1]] == list(BATCH_1)
    assert [e["angle"] for e in state.attacks["fresh-eye"]] == ["retry timing"]


# -- reply and verdict -------------------------------------------------------


def test_reply_rules(cv: Converge) -> None:
    cv.ready()
    cv.batch_1(refuted=(BATCH_1[0],))
    assert ("reply: batch fresh-eye of F001 has no refuted attack"
            in _reply(cv, batch="fresh-eye"))
    assert "reply: only F001's finder finder may reply" in _reply(cv, agent=R1)
    assert "`stance` must be one of rebut, decline; got 'maybe'" in _reply(cv, stance="maybe")
    assert "`evidence` must be a non-empty string" in _reply(cv, evidence=None)
    problems = cv.append("reply", FINDER, claim="F001", batch=1, stance="rebut",
                         evidence="new evidence", evidence_sha256="0" * 64)
    assert "`evidence_sha256` does not match the evidence" in problems
    assert "reply: decline carries no evidence" in _reply(cv, stance="decline")
    assert ("reply: `text` is given only with stance rebut"
            in _reply(cv, stance="decline", evidence=None, text="narrower"))
    assert "`text` must be a non-empty string" in _reply(cv, text=" ")
    assert _reply(cv, text="x breaks y only for None") == []
    assert _claim(cv).text == "x breaks y only for None"
    assert _claim(cv).original == "claim 1"


def test_verdict_rules(cv: Converge) -> None:
    cv.ready()
    cv.batch_1(refuted=(BATCH_1[1], BATCH_1[3]))
    assert _reply(cv) == []
    assert ("verdict: only r1, who recorded the first refuted attack of F001 batch 1, "
            "gives the verdict") in _verdict(cv, "agree", agent=R2)
    assert ("`verdict` must be one of agree, disagree; got 'maybe'"
            in _verdict(cv, "maybe"))
    assert "verdict: disagree needs `evidence`" in _verdict(cv, "disagree")
    assert ("verdict: batch fresh-eye of F001 has no refuted attack"
            in _verdict(cv, "agree", batch="fresh-eye"))
    assert _verdict(cv, "disagree", evidence="b.py:3 still passes None") == []


def test_agree_keeps_the_revised_text_and_survived(cv: Converge) -> None:
    cv.ready()
    cv.batch_1(refuted=(BATCH_1[0],))
    assert _reply(cv, text="narrower claim") == []
    assert _verdict(cv, "agree") == []
    state = _state(cv)
    assert state.status == "survived" and _claim(cv).text == "narrower claim"
    assert state.verdicts[1][0]["verdict"] == "agree"


def test_second_rebut_disputes_and_needs_new_evidence(cv: Converge) -> None:
    cv.ready()
    cv.batch_1(refuted=(BATCH_1[0],))
    assert _reply(cv, evidence="first") == []
    assert _verdict(cv, "disagree", evidence="still wrong") == []
    assert ("reply: this evidence was already given for F001; a rebut needs new evidence"
            in _reply(cv, evidence="first"))
    assert _reply(cv, evidence="second") == []
    state = _state(cv)
    assert state.status == "disputed"
    assert [r["stance"] for r in state.replies[1]] == ["rebut", "rebut"]


def test_decline_kills_the_claim(cv: Converge) -> None:
    cv.ready(cut="after")
    cv.batch_1(refuted=(BATCH_1[0],))
    assert _reply(cv, stance="decline", evidence=None) == []
    assert _state(cv).status == "killed"
    assert not _claim(cv).live
    assert "F001 is killed; it accepts nothing" in _cut(cv, "after")


# -- cut, accept and rebut -----------------------------------------------------------


def test_cut_accept_and_rebut_need_when(cv: Converge) -> None:
    cv.ready(cut="before")
    assert "cut: missing required field `when`" in _cut(cv, None)
    assert "`when` must be one of before, after; got 'during'" in _cut(cv, "during")
    assert _cut(cv, "before") == []
    problems = cv.append("accept", FINDER, claim="F001", round=1)
    assert "accept: missing required field `when`" in problems
    assert "rebut: missing required field `when`" in _rebut(cv, "e", when=None)


def test_before_cut_confidence_is_inferred(cv: Converge) -> None:
    cv.ready(cut="before")
    assert ("cut: a before cut has confidence inferred; got 'traced'"
            in _cut(cv, "before", confidence="traced"))
    assert _cut(cv, "before", confidence="inferred") == []


def test_cut_values_and_choice(cv: Converge) -> None:
    cv.ready(cut="before")
    assert ("cut: F001 has difficulty redesign; a non-empty `choice` is required"
            in _cut(cv, "before", difficulty="redesign"))
    assert "`severity` must be one of" in " ".join(_cut(cv, "before", severity="huge"))
    assert "cut: no evidence for `difficulty`" in " ".join(
        _cut(cv, "before", evidence={"entry-points": "x", "blast-radius": "y",
                                     "evidence-tier": "z"}))
    assert _cut(cv, "before", difficulty="redesign", choice="split or patch") == []


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
    assert _cut(cv, "before", rnd=2, severity="degraded") == []
    assert cv.append("accept", FINDER, claim="F001", round=2, when="before") == []
    assert ("accept: F001 before cut round 2 is already accepted"
            in cv.append("accept", FINDER, claim="F001", round=2, when="before"))


def test_cut_rounds_and_cap_count_per_when(cv: Converge) -> None:
    cv.ready(cut="both", cut_rounds=2)
    assert _cut(cv, "before") == []
    assert _rebut(cv, "e1") == []
    assert _cut(cv, "before", rnd=2, severity="data-loss") == []
    assert "cut: round 3 exceeds caps.cut_rounds 2" in _cut(cv, "before", rnd=3)
    assert _rating(cv)["severity"] == "data-loss"
    assert model.rank_key(_claim(cv))[0] == model.SEVERITY.index("data-loss")
    cv.batch_1()
    cv.fresh_eye()
    assert "cut: F001 next after cut round is 1, got 2" in _cut(cv, "after", rnd=2)
    assert _cut(cv, "after", severity="security") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="after") == []
    state = _state(cv)
    assert sorted(state.cuts["before"].rounds) == [1, 2]
    assert sorted(state.cuts["after"].rounds) == [1]
    assert state.cuts["after"].accepted == 1
    assert _rating(cv)["severity"] == "security" and state.cutters == {CUTTER}
    assert model.rank_key(_claim(cv))[0] == model.SEVERITY.index("security")


def test_rebut_needs_new_evidence(cv: Converge) -> None:
    cv.ready(cut="before", cut_rounds=3)
    assert _cut(cv, "before") == []
    assert _rebut(cv, "e1") == []
    assert _cut(cv, "before", rnd=2, severity="degraded") == []
    assert ("rebut: this evidence was already given for F001; a rebut needs new evidence"
            in _rebut(cv, "e1"))


def test_cut_commands_take_when(cv: Converge) -> None:
    cv.ready(cut="before")
    out = cv.cut("F001", 1, when="before", confidence="inferred").stdout
    assert out.startswith("CUT seq=") and out.splitlines()[0].endswith("F001 when=before round=1")
    out = cv.rebut_cut("F001", "the retry path reaches it", when="before").stdout
    assert out.startswith("REBUT seq=") and out.splitlines()[0].endswith("F001 when=before")
    cv.cut("F001", 2, when="before", frequency="rare", confidence="inferred")
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
    assert ("attack: the slate is in phase cut-before; attack needs phase attack"
            in cv.attack("F001", BATCH_1[0]))
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
