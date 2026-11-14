"""Prepare declared sibling plugins during explicit setup."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import deque
from pathlib import Path

from bootgear_cli import clikit, gear

PLUGIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class DependencySetupError(Exception):
    """A required plugin could not be prepared."""


def _manifest(root: Path) -> dict:
    path = root / ".claude-plugin" / "plugin.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DependencySetupError(f"Could not read {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise DependencySetupError(f"{path}: plugin manifest must be an object.")
    return document


def _installed(host: str) -> dict[str, Path]:
    root = Path(os.environ.get("GEAR_ROOT", str(gear.DEFAULT_ROOT)))
    try:
        roots, _, _ = gear._host_plugin_roots(root, refresh=True, strict=True, host=host)
    except gear.GearError as exc:
        raise DependencySetupError(str(exc)) from exc
    plugins: dict[str, Path] = {}
    for installed in roots:
        if not (installed / ".claude-plugin" / "plugin.json").is_file():
            continue
        name = _manifest(installed).get("name")
        if isinstance(name, str):
            plugins[name] = installed
    return plugins


def _install(name: str) -> None:
    command = ["codex", "plugin", "add", f"{name}@bootgear"]
    label = " ".join(command)
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DependencySetupError(f"{label} failed: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise DependencySetupError(f"{label} failed: {detail}")


def prepare(target: str) -> tuple[str, ...]:
    """Verify the installed target and prepare its transitive declared dependencies."""
    if not PLUGIN_NAME.fullmatch(target):
        raise DependencySetupError(f"Invalid plugin name: {target!r}.")
    host = clikit.host()
    if host not in {"claude", "codex"}:
        raise DependencySetupError("Select a host with Gear --host claude or --host codex, then retry setup.")
    if shutil.which(host) is None:
        raise DependencySetupError(f"{host} is missing. Install the host CLI, then retry setup.")
    plugins = _installed(host)
    if target not in plugins:
        raise DependencySetupError(f"Plugin {target!r} has no enabled installed root. Install it through {host}, then retry setup.")
    pending = deque([target])
    visited: set[str] = set()
    missing: set[str] = set()
    while pending:
        name = pending.popleft()
        if name in visited:
            continue
        visited.add(name)
        if name not in plugins:
            if host == "claude":
                missing.add(name)
                continue
            _install(name)
            plugins = _installed(host)
            if name not in plugins:
                raise DependencySetupError(f"Plugin {name!r} has no enabled installed root after installation. Enable it through Codex, then retry setup.")
        path = plugins[name]
        dependencies = _manifest(path).get("dependencies", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(dependency, str) or not PLUGIN_NAME.fullmatch(dependency)
            for dependency in dependencies
        ):
            raise DependencySetupError(f"{path / '.claude-plugin' / 'plugin.json'}: dependencies must contain Bootgear plugin names.")
        pending.extend(dependencies)
    if missing:
        raise DependencySetupError(f"Required plugins have no enabled installed root: {', '.join(sorted(missing))}. Complete native Claude dependency installation, then retry setup.")
    return tuple(sorted(visited))
