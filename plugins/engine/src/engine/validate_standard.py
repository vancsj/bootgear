#!/usr/bin/env python3
"""Validate a .bootgear/config/*-standard.md file.

Checks the standard-file format: an optional `severities: [a, b, c]` line (most severe first,
required once a file uses more than one severity), a `cutoff: <severity>`
line naming a value from that list, an optional `iteration_cap: <int>`
line, then one `## R### [severity]` heading per rule with non-empty
prose beneath it. Read-only — this script never writes to the file;
it's human-owned, edited directly.

    validate_standard.py <path>   # exit 0 and print "ok" if valid,
                                   # otherwise exit 1 and print every
                                   # problem found (not just the first)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Top-level fields must appear as their own line, at column 0, outside
# any rule's body — matched only against lines before the first rule
# heading, so a rule's free-text prose can't be mistaken for one of these.
SEVERITIES_LINE_RE = re.compile(r"^severities:[ \t]*\[(.*?)\][ \t]*$", re.MULTILINE)
# Looser: any line starting with the severities: key, whether or not a
# bracketed list follows — catches a missing/malformed bracket (e.g.
# "severities:" alone, or "severities: must, should" with no brackets at
# all), which SEVERITIES_LINE_RE just fails to match and would otherwise be
# silently treated as prose.
SEVERITIES_LIKE_RE = re.compile(r"^severities:.*$", re.MULTILINE)
CUTOFF_LINE_RE = re.compile(r"^cutoff:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
# Looser: any line starting with the cutoff: key, whether or not a bare
# single-token value follows in the shape CUTOFF_LINE_RE requires — catches
# a missing value, a value with embedded whitespace, or trailing extra
# text (e.g. "cutoff:" alone, or "cutoff: must extra"), which
# CUTOFF_LINE_RE just fails to match and would otherwise be silently
# treated as prose (or, if a separate valid cutoff: line also exists,
# silently ignored as a malformed duplicate).
CUTOFF_LIKE_RE = re.compile(r"^cutoff:.*$", re.MULTILINE)
ITERATION_CAP_LINE_RE = re.compile(r"^iteration_cap:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
# Looser: any line starting with the iteration_cap: key, whether or not a
# value follows in the shape ITERATION_CAP_LINE_RE requires — catches an
# empty/missing value (e.g. "iteration_cap:" alone), which ITERATION_CAP_LINE_RE
# just fails to match and would otherwise be silently treated as prose.
ITERATION_CAP_LIKE_RE = re.compile(r"^iteration_cap:.*$", re.MULTILINE)
# Severity capture excludes ']' AND whitespace (not just requiring \S, and
# not just excluding ']') so two distinct malformed shapes are both rejected
# by the strict regex rather than silently accepted: a doubled closing
# bracket (e.g. "## R001 [must]]", which would otherwise be absorbed into
# the severity value as "must]"), and embedded whitespace inside the
# brackets (e.g. "## R001 [must extra]" or "## R001 [ must]"), which the
# documented error message for RULE_HEADING_LIKE_RE below already promises
# is rejected ("severity in brackets with no spaces inside them") — using
# only [^\]]+ would silently accept whitespace, since it excludes solely
# ']', not the class \S already excluded before it.
RULE_HEADING_RE = re.compile(r"^##[ \t]+(R[0-9]+)[ \t]+\[([^\]\s]+)\][ \t]*$", re.MULTILINE)
# Looser: anything that starts like a rule heading (## R, then any run of
# characters that aren't a digit, then a digit and/or more alnum) whether or
# not the rest matches the strict format above — used to catch a heading
# with a malformed ID (a letter suffix like "R001X", one or more spaces like
# "R 001"/"R  001", a punctuation separator like "R_001"/"R-001"/"R#001",
# letters before the digits like "R-foo001", a run of separator characters
# of any length, or a Unicode digit alias), severity bracket, or trailing
# text, which RULE_HEADING_RE would otherwise just fail to match and
# silently treat as ordinary prose. Requires a digit to appear somewhere
# after "R" (not necessarily immediately after it) so a heading like
# "## Requirements" (with no digit at all) isn't caught, while any run of
# non-digit characters between "R" and its first digit — however long — is
# tolerated regardless of what that run contains. There is deliberately no
# cap on how far past "R" a digit may appear: any bound is bypassable by a
# long enough malformed separator (e.g. "## R_____________________001"),
# which would then silently validate as ordinary prose. An over-inclusive match here
# (e.g. an unrelated heading like "## Requirements gathered in 2024" or
# "## R&D notes for phase 2" happening to also match) is an acceptable
# false positive: a human reviews and dismisses an extra reported problem,
# but a false negative here would let real corruption validate as `ok`
# silently.
RULE_HEADING_LIKE_RE = re.compile(r"^##[ \t]+R[^\d\n]*?\d\w*.*$", re.MULTILINE)
# RULE_HEADING_LIKE_RE requires a digit somewhere after "R" by design (see
# above), so a heading with NO digit at all — "## R [must]", missing its ID
# entirely — never matches either regex and validates as ordinary prose,
# even with a same-line severity bracket right where a real rule's would be.
# Bare "## Requirements"-style prose is deliberately not flagged (see
# RULE_HEADING_LIKE_RE's own reasoning above), so this can't just drop the
# digit requirement outright without reintroducing that false positive.
# Instead this catches only the much narrower, unambiguous shapes: "R" on
# its own (not part of a longer word — nothing but optional spaces/tabs
# between it and whatever follows), either immediately followed by a
# `[...]`-shaped bracket, or with nothing else at all on the line but
# trailing whitespace. No real English heading ever puts a bracket directly
# after a bare "R" this way, or is just the single letter "R" standing alone
# as a complete heading — "Reviewed [...]"/"Rated [...]"/"R&D [...]" and
# "## Requirements" all have non-whitespace characters immediately after
# "R", so none of them match either alternative.
RULE_HEADING_NO_DIGIT_RE = re.compile(
    r"^##[ \t]+R(?:[ \t]*\[[^\n]*|[ \t]*)$", re.MULTILINE)
RULE_ID_RE = re.compile(r"^R([0-9]{3})$")
# Group 1: the fence marker. Group 2: whatever follows it on the line — an
# opening fence may carry an info string there (e.g. ```text); a closing
# fence, per CommonMark, may not (only trailing whitespace is allowed). A
# backtick fence's info string additionally may not itself contain a
# backtick, per CommonMark — matched separately below so a line like
# "```bad`" is never treated as a valid fence opener at all (it isn't one),
# leaving whatever follows it in the document visible to the parser as
# ordinary text instead of being wrongly blanked as fence contents.
FENCE_RE = re.compile(r"^ {0,3}(```+(?!.*`)|~~~+)(.*)$", re.MULTILINE)


# Matches a complete HTML comment, however many lines it spans (DOTALL) —
# CommonMark's own comment syntax has no line restriction, unlike a fence's
# opening/closing markers. An unterminated "<!--" with no matching "-->"
# is left alone here rather than blanked to end-of-file the way an
# unclosed fence is: CommonMark itself treats stray "<!--" with no closer
# as literal text, not as an open block that swallows the rest of the
# document, so blanking to EOF here would blank real content CommonMark
# would still render.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


# CommonMark HTML block type 1: a line starting (up to 3 leading spaces)
# with a case-insensitive `<pre`, `<script`, or `<style` tag, provided the
# next character is whitespace, `>`, or end of line (so `<pretend>` doesn't
# open one). Only these three tag names get the "runs verbatim until the
# matching closing tag, anywhere later on a line" treatment — the only
# other raw-HTML-block starts CommonMark defines (a handful of specific
# block-level tag names ending a paragraph, an XML declaration, a
# processing instruction, a CDATA section) are deliberately not handled
# here: unlike <pre>/<script>/<style>, several of those close on a blank
# line rather than a specific closing tag, which would need its own
# separate state-machine rule, and a rule-standard file mixing raw
# non-code HTML in with its rule text is not a pattern this validator
# otherwise needs to support. Handling just these three covers the concrete
# gap: a fake "## R### [sev]" heading pasted inside a <pre> block (e.g. showing forbidden syntax as an
# example) would otherwise validate as a real rule, and `</pre>` alone
# would count as that rule's "prose."
RAW_HTML_OPEN_RE = re.compile(
    r"^ {0,3}<(pre|script|style)(?=[ \t>]|$)", re.IGNORECASE | re.MULTILINE)


def _blank_span(text: str, start: int, end: int) -> str:
    return "".join("\n" if c == "\n" else " " for c in text[start:end])


def _blank_fences_and_comments(text: str) -> str:
    """Replace the contents of every fenced block (``` or ~~~, indented up
    to 3 spaces per CommonMark), every HTML comment, and every raw
    <pre>/<script>/<style> HTML block with blanks of the same shape, so a
    rule heading or top-level field written inside any of them is never
    parsed as real — while every other line/column keeps its original
    position for error reporting.

    All three are blanked in a single left-to-right scan, not independent
    passes, because any two of them can appear on the same line (or one
    inside another) and a naive pass order gets some direction wrong no
    matter which runs first:

    - Comments-then-fences would let a fence marker embedded inside a
      comment (e.g. a comment showing fence syntax) survive as a real
      fence-open marker, consuming real content past the comment's own
      close — the comment's blanking never gets a chance to protect it,
      since the fence pass runs on text that still has the marker intact.
    - Fences-then-comments would do the opposite: a real fence's closing
      marker line followed on the same line by comment-shaped text (e.g.
      "```<!-- not a closing fence -->") fails CommonMark's "closing fence
      must be bare" rule while the trailing text is still there, but a
      later comment-blanking pass turns that same trailing text to spaces
      first, making the line look bare — closing the fence early and
      exposing whatever comes after as real.
    - The same reasoning applies to a raw HTML block's own open tag: run a
      pass for it independently of comments/fences and a "<pre>" written
      inside a comment (or a fence) would wrongly be treated as a real
      block opener, consuming real content past that comment's/fence's own
      close.

    Scanning once, left to right, avoids all of this: while a construct is
    open (a fence or a raw HTML block — the two are mutually exclusive
    "open" states, and comments don't have one since they're always
    matched whole), only that construct's own closing rule is checked (its
    contents are verbatim — comment/fence/raw-HTML syntax inside it isn't
    recognized as such, per CommonMark, and closing-marker lines are
    judged against the real, unblanked trailing text so a same-line
    comment can never turn a non-bare fence closer into a bare one).
    While nothing is open, whichever of the next fence-open marker, the
    next comment start, or the next raw-HTML-block open tag comes first in
    the text is the one that actually opens — one fully containing another
    is blanked as a whole span before the other's scan ever reaches the
    marker inside it.

    A fence only closes on a matching character (``` never closes on ~~~
    or vice versa, per CommonMark), at least as many repeats of it, and no
    trailing info string (a closing fence must be bare — CommonMark permits
    only ordinary spaces/tabs trailing it, not any Unicode whitespace, so a
    bare .strip() would wrongly accept e.g. a trailing non-breaking space);
    an unclosed fence runs to the end of the file, so everything after it
    is blanked too. A raw HTML block closes at the first line containing
    its own tag name's closing form (`</pre>`, `</script>`, or `</style>`,
    case-insensitive) anywhere on the line — CommonMark does not require it
    to be bare the way a fence closer must be — and likewise runs to end of
    file if never closed. An unterminated comment ("<!--" with no matching
    "-->") is left alone rather than blanked to end-of-file the way an
    unclosed fence or raw HTML block is: CommonMark treats stray "<!--" as
    literal text, not an open block swallowing the rest of the document."""
    out = []
    pos = 0
    fence_iter = FENCE_RE.finditer(text)
    comment_iter = _HTML_COMMENT_RE.finditer(text)
    raw_html_iter = RAW_HTML_OPEN_RE.finditer(text)
    next_fence = next(fence_iter, None)
    next_comment = next(comment_iter, None)
    next_raw_html = next(raw_html_iter, None)
    open_marker: str | None = None  # fence marker text, when a fence is open
    open_raw_html_tag: str | None = None  # lowercased tag name, when a raw HTML block is open

    while True:
        while next_fence is not None and next_fence.start() < pos:
            next_fence = next(fence_iter, None)
        while next_comment is not None and next_comment.start() < pos:
            next_comment = next(comment_iter, None)
        while next_raw_html is not None and next_raw_html.start() < pos:
            next_raw_html = next(raw_html_iter, None)
        if (next_fence is None and next_comment is None and next_raw_html is None
                and open_raw_html_tag is None):
            break

        if open_raw_html_tag is not None:
            # `[ \t]*`, not `\s*` — the closing tag itself (`</pre>` etc.)
            # must be intact on one line, per CommonMark; `\s*` would also
            # match a newline between the tag name and `>` (e.g.
            # "</script\n>"), treating a close split across two lines as if
            # it were real, closing the block one line early and exposing
            # whatever comes after — up to and including a fake rule
            # heading — as validated real content instead of leaving it
            # blanked through to a genuine one-line close or EOF.
            close_re = re.compile(rf"</{open_raw_html_tag}[ \t]*>", re.IGNORECASE)
            close_m = close_re.search(text, pos)
            close_line_end = text.find("\n", close_m.end()) if close_m else -1
            block_end = close_line_end if close_line_end != -1 else len(text)
            inside = text[pos:block_end]
            out.append("\n" * inside.count("\n"))
            pos = block_end
            open_raw_html_tag = None
            continue

        if open_marker is not None:
            if next_fence is None:
                break
            m = next_fence
            char = open_marker[0]
            closes = (m.group(1)[0] == char and len(m.group(1)) >= len(open_marker)
                      and m.group(2).strip(" \t") == "")
            if closes:
                inside = text[pos:m.start()]
                out.append("\n" * inside.count("\n"))
                out.append(text[m.start():m.end()])
                pos = m.end()
                open_marker = None
            next_fence = next(fence_iter, None)
            continue

        candidates: list[re.Match[str]] = [
            c for c in (next_fence, next_comment, next_raw_html) if c is not None
        ]
        m = min(candidates, key=lambda candidate: candidate.start())
        if m is next_comment:
            out.append(text[pos:m.start()])
            out.append(_blank_span(text, m.start(), m.end()))
            pos = m.end()
            next_comment = next(comment_iter, None)
        elif m is next_raw_html:
            out.append(text[pos:m.end()])
            open_raw_html_tag = m.group(1).lower()
            pos = m.end()
            next_raw_html = next(raw_html_iter, None)
        else:
            out.append(text[pos:m.end()])
            open_marker = m.group(1)
            pos = m.end()
            next_fence = next(fence_iter, None)

    if open_raw_html_tag is not None:
        inside = text[pos:]
        out.append("\n" * inside.count("\n"))
        pos = len(text)
    if open_marker is not None:
        inside = text[pos:]
        out.append("\n" * inside.count("\n"))
        pos = len(text)
    out.append(text[pos:])
    return "".join(out)


# A line that carries no prose of its own: a genuine fence marker (its
# contents are already blanked by _blank_fences_and_comments by the time
# _split_rules runs, but the marker line itself, e.g. "```text", survives as
# literal text) or a complete one-line HTML comment. Used only to decide
# whether a rule's body has real prose — a body that is only fence markers
# and/or comments around blanked fence content is empty in substance even
# though `body.strip()` is non-empty, so checking `if not body` alone would
# wrongly accept it. Reuses FENCE_RE itself for the fence-marker half (not a
# second, looser backtick/tilde pattern) so a line FENCE_RE rejects as a
# fence at all — e.g. a backtick run whose info string itself contains a
# backtick, which CommonMark treats as ordinary text, not a fence opener —
# is never wrongly excluded from prose here either; the two checks must
# agree on what counts as a fence, or a line the fence logic already decided
# was real text could still be silently treated as a marker by this helper.
# The HTML-comment half is defensive, not load-bearing, when called from
# `validate()`: comments are already blanked by `_blank_fences_and_comments`
# in `validate()` itself before `_split_rules` ever runs, so a comment
# survives here only as content, but keeping the check makes `_has_prose`
# correct on its own if ever called without that preprocessing.
_NON_PROSE_LINE_RE = re.compile(r"^\s*<!--.*-->\s*$")


def _has_prose(body: str) -> bool:
    # RAW_HTML_OPEN_RE is checked too, the same reason FENCE_RE is: a raw
    # HTML block's opener survives _blank_fences_and_comments as literal
    # text (its own contents and closing tag are fully blanked), so a rule
    # whose body is only that opener — e.g. an empty "<script>...</script>"
    # pair with nothing between — has no real prose even though the
    # opener's own text makes `body.strip()` non-empty.
    return any(line.strip()
               and not _NON_PROSE_LINE_RE.match(line)
               and not FENCE_RE.match(line)
               and not RAW_HTML_OPEN_RE.match(line)
               for line in body.split("\n"))


def _split_rules(text: str) -> list[tuple[str, str, int, str]]:
    """Return (id, severity, line_number, body) for every ## R### [sev] heading."""
    headings = list(RULE_HEADING_RE.finditer(text))
    rules = []
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        line_no = text.count("\n", 0, m.start()) + 1
        rules.append((m.group(1), m.group(2), line_no, body))
    return rules


def _preamble(text: str) -> str:
    """Text before the first rule heading — where severities:/cutoff: must live."""
    first = RULE_HEADING_RE.search(text)
    return text if first is None else text[: first.start()]


def validate(text: str) -> list[str]:
    text = _blank_fences_and_comments(text)
    problems: list[str] = []
    preamble = _preamble(text)

    severities_matches = list(SEVERITIES_LINE_RE.finditer(preamble))
    if len(severities_matches) > 1:
        problems.append(
            f"{len(severities_matches)} top-level `severities:` lines found "
            f"before the first rule — exactly one is allowed"
        )
    severities: list[str] | None = None
    if severities_matches:
        raw = severities_matches[0].group(1)
        parts = [s.strip() for s in raw.split(",")]
        empty_count = sum(1 for s in parts if not s)
        if empty_count:
            problems.append(
                f"`severities:` has {empty_count} empty element(s) (e.g. a "
                f"trailing/doubled comma): {raw}"
            )
        severities = [s for s in parts if s]
        if len(set(severities)) != len(severities):
            problems.append(f"`severities:` lists a duplicate value: {raw}")
        whitespace_values = [s for s in severities if re.search(r"\s", s)]
        if whitespace_values:
            problems.append(
                f"`severities:` declares value(s) containing whitespace "
                f"({', '.join(repr(s) for s in whitespace_values)}): {raw} — "
                f"no rule heading can ever use one of these, since "
                f"RULE_HEADING_RE's own severity bracket (`[^\\]\\s]+`) excludes "
                f"whitespace entirely; a declared severity with no rule able to "
                f"carry it would validate as `ok` while being structurally dead"
            )
    strict_sev_lines = {m.start() for m in SEVERITIES_LINE_RE.finditer(preamble)}
    for m in SEVERITIES_LIKE_RE.finditer(preamble):
        if m.start() not in strict_sev_lines:
            line_no = text.count("\n", 0, m.start()) + 1
            problems.append(
                f"line {line_no}: '{m.group(0)}' looks like a `severities:` line "
                f"but its value isn't a bracketed list, e.g. `severities: [must, "
                f"should]` — this is checked even when a separate valid "
                f"`severities:` line also exists, since a malformed duplicate "
                f"must not be silently ignored"
            )

    cutoff_matches = list(CUTOFF_LINE_RE.finditer(preamble))
    if not cutoff_matches:
        problems.append("no top-level `cutoff: <severity>` line found before the first rule")
        cutoff = None
    else:
        if len(cutoff_matches) > 1:
            problems.append(
                f"{len(cutoff_matches)} top-level `cutoff:` lines found "
                f"before the first rule — exactly one is allowed"
            )
        cutoff = cutoff_matches[0].group(1)
    strict_cutoff_lines = {m.start() for m in CUTOFF_LINE_RE.finditer(preamble)}
    for m in CUTOFF_LIKE_RE.finditer(preamble):
        if m.start() not in strict_cutoff_lines:
            line_no = text.count("\n", 0, m.start()) + 1
            problems.append(
                f"line {line_no}: '{m.group(0)}' looks like a `cutoff:` line but "
                f"has no value, one with embedded whitespace, or trailing extra "
                f"text — this is checked even when a separate valid `cutoff:` "
                f"line also exists, since a malformed duplicate must not be "
                f"silently ignored"
            )

    iteration_cap_matches = list(ITERATION_CAP_LINE_RE.finditer(preamble))
    if len(iteration_cap_matches) > 1:
        problems.append(
            f"{len(iteration_cap_matches)} top-level `iteration_cap:` lines found "
            f"before the first rule — exactly one is allowed"
        )
    if iteration_cap_matches:
        raw_cap = iteration_cap_matches[0].group(1)
        if not raw_cap.isascii() or not raw_cap.isdigit() or int(raw_cap) < 1:
            problems.append(f"`iteration_cap` must be a positive integer, got '{raw_cap}'")
    strict_cap_lines = {m.start() for m in ITERATION_CAP_LINE_RE.finditer(preamble)}
    for m in ITERATION_CAP_LIKE_RE.finditer(preamble):
        if m.start() not in strict_cap_lines:
            line_no = text.count("\n", 0, m.start()) + 1
            problems.append(
                f"line {line_no}: '{m.group(0)}' looks like an `iteration_cap:` "
                f"line but has no value, or one with embedded whitespace — this "
                f"is checked even when a separate valid `iteration_cap:` line "
                f"also exists, since a malformed duplicate must not be silently "
                f"ignored"
            )

    strict_lines = {m.start() for m in RULE_HEADING_RE.finditer(text)}
    for m in RULE_HEADING_LIKE_RE.finditer(text):
        if m.start() not in strict_lines:
            line_no = text.count("\n", 0, m.start()) + 1
            problems.append(
                f"line {line_no}: '{m.group(0)}' looks like a rule heading but "
                f"doesn't match the required `## R### [severity]` format exactly "
                f"— no trailing text after the bracket, ID padded to 3 digits, "
                f"severity in brackets with no spaces inside them"
            )
    like_lines = {m.start() for m in RULE_HEADING_LIKE_RE.finditer(text)}
    for m in RULE_HEADING_NO_DIGIT_RE.finditer(text):
        if m.start() not in like_lines:
            line_no = text.count("\n", 0, m.start()) + 1
            problems.append(
                f"line {line_no}: '{m.group(0)}' looks like a rule heading with "
                f"its ID missing entirely (no digit after 'R') — a real rule "
                f"heading always has an ID; this cannot be a genuine rule and "
                f"would otherwise silently validate as ordinary prose"
            )

    rules = _split_rules(text)
    if not rules:
        problems.append("no `## R### [severity]` rule headings found")

    seen_ids: dict[str, int] = {}
    numeric_ids: list[tuple[int, str, int]] = []
    severities_seen: set[str] = set()

    for rule_id, severity, line_no, body in rules:
        if rule_id in seen_ids:
            problems.append(
                f"line {line_no}: duplicate rule ID '{rule_id}' "
                f"(first seen at line {seen_ids[rule_id]})"
            )
        else:
            seen_ids[rule_id] = line_no

        id_match = RULE_ID_RE.match(rule_id)
        if not id_match:
            problems.append(
                f"line {line_no}: rule ID '{rule_id}' must be R followed by "
                f"exactly 3 digits (e.g. R001), not a shorter or longer form"
            )
        else:
            numeric_ids.append((int(id_match.group(1)), rule_id, line_no))

        severities_seen.add(severity)

        if not _has_prose(body):
            problems.append(f"line {line_no}: rule '{rule_id}' has no prose beneath its heading")

    ordered = sorted(numeric_ids, key=lambda t: t[0])
    if [n for n, _, _ in numeric_ids] != [n for n, _, _ in ordered]:
        problems.append(
            "rule IDs are not in increasing order in the file — "
            "reordering an existing ID risks confusion with what a past "
            "finding actually cited"
        )

    if severities is not None:
        unknown = severities_seen - set(severities)
        if unknown:
            problems.append(
                f"rule severities not declared in `severities:`: "
                f"{', '.join(sorted(unknown))} (declared: {', '.join(severities)})"
            )
    elif len(severities_seen) > 1:
        problems.append(
            f"file uses more than one severity ({', '.join(sorted(severities_seen))}) "
            f"but has no top-level `severities:` line declaring their order — "
            f"required whenever more than one severity is in use, since rank "
            f"can't be inferred from string comparison or rule order"
        )

    if cutoff is not None and rules:
        if severities is not None and cutoff not in severities:
            problems.append(
                f"cutoff '{cutoff}' is not one of the declared `severities:` "
                f"values ({', '.join(severities)})"
            )
        elif severities is None and cutoff not in severities_seen:
            problems.append(
                f"cutoff '{cutoff}' does not match the only severity actually "
                f"used by a rule in this file (severities present: "
                f"{', '.join(sorted(severities_seen)) or 'none'})"
            )

    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="path to a *-standard.md file")
    args = parser.parse_args()

    if not args.path.exists():
        sys.exit(f"no file at {args.path}")

    text = args.path.read_text()
    problems = validate(text)

    if problems:
        print(f"{args.path}: {len(problems)} problem(s) found:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    print(f"{args.path}: ok")


if __name__ == "__main__":
    main()
