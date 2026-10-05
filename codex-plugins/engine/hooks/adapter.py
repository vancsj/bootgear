#!/usr/bin/env python3
"""Installed Codex host adapter entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOST = "codex"
_ROOT_ENV = "PLUGIN_ROOT"


def _source_dir() -> Path:
    root = os.environ.get(_ROOT_ENV)
    if root:
        return Path(root).expanduser().resolve(strict=False) / "src"
    return Path(__file__).resolve().parent.parent / "src"


_plugin_root = Path(os.environ.get(_ROOT_ENV, Path(__file__).resolve().parent.parent))
os.environ.setdefault(_ROOT_ENV, str(_plugin_root.resolve(strict=False)))
_source = _source_dir()
if str(_source) not in sys.path:
    sys.path.insert(0, str(_source))

from engine.host_adapter import run

if __name__ == "__main__":
    raise SystemExit(run(HOST, sys.argv[1:]))
