"""The deputy's ledger commands: list candidates, record a decision, pin an assertion.

This script judges nothing. `candidates` prints the matching entries in full for the
ask skill to read; `record` and `assert` write to the deputy root through memory-ledger's
gear command. Every write runs `save --only deputy`, and the deputy root must have no remote.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

GEAR = Path(os.environ.get("GEAR_PY") or Path(__file__).resolve().parents[3] / "cli" / "gear.py")
DEFAULT_LIMIT = 8
HIT = re.compile(r"^\s+\d+\.\d+ \(\d+/\d+\)\s+(\S+)\s*$")
EXACT = re.compile(r"^EXACT\s+(\S+)")


def ledger(deputy_root: Path, *args: str) -> subprocess.CompletedProcess:
    if not GEAR.is_file():
        sys.exit(f"gear.py not found at {GEAR}; set GEAR_PY to the bootgear cli/gear.py path")
    return subprocess.run([sys.executable, str(GEAR), "memory-ledger", "ledger",
                           "--deputy-root", str(deputy_root), *args],
                          capture_output=True, text=True)


def normal(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def slug_for(question: str) -> str:
    return "decisions/" + (re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:60] or "question")


def matching_slugs(deputy_root: Path, question: str) -> list[str]:
    r = ledger(deputy_root, "resolve", question, "--only", "deputy")
    slugs: list[str] = []
    for line in r.stdout.splitlines():
        m = EXACT.match(line) or HIT.match(line)
        if m and m.group(1) not in slugs:
            slugs.append(m.group(1))
    return slugs


def show(deputy_root: Path, slug: str) -> str:
    return ledger(deputy_root, "show", slug, "--only", "deputy").stdout


def candidates(deputy_root: Path, question: str, limit: int) -> int:
    if not deputy_root.is_dir():
        print("ESCALATE deputy-root-absent")
        return 0
    slugs = matching_slugs(deputy_root, question)
    if not slugs:
        print("NO-CANDIDATES")
        return 0
    for slug in slugs[:limit]:
        print(f"CANDIDATE {slug}")
        print(show(deputy_root, slug).rstrip())
        print()
    if len(slugs) > limit:
        print(f"CUT {len(slugs) - limit} more matching entries not shown")
    print("NOTE the resolver keeps matches above its largest score gap; weaker matches may be hidden")
    return 0


def question_of(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("Q: "):
            return line[3:]
    return None


def first_claim(text: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## ") and i + 1 < len(lines):
            return lines[i + 1].strip()
    return None


def refuse_remote(deputy_root: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(deputy_root), "remote"], capture_output=True, text=True)
    if r.stdout.strip():
        return f"the deputy root {deputy_root} has a git remote; the deputy ledger is local only"
    return None


def record(deputy_root: Path, question: str, claim: str, because: str, options: str,
           stakes: str, session_ledger: Path) -> int:
    if problem := refuse_remote(deputy_root):
        print(f"REFUSED {problem}", file=sys.stderr)
        return 2
    existing = [s for s in matching_slugs(deputy_root, question)
                if normal(question_of(show(deputy_root, s)) or "") == normal(question)]
    for slug in existing:
        if normal(first_claim(show(deputy_root, slug)) or "") == normal(claim):
            print(f"UNCHANGED {slug}")
            return 0
    base = slug_for(question)
    slug = base if not existing else f"{base}-newer-{len(existing) + 1}"
    newer = f" Newer than {existing[-1]}." if existing else ""
    because_line = f"{because}.{newer} Context: options {options}; stakes {stakes}."
    # A changed answer to a recorded question is deliberate, so memory-ledger's
    # near-duplicate refusal is passed on purpose.
    extra = ["--anyway"] if existing else []
    # The check is built here, with the answer and the path quoted, so the answer
    # text never reaches the shell as code.
    evidence = f"grep -qF -- {shlex.quote(claim)} {shlex.quote(str(session_ledger))}"
    r = ledger(deputy_root, "new", slug, "--deputy", "--q", question, "--claim", claim,
               "--because", because_line, "--evidence", evidence, *extra)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return r.returncode
    return save(deputy_root, f"NEW {slug}")


def save(deputy_root: Path, message: str) -> int:
    r = ledger(deputy_root, "save", "--only", "deputy")
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return r.returncode
    print(message)
    return 0


def assert_(deputy_root: Path, slug: str, answer: str, why: str, confirmed: bool) -> int:
    if not confirmed:
        print("REFUSED assert needs --confirmed-by-user, set only after the user confirms",
              file=sys.stderr)
        return 2
    if problem := refuse_remote(deputy_root):
        print(f"REFUSED {problem}", file=sys.stderr)
        return 2
    r = ledger(deputy_root, "assert", slug, answer, "--why", why, "--only", "deputy")
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return r.returncode
    return save(deputy_root, f"ASSERTED {slug} {answer}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deputy.py", description=__doc__)
    p.add_argument("--deputy-root", dest="deputy_root", metavar="PATH",
                   default=os.environ.get("LEDGER_DEPUTY_ROOT", "~/.memory-ledger/deputy"))
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="print the matching deputy entries in full")
    c.add_argument("question")
    c.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    rc = sub.add_parser("record", help="write a decision the user answered")
    for flag in ("question", "claim", "because", "options", "stakes"):
        rc.add_argument(f"--{flag}", required=True)
    rc.add_argument("--session-ledger", dest="session_ledger", required=True, metavar="PATH",
                    help="the session ledger file that must contain the answer text")
    a = sub.add_parser("assert", help="pin an answer at 1.00 on a user's ruling")
    a.add_argument("slug")
    a.add_argument("answer")
    a.add_argument("--why", required=True)
    a.add_argument("--confirmed-by-user", dest="confirmed", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.deputy_root).expanduser()
    if args.cmd == "candidates":
        return candidates(root, args.question, args.limit)
    if args.cmd == "record":
        return record(root, args.question, args.claim, args.because, args.options,
                      args.stakes, Path(args.session_ledger).expanduser())
    return assert_(root, args.slug, args.answer, args.why, args.confirmed)


if __name__ == "__main__":
    sys.exit(main())
