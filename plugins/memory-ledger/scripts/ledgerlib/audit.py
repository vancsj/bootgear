"""`audit`: the one portability fact a program can settle, plus the raw material for the rest.

The one thing a regex here may assert is about path shape, not path owner:

  UNPORTABLE  the Evidence line names a filesystem path that is neither
              relative (resolves under whoever's cwd runs it — the repo the
              question is about) nor a fixed system path every install shares
              (/etc, /usr, /bin, /opt, /var, /Applications) or a tool's own
              fixed cache dir (~/.gradle, ~/.m2, ...). Everything else that
              names a path — /Users/…, /home/…, any ~/… at all including the
              ledger's own ~/<checkout> convention, a Claude Code scratchpad
              — names this account's own layout or a session's temporary
              directory, not something guaranteed to exist for the next
              reader. A path that must survive between machines belongs in
              `Repo:`/`--repo`, which names the checkout instead of guessing
              where it sits.

              A URL is not a path and is always exempt.

**Which ledger an entry belongs in is never decided here.** Sorting entries by
pattern would mislabel: a path under `~/` looks personal but is often a
convention the whole team shares, so shared facts would be filed as
machine-local with total confidence. That holds for the *claim* an answer
makes — no heuristic sorts those, `--json` dumps every one uncategorised for
a reader to judge. It does not hold for the *check*: whether a path is
rerunnable from a location every session has is a fact about the string, so
the check is sorted mechanically even where the claim can't be.

The question a reader applies to each *claim*:

    Could someone else, on their own machine, run an equivalent check and get
    the same answer?

No → the entry belongs in the local ledger. Yes, but only once some local
state exists → the entry is shared and the CHECK is the defect: when that
state is absent the command exits non-zero with no output, indistinguishable
from a proven absence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .store import load_entries

# Any absolute or `~`-relative path. A relative path (no leading `/` or `~`)
# never matches — it resolves under whoever's cwd runs the check, the one
# location every session has: the repo the question is about. The lookbehind
# also excludes a URL's `//` (as in `https://host/path`): a scheme's colon is
# not a word character, so a plain "not preceded by \w or /" miscounts that
# slash as a path start.
_PATH_CANDIDATE = re.compile(r"(?<![\w/:])/(?!/)[\w./-]*/|(?<![\w/])~[\w./-]*/")

# A tool's own fixed cache dir — same shape on anyone's machine that has the
# tool, not a name the author chose. Unlike ~/<checkout>, where the checkout's
# location and name are the author's own convention.
_TOOL_CACHE = re.compile(r"^~/\.(?:gradle|m2|npm|cargo|rustup|cache|nvm|rbenv|pyenv|venv)/")

# A fixed system path every install shares — not this account's layout.
_SYSTEM_PATH = re.compile(r"^/(?:etc|usr|bin|sbin|opt|var|Applications|Library|System)/")


def unportable_paths(evidence: str) -> list[str]:
    """Every /Users/, /home/, or ~/-anything path (~/<checkout> included) and
    every Claude Code scratchpad (/tmp/claude-<uid>/<project>/<session-uuid>/…,
    or /private/tmp on macOS — deleted with the session, so not even this
    machine can rerun it later), minus tool caches and system paths.
    """
    candidates = {m.group(0) for m in _PATH_CANDIDATE.finditer(evidence)}
    return sorted(p for p in candidates
                  if not _TOOL_CACHE.match(p) and not _SYSTEM_PATH.match(p))


def _answers(ledgers, filter_text):
    for lg in ledgers:
        for e in load_entries(lg.root, lg.kind):
            if Path(e.slug).name == "_about":
                continue
            if filter_text and filter_text not in e.slug \
                    and filter_text.lower() not in e.question.lower():
                continue
            for a in e.answers:
                if a.evidences:
                    yield lg, e, a


def cmd_audit(args, root=None):
    ledgers = args.ledgers
    rows = list(_answers(ledgers, args.filter))

    if args.json:
        # Everything, uncategorised. A session reads these and decides; nothing
        # here has pre-judged which are worth its attention.
        print(json.dumps([{
            "ledger": lg.kind,
            "slug": e.slug,
            "answer": a.aid,
            "question": e.question,
            "claim": a.claim,
            "evidence": [ev.removeprefix("Evidence:").strip() for ev in a.evidences],
            "unportable": unportable_paths("\n".join(a.evidences)),
        } for lg, e, a in rows], indent=2))
        return 0

    flagged = 0
    for lg, e, a in rows:
        # In the local ledger an absolute home path is portable enough — that
        # ledger never leaves the machine it describes.
        if lg.kind == "local":
            continue
        paths = unportable_paths("\n".join(a.evidences))
        if not paths:
            continue
        flagged += 1
        tag = f"  [{lg.kind}]" if len(ledgers) > 1 else ""
        print(f"UNPORTABLE  {e.slug} {a.aid}{tag} — hardcodes {', '.join(paths)}")
        for ev in a.evidences:
            print(f"            {ev}")

    print(f"\n{flagged} unportable, of {len(rows)} answers with an Evidence line.")
    if flagged:
        print("Answer bodies are immutable, so this is fixed by adding an answer that "
              "carries a portable check — `ledger.py rival <slug> --keep-evidence <aN> "
              "--evidence \"…\"` using a repo-relative path, or --repo <name> to name the "
              "checkout instead of embedding its location. The new answer starts "
              "unconfirmed and earns its own votes.")
    print("\nWhich ledger each entry belongs in is not decided here and has no heuristic. "
          "`ledger.py audit --json [--filter <text>]` dumps every answer with its question, "
          "claim and check; read them and ask whether someone else, on their own machine, "
          "would get the same answer.")
    return 0
