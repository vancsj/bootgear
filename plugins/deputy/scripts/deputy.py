"""The deputy's ledger commands: list candidates, record a decision, pin an assertion.

This script judges nothing. `candidates` prints the matching entries in full for the
ask skill to read; `record` and `assert` write through the registered memory-ledger command.
Every write runs `save --only deputy`, and the deputy root must have no remote.
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

from bootgear_cli import clikit
from bootgear_cli.clikit import caller_path, current_program
from bootgear_cli.gear import resolve_command

DEFAULT_LIMIT = 8
MISSING = "memory-ledger not found; install the memory-ledger plugin"


class LedgerMissing(Exception):
    """The memory-ledger command is not registered."""


def ledger_command() -> list[str]:
    """Return Gear's registered memory-ledger command."""
    command = resolve_command("ledger")
    if command is None:
        raise LedgerMissing(MISSING)
    return command


def ledger(deputy_root: Path, *args: str, signer: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    return subprocess.run([*ledger_command(), "--deputy-root", str(deputy_root), *signer, *args],
                          capture_output=True, text=True, check=False)


PRONOUN = re.compile(
    r"\b(i|me|my|mine|you|your|yours|it|its|itself|we|she|they)\b",
    re.IGNORECASE,
)
OPTION = re.compile(r"\bor\b|\beither\b|\([a-z0-9]\)|\b[a-z0-9]\)|\b[a-z0-9]:\s", re.IGNORECASE)
BARE_ANSWER = re.compile(r"\(?[a-z]\)?\.?|\d+\.?", re.IGNORECASE)
MAX_WORDS = 20
ENGINE_SOLO_LINE = re.compile(
    r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} \[solo\] (?P<summary>.*)$")
RECORD_EXAMPLE = (
    'record --question "Which design?" --claim "Use the direct call." '
    '--session-ledger session.md --confirmed-by-user'
)


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


def session_id_from_environment(explicit: str | None, host: str | None = None) -> str | None:
    """The CLI option, else the `clikit.session_id` environment order."""
    return clikit.session_id(explicit, host=host)


def record(deputy_root: Path, question: str, claim: str, session_ledger: Path,
           confirmed: bool, host: str = "claude", session_id: str | None = None) -> int:
    if not confirmed:
        print(f"example: {RECORD_EXAMPLE}", file=sys.stderr)
        print("commands: candidates, record, assert", file=sys.stderr)
        print("REFUSED record requires --confirmed-by-user", file=sys.stderr)
        return 2
    because = "The user confirmed this canonical decision."
    if problems := entry_problems(question, claim, because):
        print("REFUSED " + "; ".join(problems), file=sys.stderr)
        return 2
    session_id = session_id_from_environment(session_id, host)
    if host == "codex" and not session_id:
        print("REFUSED " + clikit.missing_session("--session-id"), file=sys.stderr)
        return 2
    # On Codex the global options set the signer of every ledger call; `new` also takes `--as`.
    signer = ("--host", host)
    if session_id:
        signer += ("--session-id", session_id)
    sign_as = ["--as", f"codex:{session_id}"] if host == "codex" else []
    if problem := refuse_remote(deputy_root):
        print(f"REFUSED {problem}", file=sys.stderr)
        return 2
    # Match the complete Engine entry and verify the same match in the stored Evidence check.
    text = session_ledger.read_text(encoding="utf-8") if session_ledger.is_file() else ""
    summary = f"Canonical question: {question} | Canonical decision: {claim}"
    count = sum(
        1 for line in text.splitlines()
        if (match := ENGINE_SOLO_LINE.fullmatch(line)) and match.group("summary") == summary
    )
    if count == 0:
        print(f"REFUSED the session ledger {session_ledger} does not contain the canonical record",
              file=sys.stderr)
        return 2
    evidence = (
        "test \"$(sed -nE 's/^- [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} "
        "\\[solo\\] (.*)$/\\1/p' "
        f"{shlex.quote(str(session_ledger))} | grep -Fxc -- {shlex.quote(summary)})\" -ge {count}"
    )
    # memory-ledger adds the check as a vote when a similar question has this claim.
    r = ledger(deputy_root, "vote", "--question", question, "--claim", claim,
               "--evidence", evidence, "--only", "deputy", signer=signer)
    if r.returncode not in (0, 1):
        print(r.stdout + r.stderr, file=sys.stderr)
        return r.returncode
    if r.returncode == 0:
        outcome = [line for line in r.stdout.splitlines()
                   if line.startswith(("VOTED ", "UNCHANGED "))][-1]
        _, slug, aid, *_ = outcome.split()
        r = ledger(deputy_root, "sign", slug, aid, "--only", "deputy", *sign_as, signer=signer)
        already_signed = (outcome.startswith("UNCHANGED ")
                          and " already signed " in r.stderr
                          and " — nothing to correct" in r.stderr)
        if r.returncode != 0 and not already_signed:
            print(r.stdout + r.stderr, file=sys.stderr)
            return r.returncode
        return save(deputy_root, outcome, signer)
    existing = [line.split()[1] for line in r.stdout.splitlines()
                if line.startswith("SAME-QUESTION ")]
    because_line = because
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
    catalog = clikit.Catalog(prog=current_program("deputy", "deputy"), examples={
        "candidates": 'candidates "Which design meets the requirement?" --limit 3',
        "record": RECORD_EXAMPLE,
        "assert": 'assert decisions/example a1 --why "The user confirmed this answer." --confirmed-by-user',
    })
    p = clikit.parser_class(catalog)(prog=catalog.prog, description=__doc__)
    p.add_argument("--deputy-root", dest="deputy_root", metavar="PATH",
                   default=os.environ.get("LEDGER_DEPUTY_ROOT", "~/.memory-ledger/deputy"),
                   help="deputy ledger directory; must have no remote for writes")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="print the matching deputy entries in full")
    c.add_argument("question", help="judgment question to match against recorded decisions")
    c.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="maximum candidate entries (default: 8)")
    rc = sub.add_parser("record", help="write a decision the user answered")
    rc.add_argument("--question", required=True)
    rc.add_argument("--claim", required=True)
    rc.add_argument("--session-ledger", dest="session_ledger", required=True, metavar="PATH",
                    help="the Engine session ledger that must contain the exact canonical record")
    rc.add_argument("--confirmed-by-user", dest="confirmed", action="store_true",
                    help="the main agent saw the user's confirmation reply")
    rc.add_argument("--host", choices=("claude", "codex"),
                    help="the host that signs the ledger calls")
    rc.add_argument("--session-id", dest="session_id", metavar="ID",
                    help="the host session id; the environment normally supplies it")
    a = sub.add_parser("assert", help="pin an answer at 1.00 on a user's ruling")
    a.add_argument("slug", help="recorded deputy question slug")
    a.add_argument("answer", help="answer id, for example a1")
    a.add_argument("--why", required=True, help="user's reason for pinning this answer")
    a.add_argument("--confirmed-by-user", dest="confirmed", action="store_true", help="required after explicit user confirmation")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = caller_path(args.deputy_root)
    try:
        if args.cmd == "candidates":
            return candidates(root, args.question, args.limit)
        if args.cmd == "record":
            return record(root, args.question, args.claim, caller_path(args.session_ledger),
                          args.confirmed,
                          clikit.host(args.host) or "claude", args.session_id)
        return assert_(root, args.slug, args.answer, args.why, args.confirmed)
    except LedgerMissing:
        if args.cmd == "candidates":
            print("ESCALATE memory-ledger-not-found")
            return 0
        print(f"REFUSED {MISSING}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
