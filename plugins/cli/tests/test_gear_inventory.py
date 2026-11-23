from __future__ import annotations

import json
import stat
from unittest.mock import patch

from bootgear_cli import hook_loader

from .cli_integration_test_support import GearIntegrationTestsCase


class HostPluginStoreTests(GearIntegrationTestsCase):
    def test_standalone_inventory_is_created_only_by_explicit_reconcile(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._provider_record(host)
                root = self.base / f"empty-{host}"
                root.mkdir()
                command = ("--root", str(root), "fixture-provider", "probe")
                before = self._run(host, *command)
                self.assertEqual(before.returncode, 2)
                self.assertIn("reconcile", before.stderr)
                self.assertEqual(self._query_count(host), 0)
                reconcile = self._run(host, "--root", str(root), "reconcile")
                self.assertEqual(reconcile.returncode, 0, reconcile.stderr)
                self.assertEqual(self._run(host, *command).stdout, "ready\n")
                self.assertEqual(self._run(host, *command).stdout, "ready\n")
                self.assertEqual(self._query_count(host), 1)
                another = self.base / f"another-{host}"
                another.mkdir()
                self.assertEqual(self._run(host, *command, cwd=another).returncode, 2)
                self.assertEqual(self._query_count(host), 1)

    def test_codex_explicit_scan_keeps_marketplaces_scoped(self) -> None:
        self._provider_record("codex")
        self.env["GEAR_TEST_CODEX_UNSCOPED_FAIL"] = "1"
        marketplaces = self.base / "marketplaces.json"
        marketplaces.write_text(json.dumps({"marketplaces": [
            {"name": "fixture-marketplace"}, {"name": "openai-curated-remote"},
        ]}))
        self.env["GEAR_TEST_CODEX_MARKETPLACES"] = str(marketplaces)
        result = self._run("codex", "reconcile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fixture-provider probe", result.stdout)
        self.assertEqual(self.queries.read_text().splitlines(), [
            "codex plugin marketplace list --json",
            "codex plugin list --marketplace fixture-marketplace --json",
        ])

    def test_profiles_do_not_share_session_inventory(self) -> None:
        with patch.dict("os.environ", self.env):
            first = hook_loader.store_path("codex", "same-id")
            hook_loader._write_entry(first, {"installed": []}, self.base)
            with patch.dict("os.environ", {"CODEX_HOME": str(self.base / "other profile")}):
                self.assertNotEqual(first, hook_loader.store_path("codex", "same-id"))
                with self.assertRaisesRegex(RuntimeError, "fresh.*session"):
                    hook_loader.host_inventory("codex", "same-id")
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)

    def test_nested_reconcile_never_queries(self) -> None:
        self.env["BOOTGEAR_HOOK_ACTIVE"] = "1"
        result = self._run("codex", "reconcile")
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the hook", result.stderr)
        self.assertEqual(self._query_count("codex"), 0)

    def _provider_record(self, host: str) -> None:
        if host == "codex":
            path = self.codex_home / "plugins/cache/fixture-marketplace/fixture-provider/1.0.0"
            self.codex_list.write_text(json.dumps({"installed": [{
                "name": "fixture-provider", "version": "1.0.0",
                "enabled": True, "marketplaceName": "fixture-marketplace",
            }]}))
        else:
            path = self.claude_home / "fixture-provider"
            self.claude_list.write_text(json.dumps([{
                "installPath": str(path), "enabled": True, "id": "fixture-provider@fixture-marketplace",
            }]))
        self._plugin(path, "fixture-provider", "ready")
