"""The size of a fix: files, test files and changed lines of a unified diff.

A file's path is taken from its `+++ ` header (the `--- ` header for a deletion), cut at
the first tab (`diff -u` appends a timestamp) with one leading `a/` or `b/` removed.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

HUNK_RE = re.compile(r"\A@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
RENAME = ("rename from ", "rename to ", "copy from ", "copy to ")
BINARY = ("Binary files ", "GIT binary patch")


class EffortError(Exception):
    pass


def header_path(raw: str) -> str:
    path = raw.split("\t", 1)[0].strip()
    return path[2:] if path.startswith(("a/", "b/")) else path


def is_test(path: str, test_globs: list[str]) -> bool:
    """`path` matches a glob; a glob starting with `**/` also matches at the top level."""
    return any(fnmatch.fnmatchcase(path, glob)
               or (glob.startswith("**/") and fnmatch.fnmatchcase(path, glob[3:]))
               for glob in test_globs)


def _absolute(path: str, root: Path) -> str:
    return os.path.normpath(path if os.path.isabs(path) else root / path)


def _relative(path: str, root: Path | None) -> str:
    """`path` relative to `root` when one of its absolute forms lies under it."""
    if root is None:
        return path
    for candidate in (_absolute(path, root), os.path.normpath("/" + path)):
        if candidate.startswith(os.path.normpath(root) + os.sep):
            return os.path.relpath(candidate, root)
    return path


def same_file(path: str, loc_path: str, root: Path) -> bool:
    """A patch path equals the loc path: the patch path joined to `root` unless absolute,
    or `/` plus the patch path (`git diff --no-index` drops the leading `/`), against the
    loc path joined to `root` unless absolute."""
    target = _absolute(loc_path, root)
    return target in (_absolute(path, root), os.path.normpath("/" + path))


def _files(patch: str) -> list[tuple[str, int]]:
    """(path, changed lines) per file of the diff."""
    files: list[list[Any]] = []
    old: str | None = None
    lines = iter(patch.splitlines())
    for line in lines:
        if line.startswith(RENAME):
            raise EffortError(f"a rename or copy is not measured: {line}")
        if line.startswith(BINARY):
            raise EffortError(f"a binary diff is not measured: {line}")
        if line.startswith("--- "):
            old = header_path(line[4:])
        elif line.startswith("+++ "):
            new = header_path(line[4:])
            files.append([old if new == "/dev/null" and old else new, 0])
        elif (match := HUNK_RE.match(line)) is not None:
            if not files:
                raise EffortError("not a unified diff: a hunk comes before its `+++ ` header")
            removed, added = int(match.group(1) or 1), int(match.group(2) or 1)
            while removed > 0 or added > 0:
                body = next(lines, None)
                if body is None:
                    raise EffortError(f"not a unified diff: a hunk of {files[-1][0]} ends early")
                if body.startswith("\\"):
                    continue
                if body.startswith("-"):
                    removed -= 1
                elif body.startswith("+"):
                    added -= 1
                elif body.startswith(" ") or not body:
                    removed, added = removed - 1, added - 1
                    continue
                else:
                    raise EffortError(f"not a unified diff: bad hunk line {body!r}")
                files[-1][1] += 1
    if not files or any(count == 0 for _, count in files):
        raise EffortError("not a unified diff: every file needs a `+++ ` header and a "
                          "changed line")
    return [(path, count) for path, count in files]


def measure(patch: str, test_globs: list[str], root: Path | None = None) -> dict[str, Any]:
    """`files` (non-test), `test_files`, changed `lines` (`+` and `-` body lines) and the
    non-test `paths` of a unified diff; raise EffortError for a rename, a binary diff or an
    unparsable patch. A path is a test file when its form relative to `root` matches a
    glob."""
    files = _files(patch)
    paths = [path for path, _ in files if not is_test(_relative(path, root), test_globs)]
    return {"files": len(paths), "test_files": len(files) - len(paths),
            "lines": sum(count for _, count in files), "paths": paths}
