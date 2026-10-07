from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

TASK = Path(__file__).resolve().parents[1] / "scripts" / "converge"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(root / "home")}
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
