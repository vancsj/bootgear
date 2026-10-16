"""Advisor seats: the init event records each seat's mechanism and the advisor's roles."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from conftest import BIN, PLUGIN_DIR, Converge
from converge import ledger, model

ADVISOR = {"roles": ["refuter", "gap-hunter"], "brief": "Act only as r2."}
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
                      "advisor_roles:\n  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n")


def _settlement(cv: Converge, text: str) -> Path:
    path = cv.root / "settlement.yaml"
    path.write_text(text)
    return path


def _init_args(cv: Converge, *extra: str) -> list[str]:
    return ["init", "s1", "--dir", str(cv.dir), "--as", "orch", "--lenses", "correctness",
            "--angles", str(cv.angles), "--project-root", str(cv.project), *extra]


def _line(lines: list[str], prefix: str) -> str:
    found = [line for line in lines if line.startswith(prefix)]
    assert len(found) == 1, (prefix, lines)
    return found[0]


def _scope_converge(scope: str) -> Path:
    # SCOPE: write events only with: UV_CACHE_DIR="..." <abs-converge> <attack|...> ...
    tail = scope.split('converge-uv-cache" ', 1)[1]
    return Path(tail.split(" ", 1)[0])


def _assert_driver(lines: list[str], cv: Converge, *, converge_path: Path | None = None) -> None:
    step = _line(lines, "DRIVER r2 step (one background step per turn): ")
    assert ' send --channel "$CHANNEL" --from asker --to listener --kind request --body-file ' in step
    assert f"--body-file {cv.dir}/s1.r2.request.txt && " in step
    assert step.endswith(' receive --channel "$CHANNEL" --for asker --timeout 300')
    assert step.count(" receive ") == 1 and "while" not in step
    placeholders = _line(lines, "DRIVER r2 placeholders: ")
    for fragment in ("literal channel.py path and channel number", "pairing printed",
                     '"$CHANNEL_SCRIPT"', '"$CHANNEL"'):
        assert fragment in placeholders, placeholders
    then = _line(lines, "DRIVER r2 then: ")
    for fragment in ("do not run the while-loop next that send prints",
                     "5 receives in total, the one in the step included",
                     "on receive exit 1 run that receive alone again",
                     "parent_id is this send's message_id and fetch it",
                     "after the 5th receive", "stops the slate blocked naming r2"):
        assert fragment in then, then
    assert "at most 5 times" not in then
    other = _line(lines, "DRIVER r2 other messages: ")
    for fragment in ("parent_id is not this send's message_id is a late reply",
                     "fetch it so it stops reappearing, discard it",
                     "without counting it toward the 5",
                     "any other kind is a protocol error: stop the slate blocked naming r2"):
        assert fragment in other, other
    assert ".sent" not in other
    check = _line(lines, "DRIVER r2 check: ")
    for fragment in ("converge status s1 --dir ", "--json; a reply starting", "WRITE-DENIED",
                     "absent from status", "blocked naming r2",
                     "never redo the turn with a native subagent"):
        assert fragment in check, check
    head = lines.index(_line(lines, "REQUEST r2 (write to the body file before each send"))
    assert lines[head + 1] == "TYPE: delegate"
    assert lines[head + 2].startswith(
        "USER_REQUEST: You are seat r2 (refuter, gap-hunter) on converge slate s1. Act only as r2.")
    assert lines[head + 3].startswith("CONTEXT: <claims under test")
    scope = lines[head + 4]
    assert scope.startswith('SCOPE: write events only with: UV_CACHE_DIR="${TMPDIR:-/tmp}/converge-uv-cache" ')
    for fragment in (f"--dir {cv.dir} --as r2", f"append to {cv.dir}/s1.jsonl",
                     "request write permission", "require_escalated",
                     'reply "WRITE-DENIED r2: <the error text>"', "|escalate|angle-na>"):
        assert fragment in scope, scope
    path = _scope_converge(scope)
    assert path.is_absolute() and path.is_file() and os.access(path, os.X_OK), path
    if converge_path is not None:
        assert path == converge_path


def test_init_with_advisor_settlement_prints_seats_and_driver(cv: Converge) -> None:
    settlement = _settlement(cv, ADVISOR_SETTLEMENT)
    lines = cv(*_init_args(cv, "--settlement", str(settlement))).stdout.splitlines()
    assert lines[0].startswith("INIT s1 lenses=correctness ")
    assert lines[1] == ("SEATS main=native_subagent finder=native_subagent r1=native_subagent "
                        "r2=advisor cutter=native_subagent")
    _assert_driver(lines, cv)
    nxt = lines[-1]
    assert nxt.startswith("next: reclaim the advisor channel for r2 "), nxt
    for fragment in ("advisor channels decision", "--mode asking",
                     "prints the channel.py path and the channel number",
                     "keep the channel open after this slate",
                     "if it hands back no listener, stop blocked naming r2"):
        assert fragment in nxt, nxt
    event = cv.events()[0]
    assert event["seats"] == {"main": "native_subagent", "finder": "native_subagent",
                              "r1": "native_subagent", "r2": "advisor", "cutter": "native_subagent"}
    assert event["advisor"] == {"roles": ["refuter", "gap-hunter"], "brief": "Act only as r2."}


def test_init_with_advisor_settlement_json(cv: Converge) -> None:
    settlement = _settlement(cv, ADVISOR_SETTLEMENT)
    data = json.loads(cv(*_init_args(cv, "--settlement", str(settlement), "--json"),
                         env=PIPE).stdout)
    assert data["seats"]["r2"] == "advisor"
    assert [d["seat"] for d in data["drivers"]] == ["r2"]
    assert data["drivers"][0]["step"].endswith("--timeout 300")
    assert data["drivers"][0]["request"].startswith("TYPE: delegate\n")
    assert data["notes"] == []
    assert data["next"].startswith("reclaim the advisor channel for r2")


def test_init_driver_names_the_shipped_wrapper(cv: Converge) -> None:
    cv.use_bin = True
    settlement = _settlement(cv, ADVISOR_SETTLEMENT)
    lines = cv(*_init_args(cv, "--settlement", str(settlement))).stdout.splitlines()
    _assert_driver(lines, cv, converge_path=BIN.resolve())


def _refused_lines(cv: Converge, settlement: Path) -> list[str]:
    result = cv(*_init_args(cv, "--settlement", str(settlement)), code=2)
    assert not cv.path().exists()
    return result.stderr.splitlines()


NEXT_FIX = ("next: correct converge_seats or advisor_roles in {path} so they agree, then rerun "
            "init; in an engine run the settlement is fixed: stop blocked and report this refusal")


def test_init_refuses_roles_without_advisor_seat(cv: Converge) -> None:
    settlement = _settlement(cv, "converge_seats: {r2: native_subagent}\n"
                                 "advisor_roles: {roles: [refuter], brief: Act only as r2.}\n")
    lines = _refused_lines(cv, settlement)
    assert lines[0].startswith("example: converge init ")
    message = lines.index("converge: settlement seats do not match its advisor roles:")
    assert lines[message + 1] == (
        "  - advisor_roles: names refuter but converge_seats.r2 is native_subagent; "
        "set converge_seats.r2: advisor, or remove refuter from advisor_roles.roles")
    assert message + 2 == len(lines) - 1
    assert any(line.startswith("example: converge init ") and line.endswith("--settlement <file>")
               for line in lines), lines
    assert any(line.startswith("commands: ") for line in lines), lines
    assert lines[-1] == NEXT_FIX.format(path=settlement)


def test_init_refusal_json_carries_example_and_next(cv: Converge) -> None:
    settlement = _settlement(cv, "advisor_roles: {roles: [gap-hunter], brief: Act only as r2.}\n")
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
    assert lines[0].startswith("example: converge init ")
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
    assert lines[0].startswith("example: converge init ")
    assert lines[-3:-1] == ["converge: invalid settlement seats:",
                            "  - --settlement must be a YAML mapping (the engine settlement)"]
    assert "  - --settlement must be a YAML mapping (the engine settlement)" in lines
    assert lines[-1] == NEXT_FIX.format(path=settlement)


def test_init_r2_advisor_without_roles_uses_defaults(cv: Converge) -> None:
    settlement = _settlement(cv, "converge_seats: {r2: advisor}\n")
    lines = cv(*_init_args(cv, "--settlement", str(settlement))).stdout.splitlines()
    assert ("NOTE r2 is advisor with no advisor role in the settlement; it takes refuter, "
            "gap-hunter and the stock brief") in lines
    request = _line(lines, "USER_REQUEST: ")
    assert request.startswith("USER_REQUEST: You are seat r2 (refuter, gap-hunter) on converge "
                              "slate s1. Act only as this seat on this slate; do not extend the role.")
    assert cv.events()[0]["advisor"] == {
        "roles": ["refuter", "gap-hunter"],
        "brief": "Act only as this seat on this slate; do not extend the role."}
    assert lines[-1].startswith("next: reclaim the advisor channel for r2")


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
    assert data["drivers"] == [] and len(data["notes"]) == 1


def test_init_refuters_out_of_range_is_a_usage_refusal(cv: Converge) -> None:
    err = cv(*_init_args(cv, "--refuters", "3"), code=2).stderr
    assert "argument --refuters: invalid choice:" in err and "(choose from 1, 2)" in err, err
    assert "example: converge init " in err


def test_codex_role_settlement_matches_plain_init(cv: Converge) -> None:
    settlement = _settlement(cv, 'codex_role: "adversarial reviewer"\ngoal: x\n')
    with_file = cv(*_init_args(cv, "--settlement", str(settlement))).stdout
    plain = cv(*_init_args(cv, "--dir", str(cv.root / "plain"))).stdout
    assert with_file.replace(str(cv.dir), "D") == plain.replace(str(cv.root / "plain"), "D")
    assert cv.events()[0]["seats"] == {seat: "native_subagent"
                                       for seat in ("main", "finder", "r1", "r2", "cutter")}


def test_status_reprints_seats_and_drivers(cv: Converge) -> None:
    settlement = _settlement(cv, ADVISOR_SETTLEMENT)
    cv(*_init_args(cv, "--settlement", str(settlement)))
    data = json.loads(cv.ok("status", "s1", "--json").stdout)
    assert data["seats"]["r2"] == "advisor"
    assert [d["seat"] for d in data["drivers"]] == ["r2"]
    assert data["drivers"][0]["request"].startswith("TYPE: delegate\n")
    head = cv.ok("status", "s1").stdout.splitlines()[0]
    assert head.startswith("SLATE s1 lenses=correctness ") and " advisor=r2" in head


def test_status_of_a_native_slate_shows_no_advisor(cv: Converge) -> None:
    cv.init()
    data = json.loads(cv.ok("status", "s1", "--json").stdout)
    assert data["seats"] == {} and data["drivers"] == []
    assert " advisor=-" in cv.ok("status", "s1").stdout.splitlines()[0]


def test_manifest_declares_advisor_dependency() -> None:
    manifest = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["dependencies"] == ["memory-ledger", "advisor", "deputy"]
