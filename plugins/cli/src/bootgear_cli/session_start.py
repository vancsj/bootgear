"""Refresh the stored host plugin list of the session that starts or resumes."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys

from bootgear_cli import hook_loader


def main() -> int:
    """Query the host once and rewrite the session's entry. A query, store or payload
    failure prints nothing and exits 0."""
    with contextlib.suppress(OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired):
        payload = json.loads(sys.stdin.buffer.read())
        host = os.environ.get("BOOTGEAR_HOST")
        session = hook_loader.safe_session(payload.get("session_id")) if isinstance(payload, dict) else None
        if host in {"claude", "codex"} and session:
            hook_loader.host_inventory(host, session, refresh=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
