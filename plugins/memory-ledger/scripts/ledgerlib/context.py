"""Invocation context supplied by a host adapter or the standalone CLI."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from bootgear_cli import clikit


@dataclass(frozen=True)
class InvocationContext:
    cwd: Path
    host: str = "standalone"
    session_id: str | None = None
    repo: str | None = None
    ref: str | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        host: str | None = None,
        session_id: str | None = None,
    ) -> InvocationContext:
        caller = (os.environ.get("MEMORY_LEDGER_CWD")
                  or os.environ.get("GEAR_CALLER_CWD")
                  or str(Path.cwd()))
        resolved_host = clikit.host(host)
        return cls(Path(caller).expanduser().resolve(), resolved_host or "standalone",
                   clikit.session_id(session_id, host=resolved_host))

    def with_scope(self, *, repo: str | None = None, ref: str | None = None) -> InvocationContext:
        return replace(self, repo=repo, ref=ref)


def contextual_path(value: str | Path, context: InvocationContext | None = None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    base = context.cwd if context is not None else Path.cwd()
    return base / path
