"""Reading entries off disk, and the identity cache that keeps `resolve` fast.

The cache is validated by a filesystem stamp rather than by git, because an
ignore rule can hide an entry from git entirely and a cache that inherited that
blindness would serve a ledger with files silently missing.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import sys
from pathlib import Path

from .config import Ledger
from .constants import (
    ALT_RE,
    ANSWER_RE,
    ASSERTED_RE,
    BECAUSE_RE,
    CACHE_NAME,
    CACHE_VERSION,
    EVIDENCE_RE,
    OUTPUT_RE,
    Q_RE,
    REF_RE,
    REPO_RE,
    SIG_RE,
    USE_RE,
)
from .model import Answer
from .scoring import normalize


class Entry:
    def __init__(self, path: Path, root: Path, kind: str | None = None):
        self.path = path
        self.root = root
        self.kind = kind
        self.slug = str(path.relative_to(root).with_suffix(""))
        self.lines = path.read_text(encoding="utf-8").splitlines()
        self.question = ""
        self.alt_terms: list[str] = []
        self.redirect = None
        self.answers: list[Answer] = []
        self._tokens: set[str] | None = None
        self._parse()

    def _parse(self):
        current = None
        for idx, line in enumerate(self.lines):
            m = ANSWER_RE.match(line)
            if m:
                current = Answer(m.group(1), m.group(2).strip(), float(m.group(3)),
                                 m.group(4), bool(m.group(5)), idx)
                self.answers.append(current)
                continue
            if current is None:
                if q := Q_RE.match(line):
                    self.question = q.group(1)
                elif alt := ALT_RE.match(line):
                    self.alt_terms = [t.strip() for t in alt.group(1).split(",") if t.strip()]
                elif use := USE_RE.match(line):
                    self.redirect = use.group(1)
                continue
            # Every non-blank line in this answer's block, recognised or not.
            # Blanks are skipped so a new signature lands against the last content
            # line rather than after the entry's trailing newline.
            if line.strip():
                current.last_line_idx = idx
            if BECAUSE_RE.match(line):
                current.because = line.rstrip()
                current.last_body_idx = idx
            elif EVIDENCE_RE.match(line):
                # append: an answer may carry several checks. Assigning here is
                # what silently dropped every Evidence line but the last, while
                # leaving them visible in the file — a reader saw two checks, the
                # hash covered one, and nothing reported the gap.
                current.evidences.append(line.rstrip())
                current.last_body_idx = idx
            elif REPO_RE.match(line):
                current.repo = line.rstrip()
                current.last_body_idx = idx
            elif ASSERTED_RE.match(line):
                current.asserted_line = line.rstrip()
                current.last_body_idx = idx
            elif REF_RE.match(line):
                current.ref = line.rstrip()
                current.last_body_idx = idx
            elif s := SIG_RE.match(line):
                current.sigs.append({"mark": s.group(1), "who": s.group(2),
                                     "date": s.group(3), "hash": s.group(4),
                                     # checks the answer carried when this was cast;
                                     # None on signatures written before e= existed
                                     "depth": int(s.group(5)) if s.group(5) else None,
                                     "author": bool(s.group(6)), "idx": idx,
                                     "output": []})
                current.last_body_idx = idx
            elif (o := OUTPUT_RE.match(line)) and current.sigs:
                # Belongs to the signature above it; never hashed.
                current.sigs[-1]["output"].append(o.group(1))

    def tokens(self) -> set[str]:
        """Cached: this is called O(N × |query|) times per resolve.

        Recomputing it meant re-normalising the question, slug and alt_terms on
        every one of those calls, which made `resolve` quadratic in wall-clock
        rather than merely in set intersections.
        """
        if self._tokens is None:
            text = " ".join([self.question, self.slug.replace("/", " ").replace("-", " ")]
                            + self.alt_terms)
            self._tokens = set(normalize(text))
        return self._tokens

    def write(self):
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        restamp_cache(self.root)


class CachedEntry:
    """The identity half of an entry: what retrieval scores, and nothing else.

    Deliberately holds only slug, question and alt_terms. Those are the fields
    `resolve` matches on, and — this is the part that makes the cache cheap —
    the only fields no command changes after creation. `sign`, `refute` and
    `promote` all touch evidence, refs and signatures, so none of them can
    invalidate this. Storing `checked` or `conf` here would drag every
    signature back onto the invalidation path for a field the scorer never reads.

    Tokens are stored in the cache rather than derived on read. Deriving them is
    free on a small ledger and becomes the single largest cost in the warm path on
    a large one, because every row pays it whether or not the query ever touches
    that row. Persisting them moves the work to the write that created the entry,
    where it happens once.
    """

    __slots__ = ("_tokens", "alt_terms", "kind", "question", "slug")

    def __init__(self, slug: str, question: str, alt_terms: list[str],
                 tokens: set[str] | None = None, kind: str | None = None):
        self.slug, self.question, self.alt_terms = slug, question, alt_terms
        self._tokens = tokens
        # Which ledger this row came from. Not cached to disk: it is a property
        # of the root the cache file sits in, so persisting it would be the same
        # fact twice, with the copy free to disagree after a `setup` move.
        self.kind = kind

    def tokens(self) -> set[str]:
        if self._tokens is None:
            self._tokens = set(normalize(self.identity_text()))
        return self._tokens

    def identity_text(self) -> str:
        return " ".join([self.question,
                         self.slug.replace("/", " ").replace("-", " ")] + self.alt_terms)


def cache_stamp(root: Path) -> tuple[int, float, str]:
    """(number of entry files, newest mtime) — the tree as the filesystem sees it.

    Not `git status`, though that is four times cheaper. Git only reports files
    it is willing to see, and an ignore rule can hide an entry from it entirely:
    a folder named `build/` matches the global ignore rule almost every developer
    carries, so its own `_about.md` could sit uncommitted and invisible. A cache
    validated by git would have inherited that blindness and served a ledger
    with entries silently missing — the exact failure that makes a session mint
    a duplicate.

    Three parts, because each misses something the others catch. The newest
    mtime sees edits. The path digest sees renames — `git mv` is a rename(2),
    which preserves the file's mtime entirely, so an mtime-only stamp serves a
    slug whose file no longer exists. And the count is the cheap guard on
    deletions. The walk already has the names in hand, so the digest costs no
    extra syscalls.
    """
    count = 0
    newest = 0.0
    hasher = hashlib.sha256()
    for dirpath, _, files in sorted(os.walk(root)):
        if ".git" in dirpath:
            continue
        for f in sorted(files):
            if f.endswith(".md"):
                count += 1
                full = os.path.join(dirpath, f)
                hasher.update(full.encode("utf-8"))
                m = os.stat(full).st_mtime
                newest = max(newest, m)
    return count, newest, hasher.hexdigest()[:16]


def write_cache(root: Path, entries: list) -> None:
    """Serialise the identity view, swapped in atomically.

    Written through a temp file and `os.replace` so a crash or a concurrent
    reader never sees a half-written cache — a truncated index is worse than no
    index, because it looks like a ledger with entries missing.
    """
    _save_cache(root, [cache_row(e.slug, e.question, e.alt_terms) for e in entries])


def cache_row(slug: str, question: str, alt_terms: list[str]) -> dict:
    """One row: slug and question because they are displayed, tokens because they score.

    `alt_terms` is deliberately not stored. It exists only to widen the token set,
    and the token set is persisted — keeping the prose too would be the same words
    twice, and it is the longest field an entry has.
    """
    text = " ".join([question, slug.replace("/", " ").replace("-", " ")] + alt_terms)
    return {"s": slug, "q": question, "t": " ".join(sorted(set(normalize(text))))}


def _save_cache(root: Path, rows: list[dict]) -> None:
    count, newest, paths = cache_stamp(root)
    payload = {"v": CACHE_VERSION, "count": count, "newest": newest,
               "paths": paths, "rows": rows}
    tmp = root / (CACHE_NAME + ".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, root / CACHE_NAME)
    except OSError:
        tmp.unlink(missing_ok=True)


def _load_cache_payload(root: Path) -> dict | None:
    path = root / CACHE_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("v") == CACHE_VERSION else None

_restamp_root: Path | None = None

def restamp_cache(root: Path) -> None:
    """Note that a write moved an mtime; the actual re-stamp happens at exit.

    Every mutation the ledger has — `sign`, `refute`, `promote`, a lint
    fixup — touches claims, evidence or signatures, none of which the cache
    stores. But all of them move the file's mtime, so the stamp goes stale and
    the next `resolve` rebuilds from every file on disk to reconstruct rows it
    already had, byte for byte. On a small ledger that rebuild is invisible; on a
    large one it lands after every single signature.

    Deferred rather than immediate because `lint --fix` writes in a loop, and a
    stamp per write would walk the whole tree once per entry — turning the fix
    it exists to avoid into a quadratic one. One re-stamp per process covers any
    number of writes, since the stamp describes the tree as it finally stands.
    """
    global _restamp_root
    _restamp_root = root


def reset_restamp() -> None:
    """Drop the pending re-stamp. For tests that work in a directory they delete.

    A module-level `global` only ever rebinds a name in its own module, so a
    caller in another file cannot clear this by assigning to it — it would
    silently create a second variable of the same name and leave this one set.
    """
    global _restamp_root
    _restamp_root = None


def _flush_restamp() -> None:
    """Refresh the three validation fields, keeping the rows.

    Silent when there is no cache yet, or when the on-disk one is a version this
    build does not read — both cases simply rebuild on the next read.
    """
    if _restamp_root is None:
        return
    data = _load_cache_payload(_restamp_root)
    if data is None:
        return
    count, _newest, paths = cache_stamp(_restamp_root)
    # Only mtimes are allowed to have moved. If the path set or the count differs
    # the rows are stale for a reason this process did not cause, and re-stamping
    # would certify content nobody checked. After a folder
    # split, for example, `git mv` renames the entries; re-stamping the old rows
    # as fresh would let `resolve` serve slugs whose files are gone while the
    # stamp matched the tree perfectly.
    if (data.get("count"), data.get("paths")) != (count, paths):
        return
    _save_cache(_restamp_root, data["rows"])

atexit.register(_flush_restamp)



def add_cache_row(root: Path, slug: str, question: str, alt_terms: list[str]) -> None:
    """Insert one entry's row, for `new` — the only command that adds identity."""
    data = _load_cache_payload(root)
    if data is None:
        return
    rows = [r for r in data["rows"] if r.get("s") != slug]
    rows.append(cache_row(slug, question, alt_terms))
    _save_cache(root, sorted(rows, key=lambda r: r["s"]))


def read_cache(root: Path) -> list[CachedEntry] | None:
    """The cached identity view, or None if it cannot be trusted."""
    data = _load_cache_payload(root)
    if data is None:
        return None
    try:
        count, newest, paths = cache_stamp(root)
        if (data.get("count"), data.get("newest"), data.get("paths")) != (count, newest, paths):
            return None
        return [CachedEntry(r["s"], r["q"], [], set(r["t"].split()))
                for r in data["rows"]]
    except (OSError, KeyError, TypeError, AttributeError):
        return None          # a corrupt cache is a rebuild, never an error


def index_entries(root: Path, kind: str | None = None) -> list:
    """Identity view for scoring — from cache when the tree stamp still matches.

    The stamp, not git: an ignore rule can hide an entry from git entirely, and a
    cache validated that way would serve a ledger with files silently missing.
    See `cache_stamp`.

    Writes keep the cache current in place rather than invalidating it, so this
    full rebuild is the fallback for changes nothing announced — a `git pull`, a
    hand edit, a `git mv`.
    """
    cached = read_cache(root)
    if cached is not None:
        for c in cached:
            c.kind = kind
        return cached
    entries = load_entries(root, kind)
    rows = [cache_row(e.slug, e.question, e.alt_terms) for e in entries]
    _save_cache(root, rows)
    return [CachedEntry(r["s"], r["q"], [], set(r["t"].split()), kind) for r in rows]


def load_entries(root: Path, kind: str | None = None) -> list[Entry]:
    return [Entry(p, root, kind) for p in sorted(root.rglob("*.md"))
            if p.name != "INDEX.md" and not p.name.endswith(".debate.md")]


def all_entries(ledgers: list[Ledger]) -> list[Entry]:
    return [e for lg in ledgers for e in load_entries(lg.root, lg.kind)]


def all_index(ledgers: list[Ledger]) -> list:
    """Identity view across every ledger — one scoring corpus, two homes.

    Scoring the union rather than one root at a time is the whole point of
    running two ledgers: the resolver exists to stop a question being asked
    twice, and a duplicate is no less a duplicate for sitting on the other side
    of the local/shared line. Search each root separately and the first thing
    you lose is the cross-boundary catch.
    """
    return [e for lg in ledgers for e in index_entries(lg.root, lg.kind)]


def tag_of(e, ledgers: list[Ledger]) -> str:
    """`[local]` / `[shared]`, or nothing at all when only one ledger is open."""
    return f"  [{e.kind}]" if e.kind and len(ledgers) > 1 else ""


def find_entry(root: Path, slug: str, kind: str | None = None) -> Entry:
    path = (root / slug).with_suffix(".md")
    if not path.is_file():
        sys.exit(f"no entry at {path}")
    return Entry(path, root, kind)
