#!/usr/bin/env python3
"""Reject repository files that hardcode a local path, point into the docs
folder from code or skills, narrate development history, or contain a term
from the local denylist."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# Placeholder account names that stand for "any user" in examples and tests.
PLACEHOLDER_USERS = {"someone", "you", "user", "username", "name", "me", "example", "runner"}
HOME_PATH_RE = re.compile(
    r"(?:/(?:Users|home)/|[A-Za-z]:\\Users\\)(?P<user>[A-Za-z0-9][A-Za-z0-9._-]*)"
)
# `~name/` is another account's home; plain `~/` is the reader's own.
TILDE_USER_RE = re.compile(r"(?<![\w~])~(?P<user>[A-Za-z][A-Za-z0-9._-]*)/")
SCRATCHPAD_RE = re.compile(r"(?:/tmp/claude-\d+/|/var/folders/[\w-]+/)")
# A file in this repo's own docs folder: a relative path (optionally through
# `./` or `../`), a root-relative Markdown link, or a GitHub URL into this
# repository. Naming the folder alone is not a pointer.
_DOCS_FILE = r"docs/[\w.-][\w./-]*"
DOCS_POINTER_RE = re.compile(
    rf"(?<![\w/.-])(?:\.\.?/)*{_DOCS_FILE}"
    rf"|(?<=\]\()/{_DOCS_FILE}"
    rf"|/bootgear/(?:blob|tree)/\S+?/{_DOCS_FILE}"
    rf"|raw\.githubusercontent\.com/[\w.-]+/bootgear/\S+?/{_DOCS_FILE}"
)
# Phrases that narrate how the code got here rather than what it does now.
# Kept to exact phrases: looser words like "used to" have ordinary meanings.
DIARY_PHRASES = (
    "before this " + "fix",
    "found in " + "review",
    "tried and " + "rejected",
    "an earlier " + "version",
    "previous version of this " + "test",
)
# Terms kept outside the repo (personal skills, employer names, private
# folders) so the list itself is never committed. One term per line.
DENYLIST_ENV = "BOOTGEAR_CONTENT_DENYLIST"
DEFAULT_DENYLIST = Path.home() / ".bootgear" / "content-denylist.txt"


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    text: str
    rule: str = "hardcoded local path"

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.text}"


def _repository_files(root: Path) -> list[Path]:
    """Tracked files plus new files not yet added, so a check before the
    first commit of a file still sees it."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted({Path(name) for name in listed.split("\0") if name})


def load_denylist(path: Path | None = None) -> list[str]:
    if path is None:
        path = Path(os.environ.get(DENYLIST_ENV) or DEFAULT_DENYLIST)
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    return [line.strip().lower() for line in lines if line.strip() and not line.startswith("#")]


def line_violations(text: str) -> list[str]:
    found = [match.group(0) for match in HOME_PATH_RE.finditer(text)
             if match.group("user").lower() not in PLACEHOLDER_USERS]
    found.extend(match.group(0) for match in TILDE_USER_RE.finditer(text)
                 if match.group("user").lower() not in PLACEHOLDER_USERS)
    found.extend(match.group(0) for match in SCRATCHPAD_RE.finditer(text))
    return found


def diary_phrases(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in DIARY_PHRASES if phrase in lowered]


def _may_point_to_docs(relative: Path) -> bool:
    """README and CONTRIBUTING files describe the repo layout; the docs
    folder and test trees are the pointer targets and fixtures themselves."""
    parts = relative.parts
    if parts[0] == "docs" or "tests" in parts:
        return True
    return relative.name in {"README.md", "CONTRIBUTING.md"}


def find_violations(
    root: Path = REPOSITORY_ROOT,
    paths: list[Path] | None = None,
    denylist: list[str] | None = None,
) -> list[Violation]:
    terms = load_denylist() if denylist is None else denylist
    violations: list[Violation] = []
    for relative in paths if paths is not None else _repository_files(root):
        try:
            content = (root / relative).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(content.splitlines(), 1):
            for hit in line_violations(line):
                violations.append(Violation(relative, number, hit))
            if not _may_point_to_docs(relative):
                for match in DOCS_POINTER_RE.finditer(line):
                    violations.append(Violation(relative, number, match.group(0), "points to docs"))
            for phrase in diary_phrases(line):
                violations.append(Violation(relative, number, phrase, "development diary"))
            lowered = line.lower()
            for term in terms:
                if term in lowered:
                    violations.append(Violation(relative, number, term, "denylisted term"))
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        for violation in violations:
            print(violation.render())
        return 1
    print("OK no local paths, docs pointers, diary phrases, or denylisted terms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
