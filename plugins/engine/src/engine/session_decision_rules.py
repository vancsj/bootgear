"""Parse and validate debate entries."""

from __future__ import annotations

import re

DEBATE_MODES = {"debate", "debate-capped", "debate-degraded", "scope-settled"}
ALL_MODES = DEBATE_MODES | {"solo", "resolve"}
QUESTION_ID_RE = re.compile(r"\Aq[0-9]+\Z")
QUESTION_TAG_RE = re.compile(r"^\[(q[0-9]+)\]\s")
# Matches a full decision line as record-decision writes it: "- <ts> [<mode>]
# [<qid>] <summary>" (tag omitted for non-debate modes). Anchored on the mode
# bracket so a solo/resolve summary that happens to start with "[qN] " text
# is never mistaken for a real tag — only entries whose actual --mode was a
# debate mode ever carry one.
DECISION_ENTRY_RE = re.compile(r"^- \S+ \S+ \[(?P<mode>[^\]]+)\] (?P<rest>.*)$")
# A single bracket group: "[...]" with no nested brackets inside.
_BRACKET_GROUP_RE = re.compile(r"\[[^\[\]]*\]")
# The line's leading run: "- " (record-decision's fixed entry start), any
# non-bracket characters (the timestamp position, however malformed or
# padded), an optional run of stray "[" characters before the first real
# group (this is what lets a doubled opening bracket like "[[debate]" still
# find "[debate]" as a group instead of failing to match at all — a bare
# "[[..." has no substring matching "\[[^\[\]]*\]" until the SECOND "["),
# then a maximal run of bracket groups tolerating stray/unmatched closing
# bracket characters between them too (not just whitespace) — this is what
# lets a doubled closing bracket like "[debate]]" still be read as one
# bracket group followed by a stray "]", rather than breaking the run
# entirely the way a plain "one bracket group, then whitespace, then the
# next" pattern would. Only closing brackets are tolerated *between* groups,
# never opening ones — an opening bracket there would let the trailing
# tolerance eat into the next group's own opener, splitting one group into
# two matches that no longer read back as a single "[qN]"-shaped group (a
# normal "[mode] [q1]" shape's own "[" before "q1]" would be consumed as
# "trailing" tolerance after the mode group, leaving "q1]" with no opening
# bracket for `_BRACKET_GROUP_RE` to match). The run stops at the
# first character that is neither whitespace nor a bracket character, i.e.
# the first real prose content.
_LEADING_BRACKET_RUN_RE = re.compile(r"^- [^\[\]\n]*\[*((?:\[[^\[\]]*\][\]\s]*)+)")
_TAG_CONTENT_RE = re.compile(r"[qQ][0-9]+")


def _has_hidden_tag(entry: str) -> bool:
    """True if a `[qN]`-shaped bracket appears within the entry's leading
    run of bracket groups — the mode bracket and (if present) the tag
    bracket that follows it, however malformed either one is — rather than
    later in the entry's own free-text summary. Catches every way a tag can
    be hidden from `_parse_decision_entry` while still being unambiguously
    tag-shaped: a malformed or empty mode bracket ("- t t [] [q1] ..." — an
    empty bracket isn't `[^\\]]+`, so the whole line fails DECISION_ENTRY_RE
    and `_check_decisions_shape` would otherwise skip it via `if not parsed:
    continue`), an unknown mode, any run of whitespace between the mode
    bracket and the tag bracket, no space after the tag's closing "]", case
    variation ("[Q1]"), internal whitespace inside the tag's own brackets
    ("[ q1 ]"), an extra or missing whitespace-separated token before the
    mode bracket ("- 2000-01-01 00:00 extra [debate] [q1] ..." — a third
    token where DECISION_ENTRY_RE's fixed "\\S+ \\S+ " expects exactly two),
    a stray extra closing bracket inside or after the mode bracket
    ("[debate]] [q1] ..." — DECISION_ENTRY_RE's `[^\\]]+` mode-bracket
    content stops at the first "]", so the entry fails to parse at all, and
    a naive "one bracket group, then whitespace, then the next" adjacency
    check would also fail here since the stray "]" isn't whitespace), and a
    missing mode bracket entirely ("- 2000-01-01 00:00 [q1] round 1, ..." —
    DECISION_ENTRY_RE reads "[q1]" itself as the mode bracket, an unknown
    mode with no adjacent tag bracket that any narrower "tag right after the
    mode bracket" check would miss), and a stray extra OPENING bracket
    before the mode bracket ("- 2000-01-01 00:00 [[debate] [q1] ..." —
    DECISION_ENTRY_RE's mode-bracket content (`[^\\]]+`, no `[` excluded)
    reads the mode as the literal string "[debate" including the stray "[",
    an unknown mode with no bracket group at all for `_BRACKET_GROUP_RE` to
    find until the run's leading stray-"[" tolerance skips past it). Scans
    by bracket-group *sequence* within the leading run, not a fixed
    character-offset cutoff: an offset bound would also match real prose
    containing a `[qN]`-shaped bracket within roughly the first 40
    characters of a line (e.g. a `solo` entry's own summary discussing
    question tags), which is not a hidden tag at all. Bounding to the
    leading *bracket run* (stopping at the first non-bracket, non-whitespace
    content) keeps detection anchored to "adjacent to the mode bracket
    position," the same principle used everywhere else in this check,
    without being fooled by real prose elsewhere in the entry — for example
    a free-text mode entry and a `solo` entry that mentions `[q1]` later in
    its own prose (both correctly not flagged) and against a citation-style "[abc][q1]" deeper
    in real prose (also correctly not flagged, since it's not part of the
    line's leading run at all)."""
    m = _LEADING_BRACKET_RUN_RE.match(entry)
    if not m:
        return False
    return any(_TAG_CONTENT_RE.fullmatch(g[1:-1].strip())
               for g in _BRACKET_GROUP_RE.findall(m.group(1)))
# The only two valid shapes for a --mode debate summary, per debate/SKILL.md's
# "Recording" — a round entry ("round N, party '<role>': <content>") or the
# closing unanimous_convergence: outcome. Enforced so an ordinary round's free
# text can never accidentally start with "unanimous_convergence:" and get
# treated as the closing entry it isn't. Requires the quoted role and colon
# the documented shape actually specifies (not just "round N, party ", which
# would also match a role written without quotes or with no separator at
# all), and requires at least one non-space character after the colon so an
# empty position/response can't pass as a real round entry. The role uses
# `.+?` (non-greedy, matching the shortest span up to the first "':" that
# lets the rest of the pattern also match), not `[^']+` — a role containing
# its own apostrophe (e.g. a custom role literally named "reviewer's role",
# which execute's shape check for debate_parties permits, since it only
# requires role to be non-empty) would otherwise never match at all, since
# `[^']+` stops at that role's own internal apostrophe rather than the
# closing quote. `N` (the round number) is restricted to ASCII digits and
# includes 0 — round 0 is the scoping phase (topic/scope/principles/cutoff,
# independent-then-discuss), closed by a `scope-settled` entry before any
# round 1+ substance entry is legal; see debate/SKILL.md's "Round 0:
# scoping". Captured (not just shape-checked) so cmd_record_decision can
# enforce the round-sequencing rule below.
ROUND_ENTRY_RE = re.compile(r"\Around (?P<round>[0-9][0-9]*), party '.+?':\s*\S")


def _has_content_after_prefix(summary: str, prefix: str) -> bool:
    """True only if `summary` starts with `prefix` and something more than
    whitespace follows it — a closing summary that is just the bare prefix
    (e.g. "round_cap:" with nothing after it) carries none of the required
    content (question, tie-break, dissent, ...) and must not pass as a real
    closing entry."""
    return summary.startswith(prefix) and bool(summary[len(prefix):].strip())


def _parse_decision_entry(entry: str) -> tuple[str, str, str] | None:
    """Returns (mode, question_or_empty, summary) for one decision line, or
    None if it doesn't match the format record-decision writes. A [qN] tag
    is only ever recognized when the entry's actual mode is a debate mode —
    free text in a solo/resolve summary that happens to start with "[qN] "
    is never treated as a real tag."""
    m = DECISION_ENTRY_RE.match(entry)
    if not m:
        return None
    mode, rest = m.group("mode"), m.group("rest")
    if mode in DEBATE_MODES:
        tag = QUESTION_TAG_RE.match(rest)
        if tag:
            return mode, tag.group(1), rest[tag.end():]
    return mode, "", rest


def _is_closing_entry(mode: str, summary: str) -> bool:
    """debate-capped/debate-degraded are closing-only modes; debate is used
    for both in-progress rounds and the unanimous_convergence closing
    outcome, distinguished by the recording convention in debate/SKILL.md's
    "Recording" (a closing summary starts with its outcome name, a round
    entry starts with "round N"). `scope-settled` is deliberately excluded
    here: it closes only the round-0 scoping phase, not the question itself
    — round 1+ substance entries and the question's real close still follow
    it. See `_has_scope_settled`, the parallel check for that narrower
    meaning."""
    if mode in ("debate-capped", "debate-degraded"):
        return True
    if mode == "debate":
        return summary.startswith("unanimous_convergence:")
    return False


def _validate_decision_shape(mode: str, question: str | None, summary: str) -> list[str]:
    """Returns every error message for the ways `mode`/`question`/`summary`
    don't form one of the shapes `cmd_record_decision` allows writing; empty
    if they do.
    Called only from `cmd_record_decision`, never from `cmd_record_pitch` —
    a pitch is a progress report, not a shaped ledger entry, so none of
    these rules apply to it.

    Not shared with `_check_decisions_shape` (the read-time re-check) —
    that function re-implements its own narrower subset of these rules
    inline instead of calling this one, so a rule added here only applies
    at write time until `_check_decisions_shape` is updated to match. A
    hand-edited or otherwise corrupted historical entry that violates a
    rule only enforced here passes every later read unnoticed, the same
    corruption `_check_decisions_shape`'s own docstring warns against for
    the rules it does re-check."""
    problems: list[str] = []
    if question is not None and not QUESTION_ID_RE.match(question):
        problems.append(f"--question '{question}' must look like 'q1', 'q2', ... — "
                        f"get one with `next-question-id`, don't invent your own")
    if mode in DEBATE_MODES and question is None:
        problems.append(f"--mode {mode} requires --question <id> — every debate "
                        f"round and its closing entry must share one stable id so "
                        f"recall (and a later debate on a different question) can "
                        f"tell them apart without scanning free text; get the id "
                        f"with `next-question-id` when starting a new debate, or "
                        f"reuse the id already used for this one")
    if mode not in DEBATE_MODES and question is not None:
        problems.append(f"--question is only for debate modes ({', '.join(sorted(DEBATE_MODES))}), "
                        f"not '{mode}'")
    if mode not in DEBATE_MODES and _has_hidden_tag(f"- ts ts [{mode}] {summary}"):
        problems.append(f"--mode {mode}'s summary starts with what looks like a '[qN]' "
                        f"question tag ('{summary}') — this is indistinguishable on disk "
                        f"from a debate entry hiding its tag (see `_has_hidden_tag`), and "
                        f"every later read/write would refuse the ledger over it; reword "
                        f"the summary so it doesn't open with a bracketed '[qN]'-shaped "
                        f"token, or use a real debate mode with --question if this is "
                        f"actually a tagged debate entry")
    if mode == "debate-capped" and not (
            _has_content_after_prefix(summary, "consented_stop:")
            or _has_content_after_prefix(summary, "round_cap:")):
        problems.append(f"--mode debate-capped closes a question and must have a summary "
                        f"starting with 'consented_stop:' or 'round_cap:', followed by the "
                        f"question, tie-break/CUT-voter detail, and dissent (see debate/SKILL.md's "
                        f"\"Recording\") — got '{summary}'; a bare prefix with nothing after it is "
                        f"the same broken-entry case as no prefix at all, and an ordinary round "
                        f"entry must use --mode debate instead of debate-capped, or it would close "
                        f"the question on a non-closing message")
    if mode == "debate-degraded" and not _has_content_after_prefix(
            summary, "degraded_convergence:"):
        problems.append(f"--mode debate-degraded closes a question and must have a summary "
                        f"starting with 'degraded_convergence:', followed by the question, "
                        f"converged answer, unavailable party, and round count (see "
                        f"debate/SKILL.md's \"Recording\") — got '{summary}'; a bare prefix with "
                        f"nothing after it is the same broken-entry case as no prefix at all, and "
                        f"an ordinary round entry must use --mode debate instead of "
                        f"debate-degraded, or it would close the question on a non-closing message")
    if mode == "scope-settled" and not _has_content_after_prefix(
            summary, "scope_settled:"):
        problems.append(f"--mode scope-settled closes a question's round-0 scoping phase "
                        f"and must have a summary starting with 'scope_settled:', followed "
                        f"by the topic, scope, principles, cutoff, and any preserved "
                        f"dissent (see debate/SKILL.md's \"Round 0: scoping\") — got "
                        f"'{summary}'; a bare prefix with nothing after it is the same "
                        f"broken-entry case as no prefix at all")
    if (mode == "debate" and question is not None
            and not ROUND_ENTRY_RE.match(summary)
            and not _has_content_after_prefix(summary, "unanimous_convergence:")):
        problems.append(f"--mode debate with --question must have a summary starting with "
                        f"\"round N, party '<role>': <content>\" or 'unanimous_convergence:' "
                        f"followed by the question, agreed answer, and round count (see "
                        f"debate/SKILL.md's \"Recording\") — got '{summary}'; free text that "
                        f"happens to start with 'unanimous_convergence:' would otherwise close "
                        f"the question on an ordinary round entry, and a bare prefix with "
                        f"nothing after it is the same broken-entry case as no prefix at all")
    return problems


def _check_decisions_shape(decisions: str) -> list[tuple[str, str]]:
    """Re-check that every question-tagged, closing-capable decisions entry
    genuinely has the required prefix content for its mode, and that
    question-id/round-number sequencing is intact, on every read — not only
    at the moment `cmd_record_decision` writes it. `_is_closing_entry`
    trusts a `debate-capped`/`debate-degraded` mode, or a `debate` mode
    summary starting with `unanimous_convergence:`, as meaning the tagged
    question is closed, without itself re-checking the prefix has real
    content after it. A hand-edited entry with the right mode bracket but a
    missing or bare prefix (e.g. `[debate-capped] [q1] bad`, no
    `round_cap:`/`consented_stop:`) would otherwise still parse as
    structurally valid and be silently trusted as a genuine close, stranding
    that question as permanently (and wrongly) closed with no record of
    what actually happened. Likewise, a hand-edited `[q3]` tag appearing with
    no prior `q1`/`q2` entry, or a round number that skips or goes backward,
    would otherwise be silently trusted by `_next_question_id`/
    `_max_recorded_round`, since both simply scan whatever tags and round
    numbers already exist on disk without checking they form a real
    sequence.

    Deliberately narrower than `_validate_decision_shape`'s full write-time
    check: only re-checks entries that carry a `[qN]` tag, since that's the
    only case `_is_closing_entry`/sequencing ever inspect a summary's prefix
    or round number for. Untagged entries (including `debate`-mode entries
    recorded before `--question` was a required argument, still present in
    older ledgers) are left alone — they predate today's shape rules and are
    not corruption, just history from before a rule was tightened;
    retroactively enforcing every current shape rule against them would
    break real, already-valid ledgers instead of only catching genuine
    corruption.

    Returns every (kind, item) problem in one scan; an entry with a problem
    is skipped for the sequencing state later entries are checked against."""
    problems: list[tuple[str, str]] = []

    def bad(kind: str, entry: str, detail: str) -> None:
        problems.append((kind, f"{entry!r}: {detail}"))

    seen_qids: set[str] = set()
    closed_qids: set[str] = set()
    max_round: dict[str, int] = {}
    scope_settled_qids: set[str] = set()
    for entry in decisions.split("\n"):
        if not entry.strip():
            continue
        parsed = _parse_decision_entry(entry)
        if not parsed:
            # The entry doesn't even match DECISION_ENTRY_RE's strict mode
            # bracket (e.g. an empty "[]"), so it fell through the mode
            # check above entirely — but a genuine [qN] tag can still
            # survive right after the malformed bracket (see
            # _has_hidden_tag), hiding it from every open/closed check the
            # same way an unknown-mode-plus-tag entry would.
            if _has_hidden_tag(entry):
                bad("hidden question tag", entry,
                    "this line doesn't match the expected '- <ts> [<mode>] "
                    "[qN] ...' shape at all (a malformed or empty mode "
                    "bracket), but its content starts with what looks like "
                    "a '[qN]' question tag right where a real tag would be "
                    "— an unparseable line hides that tag from every check "
                    "that depends on it")
            continue
        mode, qid, summary = parsed
        if mode not in ALL_MODES and _has_hidden_tag(entry):
            # An unknown --mode is tolerated on its own — legacy ledgers predate
            # --mode's fixed choice set and may carry free-text labels like
            # "[debate via other-tool]" with no
            # question tag at all, which is real history, not corruption.
            # What's never tolerated is an unknown mode WITH what looks like
            # a [qN] tag in its content: `_parse_decision_entry` only ever
            # recognizes a tag when mode is already a real debate mode, so a
            # bogus mode is otherwise a way to hide a question tag from every
            # open/closed check that depends on it, `close`'s guard against
            # ending the run with a debate still open included. Checked with
            # _has_hidden_tag (not the stricter QUESTION_TAG_RE against
            # DECISION_ENTRY_RE's own `rest` group) so extra whitespace
            # between the mode bracket and the tag bracket — which shifts
            # DECISION_ENTRY_RE's `rest` group to no longer start exactly at
            # "[qN]" — doesn't let the tag slip past this check too.
            bad("hidden question tag", entry,
                f"'{mode}' is not a real --mode value "
                f"({', '.join(sorted(ALL_MODES))}), but its content starts with "
                f"what looks like a '[qN]' question tag — an unknown mode hides "
                f"that tag from every check that depends on it")
            continue
        if not qid:
            # A genuinely untagged legacy entry is fine (see the module
            # docstring above) — but a real debate-mode entry whose tag
            # _has_hidden_tag still finds is not: QUESTION_TAG_RE (used by
            # `_parse_decision_entry` to extract `qid`) requires the tag
            # immediately after the mode bracket with no stray whitespace
            # before it, exact-case "q", no internal whitespace inside its
            # own brackets, and a trailing space after the tag's own closing
            # "]" — deviating in any of those ways (e.g. "[debate]   [q1]
            # ...", "[debate] [q1]round 1, ...", "[debate] [ q1 ] ...", or
            # "[debate] [Q1] ...") makes a real, currently-valid --mode entry
            # parse as untagged instead of failing outright, hiding it from
            # every open/closed check the same way an unparseable line or
            # unknown mode would. Checked regardless of mode (not gated to
            # DEBATE_MODES) since _has_hidden_tag's own adjacency requirement
            # already rules out matching unrelated prose.
            if _has_hidden_tag(entry):
                bad("hidden question tag", entry,
                    f"'{mode}' is a real --mode value, but its content starts "
                    f"with what looks like a '[qN]' question tag that isn't "
                    f"exactly the shape record-decision always writes — this "
                    f"entry would otherwise be silently treated as an untagged "
                    f"legacy entry, hiding its question tag from every check "
                    f"that depends on it")
            continue
        # A tagged entry that fails any check below is reported and then
        # contributes no state (seen/closed/round), so the scan continues.
        if qid not in seen_qids:
            n = 1
            while f"q{n}" in seen_qids:
                n += 1
            if qid != f"q{n}":
                bad("question id out of sequence", entry,
                    f"'{qid}' is the first entry tagging this question, but "
                    f"'q{n}' was expected next — question ids must appear in "
                    f"a gapless sequence starting at q1")
                continue
        if qid in closed_qids:
            bad("entry after close", entry,
                f"'{qid}' already has a closing entry earlier in the ledger — "
                f"a debate closes exactly once and records nothing more "
                f"against that question id, a duplicate or contradictory "
                f"closing entry included; `_has_closing_entry`/`recall`'s "
                f"last-[qN]-tag resumption both assume at most one close "
                f"per question")
            continue
        if mode == "scope-settled" and qid not in max_round:
            bad("scope-settled first", entry,
                f"'{qid}'s round-0 scoping phase has no entries yet — "
                f"scope-settled cannot be a question's first decision, "
                f"the round-0 phase (independent topic/scope/principles/"
                f"cutoff, then discuss) must actually happen first (see "
                f"debate/SKILL.md's \"Round 0: scoping\")")
            continue
        round_match = ROUND_ENTRY_RE.match(summary)
        prior_max = max_round.get(qid)
        if round_match is None and prior_max is None and mode != "scope-settled":
            bad("closing entry first", entry,
                f"'{qid}' has no round entry yet — a closing entry can't "
                f"be the first thing recorded against a question id")
            continue
        round_n = int(round_match.group("round")) if round_match is not None else None
        if round_n is not None:
            if prior_max is None and round_n != 0:
                bad("first round not 0", entry,
                    f"'{qid}'s first entry must be round 0 (the scoping "
                    f"phase), got round {round_n} — see debate/SKILL.md's "
                    f"\"Round 0: scoping\"")
                continue
            if prior_max is not None and round_n < prior_max:
                bad("round goes backward", entry,
                    f"round {round_n} is lower than round {prior_max} "
                    f"already recorded for '{qid}' — round numbers for a "
                    f"question never go backward")
                continue
            if round_n >= 1 and qid not in scope_settled_qids:
                bad("round before scope-settled", entry,
                    f"'{qid}' has a round {round_n} entry but no "
                    f"scope-settled close yet — round 1+ substance is not "
                    f"legal until the round-0 scoping phase closes (see "
                    f"debate/SKILL.md's \"Round 0: scoping\")")
                continue
        if mode == "debate-capped" and not (
                _has_content_after_prefix(summary, "consented_stop:")
                or _has_content_after_prefix(summary, "round_cap:")):
            bad("closing prefix missing", entry,
                f"tagged {qid} as --mode debate-capped but the summary "
                f"has no 'consented_stop:'/'round_cap:' prefix with real "
                f"content after it — this would be silently trusted as "
                f"a genuine close of {qid}, stranding it")
            continue
        if mode == "debate-degraded" and not _has_content_after_prefix(
                summary, "degraded_convergence:"):
            bad("closing prefix missing", entry,
                f"tagged {qid} as --mode debate-degraded but the summary "
                f"has no 'degraded_convergence:' prefix with real "
                f"content after it — this would be silently trusted as "
                f"a genuine close of {qid}, stranding it")
            continue
        if (mode == "debate"
                and not ROUND_ENTRY_RE.match(summary)
                and not _has_content_after_prefix(summary, "unanimous_convergence:")):
            bad("closing prefix missing", entry,
                f"tagged {qid} as --mode debate but the summary is "
                f"neither a 'round N, party ...' entry nor a genuine "
                f"'unanimous_convergence:' close — this entry's real "
                f"shape can't be determined, and {qid}'s open/closed "
                f"state depends on it")
            continue
        seen_qids.add(qid)
        if _is_closing_entry(mode, summary):
            closed_qids.add(qid)
        if mode == "scope-settled":
            scope_settled_qids.add(qid)
        if round_n is not None:
            max_round[qid] = round_n if prior_max is None else max(prior_max, round_n)
    still_open = seen_qids - closed_qids
    if len(still_open) > 1:
        # `record-decision` itself refuses to open a second question while
        # one is already open (see cmd_record_decision's own
        # _open_question_ids check), so this state is only reachable by
        # hand-editing a [qN] tag directly into the ledger — but a hand-edit
        # is exactly what the rest of this function already defends against.
        # Left unchecked, `recall`'s "last [qN] tag" resumption rule would
        # silently resume the wrong one of the two, and every other question
        # left open would go unnoticed until something else about it broke.
        problems.append(("several open questions", (
            f"{', '.join(sorted(still_open))} are all open with no closing "
            f"entry — at most one debate question may be open at a time "
            f"(`record-decision`/`next-question-id` both refuse to open a "
            f"second one; this can only have been hand-edited in), and "
            f"`recall`'s 'last [qN] tag' resumption rule has no defined "
            f"behavior for more than one")))
    return problems
