"""The deputy installs on both hosts from one directory: the Claude and Codex manifests and the
Codex marketplace entry."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ManifestTests(unittest.TestCase):
    def test_codex_manifest_ships_the_skills_and_the_codex_hooks(self) -> None:
        codex = read_json(PLUGIN / ".codex-plugin" / "plugin.json")
        self.assertEqual(codex["name"], "deputy")
        self.assertEqual(codex["skills"], "./skills/")
        self.assertEqual(codex["hooks"], "./hooks/codex-hooks.json")
        self.assertTrue((PLUGIN / codex["hooks"]).is_file())
        self.assertTrue((PLUGIN / codex["skills"]).is_dir())
        for key in ("description", "author", "interface"):
            self.assertIn(key, codex)

    def test_both_manifests_carry_the_same_version(self) -> None:
        claude = read_json(PLUGIN / ".claude-plugin" / "plugin.json")
        codex = read_json(PLUGIN / ".codex-plugin" / "plugin.json")
        self.assertEqual(codex["version"], claude["version"])

    def test_codex_marketplace_has_one_deputy_entry(self) -> None:
        plugins = read_json(REPO / ".agents" / "plugins" / "marketplace.json")["plugins"]
        entries = [entry for entry in plugins if entry["name"] == "deputy"]
        self.assertEqual(entries, [{
            "name": "deputy",
            "source": "./plugins/deputy",
            "description": entries[0]["description"] if entries else "",
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }])

    def test_no_separate_codex_tree(self) -> None:
        self.assertFalse((REPO / "codex-plugins" / "deputy").exists())


if __name__ == "__main__":
    unittest.main()
