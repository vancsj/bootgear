"""Advisor seats: the init event records each seat's mechanism and the advisor's roles."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from converge import ledger, model

from conftest import GEAR_COMMAND, PLUGIN_DIR, Converge

ADVISOR = {"roles": ["refuter", "gap-hunter"], "brief": "Act only as r2.", "startup": "direct"}
FULL_SEATS = {"main": "native_subagent", "finder": "native_subagent", "r1": "native_subagent",
              "r2": "advisor", "cutter": "native_subagent"}


def _init_event(cv: Converge, **fields: Any) -> dict[str, Any]:
    cv.init()
    return {**cv.events()[0], **fields}


def _replay(path: Path, *events: dict[str, Any]) -> model.Slate:
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    return ledger.read(path, "s1")


def test_init_with_seats_and_advisor_replays(cv: Converge, tmp_path: Path) -> None:
    event = _init_event(cv, seats=FULL_SEATS, advisor=ADVISOR)
    assert ledger.validate_event(model.Slate("s1"), event) == []
    slate = _replay(tmp_path / "s1.jsonl", event)
    assert slate.seats == FULL_SEATS
    assert slate.advisor == ADVISOR
    assert slate.mechanism("r2") == "advisor"
    assert slate.mechanism("r1") == "native_subagent"


def test_init_rejects_every_seat_problem(cv: Converge) -> None:
    seats = {"r9": "native_subagent", "r1": "robot", "main": "advisor", "finder": "advisor"}
    event = _init_event(cv, seats=seats, advisor={"roles": ["bogus"]})
    problems = ledger.validate_event(model.Slate("s1"), event)
    text = "\n".join(problems)
    for fragment in ("seats: unknown seat 'r9'", "seats.r1: unknown mechanism 'robot'",
                     "seats.main: only r2 may be advisor", "seats.finder: only r2 may be advisor",
                     "advisor.roles: unknown role 'bogus'", "advisor.brief:",
                     "advisor: given only when seats.r2 is advisor"):
        assert fragment in text, text


def test_init_rejects_r1_advisor(cv: Converge) -> None:
    event = _init_event(cv, seats={"r1": "advisor", "r2": "advisor"}, advisor=ADVISOR)
    problems = ledger.validate_event(model.Slate("s1"), event)
    assert any(p.startswith("seats.r1: only r2 may be advisor") for p in problems), problems


def test_init_without_seats_replays_all_native(cv: Converge, tmp_path: Path) -> None:
    event = _init_event(cv)
    assert "seats" not in event
    slate = _replay(tmp_path / "s1.jsonl", event)
    assert slate.seats == {}
    assert slate.advisor is None
    assert slate.mechanism("r2") == "native_subagent"


# ---------------------------------------------------------------------------
# converge init --settlement / --refuters and status (through the CLI)

PIPE = {"BOOTGEAR_OUTPUT": ""}
ADVISOR_SETTLEMENT = ("converge_seats:\n  r2: advisor\n"
                      "advisor_roles:\n  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n  startup: direct\n")


def _settlement(cv: Converge, text: str) -> Path:
    path = cv.root / "settlement.yaml"
    path.write_text(text)
    return path


def _init_args(cv: Converge, *extra: str) -> list[str]:
    return ["init", "s1", "--dir", str(cv.dir), "--as", "orch", "--lenses", "correctness",
            "--angles", str(cv.angles), "--project-root", str(cv.project), *extra]


def _refused_lines(cv: Converge, settlement: Path) -> list[str]:
    result = cv(*_init_args(cv, "--settlement", str(settlement)), code=2)
    assert not cv.path().exists()
    return result.stderr.splitlines()


NEXT_FIX = ("next: correct converge_seats or advisor_roles in {path} so they agree, then rerun "
            "init; in an engine run the settlement is fixed: stop blocked and report this refusal")


def test_init_refuses_roles_without_advisor_seat(cv: Converge) -> None:
    settlement = _settlement(cv, "converge_seats: {r2: native_subagent}\n"
                                 "advisor_roles: {roles: [refuter], brief: Act only as r2., startup: direct}\n")
    lines = _refused_lines(cv, settlement)
    assert lines[0].startswith(f"example: {GEAR_COMMAND} init ")
    message = lines.index("converge: settlement seats do not match its advisor roles:")
    assert lines[message + 1] == (
        "  - advisor_roles: names refuter but converge_seats.r2 is native_subagent; "
        "set converge_seats.r2: advisor, or remove refuter from advisor_roles.roles")
    assert message + 2 == len(lines) - 1
    assert any(line.startswith(f"example: {GEAR_COMMAND} init ") and line.endswith("--settlement <file>")
               for line in lines), lines
    assert any(line.startswith("commands: ") for line in lines), lines
    assert lines[-1] == NEXT_FIX.format(path=settlement)


def test_init_refusal_json_carries_example_and_next(cv: Converge) -> None:
    settlement = _settlement(cv, "advisor_roles: {roles: [gap-hunter], brief: Act only as r2., startup: direct}\n")
    result = cv(*_init_args(cv, "--settlement", str(settlement), "--json"), code=2, env=PIPE)
    error = json.loads(result.stderr)["error"]
    assert error["message"] == "converge: settlement seats do not match its advisor roles:"
    assert error["example"].endswith("--settlement <file>")
    assert error["next"] == NEXT_FIX.format(path=settlement)[len("next: "):]
    assert not cv.path().exists()


def test_init_refuses_every_seat_shape_problem(cv: Converge) -> None:
    settlement = _settlement(cv, "converge_seats: {r9: advisor, r1: robot, main: advisor, "
                                 "finder: advisor, r2: advisor}\n"
                                 "advisor_roles: {roles: [bogus], brief: ''}\n")
    lines = _refused_lines(cv, settlement)
    assert lines[0].startswith(f"example: {GEAR_COMMAND} init ")
    assert "converge: invalid settlement seats:" in lines
    text = "\n".join(lines)
    for fragment in ("converge_seats: unknown seat 'r9'",
                     "converge_seats.r1: unknown mechanism 'robot'",
                     "converge_seats.main: only r2 may be advisor",
                     "converge_seats.finder: only r2 may be advisor",
                     "advisor_roles.roles: unknown role 'bogus'", "advisor_roles.brief:"):
        assert fragment in text, text
    assert lines[-1] == NEXT_FIX.format(path=settlement)


def test_init_refuses_a_settlement_that_is_not_a_mapping(cv: Converge) -> None:
    settlement = _settlement(cv, "- r2\n- advisor\n")
    lines = _refused_lines(cv, settlement)
    assert lines[0].startswith(f"example: {GEAR_COMMAND} init ")
    assert lines[-3:-1] == ["converge: invalid settlement seats:",
                            "  - --settlement must be a YAML mapping (the engine settlement)"]
    assert "  - --settlement must be a YAML mapping (the engine settlement)" in lines
    assert lines[-1] == NEXT_FIX.format(path=settlement)


def test_init_r2_advisor_without_roles_uses_defaults(cv: Converge) -> None:
    settlement = _settlement(cv, "converge_seats: {r2: advisor}\n")
    lines = cv(*_init_args(cv, "--settlement", str(settlement))).stdout.splitlines()
    assert ("NOTE r2 is advisor with no advisor role in the settlement; it takes refuter, "
            "gap-hunter and the stock brief") in lines
    assert cv.events()[0]["advisor"] == {
        "roles": ["refuter", "gap-hunter"],
        "brief": "Act only as this seat on this slate; do not extend the role.", "startup": "direct"}


def test_init_one_refuter_notes_the_unseated_advisor(cv: Converge) -> None:
    settlement = _settlement(cv, ADVISOR_SETTLEMENT)
    result = cv(*_init_args(cv, "--settlement", str(settlement), "--refuters", "1"))
    lines = result.stdout.splitlines()
    assert ("NOTE r2 is advisor in the settlement, but this slate has no r2; the advisor holds "
            "no seat on this slate") in lines
    assert not any(line.startswith(("DRIVER", "REQUEST")) for line in lines), lines
    assert not lines[-1].startswith("next:")
    event = cv.events()[0]
    assert event["seats"] == {"main": "native_subagent", "finder": "native_subagent",
                              "r1": "native_subagent", "cutter": "native_subagent"}
    assert "advisor" not in event
    data = json.loads(cv(*_init_args(cv, "--settlement", str(settlement), "--refuters", "1",
                                     "--dir", str(cv.root / "j"), "--json"), env=PIPE).stdout)
    assert len(data["notes"]) == 1


def test_init_refuters_out_of_range_is_a_usage_refusal(cv: Converge) -> None:
    err = cv(*_init_args(cv, "--refuters", "3"), code=2).stderr
    assert "argument --refuters: invalid choice:" in err, err
    assert "(choose from 1, 2)" in err.replace("'", ""), err
    assert f"example: {GEAR_COMMAND} init " in err
    assert not cv.path().exists()


def test_codex_role_settlement_matches_plain_init(cv: Converge) -> None:
    settlement = _settlement(cv, 'codex_role: "adversarial reviewer"\ngoal: x\n')
    with_file = cv(*_init_args(cv, "--settlement", str(settlement))).stdout
    plain = cv(*_init_args(cv, "--dir", str(cv.root / "plain"))).stdout
    assert with_file.replace(str(cv.dir), "D") == plain.replace(str(cv.root / "plain"), "D")
    assert cv.events()[0]["seats"] == {seat: "native_subagent"
                                       for seat in ("main", "finder", "r1", "r2", "cutter")}


def test_status_reprints_seat_mechanisms(cv: Converge) -> None:
    settlement = _settlement(cv, ADVISOR_SETTLEMENT)
    cv(*_init_args(cv, "--settlement", str(settlement)))
    data = json.loads(cv.ok("status", "s1", "--json").stdout)
    assert data["seats"]["r2"] == "advisor"
    head = cv.ok("status", "s1").stdout.splitlines()[0]
    assert head.startswith("SLATE s1 lenses=correctness ") and " advisor=r2" in head


def test_status_of_a_native_slate_shows_no_advisor(cv: Converge) -> None:
    cv.init()
    data = json.loads(cv.ok("status", "s1", "--json").stdout)
    assert data["seats"] == {}
    assert " advisor=-" in cv.ok("status", "s1").stdout.splitlines()[0]


def test_manifest_declares_advisor_dependency() -> None:
    manifest = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["dependencies"] == ["memory-ledger", "advisor", "deputy", "cli"]


def test_deferred_advisor_stays_unstarted_when_no_task_needs_it(cv: Converge) -> None:
    settlement = _settlement(cv, ADVISOR_SETTLEMENT.replace("  startup: direct\n", "")
                             + "  startup: deferred\n  launcher: start-advisor\n")
    cv.init("s1", "correctness", "orch", "--settlement", str(settlement),
            config={"steps": {"gap_hunt": False, "escalate": False, "cut": "none"}})
    cv.cover(lenses=("correctness",))
    state = json.loads(cv.ok("status", "s1", "--json").stdout)
    assert state["phase"] == "cutoff"
    assert "start-advisor" not in state["next"] and "reclaim" not in state["next"]


def test_deferred_choice_is_preserved_when_seat_uses_stock_roles(cv: Converge) -> None:
    settlement = _settlement(cv, "converge_seats: {r2: advisor}\n"
                             "advisor_roles: {roles: [], brief: Use stock roles., "
                             "startup: deferred, launcher: start-advisor}\n")
    data = json.loads(cv(*_init_args(cv, "--settlement", str(settlement), "--json")).stdout)
    assert data["seats"]["r2"] == "advisor"
    assert cv.events()[0]["advisor"]["startup"] == "deferred"


def test_invalid_startup_refuses_without_writing_a_slate(cv: Converge) -> None:
    for options, field in (("  startup: later\n", "startup"),
                           ("  startup: deferred\n", "launcher")):
        settlement = _settlement(cv, ADVISOR_SETTLEMENT.replace("  startup: direct\n", "") + options)
        result = cv(*_init_args(cv, "--settlement", str(settlement)), code=2)
        assert f"advisor_roles.{field}" in result.stderr
        assert not cv.path().exists()
