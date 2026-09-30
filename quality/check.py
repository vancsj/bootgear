#!/usr/bin/env python3
"""Run the repository's locked Python quality checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOT = REPOSITORY_ROOT / "quality"
BASELINE_PATH = QUALITY_ROOT / "baseline.json"
IDENTITY_PATHS = (
    QUALITY_ROOT / "pyproject.toml",
    QUALITY_ROOT / "uv.lock",
    QUALITY_ROOT / "ruff.toml",
    QUALITY_ROOT / "pyrightconfig.json",
)
TEMP_PATH_PATTERN = re.compile(
    r"(?:(?:/private)?/var/folders|/private/tmp|/tmp)/[^\s:]+"
)


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class Result:
    check: Check
    returncode: int
    output: str
    fingerprint: str


CHECKS = (
    Check(
        "skill-reference-contract",
        ("python", "quality/check_skill_references.py"),
    ),
    Check(
        "content",
        ("python", "quality/check_content.py"),
    ),
    Check(
        "ruff",
        (
            "ruff",
            "check",
            "--config",
            "quality/ruff.toml",
            "cli",
            "plugins/engine",
            "plugins/converge",
            "plugins/review",
            "codex-plugins/engine",
        ),
    ),
    Check(
        "basedpyright",
        ("basedpyright", "--project", "quality/pyrightconfig.json"),
    ),
    Check(
        "pytest-cli",
        ("python", "-m", "pytest", "cli/tests"),
    ),
    Check(
        "pytest-quality",
        ("python", "-m", "pytest", "quality/tests"),
    ),
    Check(
        "pytest-plugins",
        ("python", "-m", "pytest", "-n", "auto", "plugins/engine/tests"),
    ),
    Check(
        "pytest-converge",
        ("python", "-m", "pytest", "-n", "auto", "plugins/converge/tests"),
    ),
    Check(
        "pytest-review",
        ("python", "-m", "pytest", "plugins/review/tests"),
    ),
    Check(
        "pytest-codex",
        ("python", "-m", "pytest", "-n", "auto", "codex-plugins/engine/tests"),
    ),
    Check(
        "pytest-memory-ledger",
        ("python", "-m", "pytest", "plugins/memory-ledger/tests"),
    ),
    Check(
        "pytest-advisor",
        ("python", "-m", "pytest", "plugins/advisor/tests"),
    ),
)


def _identity() -> str:
    digest = hashlib.sha256()
    for path in IDENTITY_PATHS:
        digest.update(path.name.encode())
        digest.update(b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _normalise(output: str) -> str:
    output = output.replace(str(REPOSITORY_ROOT), "<repo>")
    output = output.replace(str(Path(tempfile.gettempdir())), "<tmp>")
    output = TEMP_PATH_PATTERN.sub("<tmp>", output)
    return output


def _fingerprint(output: str) -> str:
    return hashlib.sha256(_normalise(output).encode()).hexdigest()


def _load_baseline(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read baseline {path}: {exc}") from exc
    failures = document.get("failures")
    if not isinstance(failures, list):
        raise ValueError(f"{path}: failures must be a list")
    return failures


def _run_checks(
    execute: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Result]:
    def run_one(check: Check) -> Result:
        try:
            completed = execute(
                check.command,
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            output = f"{completed.stdout}{completed.stderr}"
            returncode = completed.returncode
        except OSError as exc:
            output = f"{type(exc).__name__}: {exc}"
            returncode = 127
        return Result(check, returncode, output, _fingerprint(output))

    # Checks are independent subprocesses; run them together, report in CHECKS order.
    with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
        return list(pool.map(run_one, CHECKS))


def _report(results: Sequence[Result], baseline: Sequence[dict[str, str]]) -> int:
    identity = _identity()
    baseline_keys = {
        (entry.get("check"), entry.get("fingerprint"))
        for entry in baseline
        if entry.get("identity") == identity
    }
    stale = [entry for entry in baseline if entry.get("identity") != identity]
    failures = 0

    for result in results:
        if result.returncode == 0:
            print(f"PASS {result.check.name}")
            continue
        key = (result.check.name, result.fingerprint)
        if key in baseline_keys:
            print(f"BASELINE {result.check.name}: {_normalise(result.output).strip()}")
        else:
            failures += 1
            print(f"NEW {result.check.name}: {_normalise(result.output).strip()}")

    if stale:
        failures += len(stale)
        print(f"STALE-BASELINE {len(stale)} entr{'y' if len(stale) == 1 else 'ies'}")
    return failures


def main() -> int:
    if Path.cwd().resolve() != REPOSITORY_ROOT:
        print(f"quality check must run from {REPOSITORY_ROOT}", file=sys.stderr)
        return 2
    try:
        baseline = _load_baseline(BASELINE_PATH)
        failures = _report(_run_checks(), baseline)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
