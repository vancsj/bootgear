#!/usr/bin/env python3
"""Reject cross-skill references to private files, sections, or headings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys



REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH_RE = re.compile(r"(?P<path>[^`\s\"'()<>]+/(?:SKILL|reference)\.md)")
PRIVATE_PHRASE_RE = re.compile(
    r"\b(?P<name>[a-z][a-z0-9_-]*)\s+skill(?:['’]s)\s+"
    r"(?:own\s+)?`?(?:reference|file|section|heading)(?:\.md)?`?(?![a-z0-9_-])",
    re.IGNORECASE,
)
FRONTMATTER_NAME_RE = re.compile(r"^name:\s*['\"]?([a-z][a-z0-9:_-]*)['\"]?\s*$", re.IGNORECASE)
SAME_SKILL_REFERENCE_RE = re.compile(
    r"Read `reference\.md` § (?P<path>`[^`\r\n]+`(?: > `[^`\r\n]+`)*)"
)
BROAD_SAME_SKILL_REFERENCE_RE = re.compile(r"Read `reference\.md`(?! § )")
HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")



@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    text: str
    target: str
    rule: str = "private cross-skill reference"

    def render(self, root: Path) -> str:
        relative = self.path.relative_to(root)
        return f"{relative}:{self.line}: {self.rule} to {self.target}: {self.text}"


def _skill_documents(root: Path) -> list[Path]:
    paths: list[Path] = []
    for tree in (root / "plugins", root / "codex-plugins"):
        if tree.is_dir():
            paths.extend(tree.glob("**/skills/*/SKILL.md"))
            paths.extend(tree.glob("**/skills/*/reference.md"))
    return sorted(path for path in paths if path.is_file())


def _current_skill(path: Path) -> str:
    return path.parent.name.lower()


def _frontmatter_name(path: Path) -> str | None:
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        match = FRONTMATTER_NAME_RE.match(line)
        if match:
            return match.group(1).lower()
    return None


def _public_names(paths: list[Path]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        parts = path.parts
        for marker in ("plugins", "codex-plugins"):
            if marker in parts:
                index = parts.index(marker)
                if index + 3 < len(parts) and parts[index + 2] == "skills":
                    plugin = parts[index + 1].lower()
                    skill = parts[index + 3].lower()
                    names.update({skill, f"{plugin}:{skill}"})
                break
    return names


def _target_skill(reference: str) -> str | None:
    parts = reference.replace("\\", "/").split("/")
    filename = parts[-1].lower()
    if filename not in {"skill.md", "reference.md"} or len(parts) < 2:
        return None
    if "skills" in parts[:-2]:
        index = max(i for i, part in enumerate(parts[:-2]) if part == "skills")
        return parts[index + 1].lower()
    return parts[-2].lower()


def _headings(path: Path) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    for line in path.read_text().splitlines():
        match = HEADING_RE.match(line)
        if match:
            headings.append((len(match.group("marks")), match.group("text").strip()))
    return headings


def _heading_paths(path: Path) -> list[tuple[str, ...]]:
    stack: list[tuple[int, str]] = []
    paths: list[tuple[str, ...]] = []
    for level, heading in _headings(path):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        paths.append(tuple(text for _, text in stack))
    return paths


def _reference_heading_violations(path: Path, line_number: int, line: str) -> list[Violation]:
    matches = list(SAME_SKILL_REFERENCE_RE.finditer(line))
    violations: list[Violation] = []
    reference = path.with_name("reference.md")
    for match in matches:
        wanted = tuple(part.strip() for part in re.findall(r"`([^`]+)`", match.group("path")))
        target = f"reference.md § {' > '.join(wanted)}"
        if not reference.is_file():
            violations.append(Violation(path, line_number, line.strip(), target,
                                        "missing same-skill reference file"))
            continue
        candidates = [heading for heading in _heading_paths(reference)
                      if len(heading) >= len(wanted) and heading[-len(wanted):] == wanted]
        if not candidates:
            violations.append(Violation(path, line_number, line.strip(), target,
                                        "missing same-skill reference heading"))
        elif len(candidates) > 1:
            violations.append(Violation(path, line_number, line.strip(), target,
                                        "duplicate same-skill reference heading"))
    for match in BROAD_SAME_SKILL_REFERENCE_RE.finditer(line):
        violations.append(Violation(path, line_number, line.strip(), "reference.md",
                                    "unaddressed same-skill reference"))
    return violations


def find_violations(root: Path = REPOSITORY_ROOT) -> list[Violation]:
    violations: list[Violation] = []
    documents = _skill_documents(root)
    public_names = _public_names(documents)
    for path in documents:
        current = _current_skill(path)
        frontmatter_name = _frontmatter_name(path)
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if path.name == "SKILL.md":
                violations.extend(_reference_heading_violations(path, line_number, line))
            if frontmatter_name and line.strip().lower() == f"# {frontmatter_name}":
                violations.append(
                    Violation(
                        path,
                        line_number,
                        line.strip(),
                        frontmatter_name,
                        "duplicate skill-name heading",
                    )
                )
            for match in SKILL_PATH_RE.finditer(line):
                target = _target_skill(match.group("path"))
                if target is not None and target != current:
                    violations.append(Violation(path, line_number, line.strip(), target))
            for match in PRIVATE_PHRASE_RE.finditer(line):
                target = match.group("name").lower()
                if target != current:
                    violations.append(Violation(path, line_number, line.strip(), target))
            if public_names:
                token_pattern = re.compile(
                    r"(?<![A-Za-z0-9_>}/])(?P<prefix>[$/])(?P<name>"
                    + "|".join(sorted((re.escape(name) for name in public_names), key=len, reverse=True))
                    + r")(?![A-Za-z0-9_-])"
                )
                for match in token_pattern.finditer(line):
                    target = match.group("name").lower()
                    if target.rsplit(":", 1)[-1] != current:
                        violations.append(
                            Violation(
                                path,
                                line_number,
                                line.strip(),
                                target,
                                "host-specific skill invocation",
                            )
                        )
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        for violation in violations:
            print(violation.render(REPOSITORY_ROOT))
        return 1
    print("OK skill cross-references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
