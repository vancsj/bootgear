"""The value types, and the two numbers that must come out identical for everyone.

`h=` is what a signature is a signature OF, and `conf` is how many independent
sessions ran the check and agreed. Both are computed, never typed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import date
from pathlib import Path

from .config import load_config
from .context import InvocationContext, contextual_path
from .constants import (
    CONF_CAP,
    CONFIRMED_AT,
    DISPUTE_PENALTY,
    HASH_LEN,
    MAINLINE_CANDIDATES,
    REF_RE,
    REPO_RE,
    SEED_CONF,
    VERIFY_DECAY,
    WELL_CONFIRMED_AT,
)


def answer_hash(claim: str, because_line: str, ref_line: str | None = None) -> str:
    """claim + `Because:` + `Ref:` — what a signature asserts.

    `Evidence:` and `Repo:` are out: they record how and where the claim is
    checked, not what it says, so appending a check or naming a repo voids no
    signature. `EVIDENCE-REWRITTEN` in `lint` is what stops a check being swapped
    rather than added.

    `Ref:` joins only when present, so entries written before refs existed keep
    their signatures.
    """
    parts = [claim, because_line] + ([ref_line] if ref_line else [])
    body = "\n".join(s.rstrip() for s in parts)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:HASH_LEN]


def confidence(yes: int, no: int) -> float:
    """How many independent sessions ran the check and agreed, capped below 1.00.

    Uncapped, nine independent ✓ round to 1.00 — the value an `Asserted:` header
    carries, so a tally would print a human's ruling.
    """
    raw = (1 - (1 - SEED_CONF) * VERIFY_DECAY ** yes) * DISPUTE_PENALTY ** no
    return min(round(raw, 2), CONF_CAP)


def band(conf: float) -> str:
    """A description of how much corroboration exists, never a permission.

    Nothing here filters or suppresses: every answer is returned at every level,
    and the reader decides by running the `Evidence:` line. The number reports
    how many independent sessions got the same result — it does not stand in for
    the check, and no threshold makes it able to.
    """
    if conf < CONFIRMED_AT:
        return "unconfirmed"
    if conf > WELL_CONFIRMED_AT:
        return "well-confirmed"
    return "confirmed"


def resolve_repo(context: InvocationContext | None = None) -> Path | None:
    """The checkout a `Ref:` is resolved against — normally just where you are.

    `Ref:` is optional and most entries have none, so this needs no setup and no
    config: it takes the git repo containing the current directory, which is
    already the right one. Evidence lines are written to run from the checkout
    the question is about, so a session verifying an entry is standing in it.

    `repo:` in the config file still wins if set. There is no hardcoded
    fallback: one project's path baked in here would make every branch claim
    read `missing` for anyone else, and `lint` turns `missing` into "drop the
    entry".
    """
    configured = ((context.repo if context is not None else None)
                  or load_config(context).get("repo")
                  or os.environ.get("LEDGER_REPO"))
    if configured:
        return contextual_path(str(configured), context)
    top = subprocess.run(["git", "-C", str(context.cwd if context else Path.cwd()),
                          "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    return Path(top.stdout.strip()) if top.returncode == 0 else None


def repo_name(path: Path | None = None,
              context: InvocationContext | None = None) -> str | None:
    """A short name for a checkout: its origin remote's repo, else its directory.

    The remote is preferred because it is the same string on everyone's machine,
    while a directory name is whatever the person who cloned it happened to type.
    """
    repo = path if path is not None else resolve_repo(context)
    if repo is None:
        return None
    url = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                         capture_output=True, text=True)
    if url.returncode == 0 and url.stdout.strip():
        return url.stdout.strip().rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return repo.name


_MAINLINE_CACHE: dict[str, str | None] = {}


def _detect_mainline(here: Path) -> str | None:
    def git(*a):
        return subprocess.run(["git", "-C", str(here), *a],
                              capture_output=True, text=True)

    # `origin/HEAD` is the authoritative answer where it exists, but `clone` is
    # the only thing that sets it — a repo created locally, or given a remote
    # after the fact, has none at all. So it is asked first and never relied on.
    head = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip().removeprefix("refs/remotes/")
    for candidate in MAINLINE_CANDIDATES:
        if git("rev-parse", "--verify", "--quiet",
               f"{candidate}^{{commit}}").returncode == 0:
            return candidate
    return None


def mainline_ref(here: Path | None = None,
                 context: InvocationContext | None = None) -> str | None:
    """The ref this repo calls mainline: env, then config, then ask git.

    Discovered per repo rather than assumed, in the same resolution order
    `resolve_repo` uses for `repo` — a ledger is read from whatever checkout the
    question is about, so the mainline is a property of that checkout and not of
    whoever wrote the tool.

    Returns None when nothing resolves, and callers turn that into `unknown`
    rather than a guess. A hardcoded `origin/master` would fail *silently*,
    because a ref that resolves to nothing is indistinguishable from a branch
    that simply has not merged yet — every landed branch would read `live`
    forever, `lint` would never report REF-LANDED, and `promote` would refuse
    with "is not yet in origin/master".
    """
    configured = ((context.ref if context is not None else None)
                  or os.environ.get("LEDGER_REF")
                  or load_config(context).get("ref"))
    if configured:
        return str(configured)
    if here is None:
        here = resolve_repo(context)
    if here is None:
        return None
    key = str(here)
    if key not in _MAINLINE_CACHE:
        # Memoised per checkout: `lint` calls this once per ref-scoped answer, and
        # the answer cannot change inside one process.
        _MAINLINE_CACHE[key] = _detect_mainline(here)
    return _MAINLINE_CACHE[key]


def same_repo(named: str | None,
              context: InvocationContext | None = None) -> bool:
    """Whether the checkout we are standing in is the one an answer names.

    Compared on the last path segment, case-insensitively, so `widgets`,
    `acme/widgets` and `git@github.com:acme/widgets.git` all name the same repo.
    An unnamed repo matches anything — absent means unknown, not mismatched.
    """
    if not named:
        return True
    here = repo_name(context=context)
    if here is None:
        return False
    want = named.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return here.lower() == want.lower()


def ref_state(ref: str, repo: str | None = None,
              context: InvocationContext | None = None) -> str:
    """live | merged | missing | unknown — where a branch claim stands right now.

    `repo` is the answer's `Repo:` value. When it names a checkout other than the
    one we are standing in, the honest answer is `unknown`: this process cannot
    see that repo's refs at all. Resolving the branch against the local repo
    instead makes every ref-scoped entry report REF-GONE from any other directory
    — a line that tells the reader to delete a verified entry, on evidence that
    was only ever about the caller's cwd.

    `merged` is detected by ancestry rather than by the branch being deleted, so
    an entry is flagged the moment its claim becomes a mainline claim, not
    whenever someone gets round to tidying the branch up.

    `unknown` means there is no repo to ask — you are not in one, or this repo
    has no discoverable mainline to measure against. Distinct from `missing` on
    purpose, and silent: `missing` tells a reader to drop the entry, and saying
    that merely because of where a command was run from would delete a verified
    fact over a `cd`.
    """
    if not same_repo(repo, context):
        return "unknown"
    here = resolve_repo(context)
    if here is None or not (here / ".git").exists():
        return "unknown"

    def git(*a):
        return subprocess.run(["git", "-C", str(here), *a],
                              capture_output=True, text=True).returncode

    mainline = mainline_ref(here, context)
    for candidate in (ref, f"origin/{ref}"):
        if git("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}") == 0:
            # No discoverable mainline means the merge question cannot be asked,
            # not that the answer is no. Reporting `live` here is what the old
            # hardcoded ref did, and it is a false negative that never expires.
            if mainline is None:
                return "unknown"
            merged = git("merge-base", "--is-ancestor", candidate, mainline) == 0
            return "merged" if merged else "live"
    return "missing"


def split_evidence(yes: int, no: int) -> bool:
    """Both marks standing on the same body.

    A deterministic check cannot pass for one session and fail for another, so a
    split says the `Evidence:` line depends on something it does not name —
    branch, build state, a local file. That is a defect in the check, not a
    verdict on the claim, and it is why `✗` counts as a vote and never a veto.
    """
    return yes > 0 and no > 0


class Answer:
    def __init__(self, aid, claim, conf, checked, asserted, header_idx):
        self.aid = aid
        self.claim = claim
        self.conf = conf
        self.checked = checked
        # A human pinned this at 1.00, for a question no check can settle. It
        # suspends the tally's hold on the header and nothing else.
        self.asserted = asserted
        # `Asserted: <who> <date> — <why>`, the record of who ruled and on what.
        # Absent on a header pinned by hand, which is what ASSERT-UNRECORDED is for.
        self.asserted_line = None
        self.header_idx = header_idx
        self.because = None
        # Every `Evidence:` line on this answer, in file order. A list because a
        # claim can have more than one way to check it, and chaining them into
        # one shell line was hiding failures: with `;` the chain exits 0 on a
        # partial run, so a session reads success and signs a check it never
        # completed. Separate lines are run and reported separately.
        self.evidences: list[str] = []
        self.ref = None
        # The checkout this answer's checks belong to. Absent on every answer
        # written before the field existed, so nothing may treat absent as a
        # default: guessing a repo would give a check a home it was never given.
        self.repo = None
        self.last_body_idx = header_idx
        # The last line belonging to this answer, whatever it is. Distinct from
        # last_body_idx, which only advances on a line the parser recognises: a
        # signature's recorded output matches nothing, so appending at
        # last_body_idx + 1 would land inside the previous signature's block.
        self.last_line_idx = header_idx
        self.sigs: list[dict] = []

    @property
    def evidence(self) -> str | None:
        """The first check, for callers that only need one line to display."""
        return self.evidences[0] if self.evidences else None

    @property
    def hash(self) -> str | None:
        # None without a check: `sign` reads that to refuse an untestable answer.
        if self.because is None or not self.evidences:
            return None
        return answer_hash(self.claim, self.because, self.ref)

    @property
    def ref_value(self) -> str | None:
        """The code ref this claim is scoped to, or None if it is not code-scoped.

        Absent is a real third state, not a default: plenty of settled questions
        are not about code at all, and inventing a mainline ref for one would
        invite a ref check that can only ever be meaningless.
        """
        return REF_RE.match(self.ref).group(1) if self.ref else None

    @property
    def repo_value(self) -> str | None:
        """The checkout the Evidence lines are meant to run in, or None.

        Absent is a real state, never a default. A question that is not about a
        codebase has no repo, and inventing one would invite a mismatch warning
        that could only ever be noise.
        """
        return REPO_RE.match(self.repo).group(1) if self.repo else None

    @property
    def scope_label(self) -> str:
        bits = []
        if self.repo_value:
            bits.append(f"repo {self.repo_value}")
        if self.ref_value:
            bits.append(f"ref {self.ref_value}")
        return " · ".join(bits) if bits else "unscoped"

    def tally(self) -> tuple[int, int, int]:
        """(valid ✓, valid ✗, voided) against the current body."""
        current = self.hash
        yes = no = void = 0
        for sig in self.sigs:
            if current is None or sig["hash"] != current:
                void += 1
            elif sig["mark"] == "✓":
                yes += 1
            else:
                no += 1
        return yes, no, void

    def independent(self) -> int:
        """Valid sigs from sessions other than the one that wrote the answer.

        The author's own vote is real — they ran the check to write the line —
        but it corroborates nothing, so the two are counted separately.
        """
        current = self.hash
        return sum(1 for s in self.sigs
                   if s["hash"] == current and not s["author"])


def sig_line(mark: str, who: str, h: str, depth: int, author: bool = False) -> str:
    """`e=N` is how many checks the answer carried when this was cast.

    Signatures survive an append, so without it `conf` would imply every signer
    ran every check.
    """
    return (f"    {mark} {who:<8} {date.today()}  h={h}  e={depth}"
            + ("  (author)" if author else ""))


def author_sig(who: str, h: str, depth: int) -> str:
    return sig_line("✓", who, h, depth, author=True)


def render_header(a: Answer, conf: float, checked: str) -> str:
    left = f"## {a.aid} · {a.claim}"
    right = f"conf {conf:.2f} · " + ("asserted" if a.asserted else f"checked {checked}")
    return left + " " * max(2, 62 - len(left)) + right


def asserted_line(who: str, why: str) -> str:
    return f"Asserted: {who} {date.today()} — {why}"


def git_user() -> str | None:
    """The human's name, for an `Asserted:` line.

    The one place the ledger records a person rather than a session: an assertion
    is a human's ruling, so a session id would name the wrong party.
    """
    p = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True)
    return p.stdout.strip() or None if p.returncode == 0 else None
