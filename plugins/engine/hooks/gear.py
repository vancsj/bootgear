"""Discover Gear and forward a plugin's native hook event."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

SESSION_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
STORE_MAX_AGE = 7 * 24 * 60 * 60
QUERY_TIMEOUT = 5
CODEX_REMOTE_MARKETPLACE = "openai-curated-remote"


def safe_session(value: object) -> str | None:
    """`value` when it is a session id that can name a store file, else None."""
    return value if isinstance(value, str) and SESSION_PATTERN.match(value) else None


def store_path(host: str, session: str) -> Path:
    """The store entry of one host session under the bootgear data root."""
    data = os.environ.get("XDG_DATA_HOME")
    base = Path(data).expanduser() / "bootgear" if data else Path.home() / ".bootgear"
    return base / "host-plugins" / host / f"{session}.json"


def _read_entry(path: Path) -> tuple[bool, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    if isinstance(document, dict) and isinstance(document.get("inventory"), (list, dict)):
        return True, document["inventory"]
    return False, None


def _write_entry(path: Path, inventory: object) -> None:
    """Replace the entry in one step, then prune old entries; failures are ignored."""
    try:
        path.parent.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.mkdir(exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    except OSError:
        return
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"inventory": inventory}, stream)
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        return
    cutoff = time.time() - STORE_MAX_AGE
    with contextlib.suppress(OSError):
        for entry in path.parent.iterdir():
            with contextlib.suppress(OSError):
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink()


def _query_inventory(command: list[str]) -> object:
    label = " ".join(command)
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=QUERY_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not query {label}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"{label} failed: {detail}")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError(f"{label} returned invalid JSON: {exc}") from exc


def _codex_inventory() -> object:
    command = ["codex", "plugin", "marketplace", "list", "--json"]
    listing = _query_inventory(command)
    marketplaces = listing.get("marketplaces") if isinstance(listing, dict) else None
    if not isinstance(marketplaces, list) or any(
        not isinstance(record, dict) or not isinstance(record.get("name"), str) or not record["name"]
        for record in marketplaces
    ):
        raise ValueError("codex plugin marketplace list --json returned an invalid marketplace list.")
    names = list(dict.fromkeys(record["name"] for record in marketplaces
                               if record["name"] != CODEX_REMOTE_MARKETPLACE))
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    cache = home / "plugins" / "cache"
    if any(path.relative_to(cache).parts[0] not in names for path in cache.glob("*/*/*/gear.toml")
           if path.is_file()):
        return _query_inventory(["codex", "plugin", "list", "--json"])
    installed = []
    for name in names:
        command = ["codex", "plugin", "list", "--marketplace", name, "--json"]
        inventory = _query_inventory(command)
        records = inventory.get("installed") if isinstance(inventory, dict) else None
        if not isinstance(records, list):
            raise TypeError(f"{' '.join(command)} returned an invalid installed plugin list.")
        installed.extend(records)
    return {"installed": installed, "available": []}


def host_inventory(host: str, session: str | None, *, refresh: bool = False) -> tuple[object, bool]:
    """The host's installed plugin data, and True when it came from the session store.

    Without `refresh`, a valid stored entry wins. Otherwise query the host, then store the
    result when `session` is safe. Raises RuntimeError, TypeError or ValueError that names the host
    command when the query fails, cannot run, times out, or prints invalid JSON."""
    key = safe_session(session)
    path = store_path(host, key) if key else None
    if path is not None and not refresh:
        found, inventory = _read_entry(path)
        if found:
            return inventory, True
    inventory = (_codex_inventory() if host == "codex"
                 else _query_inventory([host, "plugin", "list", "--json"]))
    if path is not None:
        _write_entry(path, inventory)
    return inventory, False


def codex_cache_root(record: dict) -> Path | None:
    """The Codex cache folder of an installed plugin record; None when its identity is incomplete."""
    values = [record.get(key) for key in ("marketplaceName", "name", "version")]
    if not all(isinstance(value, str) and value and value not in {".", ".."}
               and "/" not in value and "\\" not in value for value in values):
        return None
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    return home.joinpath("plugins", "cache", *(str(value) for value in values))


def _cli_gear(host: str, inventory: object) -> Path | None:
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
            installed = codex_cache_root(record) if record.get("name") == "cli" else None
            if installed is None:
                continue
            candidate = installed / "bin" / "gear"
        if candidate.is_file():
            return candidate
    return None


def _find_gear(root: Path, host: str, plugin: str, session: str | None) -> Path | None:
    for ancestor in root.parents:
        candidate = ancestor / "plugins" / "cli" / "bin" / "gear"
        if candidate.is_file():
            return candidate
    if plugin == "cli" and (root / "bin" / "gear").is_file():
        return root / "bin" / "gear"
    inventory, stored = host_inventory(host, session)
    gear = _cli_gear(host, inventory)
    if gear is None and stored:
        gear = _cli_gear(host, host_inventory(host, session, refresh=True)[0])
    return gear


def _payload_session(payload: bytes) -> str | None:
    try:
        event = json.loads(payload)
    except ValueError:
        return None
    return safe_session(event.get("session_id")) if isinstance(event, dict) else None


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
        plugin = tomllib.loads((root / "gear.toml").read_text())["plugin"]["name"]
        session = _payload_session(payload)
        gear = _find_gear(root, args.host, plugin, session)
        if gear is None:
            return _remind(payload, "The shared CLI plugin is missing.")
        env = {**os.environ, **({"BOOTGEAR_SESSION_ID": session} if session else {})}
        result = subprocess.run(
            [str(gear), "--host", args.host, plugin, args.command, *args.arguments],
            input=payload, capture_output=True, env=env, check=False,
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
