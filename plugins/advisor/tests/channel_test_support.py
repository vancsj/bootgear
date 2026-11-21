from __future__ import annotations

import fcntl
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
CHANNEL = PLUGIN / "skills" / "advisor" / "scripts" / "channel.py"
GEAR = REPO / "plugins" / "cli" / "bin" / "gear"

# The suite parses JSON; OutputModeTests clears this to see the prose default.
os.environ["BOOTGEAR_OUTPUT"] = "json"

sys.path.insert(0, str(CHANNEL.parent))
import channel as channel_module  # pyright: ignore[reportMissingImports]
import channel_liveness
import channel_messages
import channel_output
import channel_seats
import channel_store
from bootgear_cli import clikit

GEAR_PREFIX = shlex.split(clikit.current_program("advisor", "channel"))


SESSION_ENV = ("BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID")


def run(root: Path, *args: str, timeout: float | None = None, output: str = "--json",
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run `channel.py` with no session variables from the caller's shell, then `env`; tests pass
    `--session` or a session variable in `env` when they need one."""
    env = {**{k: v for k, v in os.environ.items() if k not in SESSION_ENV}, **(env or {})}
    return subprocess.run(
        [sys.executable, str(CHANNEL), "--root", str(root), *args, *([output] if output else [])],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def channel_json(root: Path, channel: str = "0001") -> Path:
    return root / "channels" / channel / "channel.json"


def age_seat(root: Path, role: str, seconds: float, channel: str = "0001") -> None:
    path = channel_json(root, channel)
    record = json.loads(path.read_text())
    record[f"{role}_seen_at"] -= seconds
    path.write_text(json.dumps(record))


def age_updated_at(root: Path, seconds: float, channel: str = "0001") -> None:
    path = channel_json(root, channel)
    record = json.loads(path.read_text())
    record["updated_at"] -= seconds
    path.write_text(json.dumps(record))


def rewrite_record(root: Path, content: str, channel: str = "0001") -> None:
    """Replace channel.json under the channel lock, as channel.py's own writers do."""
    lock = channel_store.channel_lock(channel_json(root, channel).parent)
    try:
        channel_store.atomic_write(channel_json(root, channel), content)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def seen_at(root: Path, role: str, channel: str = "0001") -> float:
    return float(json.loads(channel_json(root, channel).read_text())[f"{role}_seen_at"])


def wait_until(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def restart_until(root: Path, role: str, channel: str = "0001") -> object:
    return json.loads(channel_json(root, channel).read_text()).get(f"{role}_restart_until")


def set_fields(root: Path, channel: str = "0001", **fields: object) -> None:
    path = channel_json(root, channel)
    record = json.loads(path.read_text())
    record.update(fields)
    rewrite_record(root, json.dumps(record), channel)


def quoted_command(text: str) -> str:
    """The command a `next` quotes between backticks."""
    return text.split("`")[1]


def root_variants() -> list[tuple[str, list[str], dict[str, str], Path]]:
    """(label, root flag, env, resolved root) for the default, an explicit and a relative `--root`."""
    fake_home = Path(tempfile.mkdtemp(prefix="advisor-test-home-"))
    caller = Path(tempfile.mkdtemp(prefix="advisor-test-caller-"))
    explicit = Path(tempfile.mkdtemp(prefix="advisor-test-")) / "a root"
    base = {k: v for k, v in os.environ.items() if k != "BOOTGEAR_ADVISOR_DIR"}
    return [
        ("default", [], {**base, "HOME": str(fake_home)}, fake_home / ".bootgear" / "advisor"),
        ("explicit", ["--root", str(explicit)], base, explicit),
        ("relative", ["--root", "mbox"], {**base, "GEAR_CALLER_CWD": str(caller)}, caller / "mbox"),
    ]


def run_in(root_flag: list[str], env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHANNEL), *root_flag, *args],
                          capture_output=True, text=True, check=False, env=env)


def write_channel(root: Path, channel: str, **fields: object) -> Path:
    """A channel directory whose channel.json holds a fresh open record plus `fields`."""
    path = root / "channels" / channel
    (path / "messages").mkdir(parents=True, exist_ok=True)
    now = time.time()
    record = {"channel": channel, "created_at": now, "updated_at": now, "state": "waiting",
              "listener_owner": None, "asker_owner": None, **fields}
    (path / "channel.json").write_text(json.dumps(record))
    return path

__all__ = ['channel_liveness', 'channel_messages', 'channel_module', 'channel_output', 'channel_seats', 'channel_store', 'clikit']
