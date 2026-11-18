"""User-confirmed assertions in the local Deputy ledger."""
from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path

from .gitops import _git
from .model import (
    DEPUTY_BECAUSE,
    DEPUTY_CONFIRMATION,
    Answer,
    asserted_line,
    local_today,
    render_header,
)
from .scoring import mint_slug
from .store import Entry, all_entries, restamp_cache


def _entries(args) -> list[Entry]:
    return [e for e in all_entries(args.ledgers)
            if e.question and not e.redirect and e.path.stem != "_about"]


def cmd_deputy_index(args, _root: Path) -> None:
    for entry in sorted(_entries(args), key=lambda entry: entry.slug):
        pinned = any(answer.asserted for answer in entry.answers)
        if not args.asserted or pinned:
            question = entry.question.replace("\t", " ")
            print(f"{entry.slug}\t{question}")


def _target(args) -> Entry | None:
    entries = _entries(args)
    matches = [entry for entry in entries if entry.question == args.question]
    if args.entry:
        entry = next((entry for entry in matches if entry.slug == args.entry), None)
        if entry is None:
            raise SystemExit("REFUSED the selected entry no longer has the confirmed question")
        return entry
    if len(matches) > 1:
        raise SystemExit("REFUSED this question has multiple entries; select one with --entry")
    return next(iter(matches), None)


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.stem}.", delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write("\n".join(lines).rstrip("\n") + "\n")
            handle.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def _commit(root: Path, path: Path) -> None:
    relative = str(path.relative_to(root))
    _git(root, "add", "-f", "--", relative)
    if _git(root, "status", "--porcelain", "--", relative).stdout:
        result = _git(root, "commit", "-qm", "Record Deputy preference", "--only", "--", relative,
                      check=False)
        if result.returncode:
            raise SystemExit(f"REFUSED the assertion is saved on disk but Git refused the commit. "
                             f"Retry the same confirmed command.\n{result.stderr.strip()}")


def _next_answer(entry: Entry | None) -> str:
    if entry is None:
        return "a1"
    last_id = max((int(answer.aid[1:]) for answer in entry.answers), default=0)
    return f"a{last_id + 1}"


def _record(args, root: Path) -> tuple[Path, str]:
    entry = _target(args)
    if entry:
        path = entry.path
        lines = list(entry.lines)
    else:
        slug = f"decisions/{mint_slug(args.question)}"
        path = root / f"{slug}.md"
        base = path
        suffix = 2
        while path.exists():
            path = base.with_stem(f"{base.stem}-{suffix}")
            suffix += 1
        lines = [f"# {path.relative_to(root).with_suffix('')}", f"Q: {args.question}"]

    active = [answer for answer in entry.answers if answer.asserted] if entry else []
    if len(active) > 1:
        raise SystemExit("REFUSED this entry has multiple asserted answers")
    previous = next(iter(active), None)
    if previous and previous.claim == args.claim:
        return path, previous.aid
    if previous and (args.replace, args.previous_claim) != (previous.aid, previous.claim):
        raise SystemExit(f"REFUSED active assertion is {previous.aid}; confirm its replacement")
    if args.replace and previous is None:
        raise SystemExit("REFUSED the assertion selected for replacement is no longer active")

    edits = []
    if previous:
        relative = str(path.relative_to(root))
        if _git(root, "status", "--porcelain", "--", relative).stdout:
            raise SystemExit("REFUSED the active assertion has pending changes; save it before replacing it")
        start, end = previous.header_idx, previous.last_line_idx + 1
        body = []
        if previous.evidences:
            previous.asserted = False
            body = [render_header(previous, previous.counted_confidence(), str(local_today()))]
            body.extend(line for line in lines[start + 1:end] if line != previous.asserted_line)
        edits.append((start, end, body))

    answers = entry.answers if entry else []
    matching = next((answer for answer in answers if answer.claim == args.claim and answer.hash is not None), None)
    if matching:
        matching.asserted = True
        aid = matching.aid
        start = matching.header_idx
        edits.append((start, start + 1, [render_header(matching, 1.00, str(local_today()))]))
        insert_at = matching.sigs[0]["idx"] if matching.sigs else matching.last_line_idx + 1
        edits.append((insert_at, insert_at, [asserted_line("user", DEPUTY_CONFIRMATION)]))
    else:
        aid = _next_answer(entry)
        answer = Answer(aid, args.claim, 1.00, None, True, 0)
        lines.extend(["", render_header(answer, 1.00, ""), DEPUTY_BECAUSE, asserted_line("user", DEPUTY_CONFIRMATION)])
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = replacement
    _write(path, lines)
    restamp_cache(root)
    return path, aid


def cmd_deputy_preference(args, root: Path) -> None:
    if not args.confirmed_by_user:
        raise SystemExit("REFUSED preference requires --confirmed-by-user")
    if any(not value.strip() or value != value.strip() or len(value.splitlines()) != 1
           for value in (args.question, args.claim)):
        raise SystemExit("REFUSED the question and claim must each be one nonempty line")
    if args.replace and not (args.entry and args.previous_claim):
        raise SystemExit("REFUSED --replace requires --entry and --previous-claim")
    if args.previous_claim and not args.replace:
        raise SystemExit("REFUSED --previous-claim requires --replace")
    top = _git(root, "rev-parse", "--show-toplevel", check=False)
    if top.returncode or Path(top.stdout.strip()).resolve() != root.resolve():
        raise SystemExit("REFUSED the Deputy root must be a local Git repository")
    if _git(root, "remote").stdout.strip():
        raise SystemExit("REFUSED the Deputy ledger is local only; remove its remote before writing")
    git_dir = Path(_git(root, "rev-parse", "--absolute-git-dir").stdout.strip())
    with (git_dir / "deputy-preference.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path, aid = _record(args, root)
        _commit(root, path)
    print(f"ASSERTED {path.relative_to(root).with_suffix('')} {aid}")
