from __future__ import annotations

import json
import os
import shlex
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from .cli_integration_test_support import (
    GEAR,
    HOSTS,
    REPO,
    GearIntegrationTestsCase,
    gear,
)


class ResolveCommandTests(unittest.TestCase):
    def test_nested_command_prefers_current_then_exact_owner_then_unique_owner(self) -> None:
        plugins = {
            "engine": SimpleNamespace(name="engine", commands={"converge": ()}),
            "converge": SimpleNamespace(name="converge", commands={"converge": ()}),
            "spec": SimpleNamespace(name="spec", commands={"only": ()}),
        }
        with patch.object(gear, "discover", return_value=plugins):
            with patch.dict(os.environ, {"GEAR_PLUGIN": "engine", "BOOTGEAR_HOST": "codex"}):
                current = gear.resolve_command("converge")
            self.assertEqual(current, [str(GEAR), "--host", "codex", "engine", "converge"])

            with patch.dict(os.environ, {"GEAR_PLUGIN": "spec", "BOOTGEAR_HOST": "codex"}):
                exact = gear.resolve_command("converge")
            self.assertEqual(exact, [str(GEAR), "--host", "codex", "converge", "converge"])

            with patch.dict(os.environ, {"GEAR_PLUGIN": "engine", "BOOTGEAR_HOST": "codex"}):
                unique = gear.resolve_command("only")
            self.assertEqual(unique, [str(GEAR), "--host", "codex", "spec", "only"])


class HookManifestPopulationTests(unittest.TestCase):
    def test_only_engine_declares_a_pre_tool_use_hook(self) -> None:
        manifests = sorted(REPO.glob("plugins/*/hooks/*.json"))
        self.assertTrue(manifests)
        declaring = [str(path.relative_to(REPO)) for path in manifests
                     if "PreToolUse" in json.loads(path.read_text(encoding="utf-8")).get("hooks", {})]
        self.assertEqual(set(declaring), {
            "plugins/engine/hooks/codex-hooks.json",
            "plugins/engine/hooks/hooks.json",
        })


class GearIntegrationTests(GearIntegrationTestsCase):
    def test_default_root_discovery_works_from_the_relocated_entrypoint(self) -> None:
        caller = self.base / "outside-checkout"
        caller.mkdir()

        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = self._run(host, "list", cwd=caller)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("engine task", result.stdout)
                self.assertIn("cli setup", result.stdout)

    def test_provider_route_errors_print_provider_example_with_selected_root(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                root = self.base / f"route-error-root-{host}"
                provider = root / "plugins" / "fixture-provider"
                self._plugin(provider, "fixture-provider", "provider-command-ran")
                expected = shlex.join([
                    str(GEAR), "--host", host, "--root", str(root.resolve()),
                    "fixture-provider", "probe", "--help",
                ])

                for route in (("fixture-provider",), ("fixture-provider", "unknown")):
                    with self.subTest(route=route):
                        result = self._run(host, "--root", str(root), *route)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertIn(f"example: {expected}\n", result.stderr, result.stderr)
                        self.assertNotIn("example: gear --host codex list", result.stderr)
                        invocation = next(
                            line.removeprefix("example: ")
                            for line in result.stderr.splitlines()
                            if line.startswith("example: ")
                        )
                        positive = subprocess.run(
                            shlex.split(invocation), cwd=self.base, env=self.env,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=15, check=False,
                        )
                        self.assertEqual(positive.returncode, 0, positive.stderr)
                        self.assertEqual(positive.stdout, "provider-command-ran\n")

    def test_codex_session_without_host_routes_to_the_shared_package(self) -> None:
        root = self.base / "host-default-root"
        provider = self._plugin(root / "plugins" / "fixture-provider", "fixture-provider", "")
        self._write_executable(provider / "bin" / "probe",
                               '#!/bin/sh\necho "plugins $BOOTGEAR_HOST"\n')
        result = subprocess.run(
            [str(GEAR), "--root", str(root), "fixture-provider", "probe"],
            cwd=self.base, env={**self.env, "CODEX_SESSION_ID": "codex-id"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "plugins codex\n")

    def test_codex_uses_installed_cache_code_after_marketplace_checkout_changes(self) -> None:
        marketplace = self.base / "marketplace-checkout"
        checkout = marketplace / "plugins" / "fixture-provider"
        installed = (self.codex_home / "plugins" / "cache" / "fixture-marketplace"
                     / "fixture-provider" / "1.0.0")
        self._plugin(checkout, "fixture-provider", "marketplace-edited")
        self._plugin(installed, "fixture-provider", "installed-release")
        self.codex_list.write_text(json.dumps({
            "installed": [{
                "enabled": True,
                "installed": True,
                "marketplaceName": "fixture-marketplace",
                "name": "fixture-provider",
                "version": "1.0.0",
            }],
            "available": [],
        }), encoding="utf-8")

        empty_root = self.base / "empty-root"
        empty_root.mkdir()
        (checkout / "bin" / "probe").write_text(
            "#!/bin/sh\nprintf '%s\\n' 'marketplace-edited'\n", encoding="utf-8"
        )
        result = self._run("codex", "--root", str(empty_root), "fixture-provider", "probe")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "installed-release\n")
        self.assertEqual((installed / "bin" / "probe").read_text(encoding="utf-8"),
                         "#!/bin/sh\nprintf '%s\\n' 'installed-release'\n")

    def test_claude_discovers_an_enabled_installed_provider_root(self) -> None:
        installed = self.claude_home / "plugins" / "cache" / "fixture-provider"
        self._plugin(installed, "fixture-provider", "claude-installed")
        self.claude_list.write_text(json.dumps([{
            "enabled": True,
            "installPath": str(installed),
        }]), encoding="utf-8")
        empty_root = self.base / "empty-root"
        empty_root.mkdir()

        result = self._run("claude", "--root", str(empty_root), "fixture-provider", "probe")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "claude-installed\n")

    def test_claude_project_provider_uses_the_callers_project_scope(self) -> None:
        project = self.base / "caller-project"
        child = project / "nested"
        other_project = self.base / "other-project"
        child.mkdir(parents=True)
        other_project.mkdir()
        current_provider = self.claude_home / "plugins" / "cache" / "current-provider"
        other_provider = self.claude_home / "plugins" / "cache" / "other-provider"
        self._plugin(current_provider, "current-provider", "caller-project-provider")
        self._plugin(other_provider, "other-provider", "other-project-provider")
        self.claude_list.write_text(json.dumps([
            {"enabled": True, "projectPath": str(project), "installPath": str(current_provider)},
            {"enabled": True, "projectPath": str(other_project), "installPath": str(other_provider)},
        ]), encoding="utf-8")
        empty_root = self.base / "empty-root"
        empty_root.mkdir()

        for caller in (project, child):
            with self.subTest(caller=caller.name):
                current = self._run(
                    "claude", "--root", str(empty_root), "current-provider", "probe", cwd=caller
                )
                excluded = self._run(
                    "claude", "--root", str(empty_root), "other-provider", "probe", cwd=caller
                )

                self.assertEqual(current.returncode, 0, current.stderr)
                self.assertEqual(current.stdout, "caller-project-provider\n")
                self.assertEqual(excluded.returncode, 2)
                self.assertNotIn("other-project-provider", excluded.stdout)


if __name__ == "__main__":
    unittest.main()
