"""Shared package layout and active-host behavior contracts."""
from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "plugins" / "engine" / "src"))

from engine import config, session


def test_marketplaces_use_one_source_for_every_plugin() -> None:
    populations = []
    for marketplace in (REPO / ".claude-plugin/marketplace.json",
                        REPO / ".agents/plugins/marketplace.json"):
        entries = json.loads(marketplace.read_text())["plugins"]
        names = [entry["name"] for entry in entries]
        assert len(names) == len(set(names)), marketplace
        populations.append(set(names))
        for entry in entries:
            assert entry["source"] == f"./plugins/{entry['name']}", entry
    assert populations[0] == populations[1]


def test_every_shared_plugin_has_equal_native_versions() -> None:
    entries = json.loads((REPO / ".claude-plugin/marketplace.json").read_text())["plugins"]
    for entry in entries:
        root = REPO / "plugins" / entry["name"]
        manifests = [root / host / "plugin.json" for host in (".claude-plugin", ".codex-plugin")]
        for path in manifests:
            assert path.is_file(), path
        claude, codex = (json.loads(path.read_text()) for path in manifests)
        assert claude["version"] == codex["version"], entry["name"]


def test_no_mirrored_codex_source_tree() -> None:
    assert not (REPO / "codex-plugins").exists()


def test_engine_owns_only_engine_providers_and_skills() -> None:
    root = REPO / "plugins/engine"
    packages = {path.name for path in (root / "src").iterdir()
                if path.is_dir() and path.name != "__pycache__"}
    assert packages == {"engine"}
    commands = tomllib.loads((root / "gear.toml").read_text())["commands"]
    assert set(commands) == {"task", "adapter"}
    skills = {path.parent.name for path in (root / "skills").glob("*/SKILL.md")}
    assert skills == {"clarify", "debate", "execute", "recall", "resolve", "start"}


def test_clikit_has_one_provider_source() -> None:
    matches = list((REPO / "plugins").glob("*/src/**/clikit.py"))
    assert matches == [REPO / "plugins/cli/src/bootgear_cli/clikit.py"]
    assert not (REPO / "plugins/memory-ledger/scripts/ledgerlib/clikit.py").exists()


def test_independent_engine_and_converge_use_the_same_seat_rules() -> None:
    engine = REPO / "plugins/engine/src/engine/seats.py"
    converge = REPO / "plugins/converge/src/converge/seats.py"
    assert converge.read_bytes() == engine.read_bytes()


@pytest.mark.parametrize("host", ("claude", "codex"))
def test_config_uses_the_active_host_session_context(tmp_path: Path, host: str) -> None:
    for name in ("claude", "codex"):
        folder = tmp_path / f".{name}"
        folder.mkdir()
        (folder / "profile.yaml").write_text(f"source: {name}\n")
    with patch.dict(os.environ, {"HOME": str(tmp_path)}, clear=True):
        os.environ[{"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_SESSION_ID"}[host]] = "fixture"
        data = config.resolve("profile", tmp_path, None, None, None, False)
    assert data["effective"] == {"source": host}


def test_shared_session_parser_exposes_recall() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    session.add_subparsers(parser.add_subparsers(dest="cmd", required=True),
                           argparse.ArgumentParser(add_help=False))
    args = parser.parse_args(["recall", "fixture"])
    assert args.run_id == "fixture"
    assert callable(args.func)
