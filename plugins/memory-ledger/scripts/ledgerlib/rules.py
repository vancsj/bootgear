"""`rules`: each ledger's own statement of what belongs in it.

The file is prose a session reads, never parsed. It is `.txt` because the loader
reads every `*.md` under a ledger root as an entry.

The rule file must be a regular file inside the root. A symlink could point
anywhere, so nothing here reads, writes or stages through one, and a directory
or other special file at that path is reported rather than opened.
"""
from __future__ import annotations

import os
from pathlib import Path

from .clikit import refuse

RULES_FILE = "WHAT-BELONGS.txt"
_DEFAULTS = Path(__file__).resolve().parents[2] / "rules"
_FIX = "replace it with a regular file"


def rules_path(root: Path) -> Path:
    return root / RULES_FILE


def rules_problem(path: Path) -> str | None:
    """Why `path` cannot be used as a rule file, or None when it is a regular
    non-symlink file or does not exist at all."""
    if path.is_symlink():
        return "is a symbolic link"
    if not path.exists():
        return None
    if path.is_dir():
        return "is a directory"
    if not path.is_file():
        return "is not a regular file"
    return None


def default_text(kind: str) -> str:
    return (_DEFAULTS / f"{kind}.txt").read_text(encoding="utf-8")


def seed_hint(kind: str, prog: str = "ledger.py") -> str:
    return f"run: {prog} rules --init --only {kind}"


def _seed(path: Path, text: str) -> None:
    # O_EXCL fails on any existing path, a dangling symlink included, so a link
    # created after the check is never followed.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def cmd_rules(args, root=None):
    prog = getattr(args, "prog", None) or "ledger.py"
    only = getattr(args, "only", None)
    scope = f" --only {only}" if only else ""
    problems = [(lg, rules_path(lg.root), rules_problem(rules_path(lg.root)))
                for lg in args.ledgers]
    problems = [(lg, path, why) for lg, path, why in problems if why]
    if args.init:
        if problems:
            refuse(f"rules --init refused: a rule file path is not a regular file — {_FIX}",
                   [("not a regular file", f"{lg.kind}: {path} {why}")
                    for lg, path, why in problems])
        seeded = False
        for lg in args.ledgers:
            path = rules_path(lg.root)
            if path.is_file():
                print(f"RULES    {lg.kind}  kept {path}")
            else:
                _seed(path, default_text(lg.kind))
                print(f"RULES    {lg.kind}  seeded {path}")
                seeded = True
        if seeded:
            print(f"next: {prog} save{scope}")
        return 0

    blocked = {lg.kind: why for lg, _, why in problems}
    missing = False
    for lg in args.ledgers:
        path = rules_path(lg.root)
        if lg.kind in blocked:
            print(f"RULES    {lg.kind}  {path} {blocked[lg.kind]} — not read; {_FIX}")
        elif path.is_file():
            print(f"RULES    {lg.kind}  {path}")
            print(path.read_text(encoding="utf-8").rstrip("\n"))
            print()
        else:
            print(f"RULES    {lg.kind}  {path} missing — {seed_hint(lg.kind, prog)}")
            missing = True
    if blocked:
        return 1
    if missing:
        print(f"next: {prog} rules --init{scope}")
    return 0


def warn_missing_rules(root: Path, kind: str, prog: str = "ledger.py") -> None:
    path = rules_path(root)
    why = rules_problem(path)
    if why:
        print(f"WARN     {kind} ledger {RULES_FILE} {why} — {_FIX}")
    elif not path.is_file():
        print(f"WARN     {kind} ledger has no {RULES_FILE} — {seed_hint(kind, prog)}")
