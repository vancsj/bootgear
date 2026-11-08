from __future__ import annotations

import importlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
CLI_ROOT = REPO / "plugins" / "cli"
GEAR = CLI_ROOT / "bin" / "gear"
HOOK_TEMPLATE = CLI_ROOT / "hook-loader.py"
sys.path.insert(0, str(CLI_ROOT / "src"))
gear = importlib.import_module("bootgear_cli.gear")


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


class GearIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="gear-cli-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.codex_home = self.base / "codex-home"
        self.claude_home = self.base / "claude-config"
        self.codex_list = self.base / "codex-list.json"
        self.claude_list = self.base / "claude-list.json"
        self.codex_list.write_text('{"installed": [], "available": []}\n', encoding="utf-8")
        self.claude_list.write_text("[]\n", encoding="utf-8")
        self._write_executable(
            self.bin / "codex",
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            "print(Path(os.environ['GEAR_TEST_CODEX_LIST']).read_text(encoding='utf-8'), end='')\n",
        )
        self._write_executable(
            self.bin / "claude",
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            "print(Path(os.environ['GEAR_TEST_CLAUDE_LIST']).read_text(encoding='utf-8'), end='')\n",
        )
        self.env = {
            "HOME": str(Path.home()),
            "CODEX_HOME": str(self.codex_home),
            "CLAUDE_CONFIG_DIR": str(self.claude_home),
            "GEAR_TEST_CODEX_LIST": str(self.codex_list),
            "GEAR_TEST_CLAUDE_LIST": str(self.claude_list),
            "PATH": os.pathsep.join((str(self.bin), str(Path(sys.executable).parent), "/usr/bin:/bin")),
            "LANG": "C.UTF-8",
        }

    def _write_executable(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def _plugin(self, root: Path, name: str, message: str) -> Path:
        plugin = root / "gear.toml"
        root.mkdir(parents=True, exist_ok=True)
        (root / "bin").mkdir(exist_ok=True)
        (root / "bin" / "probe").write_text(
            f"#!/bin/sh\nprintf '%s\\n' '{message}'\n", encoding="utf-8"
        )
        (root / "bin" / "probe").chmod(0o755)
        plugin.write_text(
            f'[plugin]\nname = "{name}"\n\n'
            '[commands.probe]\nexec = ["./bin/probe"]\n',
            encoding="utf-8",
        )
        return root

    def _run(self, host: str, *args: str, cwd: Path | None = None
             ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(GEAR), "--host", host, *args],
            cwd=cwd or self.base,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def _install_fake_cli(self, host: str) -> Path:
        if host == "codex":
            plugin = (self.codex_home / "plugins" / "cache" / "fixture-marketplace"
                      / "cli" / "1.0.0")
            plugin_id = {
                "enabled": True,
                "name": "cli",
                "marketplaceName": "fixture-marketplace",
                "version": "1.0.0",
            }
            self.codex_list.write_text(json.dumps({"installed": [plugin_id], "available": []}),
                                       encoding="utf-8")
        else:
            plugin = self.claude_home / "plugins" / "cache" / "cli"
            self.claude_list.write_text(json.dumps([{
                "enabled": True,
                "id": "cli@fixture-marketplace",
                "installPath": str(plugin),
            }]), encoding="utf-8")
        executable = plugin / "bin" / "gear"
        executable.parent.mkdir(parents=True, exist_ok=True)
        self._write_executable(executable, dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            payload = sys.stdin.buffer.read()
            Path(os.environ["GEAR_TEST_ARGS"]).write_text(
                json.dumps(sys.argv[1:]), encoding="utf-8"
            )
            Path(os.environ["GEAR_TEST_EVENT"]).write_bytes(payload)
            if os.environ.get("GEAR_TEST_MODE") == "missing-runtime":
                print("gear: Shared runtime is missing. Run cli:setup, then retry.", file=sys.stderr)
                raise SystemExit(2)
            sys.stdout.buffer.write(b"forwarded output\\n")
            sys.stderr.buffer.write(b"forwarded warning\\n")
            raise SystemExit(7)
        """))
        return plugin

    def _hook_provider(self, host: str) -> Path:
        source = REPO / ("plugins" if host == "claude" else "codex-plugins") / "engine"
        root = self.base / f"{host}-provider"
        hooks = root / "hooks"
        hooks.mkdir(parents=True)
        shutil.copyfile(source / "hooks" / "gear", hooks / "gear")
        shutil.copyfile(source / "hooks" / "gear.py", hooks / "gear.py")
        (hooks / "gear").chmod(0o755)
        (root / "gear.toml").write_text(
            '[plugin]\nname = "fixture-provider"\n\n'
            '[commands.probe]\nexec = ["./bin/probe"]\n',
            encoding="utf-8",
        )
        return root

    def _run_hook(self, host: str, root: Path, payload: bytes, *, mode: str = "forward"
                  ) -> subprocess.CompletedProcess[bytes]:
        event_log = self.base / f"{host}-hook-event.json"
        args_log = self.base / f"{host}-gear-args.json"
        env = {
            **self.env,
            "GEAR_TEST_EVENT": str(event_log),
            "GEAR_TEST_ARGS": str(args_log),
            "GEAR_TEST_MODE": mode,
        }
        return subprocess.run(
            [str(root / "hooks" / "gear"), "--host", host, "probe", "one"],
            cwd=root,
            env=env,
            input=payload,
            capture_output=True,
            timeout=15,
            check=False,
        )

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
        for host, registration_dir in (("claude", "plugins"), ("codex", "codex-plugins")):
            with self.subTest(host=host):
                root = self.base / f"route-error-root-{host}"
                provider = root / registration_dir / "fixture-provider"
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

    def test_native_hook_loaders_match_the_shared_template(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                source = REPO / ("plugins" if host == "claude" else "codex-plugins") / "engine"
                self.assertEqual((source / "hooks" / "gear.py").read_bytes(),
                                 HOOK_TEMPLATE.read_bytes())

    def test_native_hooks_report_missing_cli_and_offer_setup(self) -> None:
        payload = b'{"hook_event_name":"SessionStart"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                root = self._hook_provider(host)
                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 0, result.stderr.decode())
                guidance = json.loads(result.stdout)
                output = guidance["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "SessionStart")
                self.assertIn("The shared CLI plugin is missing", output["additionalContext"])
                self.assertIn("Invoke cli:setup", output["additionalContext"])

    def test_native_hooks_report_missing_runtime_and_offer_setup(self) -> None:
        payload = b'{"hook_event_name":"PreToolUse","event":"runtime"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._install_fake_cli(host)
                root = self._hook_provider(host)
                result = self._run_hook(host, root, payload, mode="missing-runtime")

                self.assertEqual(result.returncode, 0, result.stderr.decode())
                guidance = json.loads(result.stdout)
                output = guidance["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "PreToolUse")
                self.assertIn("Shared runtime is missing", output["additionalContext"])
                self.assertIn("Invoke cli:setup", output["additionalContext"])

    def test_native_hooks_forward_event_output_and_exit_status(self) -> None:
        payload = b'{"hook_event_name":"SessionStart","event":"forward"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                cli = self._install_fake_cli(host)
                root = self._hook_provider(host)
                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 7)
                self.assertEqual(result.stdout, b"forwarded output\n")
                self.assertEqual(result.stderr, b"forwarded warning\n")
                self.assertTrue((cli / "bin" / "gear").is_file())
                self.assertEqual((self.base / f"{host}-hook-event.json").read_bytes(), payload)
                self.assertEqual(json.loads((self.base / f"{host}-gear-args.json").read_text()), [
                    "--host", host, "fixture-provider", "probe", "one",
                ])


if __name__ == "__main__":
    unittest.main()
