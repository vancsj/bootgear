"""Discover Gear and forward a plugin's native hook event."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path

SESSION_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
LOCK_TIMEOUT = 30
QUERY_TIMEOUT = 5
CODEX_REMOTE_MARKETPLACE = "openai-curated-remote"


def safe_session(value: object) -> str | None:
    """`value` when it is a session id that can name a store file, else None."""
    return value if isinstance(value, str) and SESSION_PATTERN.match(value) else None


def profile_root(host: str) -> Path:
    variable, default = ("CODEX_HOME", ".codex") if host == "codex" else ("CLAUDE_CONFIG_DIR", ".claude")
    configured = os.environ.get(variable)
    return Path(configured).expanduser().resolve() if configured else Path.home() / default


def _path_key(path: Path) -> str:
    return hashlib.sha256(os.fsencode(path.resolve())).hexdigest()[:24]


def store_path(host: str, session: str | None, activation: Path | None = None) -> Path:
    data = os.environ.get("XDG_DATA_HOME")
    base = Path(data).expanduser() / "bootgear" if data else Path.home() / ".bootgear"
    directory = base / "host-plugins" / host / _path_key(profile_root(host))
    if session:
        return directory / "sessions" / f"{session}.json"
    return directory / "projects" / f"{_path_key(activation or Path.cwd())}.json"


def _read_entry(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(document, dict) and isinstance(document.get("inventory"), (list, dict)):
        activation = document.get("activation")
        if isinstance(activation, str) and Path(activation).is_absolute():
            return document
    return None


def _write_entry(path: Path, inventory: object, activation: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump({"inventory": inventory, "activation": str(activation.resolve())}, output)
            output.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def write_profile_inventory(host: str, activation: Path, inventory: object) -> None:
    _write_entry(store_path(host, None, activation), inventory, activation)


def _query_inventory(command: list[str], cwd: Path | None = None) -> object:
    label = " ".join(command)
    try:
        result = subprocess.run(
            command, cwd=cwd, stdin=subprocess.DEVNULL,
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


def _codex_inventory(cwd: Path) -> object:
    command = ["codex", "plugin", "marketplace", "list", "--json"]
    listing = _query_inventory(command, cwd)
    marketplaces = listing.get("marketplaces") if isinstance(listing, dict) else None
    if not isinstance(marketplaces, list) or any(
        not isinstance(record, dict) or not isinstance(record.get("name"), str) or not record["name"]
        for record in marketplaces
    ):
        raise ValueError("codex plugin marketplace list --json returned an invalid marketplace list.")
    names = list(dict.fromkeys(record["name"] for record in marketplaces
                               if record["name"] != CODEX_REMOTE_MARKETPLACE))
    home = profile_root("codex")
    cache = home / "plugins" / "cache"
    if any(path.relative_to(cache).parts[0] not in names for path in cache.glob("*/*/*/gear.toml")
           if path.is_file()):
        return _query_inventory(["codex", "plugin", "list", "--json"], cwd)
    installed = []
    for name in names:
        command = ["codex", "plugin", "list", "--marketplace", name, "--json"]
        inventory = _query_inventory(command, cwd)
        records = inventory.get("installed") if isinstance(inventory, dict) else None
        if not isinstance(records, list):
            raise TypeError(f"{' '.join(command)} returned an invalid installed plugin list.")
        installed.extend(records)
    return {"installed": installed, "available": []}


@contextlib.contextmanager
def _inventory_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + LOCK_TIMEOUT
    with lock_path.open("a+b") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Inventory refresh is busy. Start a fresh host session.") from exc
                time.sleep(0.05)
        yield


def _local_claude_roots() -> dict[str, str]:
    path = profile_root("claude") / "plugins" / "known_marketplaces.json"
    try:
        marketplaces = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(marketplaces, dict):
        return {}
    roots = {}
    for marketplace, config in marketplaces.items():
        source = config.get("source") if isinstance(config, dict) else None
        if not isinstance(source, dict) or source.get("source") != "directory":
            continue
        location = config.get("installLocation")
        if not isinstance(location, str) or not Path(location).is_absolute():
            continue
        root = Path(location).resolve()
        try:
            catalog = json.loads((root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in catalog.get("plugins", []) if isinstance(catalog, dict) else ():
            name, relative = (entry.get("name"), entry.get("source")) if isinstance(entry, dict) else (None, None)
            if isinstance(name, str) and isinstance(relative, str) and not Path(relative).is_absolute():
                resolved = (root / relative).resolve()
                if resolved.is_relative_to(root):
                    roots[f"{name}@{marketplace}"] = str(resolved)
    return roots


def query_inventory(host: str, activation: Path) -> object:
    if host == "codex":
        inventory = _codex_inventory(activation)
        if not isinstance(inventory, dict) or not isinstance(inventory.get("installed"), list):
            raise ValueError("Codex returned an invalid installed plugin list.")
        return inventory
    inventory = _query_inventory(["claude", "plugin", "list", "--json"], activation)
    if not isinstance(inventory, list):
        raise TypeError("Claude returned an invalid installed plugin list.")
    roots = _local_claude_roots()
    return [{**record, "installPath": roots[record["id"]]}
            if isinstance(record, dict) and isinstance(record.get("id"), str) and record["id"] in roots
            else record for record in inventory]


@contextlib.contextmanager
def session_start_inventory(host: str, session: str, activation: Path, source: str) -> Iterator[object]:
    path = store_path(host, session)
    with _inventory_lock(path):
        if source in {"startup", "fork"} and (previous := _read_entry(path)):
            yield previous["inventory"]
            return
        path.unlink(missing_ok=True)
        inventory = query_inventory(host, activation)
        _write_entry(path, inventory, activation)
        yield inventory


def host_inventory(host: str, session: str | None, *, refresh: bool = False) -> tuple[object, bool]:
    key = safe_session(session)
    activation = Path(os.environ.get("GEAR_CALLER_CWD") or Path.cwd()).resolve()
    path = store_path(host, key, activation)
    previous = _read_entry(path)
    if refresh and os.environ.get("BOOTGEAR_HOOK_ACTIVE") != "1":
        if key:
            if not previous:
                raise RuntimeError("Session inventory is missing. Start a fresh host session.")
            with session_start_inventory(host, key, Path(previous["activation"]), "resume") as inventory:
                return inventory, False
        inventory = query_inventory(host, activation)
        write_profile_inventory(host, activation, inventory)
        return inventory, False
    if previous:
        return previous["inventory"], True
    if key:
        raise RuntimeError("Session inventory is missing. Start a fresh host session.")
    raise RuntimeError(f"Plugin inventory is missing. Run gear --host {host} reconcile, then retry.")


def applies_to(record: dict, activation: Path) -> bool:
    project = record.get("projectPath")
    if record.get("scope") in {"project", "local"} and not isinstance(project, str):
        return False
    return not project or (isinstance(project, str) and activation.is_relative_to(Path(project).resolve()))


def inventory_activation(host: str, session: str | None, default: Path) -> Path:
    entry = _read_entry(store_path(host, safe_session(session), default))
    return Path(entry["activation"]) if entry else default


def codex_cache_root(record: dict) -> Path | None:
    """The Codex cache folder of an installed plugin record; None when its identity is incomplete."""
    values = [record.get(key) for key in ("marketplaceName", "name", "version")]
    if not all(isinstance(value, str) and value and value not in {".", ".."}
               and "/" not in value and "\\" not in value for value in values):
        return None
    home = profile_root("codex")
    return home.joinpath("plugins", "cache", *(str(value) for value in values))


def _cli_gear(host: str, inventory: object, activation: Path) -> Path | None:
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
            if not applies_to(record, activation) or str(record.get("id", "")).split("@")[0] != "cli":
                continue
            location = record.get("installPath")
            if not isinstance(location, str):
                continue
            candidate = Path(location) / "bin" / "gear"
        else:
            installed = codex_cache_root(record) if record.get("name") == "cli" and record.get("installed", True) else None
            if installed is None:
                continue
            candidate = installed / "bin" / "gear"
        if candidate.is_file():
            return candidate
    return None


def _find_gear(root: Path, host: str, plugin: str, inventory: object, activation: Path) -> Path | None:
    for ancestor in root.parents:
        candidate = ancestor / "plugins" / "cli" / "bin" / "gear"
        if candidate.is_file():
            return candidate
    if plugin == "cli" and (root / "bin" / "gear").is_file():
        return root / "bin" / "gear"
    return _cli_gear(host, inventory, activation)


def _event(payload: bytes) -> dict:
    try:
        event = json.loads(payload)
    except ValueError:
        return {}
    return event if isinstance(event, dict) else {}


def _activation(host: str, live: Path) -> Path:
    project = os.environ.get("CLAUDE_PROJECT_DIR") if host == "claude" else None
    return Path(project).resolve() if project and Path(project).is_absolute() else live


@contextlib.contextmanager
def _hook_inventory(host: str, session: str, event: dict, activation: Path) -> Iterator[object]:
    if event.get("hook_event_name") == "SessionStart":
        with session_start_inventory(host, session, activation, event.get("source", "startup")) as inventory:
            yield inventory
    else:
        yield host_inventory(host, session)[0]


def _forward(args: argparse.Namespace, root: Path, payload: bytes) -> subprocess.CompletedProcess:
    plugin = tomllib.loads((root / "gear.toml").read_text())["plugin"]["name"]
    event = _event(payload)
    session = safe_session(event.get("session_id"))
    if not session:
        raise RuntimeError("Session id is missing. Start a fresh host session.")
    cwd = event.get("cwd")
    live = Path(cwd).resolve() if isinstance(cwd, str) and Path(cwd).is_absolute() else Path.cwd()
    activation = _activation(args.host, live)
    with _hook_inventory(args.host, session, event, activation) as inventory:
        activation = inventory_activation(args.host, session, activation)
        gear = _find_gear(root, args.host, plugin, inventory, activation)
        if gear is None:
            raise RuntimeError("The shared CLI plugin is missing.")
        env = {**os.environ, "BOOTGEAR_SESSION_ID": session, "BOOTGEAR_HOOK_ACTIVE": "1",
               "GEAR_CALLER_CWD": str(live)}
        return subprocess.run(
            [str(gear), "--host", args.host, plugin, args.command, *args.arguments],
            input=payload, capture_output=True, env=env, cwd=live, check=False,
        )


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
        result = _forward(args, root, payload)
        if result.returncode == 2 and b"Shared runtime" in result.stderr:
            return _remind(payload, result.stderr.decode(errors="replace").strip())
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        return result.returncode
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return _remind(payload, str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
