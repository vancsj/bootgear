"""`save`: one commit per ledger, and proof that nothing was left behind.

Staging walks the filesystem and forces each path rather than trusting `git add`,
because git's view of the tree is not the ledger — the global ignore rule for
`build/` that most developers carry can swallow a `build/` folder's own
`_about.md` with no error at all.
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

from .audit import unportable_paths
from .constants import CACHE_NAME
from .lint import cmd_lint
from .store import load_entries

_LINT_TAG = re.compile(r"^([A-Z][A-Z-]*)\s")


def _summarize_lint(report: str) -> str:
    """One line: a tally by tag, instead of every finding.

    `save` runs `lint --fix` on every save, and printing all of it inline burns
    tokens on findings nobody asked to see this run — `ledger.py lint` still
    prints every line for whoever wants the detail.
    """
    counts = Counter(m.group(1) for line in report.splitlines()
                     if (m := _LINT_TAG.match(line)))
    if not counts:
        return "lint: clean"
    total = sum(counts.values())
    breakdown = ", ".join(f"{tag} {n}" for tag, n in
                          sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return f"lint: {total} problem(s) — {breakdown}\n  ledger.py lint for detail"


def _check_remote(lg) -> str | None:
    """A shared ledger with no remote reaches nobody — `doctor` catches this,
    but nothing calls `doctor` on its own, so a save is the moment to say it
    again: work just got committed to a ledger that is still local-only.
    """
    if lg.kind != "shared":
        return None
    p = subprocess.run(["git", "-C", str(lg.root), "remote"],
                       capture_output=True, text=True)
    if not p.stdout.split():
        return (f"  warn: {lg.root} has no remote — this save stays on this "
                f"machine, not the team")
    return None


def _check_unportable(lg) -> str | None:
    """Same assertion as `ledger.py audit`, run on every save rather than only
    when someone remembers to ask: a hardcoded /Users/<you>/ in a shared
    Evidence line is invisible until another machine runs it and gets a
    spurious ✗, so the save that introduces it is the cheapest place to catch it.
    """
    if lg.kind != "shared":
        return None
    flagged = [(e.slug, a.aid) for e in load_entries(lg.root, lg.kind)
              if Path(e.slug).name != "_about"
              for a in e.answers if unportable_paths("\n".join(a.evidences))]
    if not flagged:
        return None
    shown = ", ".join(f"{slug} {aid}" for slug, aid in flagged[:5])
    more = f" (+{len(flagged) - 5} more)" if len(flagged) > 5 else ""
    return (f"  warn: {len(flagged)} answer(s) hardcode a home path — {shown}"
            f"{more}\n  ledger.py audit for detail")


def _git(root: Path, *a, check=True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
    if check and p.returncode:
        sys.exit(f"git {' '.join(a)} failed:\n{(p.stderr or p.stdout).strip()}")
    return p


def save_one(args, root):
    """Stage every entry in one ledger, commit, and prove nothing was left behind.

    The reason this is a command and not three git calls in a skill: git's view
    of the tree is not the ledger. The global ignore rule for `build/` that most
    developers carry can silently swallow a `build/` folder's own `_about.md` —
    `git add -A` reports success, the entry sits uncommitted and invisible, and
    the next session has no way to know a folder's charter is missing. Any folder named for a build artefact
    (`dist/`, `target/`, `out/`) reproduces it, and the repo's own `.gitignore`
    cannot pre-empt names nobody has chosen yet.

    So staging walks the filesystem and forces each path, and then — the part
    that actually makes this safe — it re-walks afterwards and fails if a single
    `.md` is not in the new commit. A silent omission becomes a hard error,
    which is the one thing `git add` will never do for you.
    """
    if _git(root, "rev-parse", "--git-dir", check=False).returncode:
        sys.exit(f"{root} is not a git repository — nothing to save into")

    entries = sorted(p for p in root.rglob("*.md"))
    if not entries:
        # Not fatal any more. A freshly created local ledger is legitimately
        # empty, and killing the whole save over it would strand the shared
        # ledger's commit — the one with something in it.
        print(f"  {root} holds no entries yet — nothing to commit")
        return 0
    # -f defeats every ignore rule, global and repo-local, for entry files only.
    # The cache is never passed in, so no ignore rule has to be trusted to omit it.
    _git(root, "add", "-f", "--", *[str(p.relative_to(root)) for p in entries])
    _git(root, "add", "-u", "--", ".")          # deletions and renames

    staged = _git(root, "diff", "--cached", "--name-only").stdout.split()
    if not staged:
        print("nothing to save — every entry is already committed")
        return 0

    msg = args.message or _save_message(root, staged)
    _git(root, "commit", "-q", "-m", msg)
    head = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()

    # The guarantee: every .md on disk is in this commit, or this is an error.
    in_commit = set(_git(root, "ls-tree", "-r", "--name-only", "HEAD").stdout.split())
    missing = [str(p.relative_to(root)) for p in entries
               if str(p.relative_to(root)) not in in_commit]
    if missing:
        sys.exit(f"COMMITTED {head} BUT {len(missing)} entr(ies) are not in it:\n  "
                 + "\n  ".join(missing)
                 + "\nAn ignore rule is eating them. Check `git check-ignore -v <path>`.")
    if (root / CACHE_NAME).is_file() and CACHE_NAME in in_commit:
        sys.exit(f"{CACHE_NAME} got committed — it is a local cache and must be ignored")

    print(f"saved {head}  {len(staged)} file(s), {len(entries)} entries all present")
    print(f"  {msg.splitlines()[0]}")

    remote = _git(root, "remote", check=False).stdout.split()
    if not remote:
        print("  no remote — committed locally, nothing to push")
    elif args.no_push:
        print(f"  {remote[0]} configured; --no-push given")
    else:
        _push(root, remote[0])
    return 0


def cmd_save(args, root):
    """One commit per ledger, and a lint pass over everything first.

    Never one commit spanning both: they are separate repos precisely so the
    shared one can gain a remote without carrying local history, and a save that
    treated them as one tree would be the first thing to break that.

    A failure in one is not a reason to skip the other. A local commit that never
    happened because the shared push was rejected is work sitting unsaved in a
    repo nobody is watching, so each is attempted and the worst status is what
    the command exits with.
    """
    ledgers = args.ledgers
    if getattr(args, "lint_detail", False):
        cmd_lint(argparse.Namespace(fix=True, ledgers=ledgers), None)
    else:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_lint(argparse.Namespace(fix=True, ledgers=ledgers), None)
        print(_summarize_lint(buf.getvalue()))
    for lg in ledgers:
        for msg in (_check_remote(lg), _check_unportable(lg)):
            if msg:
                print(msg)
    print()
    worst = 0
    for lg in ledgers:
        if len(ledgers) > 1:
            print(f"── {lg.kind}: {lg.root} ──")
        worst = save_one(args, lg.root) or worst
        if len(ledgers) > 1:
            print()
    return worst


def _save_message(root: Path, staged: list) -> str:
    """A message about the resulting ledger, not about which files moved."""
    added, signed = [], []
    for f in staged:
        if not f.endswith(".md") or f.endswith(".debate.md"):
            continue
        slug = f[:-3]
        was = _git(root, "cat-file", "-e", f"HEAD:{f}", check=False).returncode == 0
        (signed if was else added).append(slug)
    bits = []
    if added:
        bits.append(f"record {len(added)} question(s)" if len(added) > 1
                    else f"record {added[0]}")
    if signed:
        bits.append(f"verify {len(signed)} answer(s)" if len(signed) > 1
                    else f"verify {signed[0]}")
    head = "; ".join(bits) or f"update {len(staged)} ledger file(s)"
    body = "\n".join(f"- {s}" for s in sorted(added + signed))
    return f"{head[0].upper()}{head[1:]}" + (f"\n\n{body}" if body else "")


def _push(root: Path, remote: str) -> None:
    """Push, and on a reject rebase onto the remote and retry exactly once."""
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    p = _git(root, "push", remote, branch, check=False)
    if p.returncode == 0:
        print(f"  pushed to {remote}/{branch}")
        return
    print(f"  push rejected — pulling {remote}/{branch} and retrying once")
    if _git(root, "pull", "--rebase", remote, branch, check=False).returncode:
        sys.exit("pull --rebase failed; resolve it by hand — the commit is safe locally")
    p = _git(root, "push", remote, branch, check=False)
    if p.returncode:
        sys.exit(f"push still rejected:\n{(p.stderr or p.stdout).strip()}\n"
                 f"The commit is safe locally; push it by hand.")
    print(f"  pushed to {remote}/{branch} after rebase")
