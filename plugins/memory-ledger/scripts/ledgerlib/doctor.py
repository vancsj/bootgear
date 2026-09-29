"""`doctor`: is this machine able to run the ledger at all, and is it configured?

Setup calls this first and last. It exists so the dependency check is a command
with an exit code rather than a paragraph of prose a session reads and skips —
and so that "it is broken" arrives as a named cause instead of a traceback three
steps later.

Every check reports what it actually found, never just ok/fail: a version number,
a path, the config file it read. A check that only says "ok" cannot be argued
with when the thing it checked is wrong.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import config_candidates, load_config, resolve_roots
from .constants import DEFAULT_LOCAL_ROOT, DEFAULT_SHARED_ROOT, KINDS
from .context import InvocationContext

# Walrus assignments in the entry parser put the hard floor at 3.8. Reported
# rather than assumed: a session on an older interpreter gets a SyntaxError from
# an import, which names a file and a colon and not the actual problem.
MIN_PYTHON = (3, 8)

OK, WARN, FAIL = "ok  ", "warn", "FAIL"


def _row(state, label, detail, rows=None):
    if rows is None:
        print(f"{state}  {label:<24} {detail}")
    else:
        rows.append({"state": state.strip(), "label": label, "detail": detail})
    return state


def _git_ok(path: Path, *a):
    p = subprocess.run(["git", "-C", str(path), *a], capture_output=True, text=True)
    return p.returncode == 0, (p.stdout or p.stderr).strip()


def capability_status(context: InvocationContext | None = None,
                      shared_override: str | None = None,
                      local_override: str | None = None) -> str:
    """Return the capability state without printing or writing ledger files."""
    context = context or InvocationContext.from_environment()
    config = next((path for path in config_candidates(context) if path.is_file()), None)
    roots = resolve_roots(shared_override, local_override, context)
    if roots[KINDS[0]] == roots[KINDS[1]]:
        return "broken"
    if not roots[KINDS[0]].is_dir() or not (roots[KINDS[0]] / ".git").exists():
        if not config and not any(roots[kind].exists() for kind in KINDS):
            return "unconfigured"
        return "broken"
    local = roots[KINDS[1]]
    if local.exists() and (not local.is_dir() or not (local / ".git").exists()):
        return "broken"
    if not any(roots[kind].is_dir() for kind in KINDS):
        return "unconfigured" if config is None else "broken"
    return "configured"


def cmd_doctor(args, root=None):
    context = getattr(args, "context", None) or InvocationContext.from_environment()
    rows = []
    machine_rows = rows if args.json else None
    states = []

    v = sys.version_info
    states.append(_row(OK if v >= MIN_PYTHON else FAIL, "python",
                       f"{v.major}.{v.minor}.{v.micro} at {sys.executable} "
                       f"(need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})", machine_rows))

    git = shutil.which("git")
    if git:
        _, out = _git_ok(context.cwd, "--version")
        states.append(_row(OK, "git", f"{out or 'present'} at {git}", machine_rows))
    else:
        states.append(_row(FAIL, "git", "not on PATH — `save` cannot commit anything", machine_rows))

    sid = context.session_id or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    states.append(_row(OK if sid else WARN, "session id",
                       f"{context.host} session_id={sid}" if sid else
                       "session identity unset — `sign` will refuse without --as", machine_rows))

    cfg_path = next((c for c in config_candidates(context) if c.is_file()), None)
    mem = load_config(context).get("memory") or {}
    if cfg_path:
        keys = ", ".join(f"{k}={v}" for k, v in mem.items()) or "no memory: block"
        states.append(_row(OK if mem else WARN, "config", f"{cfg_path} — {keys}", machine_rows))
    else:
        states.append(_row(WARN, "config",
                           f"no config file found — falling back to defaults "
                           f"({DEFAULT_SHARED_ROOT}, {DEFAULT_LOCAL_ROOT}). Looked in: "
                           + ", ".join(str(c) for c in config_candidates(context)), machine_rows))

    roots = resolve_roots(args.root, args.local_root, context)
    if roots[KINDS[0]] == roots[KINDS[1]]:
        states.append(_row(FAIL, "roots", "shared and local resolve to the same path", machine_rows))
    for kind in KINDS:
        p = roots[kind]
        if not p.is_dir():
            states.append(_row(WARN if kind == "local" else FAIL, f"{kind} ledger",
                               f"{p} does not exist", machine_rows))
            continue
        if not (p / ".git").exists():
            states.append(_row(FAIL, f"{kind} ledger", f"{p} is not a git repository", machine_rows))
            continue
        n = len([x for x in p.rglob("*.md") if not x.name.endswith(".debate.md")])
        has_remote, remote = _git_ok(p, "remote", "get-url", "origin")
        where = f"origin {remote}" if has_remote else "no remote (local only)"
        # A shared ledger with no remote reaches nobody. Not fatal, since that is
        # where every ledger starts, but it is the single thing most likely to be
        # silently untrue about a setup someone believes is finished.
        state = WARN if (kind == "shared" and not has_remote) else OK
        states.append(_row(state, f"{kind} ledger",
                           f"{p} — {n} entries, {where}", machine_rows))
        probe = p / ".ledger-write-probe"
        try:
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            states.append(_row(FAIL, f"{kind} writable", f"{exc}", machine_rows))

    ignored = []
    for kind in KINDS:
        p = roots[kind]
        gi = p / ".gitignore"
        if p.is_dir() and (not gi.is_file() or ".ledger-cache.json" not in
                           gi.read_text(encoding="utf-8")):
            ignored.append(kind)
    if ignored:
        states.append(_row(WARN, "cache ignored",
                           f"{', '.join(ignored)}: .ledger-cache.json is not in .gitignore "
                           f"— a shared cache is a stale second copy", machine_rows))
    else:
        states.append(_row(OK, "cache ignored", ".ledger-cache.json ignored in every ledger", machine_rows))

    fails = sum(1 for s in states if s == FAIL)
    warns = sum(1 for s in states if s == WARN)
    capability = capability_status(context, args.root, args.local_root)
    status = ("unconfigured" if capability == "unconfigured" else
              "broken" if fails else capability)
    if args.json:
        import json
        print(json.dumps({
            "capability": "memory-ledger",
            "status": status,
            "roots": {kind: str(roots[kind]) for kind in KINDS},
            "config": str(cfg_path) if cfg_path else None,
            "failures": [f"{row['label']}: {row['detail']}" for row in rows if row["state"] == "FAIL"],
            "warnings": [f"{row['label']}: {row['detail']}" for row in rows
                         if row["state"].lower() == WARN],
        }, separators=(",", ":")))
        return {"configured": 0, "broken": 1, "unconfigured": 3}[status]
    print(f"\n{fails} failure(s), {warns} warning(s)")
    if fails:
        print("Fix the failures before writing anything — run /memory-ledger:setup.")
    return 1 if fails else 0
