"""Check selected Markdown prose against explicit sentence limits."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LIMITS = {"procedure": 20, "description": 25}
LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
FENCE = re.compile(r"^\s{0,3}(`{3,}(?!`)(?=[^`]*$)|~{3,})")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
INLINE_CODE = re.compile(r"(`+)(.+?)\1", re.DOTALL)
LINK = re.compile(r"!?\[([^\]]+)\]\((?:[^()\n]|\([^()\n]*\))*\)|!?\[([^\]]+)\]\[[^\]]*\]")
WORD = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*|[\ue000-\uf8ff]", re.UNICODE)


@dataclass
class Prose:
    text: str
    lines: list[int]

    def slice(self, start: int, end: int) -> Prose:
        return Prose(self.text[start:end], self.lines[start:end])


def _joined(parts: list[tuple[str, int]]) -> Prose:
    text = " ".join(part for part, _ in parts)
    lines: list[int] = []
    for part, line in parts:
        if lines:
            lines.append(line)
        lines.extend([line] * len(part))
    return Prose(text, lines)


def _cells(line: str) -> list[str]:
    cells: list[str] = []
    start = 0
    code = ""
    for match in re.finditer(r"`+|\\.|\|", line):
        token = match.group()
        if token.startswith("`"):
            code = "" if token == code else token if not code else code
        elif token == "|" and not code:
            cells.append(line[start:match.start()].strip())
            start = match.end()
    cells.append(line[start:].strip())
    return [cell for cell in cells if cell]


def _blocks(source: str) -> Iterator[Prose]:
    lines = source.splitlines()
    parts: list[tuple[str, int]] = []
    fence = ""
    list_indent = 0
    table = False
    for index, line in enumerate(lines):
        item = LIST_ITEM.match(line)
        heading = re.match(r"^\s{0,3}#{1,6}(?:\s|$)", line)
        rule = TABLE_RULE.fullmatch(line)
        continues_paragraph = bool(parts) and not (
            fence or item or heading or rule or FENCE.match(line) or re.match(r"^\s{0,3}>", line)
        )
        if list_indent and line.strip() and not line.startswith(" " * list_indent) and not continues_paragraph:
            list_indent = 0
            fence = ""
        if item and not fence:
            list_indent = item.start(1)
            content = item[1]
        else:
            content = line[list_indent:] if line.startswith(" " * list_indent) else line
        marker = FENCE.match(content)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = ""
            continue
        setext = index + 1 < len(lines) and re.fullmatch(r"\s{0,3}(?:=+|-+)\s*", lines[index + 1])
        definition = re.match(r"^\s{0,3}\[[^\]]+\]:\s*\S", line)
        is_table = "|" in line and (table or (index + 1 < len(lines) and TABLE_RULE.fullmatch(lines[index + 1])))
        boundary = marker or heading or setext or definition or rule or is_table or item or not line.strip()
        if boundary and parts:
            yield _joined(parts)
            parts = []
        if marker:
            fence = marker[1]
        elif heading or setext or definition or rule or re.fullmatch(r"\s*(?:[-*_]\s*){3,}", line):
            pass
        elif is_table:
            for cell in _cells(line):
                yield _joined([(cell, index + 1)])
        elif line.strip():
            parts.append(((item[1] if item else line).strip(), index + 1))
        table = bool(is_table or rule)
    if parts:
        yield _joined(parts)


def _substitute(prose: Prose, pattern: re.Pattern[str],
                replacement: Callable[[re.Match[str]], str | Prose]) -> Prose:
    text: list[str] = []
    lines: list[int] = []
    start = 0
    for match in pattern.finditer(prose.text):
        value = replacement(match)
        text.extend((prose.text[start:match.start()], value.text if isinstance(value, Prose) else value))
        lines.extend(prose.lines[start:match.start()])
        lines.extend(value.lines if isinstance(value, Prose) else [prose.lines[match.start()]] * len(value))
        start = match.end()
    text.append(prose.text[start:])
    lines.extend(prose.lines[start:])
    return Prose("".join(text), lines)


def _sentences(prose: Prose) -> Iterator[Prose]:
    start = 0
    for match in re.finditer(r"[.!?]+[\"'”’*_]*(?=\s|$)", prose.text):
        yield prose.slice(start, match.end())
        start = match.end()
    if prose.text[start:].strip():
        yield prose.slice(start, len(prose.text))


def _findings(block: Prose, path: Path, limit: int) -> list[dict[str, Any]]:
    tokens: dict[str, str] = {}

    def token(text: str) -> str:
        key = chr(0xE000 + len(tokens))
        tokens[key] = text
        return key

    block = _substitute(block, INLINE_CODE, lambda match: token(match[0]))
    block = _substitute(block, LINK, lambda match: block.slice(*match.span(1 if match[1] else 2)))
    findings: list[dict[str, Any]] = []

    def inspect(prose: Prose) -> None:
        for sentence in _sentences(prose):
            words = len(WORD.findall(sentence.text))
            if words <= limit:
                continue
            first = next(index for index, char in enumerate(sentence.text) if not char.isspace())
            text = sentence.text.strip()
            for key, value in reversed(tokens.items()):
                text = text.replace(key, value)
            findings.append({"path": str(path), "line": sentence.lines[first], "words": words,
                             "limit": limit, "text": text})

    def parentheses(prose: Prose) -> Prose:
        text: list[str] = []
        locations: list[int] = []
        start = 0
        depth = 0
        opening = 0
        for index, char in enumerate(prose.text):
            if char == "(":
                if depth == 0:
                    opening = index
                depth += 1
            elif char == ")" and depth:
                depth -= 1
                if depth == 0:
                    inner = parentheses(prose.slice(opening + 1, index))
                    inspect(inner)
                    text.extend((prose.text[start:opening], token(prose.text[opening:index + 1])))
                    locations.extend(prose.lines[start:opening])
                    locations.append(prose.lines[opening])
                    start = index + 1
        text.append(prose.text[start:])
        locations.extend(prose.lines[start:])
        return Prose("".join(text), locations)

    inspect(parentheses(block))
    return sorted(findings, key=lambda item: item["line"])


def check_files(paths: list[Path], kind: str) -> dict[str, Any]:
    """Read each selected file and report sentence findings and read failures."""
    limit = LIMITS[kind]
    checked: list[str] = []
    findings: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append({"path": str(path), "message": str(exc)})
            continue
        checked.append(str(path))
        for block in _blocks(source):
            findings.extend(_findings(block, path, limit))
    outcome = "unavailable" if diagnostics else "needs-reading" if findings else "passed"
    next_step = {
        "unavailable": "Caller resolves each file failure, then runs the writing check again.",
        "needs-reading": "Author reads the findings, fixes clear issues, and checks the remaining writing rules.",
        "passed": "Author reads the selected text and checks the remaining writing rules before recording a pass.",
    }[outcome]
    return {
        "check_kind": "mechanical-writing", "kind": kind, "outcome": outcome,
        "checked_files": checked, "findings": findings, "diagnostics": diagnostics,
        "checks": [f"Sentence length: at most {limit} words for {kind} text."],
        "counting_policy": [
            "Check paragraphs, list items, and table cells. Join wrapped prose lines and preserve source lines.",
            "Exclude headings, fenced code, and link destinations. Count visible link labels.",
            "Count each inline code span and each hyphenated group as one word.",
            "Check parenthetical text separately. Count each group once in the enclosing sentence.",
            "A colon before a vertical list ends that counted sentence.",
            "Count letter and number groups, with internal hyphens or apostrophes, as words.",
            "Periods, question marks, and exclamation marks end sentences before whitespace or the text end.",
        ],
        "limitations": [
            "This mechanical check does not establish full ASD-STE100 compliance or completed author reading.",
            "Other ASD special counts, abbreviations, vocabulary, grammar, meaning, and structure require author reading.",
            "The Markdown extraction covers ordinary prose. It does not render embedded HTML or Markdown extensions.",
        ],
        "next": next_step,
    }
