#!/usr/bin/env python3
"""Run canonical host-adapter fixtures through an installed-style wrapper."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "host_adapter" / "cases.json"
PLUGIN_ROOTS = {
    "claude": REPO_ROOT / "plugins" / "engine",
    "codex": REPO_ROOT / "codex-plugins" / "engine",
}


def _run(case: dict, home: Path) -> None:
    host = case["host"]
    plugin_root = PLUGIN_ROOTS[host]
    wrapper = plugin_root / "hooks" / "adapter.py"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT" if host == "claude" else "PLUGIN_ROOT"] = str(plugin_root)
    for item in case.get("setup", {}).get("files", []):
        target = (home / item["path"]).resolve()
        target.relative_to(home.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["text"], encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="host-adapter-trace-") as trace_dir:
        trace_path = Path(trace_dir) / "trace.jsonl"
        env["BOOTGEAR_HOST_ADAPTER_TRACE_FILE"] = str(trace_path)
        result = subprocess.run(
            [
                sys.executable,
                str(wrapper),
                "--handler",
                case["handler"],
                "--matcher-pattern",
                case["matcher_pattern"],
            ],
            input=case.get("input_json", json.dumps(case.get("input", {}))),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        trace_rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    expected = case["expected"]
    assert result.returncode == expected["exit"], (case["name"], result.stderr)
    assert result.stdout == expected["stdout"], (case["name"], result.stdout)
    assert trace_rows and trace_rows[-1]["decision"] == expected["decision"], (
        case["name"],
        trace_rows,
    )
    if "stderr" in expected:
        assert result.stderr == expected["stderr"], (case["name"], result.stderr)
    else:
        assert expected["stderr_contains"] in result.stderr, (case["name"], result.stderr)
    if "marker" in expected:
        marker = expected["marker"]
        actual = json.loads((home / marker["path"]).read_text())
        for key, value in marker["contains"].items():
            assert actual.get(key) == value, (case["name"], key, actual)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=sorted(PLUGIN_ROOTS), required=True)
    parser.add_argument("--fixture", type=Path, default=FIXTURES)
    args = parser.parse_args()
    cases = json.loads(args.fixture.read_text())
    selected = [case for case in cases if case["host"] == args.host]
    for case in selected:
        with tempfile.TemporaryDirectory(prefix="host-adapter-home-") as home:
            _run(case, Path(home))
    print(f"host-adapter fixtures passed: {args.host} ({len(selected)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
