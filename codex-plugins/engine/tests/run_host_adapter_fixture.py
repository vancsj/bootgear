#!/usr/bin/env python3
"""Codex entry point for the canonical host-adapter fixture corpus."""
from __future__ import annotations

import runpy
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[3] / "plugins" / "engine" / "tests" / "run_host_adapter_fixture.py"


if __name__ == "__main__":
    runpy.run_path(str(RUNNER), run_name="__main__")
