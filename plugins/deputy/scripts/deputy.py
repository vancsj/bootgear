"""The deputy's ledger commands: list candidates, record a decision, pin an assertion.

This script judges nothing. `candidates` prints the matching entries in full for the
ask skill to read; `record` and `assert` write to the deputy root through memory-ledger: its
gear command in a repo checkout, else the highest installed memory-ledger version beside this
plugin in the host's plugin cache. Every write runs `save --only deputy`, and the deputy root
must have no remote.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ABOVE = Path(__file__).resolve().parents[3]
GEAR = Path(os.environ.get("GEAR_PY") or ABOVE / "cli" / "gear.py")
DEFAULT_LIMIT = 8
MISSING = "memory-ledger not found; install the memory-ledger plugin"


class LedgerMissing(Exception):
    """Neither cli/gear.py nor an installed memory-ledger copy exists."""


def version_key(script: Path) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in script.parents[1].name.split("."))
    except ValueError:
        return None


def ledger_command() -> list[str]:
    """The gear command in a repo checkout, else the highest installed memory-ledger version
    in the plugin cache: <cache>/memory-ledger/<version>/scripts/ledger.py."""
    if GEAR.is_file():
        return [sys.executable, str(GEAR), "memory-ledger", "ledger"]
    installed = [(key, script) for script in ABOVE.glob("memory-ledger/*/scripts/ledger.py")
                 if (key := version_key(script)) is not None]
    if not installed:
        raise LedgerMissing(MISSING)
    return [sys.executable, str(max(installed)[1])]


def ledger(deputy_root: Path, *args: str, signer: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    return subprocess.run([*ledger_command(), "--deputy-root", str(deputy_root), *signer, *args],
                          capture_output=True, text=True, check=False)


PRONOUN = re.compile(r"\b(i|me|my|mine|you|your|yours|it|its|itself)\b", re.IGNORECASE)
OPTION = re.compile(r"\bor\b|\beither\b|\([a-z0-9]\)|\b[a-z0-9]\)|\b[a-z0-9]:\s", re.IGNORECASE)
BARE_ANSWER = re.compile(r"\(?[a-z]\)?\.?|\d+\.?", re.IGNORECASE)
MAX_WORDS = 20


def sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]


def entry_problems(question: str, claim: str, because: str) -> list[str]:
    """The mechanical Q&A standards. An empty list means the entry may be written."""
    problems = []
    for label, text in (("question", question), ("answer", claim)):
        if not text.strip():
            problems.append(f"the {label} is empty")
        if PRONOUN.search(text):
            problems.append(f"the {label} uses a pronoun")
        if any(len(part.split()) > MAX_WORDS for part in sentences(text)):
            problems.append(f"a sentence in the {label} has more than {MAX_WORDS} words")
    if OPTION.search(question):
        problems.append("the question lists options")
    if BARE_ANSWER.fullmatch(claim.strip()):
        problems.append("the answer is a bare letter or number")
    if len(sentences(because)) != 1:
        problems.append("the reason is not one sentence")
    if ";" in because:
        problems.append("the reason is not one clause")
    return problems


def resolve_data(deputy_root: Path, question: str, signer: tuple[str, ...] = ()) -> dict:
    """memory-ledger's resolve for the deputy kind: the exact slug, the minted slug, the candidates."""
    r = ledger(deputy_root, "resolve", question, "--all", "--data", "--only", "deputy", signer=signer)
    if r.returncode != 0:
        sys.exit(r.stdout + r.stderr)
    return json.loads(r.stdout)


def matching_slugs(deputy_root: Path, question: str) -> list[str]:
    """Matching slugs: the exact slug first, then the candidates best score first."""
    data = resolve_data(deputy_root, question)
    rows = sorted(data["candidates"], key=lambda row: -row["score"])
    slugs = [data["exact"]] if data["exact"] else []
    return slugs + [row["slug"] for row in rows if row["slug"] != data["exact"]]


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
    return 0


def refuse_remote(deputy_root: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(deputy_root), "remote"], capture_output=True, text=True,
                       check=False)
    if r.stdout.strip():
        return f"the deputy root {deputy_root} has a git remote; the deputy ledger is local only"
    return None


def session_id_from_environment(explicit: str | None) -> str | None:
    """Resolve a signer session from the CLI option and shared host variables."""
    if explicit is not None:
        return explicit
    return (os.environ.get("BOOTGEAR_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or None)


def record(deputy_root: Path, question: str, claim: str, because: str, options: str,
           stakes: str, session_ledger: Path, host: str = "claude", session_id: str | None = None) -> int:
    if problems := entry_problems(question, claim, because):
        print("REFUSED " + "; ".join(problems), file=sys.stderr)
        return 2
    session_id = session_id_from_environment(session_id)
    if host == "codex" and not session_id:
        print("REFUSED codex needs --session-id", file=sys.stderr)
        return 2
    # On Codex the global options set the signer of every ledger call; `new` also takes `--as`.
    signer = ("--host", host)
    if session_id:
        signer += ("--session-id", session_id)
    sign_as = ["--as", f"codex:{session_id}"] if host == "codex" else []
    if problem := refuse_remote(deputy_root):
        print(f"REFUSED {problem}", file=sys.stderr)
        return 2
    # The check counts occurrences of the answer in the session ledger and requires at
    # least as many as there are now. A second answer in the same session raises the
    # count, so its check text differs and memory-ledger takes it as another vote.
    # The answer and the path are quoted, so the answer text never reaches the shell as code.
    text = session_ledger.read_text(encoding="utf-8") if session_ledger.is_file() else ""
    count = sum(1 for line in text.splitlines() if claim in line)
    if count == 0:
        print(f"REFUSED the session ledger {session_ledger} does not contain the answer",
              file=sys.stderr)
        return 2
    evidence = (f'test "$(grep -cF -- {shlex.quote(claim)} {shlex.quote(str(session_ledger))})"'
                f" -ge {count}")
    # memory-ledger adds the check as a vote when a similar question has this claim.
    r = ledger(deputy_root, "vote", "--question", question, "--claim", claim,
               "--evidence", evidence, "--only", "deputy", signer=signer)
    if r.returncode not in (0, 1):
        print(r.stdout + r.stderr, file=sys.stderr)
        return r.returncode
    if r.returncode == 0:
        outcome = [line for line in r.stdout.splitlines()
                   if line.startswith(("VOTED ", "UNCHANGED "))][-1]
        if outcome.startswith("VOTED "):
            # The signature makes this session an independent signer. `sign` does not run the
            # Evidence pointer, so a session ledger that is gone does not block it.
            _, slug, aid, *_ = outcome.split()
            r = ledger(deputy_root, "sign", slug, aid, "--only", "deputy", *sign_as, signer=signer)
            if r.returncode != 0:
                print(r.stdout + r.stderr, file=sys.stderr)
                return r.returncode
            return save(deputy_root, outcome, signer)
        print(outcome)
        return 0
    existing = [line.split()[1] for line in r.stdout.splitlines()
                if line.startswith("SAME-QUESTION ")]
    because_line = f"{because}. Context: options {options}; stakes {stakes}."
    if existing:
        # The same question with another answer is a rival on its entry, not a new entry.
        target = existing[0]
        r = ledger(deputy_root, "rival", target, "--claim", claim, "--because", because_line,
                   "--evidence", evidence, "--only", "deputy", *sign_as, signer=signer)
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr)
            return r.returncode
        return save(deputy_root, f"RIVAL {target}", signer)
    # The slug is memory-ledger's minted slug. Memory-ledger's duplicate gate applies to every new entry.
    slug = "decisions/" + resolve_data(deputy_root, question, signer)["mint"]
    r = ledger(deputy_root, "new", slug, "--deputy", "--q", question, "--claim", claim,
               "--because", because_line, "--evidence", evidence, *sign_as, signer=signer)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return r.returncode
    return save(deputy_root, f"NEW {slug}", signer)


def save(deputy_root: Path, message: str, signer: tuple[str, ...] = ()) -> int:
    r = ledger(deputy_root, "save", "--only", "deputy", signer=signer)
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
    rc.add_argument("--host", choices=("claude", "codex"),
                    default=os.environ.get("BOOTGEAR_HOST", "claude"),
                    help="the host that signs the ledger calls")
    rc.add_argument("--session-id", dest="session_id", metavar="ID",
                    help="the host session id; required with --host codex")
    a = sub.add_parser("assert", help="pin an answer at 1.00 on a user's ruling")
    a.add_argument("slug")
    a.add_argument("answer")
    a.add_argument("--why", required=True)
    a.add_argument("--confirmed-by-user", dest="confirmed", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.deputy_root).expanduser()
    try:
        if args.cmd == "candidates":
            return candidates(root, args.question, args.limit)
        if args.cmd == "record":
            return record(root, args.question, args.claim, args.because, args.options,
                          args.stakes, Path(args.session_ledger).expanduser(), args.host,
                          args.session_id)
        return assert_(root, args.slug, args.answer, args.why, args.confirmed)
    except LedgerMissing:
        if args.cmd == "candidates":
            print("ESCALATE memory-ledger-not-found")
            return 0
        print(f"REFUSED {MISSING}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
