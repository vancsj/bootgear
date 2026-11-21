from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import pytest
from workflow_output_test_support import (
    ADVISOR_SETTLEMENT,
    FINDER,
    FIX_NEXT,
    MAIN,
    PROGRAM,
    STEPS,
    Slate,
    _ok,
    _one,
    _seat_init,
    _settlement,
)


def test_shared_init_prints_advisor_driver(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement)).stdout.splitlines()
    assert lines[1] == ("SEATS main=native_subagent finder=native_subagent r1=native_subagent "
                        "r2=advisor cutter=native_subagent")
    step = _one(lines, "DRIVER r2 step (one background step per turn): ")
    assert f"--body-file {ledger}/s1.r2.request.txt && " in step
    assert step.endswith(' receive --channel "$CHANNEL" --for asker --timeout 300')
    assert 'python3 "$CHANNEL_SCRIPT"' not in step
    assert step.count(" receive ") == 1 and "while" not in step
    placeholders = _one(lines, "DRIVER r2 placeholders: ")
    assert "Gear channel command and channel number" in placeholders
    assert '"$CHANNEL"' in placeholders
    then = _one(lines, "DRIVER r2 then: ")
    assert "5 receives in total, the one in the step included" in then
    assert "after the 5th receive" in then and "at most 5 times" not in then
    other = _one(lines, "DRIVER r2 other messages: ")
    assert "is a late reply" in other and "without counting it toward the 5" in other
    assert "any other kind is a protocol error: stop the slate blocked naming r2" in other
    check = _one(lines, "DRIVER r2 check: ")
    assert "WRITE-DENIED" in check and "never redo the turn with a native subagent" in check
    scope = _one(lines, "SCOPE: ")
    assert scope.startswith("SCOPE: Call cli:gear through your own host.")
    assert "UV_CACHE_DIR" not in scope
    assert PROGRAM not in scope
    gear = Path(shlex.split(PROGRAM)[0])
    assert gear.is_file() and os.access(gear, os.X_OK)
    for fragment in (f"--dir {ledger} --as r2", "If a write is denied, stop",
                     'reply "WRITE-DENIED r2: <the error text>"',
                     "--role-host <your executing host>"):
        assert fragment in scope, scope
    nxt = lines[-1]
    assert nxt.startswith("next: reclaim the advisor channel for r2 "), nxt
    assert "prints the Gear command and channel number" in nxt
    assert "keep the channel open after this slate" in nxt


@pytest.mark.parametrize("command", ["init", "status"])
@pytest.mark.parametrize("output", ["--prose", "--json"])
def test_shared_advisor_request_requires_hand_filled_test_context(
        tmp_path: Path, command: str, output: str) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    if command == "init":
        result = _seat_init(tmp_path, ledger, "--settlement", str(settlement), output)
    else:
        _seat_init(tmp_path, ledger, "--settlement", str(settlement))
        for angle in ("changed-contract", "failure-path"):
            _ok(tmp_path, "angle-na", "s1", "--dir", str(ledger), "--as", FINDER,
                "--phase", "find", "--lens", "correctness", "--angle", angle,
                "--reason", "no I/O in diff")
        result = _ok(tmp_path, "status", "s1", "--dir", str(ledger), output)
    if command == "status" and output == "--prose":
        lines = result.stdout.splitlines()
        assert lines[0].startswith("SLATE s1 lenses=correctness ")
        assert lines[-1].startswith("next: ")
        assert not any(line.startswith(("DRIVER", "REQUEST", "Tests already ran:")) for line in lines)
        return
    if output == "--json":
        lines = json.loads(result.stdout)["drivers"][0]["request"].splitlines()
    else:
        lines = result.stdout.splitlines()
        head = lines.index(_one(lines, "REQUEST r2 (write to the body file before each send"))
        lines = lines[head + 1:]
    assert lines[0] == "TYPE: delegate"
    assert lines[1].startswith("USER_REQUEST: You are seat r2 (refuter, gap-hunter) on converge slate s1.")
    assert lines[2].startswith("CONTEXT: <claims under test")
    assert lines[3].startswith("SCOPE: Call cli:gear through your own host.")
    assert lines[4:6] == [
        "Tests already ran:",
        "- latest test: <recorded command>; result: <one recorded result line>",
    ]
    for fragment in ("memory-ledger entries", "Preserve all other write limits",
                     "--role-host <your executing host>",
                     "If a write is denied, stop",
                     'reply "WRITE-DENIED r2: <the error text>"'):
        assert fragment in lines[3], lines[3]
    request = "\n".join(lines[6:])
    for fragment in ("Required: main agent fills this part by hand before each send.",
                     "latest test command recorded in the run ledger", "only part of the tests",
                     "one result line from that record", "no exit code or record path",
                     "Do not combine commands that did not run together.",
                     "If no test result is recorded, write none recorded.",
                     "Skip redundant runs covered by recorded test commands.",
                     "You can probe behaviour those commands did not cover."):
        assert fragment in request, request


def test_shared_init_refuses_seat_mismatch(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {r2: native_subagent}\n"
                                       "advisor_roles: {roles: [refuter], brief: Act only as r2., startup: early}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement), code=2).stderr.splitlines()
    assert lines[0].startswith("example: ") and lines[0].endswith("--settlement <file>")
    message = lines.index("converge: settlement seats do not match its advisor roles:")
    assert "set converge_seats.r2: advisor, or remove refuter" in lines[message + 1]
    assert message + 2 == len(lines) - 1
    assert lines[-1] == FIX_NEXT.format(path=settlement)
    error = json.loads(_seat_init(tmp_path, ledger, "--settlement", str(settlement), "--json",
                                  code=2).stderr)["error"]
    assert error["example"].endswith("--settlement <file>")
    assert error["next"] == FIX_NEXT.format(path=settlement)[len("next: "):]
    assert not (ledger / "s1.jsonl").exists()


def test_shared_init_refuses_non_r2_advisor_seat(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {finder: advisor, r2: advisor}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement), code=2).stderr.splitlines()
    assert lines[0].startswith("example: ")
    assert "converge: invalid settlement seats:" in lines
    assert any(line.startswith("  - converge_seats.finder: only r2 may be advisor")
               for line in lines), lines
    assert lines[-1] == FIX_NEXT.format(path=settlement)
    assert not (ledger / "s1.jsonl").exists()


def test_shared_r2_advisor_without_roles_uses_defaults(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {r2: advisor}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement)).stdout.splitlines()
    assert ("NOTE r2 is advisor with no advisor role in the settlement; it takes refuter, "
            "gap-hunter and the stock brief") in lines
    assert _one(lines, "USER_REQUEST: ").startswith(
        "USER_REQUEST: You are seat r2 (refuter, gap-hunter) on converge slate s1. "
        "Act only as this seat on this slate; do not extend the role.")
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert init["advisor"]["roles"] == ["refuter", "gap-hunter"]


def test_shared_refuters_one_notes_unseated_advisor(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement),
                       "--refuters", "1").stdout.splitlines()
    assert ("NOTE r2 is advisor in the settlement, but this slate has no r2; the advisor holds "
            "no seat on this slate") in lines
    assert not any(line.startswith(("DRIVER", "REQUEST")) for line in lines), lines
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert "r2" not in init["seats"] and "advisor" not in init
    assert init["refuters"] == 1


def test_shared_init_refuters_out_of_range_is_a_usage_refusal(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    err = _seat_init(tmp_path, ledger, "--refuters", "3", code=2).stderr
    assert "argument --refuters: invalid choice:" in err, err
    assert "(choose from 1, 2)" in err.replace("'", ""), err
    assert f"example: {PROGRAM} init " in err
    assert not (ledger / "s1.jsonl").exists()


def test_shared_status_reprints_drivers(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    _seat_init(tmp_path, ledger, "--settlement", str(settlement))
    data = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert data["seats"]["r2"] == "advisor"
    assert [d["seat"] for d in data["drivers"]] == ["r2"]
    assert data["drivers"][0]["step"].endswith("--timeout 300")
    head = _ok(tmp_path, "status", "s1", "--dir", str(ledger)).stdout.splitlines()[0]
    assert " advisor=r2" in head


def test_shared_slate_without_seats_is_all_native(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _seat_init(tmp_path, ledger)
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert "seats" not in init and "advisor" not in init
    data = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert data["seats"] == {} and data["drivers"] == []
    head = _ok(tmp_path, "status", "s1", "--dir", str(ledger)).stdout.splitlines()[0]
    assert " advisor=-" in head


def test_shared_deferred_advisor_waits_for_gap_hunt(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT.replace("  startup: early\n", "")
                             + "  startup: deferred\n  launcher: start-advisor\n")
    data = json.loads(slate.ok("init", "--as", MAIN, "--lenses", "correctness",
                              "--angles", str(slate.angles), "--project-root", str(tmp_path),
                              "--settlement", str(settlement), "--json").stdout)
    assert "continue the finder" in data["next"]
    assert "reclaim" not in data["next"] and "start-advisor" not in data["next"]
    slate.cover()
    state = json.loads(slate.ok("status", "--json").stdout)
    assert "start-advisor" in state["next"] and "gap hunt" in state["next"]
    assert "reuse" in state["drivers"][0]["prepare"]


def test_shared_deferred_choice_with_stock_roles(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {r2: advisor}\n"
                             "advisor_roles: {roles: [], brief: Use stock roles., "
                             "startup: deferred, launcher: start-advisor}\n")
    data = json.loads(_seat_init(tmp_path, ledger, "--settlement", str(settlement), "--json").stdout)
    assert "continue the finder" in data["next"]
    state = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert "start-advisor" in state["drivers"][0]["prepare"]


def test_shared_unused_deferred_advisor_is_not_started(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT.replace("  startup: early\n", "")
                             + "  startup: deferred\n  launcher: start-advisor\n")
    slate.init("--settlement", str(settlement),
               config="steps: {gap_hunt: false, escalate: false, cut: none}\n")
    slate.cover()
    state = json.loads(slate.ok("status", "--json").stdout)
    assert state["phase"] == "cutoff"
    assert "start-advisor" not in state["next"] and "reclaim" not in state["next"]


def test_shared_deferred_advisor_waits_for_fresh_eye_when_gap_hunt_is_off(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT.replace("  startup: early\n", "")
                             + "  startup: deferred\n  launcher: start-advisor\n")
    config = STEPS.replace("cut: both", "cut: none").replace("escalate: true", "escalate: false")
    slate.init("--settlement", str(settlement), config=config)
    slate.file()
    slate.cover()
    assert "start-advisor" not in slate.status()["next"]
    slate.batch_1()
    state = slate.status()
    assert state["plan"][0][0]["agent_role"] == "r2"
    assert state["plan"][0][0]["batch"] == "fresh-eye"
    assert "start-advisor" in state["next"]


def test_shared_invalid_startup_writes_no_slate(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    for options, field in (("  startup: later\n", "startup"),
                           ("  startup: deferred\n", "launcher")):
        settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT.replace("  startup: early\n", "") + options)
        result = _seat_init(tmp_path, ledger, "--settlement", str(settlement), code=2)
        assert f"advisor_roles.{field}" in result.stderr
        assert not (ledger / "s1.jsonl").exists()
