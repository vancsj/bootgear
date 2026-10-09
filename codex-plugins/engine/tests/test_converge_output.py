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
    # The default steps cut a claim before it is refuted.
    assert status_data["phase"] == "cut"
    assert {"find-run", "angle-na"} <= set(status_data["legal_event_types"])


ANGLES = Path(__file__).resolve().parents[1] / "skills" / "review" / "references" / "find-angles.yaml"


def _ok(root: Path, *args: str, code: int = 0) -> subprocess.CompletedProcess[str]:
    result = _run(root, *args)
    assert result.returncode == code, f"exit {result.returncode} for {args}\n{result.stderr}"
    return result


def _full_slate(root: Path, ledger: Path) -> None:
    # Every step off, so the slate keeps the file → refute → cut flow.
    steps = root / "steps-off.yaml"
    steps.write_text("steps: {escalate: false, early_cut: false, gap_hunt: false}\n")
    _ok(root, "init", "s1", "--dir", str(ledger), "--as", "orch", "--mode", "full",
        "--lenses", "correctness", "--angles", str(ANGLES), "--project-root", str(root),
        "--config", str(steps))
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
                     'reply "WRITE-DENIED r2: <the error text>"', "|escalate|angle-na>"):
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


# ---------------------------------------------------------------------------
# default steps: escalate, cut first, parking, exhaustion and follow-up

THREE_ATTACK = ("angles:\n  disable: [cited-but-unread, point-in-time, absent-vs-default, "
                "downstream-consumer, inverse-reading, carve-out, dependents, positive-control, "
                "inherited-bounds, guarded-elsewhere, deliberate, real-referent]\n")


def _steps_slate(root: Path, ledger: Path, *claims: str, config_text: str = THREE_ATTACK
                 ) -> None:
    """A slate with the default steps and, by default, three attack angles: boundary,
    reachability, provenance."""
    config = root / "three-attack.yaml"
    config.write_text(config_text)
    _ok(root, "init", "s1", "--dir", str(ledger), "--as", "orch", "--mode", "full",
        "--lenses", "correctness", "--angles", str(ANGLES), "--project-root", str(root),
        "--config", str(config))
    for n, text in enumerate(claims, start=1):
        _ok(root, "file", "s1", "--dir", str(ledger), "--as", "finder", "--lens", "correctness",
            "--angle", "changed-contract", "--origin", "lens", "--loc", f"a.py:{n}",
            "--claim", text, "--trigger", "None")


def _escalate(root: Path, ledger: Path, claim: str, *extra: str, code: int = 0
              ) -> subprocess.CompletedProcess[str]:
    return _ok(root, "escalate", "s1", "--dir", str(ledger), "--as", "finder", "--claim", claim,
               *extra, code=code)


def _cut_claim(root: Path, ledger: Path, claim: str, rnd: int, severity: str, *extra: str,
               code: int = 0) -> subprocess.CompletedProcess[str]:
    return _ok(root, "cut", "s1", "--dir", str(ledger), "--as", "cutter", "--claim", claim,
               "--round", str(rnd), "--frequency", "common", "--severity", severity,
               "--confidence", "traced", "--difficulty", "local",
               "--evidence", "entry-points=POST /x reaches it",
               "--evidence", "blast-radius=one row per call",
               "--evidence", "evidence-tier=traced a.py:1",
               "--evidence", "files-touched=a.py", *extra, code=code)


def _accept(root: Path, ledger: Path, claim: str, rnd: int) -> None:
    _ok(root, "accept", "s1", "--dir", str(ledger), "--as", "finder", "--claim", claim,
        "--round", str(rnd))


def _refute_claim(root: Path, ledger: Path, claim: str, rnd: int, agent: str, angle: str,
                  *outcome: str, code: int = 0) -> subprocess.CompletedProcess[str]:
    return _ok(root, "refute", "s1", "--dir", str(ledger), "--as", agent, "--claim", claim,
               "--round", str(rnd), "--angle", angle, "--tell", "tell applies",
               "--outcome", *(outcome or ("survived",)), "--evidence", "read a.py:1",
               "--searches", "rg x", "--positive-control", "rg y finds y", code=code)


def _claim_status(root: Path, ledger: Path, claim: str) -> dict:
    data = json.loads(_ok(root, "status", "s1", "--dir", str(ledger), "--json").stdout)
    return next(row for row in data["claims"] if row["id"] == claim)


def _cover(root: Path, ledger: Path) -> None:
    coverage = json.loads(_ok(root, "coverage", "s1", "--dir", str(ledger), "--json").stdout)
    for angle in coverage["lenses"]["correctness"]["missing"]:
        _ok(root, "angle-na", "s1", "--dir", str(ledger), "--as", "finder", "--phase", "find",
            "--lens", "correctness", "--angle", angle, "--reason", "not in this diff")


def test_bundled_steps_escalate_cut_accept_then_refute(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "cache key ignores locale")
    assert "F001 needs an escalate event first" in _cut_claim(
        tmp_path, ledger, "F001", 1, "degraded", code=2).stderr
    assert "F001 needs an escalate event first" in _refute_claim(
        tmp_path, ledger, "F001", 1, "r1", "boundary", code=2).stderr
    assert "wider=yes" in _escalate(tmp_path, ledger, "F001", "--wider", "every locale",
                                    "--evidence", "a.py:1 builds the key").stdout
    assert _claim_status(tmp_path, ledger, "F001")["phase"] == "cut"
    assert "needs a converged cut first" in _refute_claim(
        tmp_path, ledger, "F001", 1, "r1", "boundary", code=2).stderr
    _cut_claim(tmp_path, ledger, "F001", 1, "degraded")
    _accept(tmp_path, ledger, "F001", 1)
    claim = _claim_status(tmp_path, ledger, "F001")
    assert (claim["phase"], claim["cut"]) == ("refute", "converged")
    _refute_claim(tmp_path, ledger, "F001", 1, "r1", "boundary", "downgraded",
                  "--narrowed", "only for fr-CA")
    _refute_claim(tmp_path, ledger, "F001", 1, "r2", "reachability")
    claim = _claim_status(tmp_path, ledger, "F001")
    assert (claim["phase"], claim["cut"]) == ("cut", "open")
    assert "needs a converged cut first" in _refute_claim(
        tmp_path, ledger, "F001", 2, "r1", "provenance", code=2).stderr
    _cut_claim(tmp_path, ledger, "F001", 2, "degraded")
    _accept(tmp_path, ledger, "F001", 2)
    _refute_claim(tmp_path, ledger, "F001", 2, "r1", "provenance")
    assert _claim_status(tmp_path, ledger, "F001")["refute"] == "unconverged"


def test_bundled_steps_park_a_cosmetic_claim(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "label typo on the invoice")
    _escalate(tmp_path, ledger, "F001")
    assert "a cosmetic cut needs a non-empty `fix`" in _cut_claim(
        tmp_path, ledger, "F001", 1, "cosmetic", code=2).stderr
    _cut_claim(tmp_path, ledger, "F001", 1, "cosmetic", "--fix", "rename the label")
    _accept(tmp_path, ledger, "F001", 1)
    claim = _claim_status(tmp_path, ledger, "F001")
    assert claim["parked"] is True and claim["phase"] is None
    assert "F001 is parked" in _refute_claim(
        tmp_path, ledger, "F001", 1, "r1", "boundary", code=2).stderr


def test_bundled_steps_follow_up_claims_pass_the_gate(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "label typo on the invoice", "cache key ignores locale")
    _cover(tmp_path, ledger)
    for claim in ("F001", "F002"):
        _escalate(tmp_path, ledger, claim)
    _cut_claim(tmp_path, ledger, "F001", 1, "cosmetic", "--fix", "rename the label")
    _accept(tmp_path, ledger, "F001", 1)
    _cut_claim(tmp_path, ledger, "F002", 1, "degraded")
    _accept(tmp_path, ledger, "F002", 1)
    _refute_claim(tmp_path, ledger, "F002", 1, "r1", "boundary")
    for agent, angle in (("r1", "reachability"), ("r2", "provenance")):
        _ok(tmp_path, "angle-na", "s1", "--dir", str(ledger), "--as", agent, "--phase", "refute",
            "--claim", "F002", "--angle", angle, "--reason", "no such path here")
    assert _claim_status(tmp_path, ledger, "F002")["refute"] == "unconverged"
    cutoff = _ok(tmp_path, "cutoff", "s1", "--dir", str(ledger)).stdout
    assert "F002 follow-up rank=1 reason=unconverged" in cutoff
    assert "F001 follow-up rank=2 reason=unverified" in cutoff
    gate = _run(tmp_path, "gate", "s1", "--dir", str(ledger))
    assert gate.returncode == 0, gate.stderr
    assert "GATE ok s1" in gate.stdout
    render = _ok(tmp_path, "render", "s1", "--dir", str(ledger)).stdout
    follow_up = render.split("## Follow-up\n\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert follow_up[0].startswith("- **F002** unconverged — cache key ignores locale")
    assert follow_up[1] == ("- **F001** unverified — label typo on the invoice — "
                            "suggested fix: rename the label")


def _plan(root: Path, ledger: Path) -> dict:
    return json.loads(_ok(root, "status", "s1", "--dir", str(ledger), "--json").stdout)


def _plan_ids(batches: list[list[dict]]) -> list[list[str]]:
    return [[row["claim"] for row in batch] for batch in batches]


def test_bundled_steps_batch_plan_caps_batches_and_splits_angles(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "a", "b", "c",
                 config_text=THREE_ATTACK + "caps: {batch_items: 2}\n")
    data = _plan(tmp_path, ledger)
    assert data["caps"] == {"batch_items": 2, "angles_per_claim": 5}
    assert _plan_ids(data["plan"]["escalate"]) == [["F001", "F002"], ["F003"]]
    assert data["plan"]["escalate"][0][0] == {"claim": "F001", "finder": "finder"}
    for claim in ("F001", "F002", "F003"):
        _escalate(tmp_path, ledger, claim)
        _cut_claim(tmp_path, ledger, claim, 1, "degraded")
        _accept(tmp_path, ledger, claim, 1)
    plan = _plan(tmp_path, ledger)["plan"]
    assert plan["escalate"] == [] and plan["cut"] == []
    assert _plan_ids(plan["refute"]) == [["F001", "F002"], ["F003"]]
    assert [[(row["round"], row["angles"]) for row in batch] for batch in plan["refute"]] == [
        [(1, 1), (1, 1)], [(1, 2)]]


def test_bundled_steps_cut_round_budget_caps_and_reports(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, config_text="caps: {cut_rounds: 2}\n")
    _cover(tmp_path, ledger)
    _ok(tmp_path, "file", "s1", "--dir", str(ledger), "--as", "finder", "--lens", "correctness",
        "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1",
        "--claim", "cache key ignores locale", "--trigger", "None")
    _escalate(tmp_path, ledger, "F001")
    for rnd, angles in ((1, ("boundary", "reachability")), (2, ("provenance", "carve-out"))):
        _cut_claim(tmp_path, ledger, "F001", rnd, "degraded")
        _accept(tmp_path, ledger, "F001", rnd)
        _refute_claim(tmp_path, ledger, "F001", rnd, "r1", angles[0], "downgraded",
                      "--narrowed", f"narrower {rnd}")
        _refute_claim(tmp_path, ledger, "F001", rnd, "r2", angles[1])
    claim = _claim_status(tmp_path, ledger, "F001")
    assert (claim["cut"], claim["cut_round"]) == ("capped", 2)
    assert "exceeds caps.cut_rounds 2" in _cut_claim(
        tmp_path, ledger, "F001", 3, "degraded", code=2).stderr
    _refute_claim(tmp_path, ledger, "F001", 3, "r1", "dependents")
    _refute_claim(tmp_path, ledger, "F001", 3, "r2", "deliberate")
    cutoff = _ok(tmp_path, "cutoff", "s1", "--dir", str(ledger)).stdout
    assert "F001 reported rank=1 reason=cut-capped" in cutoff


def test_bundled_steps_rule_tagged_unconverged_claim_stays_reported(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger,
                 config_text=THREE_ATTACK + "cutoff: {report_rules: [R001]}\n")
    _cover(tmp_path, ledger)
    _ok(tmp_path, "file", "s1", "--dir", str(ledger), "--as", "finder", "--lens", "correctness",
        "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1",
        "--claim", "label typo on the invoice", "--trigger", "None", "--rule", "R001")
    _escalate(tmp_path, ledger, "F001")
    _cut_claim(tmp_path, ledger, "F001", 1, "cosmetic", "--fix", "rename the label")
    _accept(tmp_path, ledger, "F001", 1)
    assert _claim_status(tmp_path, ledger, "F001")["parked"] is False
    _refute_claim(tmp_path, ledger, "F001", 1, "r1", "boundary")
    for agent, angle in (("r1", "reachability"), ("r2", "provenance")):
        _ok(tmp_path, "angle-na", "s1", "--dir", str(ledger), "--as", agent, "--phase", "refute",
            "--claim", "F001", "--angle", angle, "--reason", "no such path here")
    assert _claim_status(tmp_path, ledger, "F001")["refute"] == "unconverged"
    cutoff = _ok(tmp_path, "cutoff", "s1", "--dir", str(ledger)).stdout
    assert "F001 reported rank=1 reason=unconverged" in cutoff


def test_bundled_steps_rebut_row_leaves_after_an_accepted_re_cut(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "cache key ignores locale")
    _escalate(tmp_path, ledger, "F001")
    _cut_claim(tmp_path, ledger, "F001", 1, "degraded")
    _accept(tmp_path, ledger, "F001", 1)
    _refute_claim(tmp_path, ledger, "F001", 1, "r1", "boundary", "downgraded",
                  "--narrowed", "only for fr-CA")
    _refute_claim(tmp_path, ledger, "F001", 1, "r2", "reachability")
    assert _plan(tmp_path, ledger)["plan"]["rebut"] == [[{"claim": "F001", "finder": "finder"}]]
    _cut_claim(tmp_path, ledger, "F001", 2, "degraded")
    assert _plan_ids(_plan(tmp_path, ledger)["plan"]["rebut"]) == [["F001"]]
    _accept(tmp_path, ledger, "F001", 2)
    assert _plan(tmp_path, ledger)["plan"]["rebut"] == []


def test_bundled_steps_converged_cut_names_each_claims_agent(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "a", "b", "c", "d", "e")
    for claim in ("F001", "F002", "F003", "F004"):
        _escalate(tmp_path, ledger, claim)
    _cut_claim(tmp_path, ledger, "F001", 1, "degraded")
    _accept(tmp_path, ledger, "F001", 1)
    _cut_claim(tmp_path, ledger, "F002", 1, "degraded")
    _cut_claim(tmp_path, ledger, "F004", 1, "degraded")
    _ok(tmp_path, "rebut", "s1", "--dir", str(ledger), "--as", "finder", "--claim", "F004",
        "--stage", "cut", "--evidence", "the retry path is guarded")
    lines = _ok(tmp_path, "converged", "s1", "--dir", str(ledger), "--phase", "cut",
                code=1).stdout.splitlines()
    step = lines[-1]
    assert step.startswith("next: ")
    assert "continue the refuters with F001" in step
    assert "continue each claim's finder to accept or rebut F002" in step
    assert "continue the cutter with F003, F004" in step
    assert "continue each claim's finder to escalate F005" in step


def _example(stderr: str) -> str:
    return next(line for line in stderr.splitlines() if line.startswith("example: "))


def test_bundled_angle_na_refusal_shows_the_form_for_its_phase(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "cache key ignores locale")
    find = _ok(tmp_path, "angle-na", "s1", "--dir", str(ledger), "--as", "finder", "--phase",
               "find", "--angle", "failure-path", "--reason", "no I/O", code=2)
    assert "--phase find --lens" in _example(find.stderr)
    refute = _ok(tmp_path, "angle-na", "s1", "--dir", str(ledger), "--as", "r1", "--phase",
                 "refute", "--angle", "boundary", "--reason", "no such path here", code=2)
    assert "--phase refute --claim" in _example(refute.stderr)


def test_bundled_angle_na_usage_refusal_follows_the_phase(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "cache key ignores locale")
    find = _ok(tmp_path, "angle-na", "s1", "--dir", str(ledger), "--as", "finder", "--phase",
               "find", "--lens", "correctness", "--angle", "failure-path", code=2)
    assert "--reason" in find.stderr and "--phase find --lens" in _example(find.stderr)


def test_bundled_steps_next_cut_round_waits_for_the_finder_answer(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _steps_slate(tmp_path, ledger, "cache key ignores locale")
    _escalate(tmp_path, ledger, "F001")
    _cut_claim(tmp_path, ledger, "F001", 1, "degraded")
    err = _cut_claim(tmp_path, ledger, "F001", 2, "degraded", code=2).stderr
    assert "cut: F001 round 1 awaits its finder; the finder must accept or rebut it first" in err
    _ok(tmp_path, "rebut", "s1", "--dir", str(ledger), "--as", "finder", "--claim", "F001",
        "--stage", "cut", "--evidence", "the retry path is guarded")
    _cut_claim(tmp_path, ledger, "F001", 2, "degraded")
