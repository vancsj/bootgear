"""Read and save local Deputy decisions through Memory Ledger."""
from __future__ import annotations

import argparse
import json
import os
import re
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


def ledger(deputy_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*ledger_command(), "--deputy-root", str(deputy_root), *args],
                          capture_output=True, text=True, check=False)


PRONOUN = re.compile(
    r"\b(i|me|my|mine|you|your|yours|it|its|itself|we|she|they)\b",
    re.IGNORECASE,
)
OPTION = re.compile(r"\bor\b|\beither\b|\([a-z0-9]\)|\b[a-z0-9]\)|\b[a-z0-9]:\s", re.IGNORECASE)
BARE_ANSWER = re.compile(r"\(?[a-z]\)?\.?|\d+\.?", re.IGNORECASE)
MAX_WORDS = 20
CONFIRMATION = "The user confirmed this canonical decision."
RECORD_EXAMPLE = (
    'record --question "Which design?" --claim "Use the direct call." --confirmed-by-user'
)


def sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]


def entry_problems(question: str, claim: str, because: str, *, check_question: bool = True) -> list[str]:
    """The mechanical Q&A standards. An empty list means the entry may be written."""
    problems = []
    for label, text in (("question", question), ("answer", claim)):
        if not text.strip():
            problems.append(f"the {label} is empty")
        elif len(text.splitlines()) != 1 or text.strip() != text:
            problems.append(f"the {label} must be one line without surrounding whitespace")
        if label == "question" and not check_question:
            continue
        if PRONOUN.search(text):
            problems.append(f"the {label} uses a pronoun")
        if any(len(part.split()) > MAX_WORDS for part in sentences(text)):
            problems.append(f"a sentence in the {label} has more than {MAX_WORDS} words")
    if check_question and OPTION.search(question):
        problems.append("the question lists options")
    if BARE_ANSWER.fullmatch(claim.strip()):
        problems.append("the answer is a bare letter or number")
    if len(sentences(because)) != 1:
        problems.append("the reason is not one sentence")
    if ";" in because:
        problems.append("the reason is not one clause")
    return problems


def resolve_data(deputy_root: Path, question: str) -> dict:
    """memory-ledger's resolve for the deputy kind: the exact slug, the minted slug, the candidates."""
    r = ledger(deputy_root, "resolve", question, "--all", "--data", "--only", "deputy")
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


def index(deputy_root: Path, asserted: bool) -> int:
    if not deputy_root.is_dir():
        print("ESCALATE deputy-root-absent", file=sys.stderr)
        return 2
    options = ["--asserted"] if asserted else []
    return relay(ledger(deputy_root, "deputy-index", *options, "--prose"))


def relay(result: subprocess.CompletedProcess) -> int:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def record(deputy_root: Path, question: str, claim: str, confirmed: bool,
           entry: str | None, replace: str | None, previous_claim: str | None) -> int:
    if not confirmed:
        print("REFUSED record requires --confirmed-by-user", file=sys.stderr)
        return 2
    if problems := entry_problems(question, claim, CONFIRMATION, check_question=entry is None):
        print("REFUSED " + "; ".join(problems), file=sys.stderr)
        return 2
    options = [f"--entry={entry}"] if entry else []
    if replace:
        options.append(f"--replace={replace}")
    if previous_claim:
        options.append(f"--previous-claim={previous_claim}")
    return relay(ledger(deputy_root, "deputy-preference", f"--question={question}",
                        f"--claim={claim}", "--confirmed-by-user", *options, "--prose"))


def save(deputy_root: Path, message: str) -> int:
    r = ledger(deputy_root, "save", "--only", "deputy", "--no-push")
    if r.returncode != 0:
        return relay(r)
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
        "index": "index --asserted",
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
    ix = sub.add_parser("index", help="print entry IDs and questions as TSV")
    ix.add_argument("--asserted", action="store_true", help="show entries with an active assertion")
    rc = sub.add_parser("record", help="save an explicitly confirmed standing decision")
    rc.add_argument("--question", required=True)
    rc.add_argument("--claim", required=True)
    rc.add_argument("--entry", help="existing entry ID to reuse")
    rc.add_argument("--replace", help="current assertion ID to replace; requires --entry and --previous-claim")
    rc.add_argument("--previous-claim", help="exact current answer shown in the confirmed replacement")
    rc.add_argument("--confirmed-by-user", dest="confirmed", action="store_true",
                    help="required after the user confirms the proposed standing decision")
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
        if args.cmd == "index":
            return index(root, args.asserted)
        if args.cmd == "record":
            return record(root, args.question, args.claim, args.confirmed, args.entry, args.replace, args.previous_claim)
        return assert_(root, args.slug, args.answer, args.why, args.confirmed)
    except LedgerMissing:
        if args.cmd == "candidates":
            print("ESCALATE memory-ledger-not-found")
            return 0
        print(f"REFUSED {MISSING}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
