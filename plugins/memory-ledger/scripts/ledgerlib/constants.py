"""Every tunable the ledger's behaviour depends on, in one place.

Split out so the numbers that decide what the tool does are readable as a set
rather than scattered through the code that consumes them. The ones that carry
meaning — the confidence anchors, the band edges, the hash length — are pinned
by `selftest`, so changing one here without changing it there is a failing test
rather than a silent behaviour change.
"""
import re

SEED_CONF = 0.30


VERIFY_DECAY = 0.55


DISPUTE_PENALTY = 0.80


CONFIRMED_AT = 0.45


WELL_CONFIRMED_AT = 0.75


# 1.00 is a human's `Asserted:` ruling. Uncapped, nine independent ✓ round to
# 1.00 and a counted tally prints it too.
CONF_CAP = 0.99


HASH_LEN = 6


# A garbage floor, not the decision. Where candidates get cut is the largest
# gap in the ranking (see cut_candidates). An absolute threshold ages badly: token
# weights shift as a ledger grows, so the same number admits steadily more marginal
# entries, and it admits most of them exactly when a query is paraphrased — which is
# when the reader most needs a short list.
FUZZY_FLOOR = 0.15


CUT_WINDOW = 12


CUT_MIN_KEEP = 2


SLUG_MAX_TOKENS = 4


GROUP_MIN_MEMBERS = 3


# Above this many direct entries, a folder stops being a place you can read and
# becomes a list you scroll. It is a lint report, never a refusal: filing is a
# judgement about meaning, and blocking a session mid-task over one buys nothing
# the next lint run would not have said just as well.
#
# Set high on purpose. A low cap turns OVERSIZE into a permanent fixture that fires
# on folders nobody would call crowded, and a report that is always on is a report
# nobody reads. 50 is the point at which a folder listing stops fitting on a screen.
FOLDER_MAX_ENTRIES = 50

# REGROUP is a warning shot before a folder hits the cap, so it stays quiet until
# a folder is at least halfway there. Reporting a 3-token cluster inside a 5-entry
# folder is self-perpetuating: a new folder is grouped on a shared token by
# construction, so it immediately proposes splitting itself on the next token
# down, and the category fills with advice nobody can act on.
REGROUP_MIN_FOLDER = FOLDER_MAX_ENTRIES // 2


CLAIM_MAX_WORDS = 40


RESOLVE_MAX_FOLDERS = 4


RESOLVE_MAX_PER_FOLDER = 3


# A rival author needs every sibling claim in full to judge how theirs differs,
# but not every check ever appended to it — `add-evidence` only grows that list,
# so an old, heavily-verified answer can carry a dozen. 3 is enough to see what
# kind of check the answer rests on and decide whether to `--keep-evidence`.
SIBLING_MAX_EVIDENCE = 3


STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "do", "does",
    "did", "what", "which", "who", "how", "why", "when", "where", "to", "for",
    "of", "in", "on", "at", "by", "with", "from", "this", "that", "these",
    "those", "it", "its", "we", "our", "us", "you", "your", "they", "their",
    "and", "or", "but", "if", "should", "must", "can", "will", "have", "has",
    "repo", "repos", "repository", "project", "use", "uses", "used", "using",
    # Negation is the ANSWER's polarity, never the question's identity. "Is A B?"
    # and "Is A not B?" are one question with opposite answers, so scoring the
    # negation splits a single question in two: asking the same question in
    # negated form scores WORSE than asking it
    # plainly, because `not` either matches nothing and takes the damping penalty
    # or matches unrelated entries that happen to contain it.
    # This is also why a slug like `no-nested-transactions` collapsing to
    # `nested-transactions` is correct rather than lossy — the polarity lives in
    # the claim, not in the filename.
    "no", "not", "never", "none", "nobody", "nothing", "neither", "nor",
    "cannot", "without", "any", "ever",
}


# `proven` is the legacy spelling of `assert`. A header this does not match parses as no
# answer at all, so dropping the alternative deletes any entry written under it.
# Nothing writes `proven`; `lint` reports one as ASSERT-UNRECORDED.
ANSWER_RE = re.compile(
    r"^##\s+(a\d+)\s+·\s+(.*?)\s+conf\s+([0-9]*\.?[0-9]+)\s+·\s+"
    r"(?:checked\s+(\d{4}-\d{2}-\d{2})|(asserted|proven))\s*$"
)


# Who pinned this answer at 1.00, and what settles it. Outside the answer hash,
# like `Repo:` and `Evidence:` — it records that a human ruled, not what the
# claim says, so pinning voids no signature.
ASSERTED_RE = re.compile(r"^Asserted:\s*(.+?)\s*$")


# `e=N` is how many checks the answer carried when this signature was cast. Optional,
# so signatures written before it parse unchanged and read as "depth unknown".
SIG_RE = re.compile(
    r"^\s+([✓✗])\s+(\S+)\s+(\d{4}-\d{2}-\d{2})\s+h=([0-9a-f]+)(?:\s+e=(\d+))?"
    r"(\s+\(author\))?(?:\s*→\s*debate)?\s*$"
)


# A recorded run's output, attached under its signature. Blockquoted rather than
# fenced so output containing a sig line or an answer header cannot parse as one.
OUTPUT_RE = re.compile(r"^\s+>\s?(.*)$")


OUTPUT_PREFIX = "    > "


Q_RE = re.compile(r"^Q:\s*(.+?)\s*$")


ALT_RE = re.compile(r"^alt_terms:\s*(.+?)\s*$")


USE_RE = re.compile(r"^USE:\s*(\S+)\s*$")


BECAUSE_RE = re.compile(r"^Because:\s*(.+?)\s*$")


EVIDENCE_RE = re.compile(r"^Evidence:\s*(.+?)\s*$")


REF_RE = re.compile(r"^Ref:\s*(\S+)\s*$")

# Which checkout the Evidence lines are meant to run in. Independent of
# REF_RE: most answers name no branch, but plenty are still about one
# specific codebase, and those are exactly the ones whose checks silently
# assume whatever directory the reader happens to be sitting in.
#
# Deliberately NOT part of the answer hash, unlike Ref. Naming the repo
# records where a check was always meant to run; it does not change what is
# claimed, and a claim never migrates to a different repo over its life. So
# it can be set later on an answer that already has signatures without
# voiding them, which is the only way the field can ever reach the answers
# written before it existed.
REPO_RE = re.compile(r"^Repo:\s*(\S+)\s*$")


# Used only when git cannot answer; the mainline is discovered per repo — see
# model.mainline_ref. A ref that does not resolve is indistinguishable from an
# unmerged branch, so a wrong assumption here fails silently.
FALLBACK_REF = "origin/main"


# Tried in order when `origin/HEAD` is unset — only `clone` populates it.
MAINLINE_CANDIDATES = ("origin/main", "origin/master", "main", "master")


SHARED, LOCAL = "shared", "local"


KINDS = (SHARED, LOCAL)


# A dot-directory of the tool's own, never inside a source tree. Where someone
# keeps their checkouts is a filing habit, not something a default may assume —
# `$HOME` is the only directory that exists for everybody. Setting
# `memory.root` / `memory.local_root` overrides these.
DEFAULT_SHARED_ROOT = "~/.memory-ledger/shared"


DEFAULT_LOCAL_ROOT = "~/.memory-ledger/local"


CACHE_NAME = ".ledger-cache.json"


CACHE_VERSION = 2        # bump whenever a row's shape changes; an older cache rebuilds


BROKEN_EVIDENCE = re.compile(
    r"command not found|no such file or directory|file not found|cannot access"
    r"|fatal:|unrecognized option|syntax error|is a directory|permission denied", re.IGNORECASE)


DUPLICATE_GATE = 0.85


SLUG_ADDRESSED = {"show", "hash", "sign", "refute", "promote", "rival", "set-repo",
                  "add-evidence", "assert"}
