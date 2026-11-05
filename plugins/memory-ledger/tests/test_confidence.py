"""Confidence from independent verdicts through both host entrypoints."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SLUG = "tech/confidence"
Ledger = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture(params=("claude", "codex"))
def host(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def ledger(tmp_path: Path, host: str) -> Ledger:
    shared, local = tmp_path / "shared", tmp_path / "local"
    for root in (shared, local):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "home"
    home.mkdir()
    command = ([sys.executable, str(PLUGIN / "scripts" / "ledger.py")]
               if host == "claude" else [str(PLUGIN / "scripts" / "ledger")])
    env = {k: v for k, v in os.environ.items()
           if k not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "GEAR_CALLER_CWD")}
    env.update(HOME=str(home), BOOTGEAR_OUTPUT="prose")

    def run(*args: str, session: str = "author", code: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [*command, "--root", str(shared), "--local-root", str(local),
             "--host", host, "--session-id", session, *args],
            cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
        )
        assert result.returncode == code, result.stdout + result.stderr
        return result

    run("new", SLUG, "--local", "--q", "How much independent support exists?",
        "--claim", "Confidence counts independent verdicts.",
        "--because", "The author does not corroborate its own answer.", "--evidence", "true")
    return run


def test_failing_verifier_lowers_confidence(ledger: Ledger) -> None:
    result = ledger("sign", SLUG, "a1", "--fail", "--output", "Controlled opposing verdict.",
                    session="verifier")
    assert "conf 0.30 → 0.24" in result.stdout
    [answer] = json.loads(ledger("show", SLUG, "--data").stdout)["answers"]
    assert answer["conf"] == 0.24
    assert (answer["yes"], answer["no"], answer["independent"]) == (1, 1, 1)


def test_mixed_verdicts_match_the_documented_confidence(ledger: Ledger) -> None:
    for session in ("verifierone", "verifiertwo"):
        ledger("sign", SLUG, "a1", session=session)
    result = ledger("sign", SLUG, "a1", "--fail", "--output", "Controlled opposing verdict.",
                    session="verifierthree")
    assert "conf 0.79 → 0.63" in result.stdout
    [answer] = json.loads(ledger("show", SLUG, "--data").stdout)["answers"]
    assert answer["conf"] == 0.63
    assert (answer["yes"], answer["no"], answer["independent"]) == (3, 1, 3)
    for args in (("show", SLUG), ("list",), ("resolve", "How much independent support exists?")):
        assert "0.63" in ledger(*args).stdout
    assert "DRIFT" not in ledger("lint", code=1).stdout


def test_correcting_a_pass_to_a_failure_removes_its_support(ledger: Ledger) -> None:
    ledger("sign", SLUG, "a1", session="verifier")
    result = ledger("sign", SLUG, "a1", "--fail", "--output", "Controlled corrected verdict.",
                    session="verifier")
    assert "conf 0.61 → 0.24" in result.stdout
    [answer] = json.loads(ledger("show", SLUG, "--data").stdout)["answers"]
    assert answer["conf"] == 0.24
    assert (answer["yes"], answer["no"], answer["independent"]) == (1, 1, 1)


def test_author_correction_does_not_count_as_independent(ledger: Ledger) -> None:
    result = ledger("sign", SLUG, "a1", "--fail", "--output", "Controlled author correction.")
    assert "conf 0.30 → 0.30" in result.stdout
    [answer] = json.loads(ledger("show", SLUG, "--data").stdout)["answers"]
    assert answer["conf"] == 0.30
    assert (answer["yes"], answer["no"], answer["independent"]) == (0, 1, 0)


def test_refutation_penalizes_confidence(ledger: Ledger, host: str) -> None:
    for session in ("verifierone", "verifiertwo"):
        ledger("sign", SLUG, "a1", session=session)
    signer = "codex:verifierone" if host == "codex" else "verifierone"
    result = ledger("refute", SLUG, "a1", signer, "--output", "Controlled opposing verdict.",
                    session="refuter")
    assert "conf 0.63" in result.stdout
    [answer] = json.loads(ledger("show", SLUG, "--data").stdout)["answers"]
    assert answer["conf"] == 0.63
    assert (answer["yes"], answer["no"], answer["independent"]) == (3, 1, 3)
