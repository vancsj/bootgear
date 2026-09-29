"""Token identity and candidate ranking — how `resolve` decides what you asked.

Only the question is scored: an entry's identity is the question it settles, not
the claim that answers it or the command that checks it.
"""
from __future__ import annotations

import math
import re

from .constants import CUT_MIN_KEEP, CUT_WINDOW, SLUG_MAX_TOKENS, STOPWORDS


def normalize(text: str, stem: bool = True) -> list[str]:
    """Tokens for matching (stemmed) or for naming (not).

    Stemming is crude suffix-stripping, which is fine for deciding that two
    questions are about the same thing and wrong for anything a human reads:
    it turns `spring` into `spr` and `corpus` into `corpu`. So it stays on for
    scoring and comes off for minting, where the output becomes a filename that
    outlives the session that typed the query.
    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS:
            continue
        if stem and len(w) > 4:
            for suffix in ("ness", "ing", "ed", "es", "s"):
                if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                    w = w[: -len(suffix)]
                    break
        if w not in out:
            out.append(w)
    return out


def mint_slug(text: str) -> str:
    tokens = normalize(text, stem=False)[:SLUG_MAX_TOKENS]
    return "-".join(tokens) if tokens else "unnamed"


def match_score(query: set, entry_tokens: set, entries: list) -> float:
    """How much of the QUERY this entry accounts for, rare words counting most.

    Not Jaccard: dividing by the union penalises an entry for being richly
    described, so every `alt_terms` line added to help retrieval made the entry
    harder to find. Dividing by the query instead means a long entry is never
    punished for its length. Rare tokens are weighted up because one hit on a
    long, rare compound says far more than three hits on a word half the ledger
    contains.

    The score is then damped by how much of the raw query was judgeable at all.
    Without it, a query whose distinctive words appear in no entry scores on its
    leftovers alone, and can reach a perfect 1.00 against a wholly unrelated entry
    on two common words. A perfect score read off a fraction of the question is
    what a duplicate gets minted on, so the top of the range has to mean the whole
    question was accounted for, not the part we could read.
    """
    if not query or not entry_tokens:
        return 0.0
    return build_scorer(query, entries)(entry_tokens)


def build_scorer(query: set, entries: list):
    """Precompute the per-query weights once, return a scorer over token sets.

    `df` depends only on the query and the corpus, never on the candidate, so it is
    computed here once rather than inside the per-candidate score, which would
    cost |query| × N² tokenisations per resolve instead of |query| × N.
    `match_score` stays a thin wrapper for the selftest and one-off callers.
    """
    n = max(len(entries), 1)
    df = {t: sum(1 for e in entries if t in e.tokens()) for t in query}
    # A token no entry contains cannot discriminate between entries; scoring it
    # at maximum rarity would let incidental words ("start", "real", "server")
    # dilute a decisive match on a rare one away to nothing.
    discriminating = {t for t in query if df[t]}
    if not discriminating or not query:
        return lambda entry_tokens: 0.0
    weight = {t: math.log(n / (1 + df[t])) + 1.0 for t in discriminating}
    total = sum(weight.values())
    damping = len(discriminating) / len(query)

    def score(entry_tokens: set) -> float:
        if not entry_tokens or not total:
            return 0.0
        hit = sum(weight[t] for t in discriminating & entry_tokens)
        return round((hit / total) * damping, 4)

    return score


def cut_candidates(pairs: list, window: int = CUT_WINDOW,
                   min_keep: int = CUT_MIN_KEEP) -> list:
    """Cut the ranked list at its largest drop, not at a constant.

    A fixed threshold ages badly: token weights shift as the ledger grows, so
    the same 0.30 admits steadily more marginal entries. The gap between a real
    match and the rest is scale-free, and it is what a reader is actually
    looking for when they scan the list.

    `min_keep` is deliberate. Cutting to a single candidate would turn "is this
    the same question?" into a rubber stamp; a runner-up to compare against is
    what keeps it a judgement.
    """
    if len(pairs) <= min_keep:
        return pairs
    w = pairs[:window]
    gaps = [(w[i][0] - w[i + 1][0], i + 1) for i in range(len(w) - 1)]
    # Ties go to the earlier (tighter) cut: -i breaks on the smaller index.
    best_at = max(gaps, key=lambda g: (g[0], -g[1]))[1]
    return w[:max(min_keep, best_at)]


def query_coverage(query: set, entries: list) -> tuple[int, int]:
    """(query tokens some entry contains, query tokens total).

    Printed beside every candidate so a reader can see what the score is a
    score OF. `0.80 (2/5 terms)` and `0.80 (5/5 terms)` are not the same claim
    about relevance, and only one of them is worth reading further.
    """
    known = sum(1 for t in query if any(t in e.tokens() for e in entries))
    return known, len(query)
