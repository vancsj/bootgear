"""Check triage reports against their recorded slate."""

from __future__ import annotations

import re

from . import protocol
from .model import Slate

# `gate --kind triage`: the report's sections, and the attack angle that re-runs a claim's
# reproduction command.
REPORT_COLUMNS = ("command", "output")
REPORT_HEADINGS = ("Cause", "Impact", "Confidence", "Next action", "Solutions")
RERUN_ANGLE = "reproduction-rerun"
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_SEPARATOR_CELL = re.compile(r"\A:?-+:?\Z")
_CODE_SPAN = re.compile(r"\A`([^`]*)`\Z")


def _cell(part: str) -> str:
    """A stripped table cell, without one code span that wraps the whole cell."""
    text = part.strip()
    span = _CODE_SPAN.match(text)
    return span.group(1).strip() if span else text


def _cells(line: str) -> list[str]:
    """The cells of a Markdown table row; `\\|` inside a cell does not split it."""
    parts = _UNESCAPED_PIPE.split(line)
    if line.startswith("|"):
        parts = parts[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        parts = parts[:-1]
    return [_cell(part) for part in parts]


def _cell_text(cell: str) -> str:
    """The plain text of a cell: `\\|` reads `|` and `<br>` reads a line break."""
    return cell.replace("\\|", "|").replace("<br>", "\n")


def _report_parts(text: str) -> tuple[list[dict[str, str]], set[str]]:
    """The `## Claims` table rows keyed by their case-folded header cells, and the case-folded
    texts of every `## ` heading."""
    rows: list[dict[str, str]] = []
    headings: set[str] = set()
    header: list[str] | None = None
    in_claims = False
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip().casefold()
            headings.add(name)
            in_claims, header = name == "claims", None
        elif in_claims and line.strip().startswith("|"):
            cells = _cells(line.strip())
            if header is None:
                header = [cell.casefold() for cell in cells]
            elif not all(_SEPARATOR_CELL.match(cell) for cell in cells):
                rows.append(dict(zip(header, cells)))
    return rows, headings


def _cause_unresolved(report: str) -> bool:
    """True when the first non-empty line under `## Cause` is `Status: unresolved`."""
    in_cause = False
    for line in report.splitlines():
        if line.startswith("## "):
            in_cause = line[3:].strip().casefold() == "cause"
        elif in_cause and line.strip():
            return line.strip().casefold() == "status: unresolved"
    return False


_LIST_ITEM = re.compile(r"(?:[-*]|\d+[.)])\s+\S")
_ROW_ID = re.compile(r"\bF\d+\b", re.IGNORECASE)
_NO_FACT = re.compile(r"\bno-fact:\s*\S", re.IGNORECASE)


def _solutions_lines(report: str) -> list[str] | None:
    """The non-empty lines under `## Solutions`, the heading matched case-folded; None without it."""
    found, lines, in_solutions = False, [], False
    for line in report.splitlines():
        if line.startswith("## "):
            in_solutions = line[3:].strip().casefold() == "solutions"
            found = found or in_solutions
        elif in_solutions and line.strip():
            lines.append(line.strip())
    return lines if found else None


def _solutions_problems(report: str, row_ids: set[str | None]) -> list[str]:
    """Each `## Solutions` line is a list item that cites a row id or states `no-fact: <reason>`;
    a cited id must name a row of `## Claims`."""
    lines = _solutions_lines(report)
    if lines is None:
        return []
    items = [line for line in lines if _LIST_ITEM.match(line)]
    problems = [f"## Solutions line is not a list item: {line!r}"
                for line in lines if not _LIST_ITEM.match(line)]
    if not items:
        problems.append("## Solutions lists no solution")
    known = {str(row_id).upper() for row_id in row_ids if row_id}
    for line in items:
        cited = {match.upper() for match in _ROW_ID.findall(line)}
        if not cited and not _NO_FACT.search(line):
            problems.append(f"## Solutions entry {line!r} cites no row id and has no "
                            "`no-fact: <reason>`")
        problems.extend(f"## Solutions cites {cid}, which has no row in ## Claims"
                        for cid in sorted(cited - known))
    return problems


def report_problems(slate: Slate, report: str, base: Slate | None = None) -> list[str]:
    """No claim is disputed or unverified; each surviving claim is reproduced and has a report
    row with its slate tier, a command and an output; each row names a slate claim and quotes
    its text; the report has every heading; a claim survives, or the cause is unresolved
    (`Status: unresolved` first in `## Cause`) and none does; each surviving claim has a
    `reproduction-rerun` attack. A killed claim needs no tier and no row. With `base`, each row
    names a claim of the base slate. Presence checks only: no command runs."""
    unverified = protocol.unverified_ids(slate)
    statuses = {claim.id: protocol.status(slate, claim, unverified)
                for claim in slate.claims.values()}
    survived = [claim for claim in slate.claims.values() if statuses[claim.id] == "survived"]
    rows, headings = _report_parts(report)
    problems = [f"{cid} is {state}; each triage cause claim must survive or be killed"
                for cid, state in statuses.items() if state in ("disputed", "unverified")]
    problems.extend(f"{claim.id} has tier {claim.tier}; a surviving triage claim needs tier "
                    "reproduced" for claim in survived if claim.tier != "reproduced")
    for row in rows:
        row_id, tier = row.get("id", ""), row.get("tier", "")
        claim = slate.claims.get(row_id)
        if claim is None:
            problems.append(f"report row {row_id} names no slate claim")
        else:
            if tier != claim.tier:
                problems.append(f"report row {row_id}: tier {tier!r} differs from the slate "
                                f"tier {claim.tier!r}")
            text = _cell_text(row.get("claim", ""))
            if text != claim.text.strip():
                problems.append(f"report row {row_id}: claim {text!r} differs from the slate "
                                f"claim {claim.text.strip()!r}")
        problems.extend(f"report row {row_id}: the {column} cell is empty"
                        for column in REPORT_COLUMNS if not row.get(column))
    row_ids = {row.get("id") for row in rows}
    problems.extend(_solutions_problems(report, row_ids))
    if base is not None:
        problems.extend(f"report row {row.get('id')} names no claim of the base slate "
                        f"{base.slate_id}; a later visit cannot add a cause claim"
                        for row in rows if row.get("id") not in base.claims)
    problems.extend(f"{claim.id} survived but has no row in the report's ## Claims table"
                    for claim in survived if claim.id not in row_ids)
    problems.extend(f"report has no ## {heading} heading"
                    for heading in REPORT_HEADINGS if heading.casefold() not in headings)
    unresolved = _cause_unresolved(report)
    if not survived and not unresolved:
        problems.append("no claim survived; a triage slate needs at least one surviving "
                        "cause claim, or `Status: unresolved` first in ## Cause")
    if survived and unresolved:
        problems.append("## Cause says `Status: unresolved`, but a claim survived")
    if unresolved and not slate.claims:
        problems.append("## Cause says `Status: unresolved` for a slate with no claims")
    if unresolved and slate.claims and not rows:
        problems.append("## Cause says `Status: unresolved`, but ## Claims has no row")
    problems.extend(f"{claim.id} survived with no {RERUN_ANGLE} attack"
                    for claim in survived if RERUN_ANGLE not in claim.used_angles)
    return problems
