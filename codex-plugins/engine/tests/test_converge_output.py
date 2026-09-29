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
