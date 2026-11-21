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

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.standard_markdown import _blank_fences_and_comments, _has_prose

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


def _extract_headings(text: str) -> tuple[str, list[re.Match[str]]]:
    text = _blank_fences_and_comments(text)
    return text, list(RULE_HEADING_RE.finditer(text))


def rule_headings(text: str) -> list[tuple[str, str]]:
    """Return the rule IDs and severities outside fenced blocks and comments."""
    _, headings = _extract_headings(text)
    return [(heading.group(1), heading.group(2)) for heading in headings]


def _split_rules(text: str, headings: list[re.Match[str]]) -> list[tuple[str, str, int, str]]:
    """Return (id, severity, line_number, body) for every ## R### [sev] heading."""
    rules = []
    for i, m in enumerate(headings):
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        line_no = text.count("\n", 0, m.start()) + 1
        rules.append((m.group(1), m.group(2), line_no, body))
    return rules


def validate(text: str) -> list[str]:
    text, headings = _extract_headings(text)
    problems: list[str] = []
    preamble = text[:headings[0].start()] if headings else text

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

    strict_lines = {heading.start() for heading in headings}
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

    rules = _split_rules(text, headings)
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
