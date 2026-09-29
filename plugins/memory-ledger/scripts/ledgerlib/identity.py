"""Host-aware signer identity validation."""
from __future__ import annotations

import os
import re
import sys

from .context import InvocationContext

_CODEX_SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _fail(message: str) -> None:
    sys.exit(f"invalid signer identity: {message}")


def validate_codex_session_id(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        _fail("Codex session_id is required")
    if value != value.strip():
        _fail("Codex session_id must not have surrounding whitespace")
    if any(ord(char) < 32 or ord(char) == 127 or char.isspace() for char in value):
        _fail("Codex session_id contains whitespace or a control character")
    if "/" in value or "\\" in value:
        _fail("Codex session_id must not contain a path separator")
    if not _CODEX_SESSION_RE.fullmatch(value):
        _fail("Codex session_id contains an unsafe character")
    return value


def resolve_identity(context: InvocationContext | None = None,
                     explicit: str | None = None) -> str:
    context = context or InvocationContext.from_environment()
    if context.host == "codex":
        session_id = validate_codex_session_id(context.session_id)
        expected = f"codex:{session_id}"
        if explicit is not None and explicit != expected:
            _fail(f"--as {explicit!r} conflicts with the Codex session identity {expected!r}")
        return expected
    if explicit:
        return explicit
    if context.host == "claude":
        session_id = context.session_id or os.environ.get("CLAUDE_CODE_SESSION_ID")
        if not session_id:
            sys.exit("no signer: CLAUDE_CODE_SESSION_ID unset — pass --as <id> to say "
                     "which session ran the evidence")
        return session_id.split("-")[0]
    if context.session_id:
        return context.session_id
    sys.exit("no signer: session identity unset — pass --as <id> or a host session id")


def live_identity(context: InvocationContext | None = None) -> str | None:
    context = context or InvocationContext.from_environment()
    if context.host in {"claude", "codex"}:
        return resolve_identity(context)
    return None
