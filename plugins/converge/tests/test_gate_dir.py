"""`gate` needs an absolute --dir holding the slate; refusals change nothing."""
from __future__ import annotations

import os

from conftest import Converge


def _snapshot(cv: Converge) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in cv.dir.iterdir()}


def test_gate_refuses_relative_dir(cv: Converge) -> None:
    cv.init()
    before = _snapshot(cv)
    rel = os.path.relpath(cv.dir, cv.project)
    result = cv("gate", "s1", "--dir", rel, code=2)
    assert "gate needs an absolute --dir" in result.stderr
    result = cv("gate", "s1", "--dir", "~/ledgers", code=2)
    assert "gate needs an absolute --dir" in result.stderr
    assert _snapshot(cv) == before


def test_gate_refuses_dir_without_the_slate(cv: Converge) -> None:
    cv.init()
    before = _snapshot(cv)
    other = cv.root / "empty"
    other.mkdir()
    result = cv("gate", "s1", "--dir", str(other), code=2)
    assert "no slate 's1' in" in result.stderr
    assert list(other.iterdir()) == []
    assert _snapshot(cv) == before


def test_gate_requires_dir(cv: Converge) -> None:
    cv.init()
    result = cv("gate", "s1", code=2)
    assert "--dir" in result.stderr
