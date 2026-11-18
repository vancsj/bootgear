from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GEAR = REPO / "plugins/cli/bin/gear"
QUESTION = "When should Engine runs start the Codex advisor?"
CLAIM = "Start the Codex advisor on first use."
NEW_CLAIM = "Start the Codex advisor during clarification."


def git(root: Path, *argv: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *argv], text=True).strip()


@pytest.fixture(params=("claude", "codex"))
def deputy(request, tmp_path):
    root = tmp_path / "deputy"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Deputy Fixture")
    git(root, "config", "user.email", "deputy@example.test")
    with (root / ".git" / "info" / "exclude").open("a") as ignore:
        ignore.write("\n.ledger-cache.json\n")
    env = {key: val for key, val in os.environ.items() if key not in {
        "BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID",
        "GEAR_CALLER_CWD",
    }}
    env["BOOTGEAR_OUTPUT"] = "prose"

    def command(route, *args):
        return subprocess.run(
            [str(GEAR), "--host", request.param, "--root", str(REPO),
             *route, "--deputy-root", str(root), *args],
            cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=60,
        )
    def call(*args):
        return command(("deputy", "deputy"), *args)

    def ledger(*args):
        return command(("memory-ledger", "ledger"), *args)

    return root, call, ledger


def record(call, claim=CLAIM, *args, confirmed=True):
    consent = ["--confirmed-by-user"] if confirmed else []
    return call("record", "--question", QUESTION, "--claim", claim, *args, *consent)


def test_confirmed_decision_is_saved_once_without_session_or_evidence(deputy):
    root, call, _ = deputy
    refusal = record(call, confirmed=False)
    assert refusal.returncode != 0
    assert "--confirmed-by-user" in refusal.stderr
    assert not list(root.rglob("*.md"))

    result = record(call)
    assert result.returncode == 0, result.stdout + result.stderr
    entry, = root.rglob("*.md")
    content = entry.read_text()
    assert "conf 1.00 · asserted" in content
    assert "Because: The user confirmed this canonical decision." in content
    assert "Evidence:" not in content
    assert git(root, "rev-list", "--count", "HEAD") == "1"
    assert record(call).returncode == 0
    assert git(root, "rev-list", "--count", "HEAD") == "1"
    assert CLAIM in call("candidates", QUESTION).stdout

    index = call("index")
    assert index.returncode == 0, index.stderr
    assert QUESTION in index.stdout


@pytest.mark.parametrize(("question", "claim"), [
    ("Which base branch should PR #1245 use?", "Use the release branch."),
    ("Which base branch should this pull request use?", "Use the release branch."),
    ("Should checks continue for this ticket?", "Continue the checks."),
    ("Should tangent 59 continue past 03:55?", "Continue the checks."),
    ("Should the current session stop at 03:55?", "Stop at 03:55."),
    ("Should the current session stop at 03:55 UTC?", "Stop at 03:55 UTC."),
    ("Should the current session continue past 03:55?", "Continue the checks."),
    ("Should the current session stop now?", "Stop the checks."),
    (QUESTION, "Use fix/current-ticket."),
])
def test_refuses_run_specific_preferences(deputy, question, claim):
    root, call, _ = deputy

    result = call("record", "--question", question, "--claim", claim, "--confirmed-by-user")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "run-specific scope" in result.stderr
    assert not list(root.rglob("*.md"))


@pytest.mark.parametrize(("question", "claim"), [
    ("Which date should legacy records use by default?", "Use 1970-01-01."),
    ("When should scheduled backups stop?", "Stop at 17:00 each weekday."),
    ("When should contributors update ticket status?", "Update the current ticket before handing off."),
    ("When should Engine stop after repeated check failures?", "Stop the current run after two failed checks."),
])
def test_accepts_recurring_preferences(deputy, question, claim):
    root, call, _ = deputy
    args = ("record", "--question", question, "--claim", claim, "--confirmed-by-user")

    result = call(*args)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ASSERTED" in result.stdout
    assert call(*args).returncode == 0
    assert git(root, "rev-list", "--count", "HEAD") == "1"


def test_changing_a_preference_requires_the_current_assertion_id(deputy):
    root, call, _ = deputy
    initial = record(call)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    entry, = root.rglob("*.md")
    slug = str(entry.relative_to(root).with_suffix(""))
    before = entry.read_bytes()
    for args in ((), ("--replace", "a9", "--previous-claim", CLAIM),
                 ("--replace", "a1", "--previous-claim", NEW_CLAIM)):
        conflict = record(call, NEW_CLAIM, "--entry", slug, *args)
        assert conflict.returncode != 0
        assert entry.read_bytes() == before
    result = record(call, NEW_CLAIM, "--entry", slug, "--replace", "a1", "--previous-claim", CLAIM)
    assert result.returncode == 0, result.stdout + result.stderr
    assert NEW_CLAIM in call("candidates", QUESTION).stdout
    assert entry.read_text().count("conf 1.00 · asserted") == 1
    assert git(root, "rev-list", "--count", "HEAD") == "2"


def test_failed_commit_can_be_retried_without_duplicate_entry(deputy):
    root, call, _ = deputy
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho fixture-commit-refusal >&2\nexit 1\n")
    hook.chmod(0o700)
    stopped = record(call)
    assert stopped.returncode != 0
    assert "fixture-commit-refusal" in stopped.stderr
    assert CLAIM in call("candidates", QUESTION).stdout
    hook.unlink()
    entry, = root.rglob("*.md")
    slug = str(entry.relative_to(root).with_suffix(""))
    replacement = record(call, NEW_CLAIM, "--entry", slug, "--replace", "a1", "--previous-claim", CLAIM)
    assert replacement.returncode != 0
    assert "pending changes" in replacement.stderr
    assert CLAIM in entry.read_text()

    result = record(call)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(root, "rev-list", "--count", "HEAD") == "1"
    assert len(list(root.rglob("*.md"))) == 1
    assert git(root, "status", "--short") == ""


def test_assertion_index_includes_entries_the_ranked_look_up_omits(deputy):
    _, call, _ = deputy
    assert record(call).returncode == 0
    alternate = "When should Engine runs start the Claude advisor?"
    first = call("record", "--question", alternate, "--claim", "Start the Claude advisor on first use.",
                 "--confirmed-by-user")
    assert first.returncode == 0, first.stderr

    ranked = call("candidates", QUESTION, "--limit", "1")
    assert alternate not in ranked.stdout
    assert "CUT" in ranked.stdout
    index = call("index", "--asserted")
    assert index.returncode == 0, index.stderr
    assert alternate in index.stdout


def test_reuses_a_legacy_question_and_answer_without_losing_evidence(deputy):
    root, call, ledger = deputy
    legacy = root / "decisions" / "advisor"
    legacy.parent.mkdir()
    entry = legacy.with_suffix(".md")
    entry.write_text(
        '# decisions/advisor\nQ: When should we start the advisor?\n\n'
        '## a1 · Start the Codex advisor on first use. conf 0.30 · checked 2026-01-01\n'
        'Because: The run only needs a listener when work starts.\nEvidence: true\n',
    )
    assert "[unconfirmed]" in call("candidates", "decisions/advisor", "--limit", "1").stdout
    result = call("record", "--question", "When should we start the advisor?", "--claim", CLAIM,
                  "--entry", "decisions/advisor", "--confirmed-by-user")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ASSERTED decisions/advisor a1"
    assert "Evidence: true" in entry.read_text()
    assert len(list(root.rglob("*.md"))) == 1
    target = ("--question", "When should we start the advisor?", "--entry", "decisions/advisor",
              "--confirmed-by-user")
    next_result = call("record", "--claim", NEW_CLAIM, *target,
                       "--replace", "a1", "--previous-claim", CLAIM)
    assert next_result.returncode == 0, next_result.stderr
    restored = call("record", "--claim", CLAIM, *target,
                    "--replace", "a2", "--previous-claim", NEW_CLAIM)
    assert restored.returncode == 0, restored.stderr
    assert restored.stdout.strip() == "ASSERTED decisions/advisor a1"
    assert entry.read_text().count(CLAIM) == 1
    assert "Evidence: true" in entry.read_text()
    assert ledger("assert", "decisions/advisor", "a1", "--only", "deputy", "--clear").returncode == 0


def test_clear_refuses_an_evidence_free_assertion_without_changing_it(deputy):
    root, call, ledger = deputy
    assert record(call).returncode == 0
    entry, = root.rglob("*.md")
    before = entry.read_bytes()
    slug = str(entry.relative_to(root).with_suffix(""))
    lint = ledger("lint", "--only", "deputy")
    assert "NO-EVIDENCE" not in lint.stdout
    refusal = ledger("assert", slug, "a1", "--only", "deputy", "--clear")
    assert refusal.returncode != 0
    assert "evidence-free assertion" in refusal.stderr
    assert entry.read_bytes() == before
