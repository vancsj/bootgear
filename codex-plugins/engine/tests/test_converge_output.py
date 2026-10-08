from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

TASK = Path(__file__).resolve().parents[1] / "scripts" / "converge"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(root / "home")}
    # VIRTUAL_ENV makes uv print a mismatch warning on stderr.
    env.pop("VIRTUAL_ENV", None)
    return subprocess.run(
        [str(TASK), *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_bundled_converge_reports_state_and_choices(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    init = _run(tmp_path, "init", "s1", "--dir", str(ledger), "--as", "slate",
                "--mode", "refute-only", "--json")
    assert init.returncode == 0, init.stderr
    assert json.loads(init.stdout)["next"].startswith("file every slate claim:")

    status = _run(tmp_path, "status", "s1", "--dir", str(ledger), "--json")
    assert status.returncode == 0, status.stderr
    status_data = json.loads(status.stdout)
    assert status_data["phase"] == "find"
    assert status_data["round"] == 0
    assert "file" in status_data["legal_event_types"]

    rendered = _run(tmp_path, "render", "s1", "--dir", str(ledger), "--json")
    assert rendered.returncode == 0, rendered.stderr
    assert json.loads(rendered.stdout)["choices"] == []


def test_bundled_full_converge_requires_find_coverage_before_cutoff(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    angles = Path(__file__).resolve().parents[1] / "skills" / "review" / "references" / "find-angles.yaml"
    init = _run(tmp_path, "init", "s1", "--dir", str(ledger), "--as", "slate",
                "--mode", "full", "--lenses", "correctness,security", "--angles", str(angles),
                "--project-root", str(tmp_path), "--json")
    assert init.returncode == 0, init.stderr

    status = _run(tmp_path, "status", "s1", "--dir", str(ledger), "--json")
    assert status.returncode == 0, status.stderr
    status_data = json.loads(status.stdout)
    assert {"file", "find-run", "angle-na"} <= set(status_data["legal_event_types"])
    assert "cutoff" not in status_data["legal_event_types"]

    cutoff = _run(tmp_path, "cutoff", "s1", "--dir", str(ledger), "--json")
    assert cutoff.returncode != 0
    assert "missing find angles" in cutoff.stderr


def test_bundled_status_keeps_finder_events_until_coverage_is_complete(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    angles = Path(__file__).resolve().parents[1] / "skills" / "review" / "references" / "find-angles.yaml"
    init = _run(tmp_path, "init", "s1", "--dir", str(ledger), "--as", "slate",
                "--mode", "full", "--lenses", "correctness", "--angles", str(angles),
                "--project-root", str(tmp_path), "--json")
    assert init.returncode == 0, init.stderr
    filed = _run(tmp_path, "file", "s1", "--dir", str(ledger), "--as", "finder",
                 "--lens", "correctness", "--angle", "changed-contract", "--origin", "lens",
                 "--loc", "a.py:1", "--claim", "claim", "--trigger", "trigger", "--json")
    assert filed.returncode == 0, filed.stderr

    status = _run(tmp_path, "status", "s1", "--dir", str(ledger), "--json")
    assert status.returncode == 0, status.stderr
    status_data = json.loads(status.stdout)
    assert status_data["phase"] == "refute"
    assert {"find-run", "angle-na"} <= set(status_data["legal_event_types"])


ANGLES = Path(__file__).resolve().parents[1] / "skills" / "review" / "references" / "find-angles.yaml"


def _ok(root: Path, *args: str, code: int = 0) -> subprocess.CompletedProcess[str]:
    result = _run(root, *args)
    assert result.returncode == code, f"exit {result.returncode} for {args}\n{result.stderr}"
    return result


def _full_slate(root: Path, ledger: Path) -> None:
    _ok(root, "init", "s1", "--dir", str(ledger), "--as", "orch", "--mode", "full",
        "--lenses", "correctness", "--angles", str(ANGLES), "--project-root", str(root))
    _ok(root, "file", "s1", "--dir", str(ledger), "--as", "finder", "--lens", "correctness",
        "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1", "--claim", "x breaks y", "--trigger", "None")


def _refute(root: Path, ledger: Path, agent: str, angle: str, code: int = 0
            ) -> subprocess.CompletedProcess[str]:
    return _ok(root, "refute", "s1", "--dir", str(ledger), "--as", agent, "--claim", "F001",
               "--round", "1", "--angle", angle, "--tell", "tell applies", "--outcome", "survived",
               "--evidence", "read a.py:1", "--searches", "rg x", "--positive-control", "rg y finds y",
               code=code)


def _cut(root: Path, ledger: Path, agent: str, rnd: str = "1", code: int = 0
         ) -> subprocess.CompletedProcess[str]:
    return _ok(root, "cut", "s1", "--dir", str(ledger), "--as", agent, "--claim", "F001",
               "--round", rnd, "--frequency", "common", "--severity", "degraded",
               "--confidence", "traced", "--difficulty", "local",
               "--evidence", "entry-points=POST /x reaches it",
               "--evidence", "blast-radius=one row per call",
               "--evidence", "evidence-tier=traced a.py:1",
               "--evidence", "files-touched=a.py", code=code)


def test_bundled_converge_refuses_a_sixth_agent(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _full_slate(tmp_path, ledger)
    _refute(tmp_path, ledger, "r1", "boundary")
    _refute(tmp_path, ledger, "r2", "reachability")
    _cut(tmp_path, ledger, "cutter")
    before = (ledger / "s1.jsonl").read_bytes()
    err = _cut(tmp_path, ledger, "cutter-2", rnd="2", code=2).stderr
    assert "agent budget: cutter-2 would be agent 6 on this slate; caps.agents is 5" in err
    assert (ledger / "s1.jsonl").read_bytes() == before


def test_bundled_converge_separates_roles(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _full_slate(tmp_path, ledger)
    assert "finder filed F001 and may not refute it" in _refute(
        tmp_path, ledger, "finder", "boundary", code=2).stderr
    _refute(tmp_path, ledger, "r1", "boundary")
    _refute(tmp_path, ledger, "r2", "reachability")
    assert "may not cut it" in _cut(tmp_path, ledger, "finder", code=2).stderr
    assert "refuters and cutters are disjoint" in _cut(tmp_path, ledger, "r1", code=2).stderr
    _cut(tmp_path, ledger, "cutter")


def test_bundled_converge_orchestrator_never_refutes_or_cuts(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _full_slate(tmp_path, ledger)
    assert "the orchestrator never writes refute" in _refute(
        tmp_path, ledger, "orch", "boundary", code=2).stderr
    _refute(tmp_path, ledger, "r1", "boundary")
    _refute(tmp_path, ledger, "r2", "reachability")
    assert "the orchestrator never writes cut" in _cut(tmp_path, ledger, "orch", code=2).stderr


def test_bundled_converge_reserves_agent_ids(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _full_slate(tmp_path, ledger)
    err = _ok(tmp_path, "file", "s1", "--dir", str(ledger), "--as", "converge", "--lens", "correctness",
              "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:2", "--claim", "z",
              "--trigger", "None", code=2).stderr
    assert "reserved for computed cutoff events" in err
    err = _ok(tmp_path, "file", "s1", "--dir", str(ledger), "--as", "slate", "--lens", "correctness",
              "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:2", "--claim", "z",
              "--trigger", "None", code=2).stderr
    assert "'slate' is reserved for refute-only" in err
    err = _ok(tmp_path, "file", "s1", "--dir", str(ledger), "--as", "finder", "--lens", "correctness",
              "--angle", "changed-contract", "--origin", "slate", "--loc", "a.py:2", "--claim", "z",
              "--trigger", "None", code=2).stderr
    assert "origin slate is only for refute-only" in err


# ---------------------------------------------------------------------------
# advisor seats: init --settlement / --refuters and status through scripts/converge

ADVISOR_SETTLEMENT = ("converge_seats:\n  r2: advisor\n"
                      "advisor_roles:\n  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n")
FIX_NEXT = ("next: correct converge_seats or advisor_roles in {path} so they agree, then rerun "
            "init; in an engine run the settlement is fixed: stop blocked and report this refusal")


def _settlement(root: Path, text: str) -> Path:
    path = root / "settlement.yaml"
    path.write_text(text)
    return path


def _seat_init(root: Path, ledger: Path, *extra: str, code: int = 0
               ) -> subprocess.CompletedProcess[str]:
    return _ok(root, "init", "s1", "--dir", str(ledger), "--as", "orch", "--mode", "full",
               "--lenses", "correctness", "--angles", str(ANGLES), "--project-root", str(root),
               *extra, code=code)


def _one(lines: list[str], prefix: str) -> str:
    found = [line for line in lines if line.startswith(prefix)]
    assert len(found) == 1, (prefix, lines)
    return found[0]


def test_bundled_init_prints_advisor_driver(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement)).stdout.splitlines()
    assert lines[1] == ("SEATS main=native_subagent finder=native_subagent r1=native_subagent "
                        "r2=advisor cutter=native_subagent")
    step = _one(lines, "DRIVER r2 step (one background step per turn): ")
    assert f"--body-file {ledger}/s1.r2.request.txt && " in step
    assert step.endswith(' receive --channel "$CHANNEL" --for asker --timeout 300')
    assert step.count(" receive ") == 1 and "while" not in step
    placeholders = _one(lines, "DRIVER r2 placeholders: ")
    assert "literal channel.py path and channel number" in placeholders
    assert '"$CHANNEL_SCRIPT"' in placeholders and '"$CHANNEL"' in placeholders
    then = _one(lines, "DRIVER r2 then: ")
    assert "5 receives in total, the one in the step included" in then
    assert "after the 5th receive" in then and "at most 5 times" not in then
    other = _one(lines, "DRIVER r2 other messages: ")
    assert "is a late reply" in other and "without counting it toward the 5" in other
    assert "any other kind is a protocol error: stop the slate blocked naming r2" in other
    check = _one(lines, "DRIVER r2 check: ")
    assert "WRITE-DENIED" in check and "never redo the turn with a native subagent" in check
    scope = _one(lines, "SCOPE: ")
    assert scope.startswith('SCOPE: write events only with: UV_CACHE_DIR="${TMPDIR:-/tmp}/converge-uv-cache" ')
    converge = Path(scope.split('converge-uv-cache" ', 1)[1].split(" ", 1)[0])
    assert converge == TASK.resolve()
    assert converge.is_file() and os.access(converge, os.X_OK)
    for fragment in (f"--dir {ledger} --as r2", "require_escalated",
                     'reply "WRITE-DENIED r2: <the error text>"'):
        assert fragment in scope, scope
    nxt = lines[-1]
    assert nxt.startswith("next: reclaim the advisor channel for r2 "), nxt
    assert "prints the channel.py path and the channel number" in nxt
    assert "keep the channel open after this slate" in nxt


def test_bundled_init_refuses_seat_mismatch(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {r2: native_subagent}\n"
                                       "advisor_roles: {roles: [refuter], brief: Act only as r2.}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement), code=2).stderr.splitlines()
    assert lines[0] == "converge: settlement seats do not match its advisor roles:"
    assert any("set converge_seats.r2: advisor, or remove refuter" in line for line in lines)
    assert any(line.startswith("example: ") and line.endswith("--settlement <file>")
               for line in lines), lines
    assert lines[-1] == FIX_NEXT.format(path=settlement)
    error = json.loads(_seat_init(tmp_path, ledger, "--settlement", str(settlement), "--json",
                                  code=2).stderr)["error"]
    assert error["example"].endswith("--settlement <file>")
    assert error["next"] == FIX_NEXT.format(path=settlement)[len("next: "):]
    assert not (ledger / "s1.jsonl").exists()


def test_bundled_init_refuses_non_r2_advisor_seat(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {finder: advisor, r2: advisor}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement), code=2).stderr.splitlines()
    assert lines[0] == "converge: invalid settlement seats:"
    assert any(line.startswith("  - converge_seats.finder: only r2 may be advisor")
               for line in lines), lines
    assert lines[-1] == FIX_NEXT.format(path=settlement)
    assert not (ledger / "s1.jsonl").exists()


def test_bundled_r2_advisor_without_roles_uses_defaults(tmp_path: Path) -> None:
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


def test_bundled_refuters_one_notes_unseated_advisor(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement),
                       "--refuters", "1").stdout.splitlines()
    assert ("NOTE r2 is advisor in the settlement, but this slate has no r2; the advisor holds "
            "no seat on this slate") in lines
    assert not any(line.startswith(("DRIVER", "REQUEST")) for line in lines), lines
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert "r2" not in init["seats"] and "advisor" not in init


def test_bundled_status_reprints_drivers(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    _seat_init(tmp_path, ledger, "--settlement", str(settlement))
    data = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert data["seats"]["r2"] == "advisor"
    assert [d["seat"] for d in data["drivers"]] == ["r2"]
    assert data["drivers"][0]["step"].endswith("--timeout 300")
    head = _ok(tmp_path, "status", "s1", "--dir", str(ledger)).stdout.splitlines()[0]
    assert " advisor=r2" in head


def test_bundled_legacy_slate_without_seats_replays(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _seat_init(tmp_path, ledger)
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert "seats" not in init and "advisor" not in init
    data = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert data["seats"] == {} and data["drivers"] == []
    head = _ok(tmp_path, "status", "s1", "--dir", str(ledger)).stdout.splitlines()[0]
    assert " advisor=-" in head
