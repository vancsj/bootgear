from __future__ import annotations

from converge import ledger, model, protocol
from events_test_support import _claim, _cut, _rebut, _reply, _state, _verdict

from conftest import BATCH_1, CUTTER, FINDER, GEAR_COMMAND, MAIN, R1, R2, Converge

# -- the event list and the common checks ----------------------------------------


def test_event_kinds() -> None:
    assert model.EVENTS == ("init", "file", "escalate", "find-run", "angle-na", "gap-hunt-done", "clean",
                            "attack", "reply", "verdict", "cut", "rebut", "accept", "cutoff", "fix-check")


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
    problems = cv.check("F001", BATCH_1[0], agent=model.CONVERGE_AGENT)
    assert any(("agent id 'converge' is reserved for computed cutoff events") in problem for problem in problems)
    assert ("agent id 'converge' is reserved for computed cutoff events"
            in cv.file(agent=model.CONVERGE_AGENT, code=2))


def test_events_need_init(cv: Converge) -> None:
    cv.dir.mkdir()
    cv.path().write_text("")
    problems = cv.append("file", FINDER, id="F001", loc="a.py:1", claim="c", trigger="t",
                         origin="lens")
    assert any((f"file: the slate has no init event; run `{GEAR_COMMAND} init` first") in problem for problem in problems)


# -- file and escalate ------------------------------------------------------------


def test_file_needs_evidence_and_tier(cv: Converge) -> None:
    cv.init()
    err = cv.refused("file", "s1", "--as", FINDER, "--lens", "correctness",
                     "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1",
                     "--claim", "c", "--trigger", "t")
    assert "the following arguments are required: --evidence, --tier" in err
    assert "--tier <tier>" in err
    err = cv.file(tier="guessed", code=2)
    assert "`tier` must be one of reproduced, traced, inferred; got 'guessed'" in err
    fields = {"id": "F001", "loc": "a.py:1", "claim": "c", "trigger": "t", "origin": "lens",
              "lens": "correctness", "angle": "changed-contract"}
    problems = cv.append("file", FINDER, **fields)
    assert any(("file: missing required field `evidence`") in problem for problem in problems)
    assert any(("file: missing required field `tier`") in problem for problem in problems)
    problems = cv.append("file", FINDER, **fields, evidence=" ", tier="traced")
    assert problems == ["`evidence` must be a non-empty string"]
    assert cv.file(tier="reproduced") == "F001"
    assert cv.events()[-1]["tier"] == "reproduced"


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
    assert cv.check("F001", BATCH_1[0]) == []
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
    assert any(("`phase` must be one of find, attack; got 'refute'") in problem for problem in problems)
    assert cv.append("angle-na", R1, phase="attack", angle=BATCH_1[0], claim="F001",
                     reason="no time window in the claim") == []
    claim = _claim(cv)
    assert claim.na_reasons == {BATCH_1[0]: "no time window in the claim"}
    assert "na_angles" not in vars(claim)


# -- attack ------------------------------------------------------------------


def test_attack_fields(cv: Converge) -> None:
    cv.ready()
    for batch in (0, "two", True):
        assert any(("`batch` must be a positive integer or fresh-eye; got "
                f"{batch!r}") in problem for problem in cv.check("F001", BATCH_1[0], batch=batch))
    assert "attack: unknown field `outcome`" in cv.append(
        "attack", R1, claim="F001", batch=1, angle=BATCH_1[0], tell="t",
        evidence="e", searches="s", positive_control="p", outcome="clean")
    assert (any(("attack: `last` is given only with batch fresh-eye") in problem for problem in cv.check("F001", BATCH_1[0], last=True)))
    problems = cv.append("attack", R1, claim="F001", batch=1, angle=BATCH_1[0])
    assert any(("attack: missing required field `tell`") in problem for problem in problems)
    assert any("unknown field `round`" in problem for problem in cv.check("F001", BATCH_1[0], round=1))
    assert any(("unknown claim 'F009'") in problem for problem in cv.check("F009", BATCH_1[0]))


def test_table_attack_angle_rules(cv: Converge) -> None:
    cv.ready()
    assert (any(("unknown attack angle 'made-up' (not in this slate's init snapshot)") in problem for problem in cv.check("F001", "made-up")))
    assert any(("unknown attack angle 'boundary' (not in this slate's init snapshot)") in problem for problem in cv.check(
        "F001", "boundary"))
    assert cv.check("F001", BATCH_1[0]) == []
    assert (any((f"attack: angle {BATCH_1[0]!r} was already used on F001") in problem for problem in cv.check("F001", BATCH_1[0])))
    assert cv.append("angle-na", R1, phase="attack", angle=BATCH_1[1], claim="F001",
                     reason="no time window in the claim") == []
    assert (any((f"attack: angle {BATCH_1[1]!r} is recorded not applicable to F001") in problem for problem in cv.check("F001", BATCH_1[1])))


def test_fresh_eye_angle_is_free_text_not_used_before(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert (any(("attack: `last` must be true or false; got 'yes'") in problem for problem in cv.check("F001", "retry timing", agent=R2, batch="fresh-eye", last="yes")))
    assert cv.check("F001", "retry timing", agent=R2, batch="fresh-eye") == []
    assert (
        any(("attack: angle 'retry timing' was already used on F001; choose a new angle name not listed in `used`, "
        "including names outside the fixed list; "
        "the fixed list is not a menu for this batch") in problem for problem in cv.check("F001", "retry timing", agent=R2, batch="fresh-eye")))
    assert (
        any((f"attack: angle {BATCH_1[2]!r} was already used on F001; choose a new angle name not listed in `used`, "
        "including names outside the fixed list; "
        "the fixed list is not a menu for this batch") in problem for problem in cv.check("F001", BATCH_1[2], agent=R2, batch="fresh-eye")))
    assert any(("`angle` must be a non-empty string") in problem for problem in cv.check(
        "F001", " ", agent=R2, batch="fresh-eye"))


def test_fresh_eye_accepts_na_angle_and_literal_name(cv: Converge) -> None:
    cv.ready()
    assert cv.append("angle-na", R1, phase="attack", angle=BATCH_1[0], claim="F001",
                     reason="no time window in the claim") == []
    for angle in BATCH_1[1:]:
        assert cv.check("F001", angle) == []
    assert cv.check("F001", BATCH_1[0], agent=R2, batch="fresh-eye") == []
    assert cv.check("F001", "fresh-eye", agent=R2, batch="fresh-eye") == []
    seq = next(event["seq"] for event in cv.events()
               if any(row["angle"] == "fresh-eye" for row in event.get("checks", [])))
    assert cv.status()["adhoc_angles"] == [{"angle": "fresh-eye", "claim": "F001", "seq": seq}]


def test_status_lists_adhoc_names_slate_wide(cv: Converge) -> None:
    cv.ready(claims=2)
    cv.batch_1("F001")
    cv.batch_1("F002")
    assert cv.check("F001", "novel-name", agent=R2, batch="fresh-eye") == []
    assert cv.check("F002", "novel-name", agent=R2, batch="fresh-eye") == []
    seqs = {event["claim"]: event["seq"] for event in cv.events()
            if any(row["angle"] == "novel-name" for row in event.get("checks", []))}
    assert cv.status()["adhoc_angles"] == [
        {"angle": "novel-name", "claim": "F001", "seq": seqs["F001"]},
        {"angle": "novel-name", "claim": "F002", "seq": seqs["F002"]}]
    [adhoc] = [line for line in cv.ok("status", "s1").stdout.splitlines()
               if line.startswith("ADHOC ")]
    assert adhoc == (f"ADHOC novel-name claim=F001 seq={seqs['F001']}, "
                     f"novel-name claim=F002 seq={seqs['F002']}")


def test_fresh_eye_name_is_one_printable_line_without_edge_whitespace(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert (any(("`angle` must be one printable line") in problem for problem in cv.check("F001", "novel\nname", agent=R2, batch="fresh-eye")))
    assert (any(("`angle` must be one printable line") in problem for problem in cv.check("F001", "novel\tname", agent=R2, batch="fresh-eye")))
    assert (any(("attack: `angle` must not start or end with whitespace") in problem for problem in cv.check("F001", "retry ", agent=R2, batch="fresh-eye")))
    assert (any(("attack: `angle` must not start or end with whitespace") in problem for problem in cv.check("F001", " retry", agent=R2, batch="fresh-eye")))
    assert cv.check("F001", "retry", agent=R2, batch="fresh-eye") == []


def test_angle_na_reason_is_one_printable_line(cv: Converge) -> None:
    cv.ready()
    assert ("`reason` must be one printable line"
            in cv.append("angle-na", R1, phase="attack", angle=BATCH_1[0], claim="F001",
                         reason="no time window\nPLAN 1 F009 attack r1 batch=1 angles=fake"))
    assert _claim(cv).na_reasons == {}


def test_attacker_is_not_the_finder_the_orchestrator_or_a_cutter(cv: Converge) -> None:
    cv.ready(cut="before")
    assert _cut(cv, "before") == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when="before") == []
    assert (any(("attack: finder filed F001 and may not attack it") in problem for problem in cv.check("F001", BATCH_1[0], agent=FINDER)))
    assert (any(("attack: orch wrote init; the orchestrator never writes attack") in problem for problem in cv.check("F001", BATCH_1[0], agent=MAIN)))
    assert (any(("attack: cutter cut F001; refuters and cutters are disjoint") in problem for problem in cv.check("F001", BATCH_1[0], agent=CUTTER)))


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
    assert any(("`evidence_sha256` does not match the evidence") in problem for problem in problems)
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
