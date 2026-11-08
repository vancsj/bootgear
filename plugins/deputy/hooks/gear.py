"""Discover Gear and forward a plugin's native hook event."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def _inventory(host: str) -> object:
    result = subprocess.run(
        [host, "plugin", "list", "--json"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=5, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{host} inventory failed: exit {result.returncode}")
    return json.loads(result.stdout)


def _find_gear(root: Path, host: str) -> Path | None:
    for ancestor in root.parents:
        candidate = ancestor / "plugins" / "cli" / "bin" / "gear"
        if candidate.is_file() and (ancestor / "codex-plugins").is_dir():
            return candidate
    inventory = _inventory(host)
    if isinstance(inventory, list):
        records = inventory
    elif isinstance(inventory, dict):
        records = inventory.get("installed", [])
    else:
        raise TypeError(f"{host} returned an invalid plugin inventory.")
    if not isinstance(records, list):
        raise TypeError(f"{host} returned an invalid installed plugin list.")
    for record in records:
        if not isinstance(record, dict) or not record.get("enabled"):
            continue
        if host == "claude":
            if str(record.get("id", "")).split("@")[0] != "cli":
                continue
            location = record.get("installPath")
            if not isinstance(location, str):
                continue
            candidate = Path(location) / "bin" / "gear"
        else:
            if record.get("name") != "cli":
                continue
            values = [record.get(key) for key in ("marketplaceName", "name", "version")]
            if not all(isinstance(value, str) and value and value not in {".", ".."}
                       and "/" not in value and "\\" not in value for value in values):
                continue
            home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
            candidate = home.joinpath("plugins", "cache", *(str(value) for value in values), "bin", "gear")
        if candidate.is_file():
            return candidate
    return None


def _remind(payload: bytes, detail: str) -> int:
    try:
        event = json.loads(payload).get("hook_event_name", "SessionStart")
    except (ValueError, AttributeError):
        event = "SessionStart"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": f"Gear setup required: {detail} Invoke cli:setup, then retry.",
    }}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=("claude", "codex"))
    parser.add_argument("command")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    payload = sys.stdin.buffer.read()
    try:
        gear = _find_gear(root, args.host)
        if gear is None:
            return _remind(payload, "The shared CLI plugin is missing.")
        plugin = tomllib.loads((root / "gear.toml").read_text())["plugin"]["name"]
        result = subprocess.run(
            [str(gear), "--host", args.host, plugin, args.command, *args.arguments],
            input=payload, capture_output=True, check=False,
        )
        if result.returncode == 2 and b"Shared runtime" in result.stderr:
            return _remind(payload, result.stderr.decode(errors="replace").strip())
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        return result.returncode
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return _remind(payload, str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
