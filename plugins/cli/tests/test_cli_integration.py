from __future__ import annotations

import importlib
import json
import os
import shlex
import shutil
import stat
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
HOOK_TEMPLATE = CLI_ROOT / "src" / "bootgear_cli" / "hook_loader.py"
LOADER_PLUGINS = ("codex-plugins/engine", "plugins/advisor", "plugins/cli", "plugins/deputy",
                  "plugins/engine", "plugins/memory-ledger")
sys.path.insert(0, str(CLI_ROOT / "src"))
gear = importlib.import_module("bootgear_cli.gear")

from .host_fixture import HOSTS, query_count, write_fake_host


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
    def test_no_plugin_declares_a_pre_tool_use_hook(self) -> None:
        manifests = sorted([*REPO.glob("plugins/*/hooks/*.json"),
                            *REPO.glob("codex-plugins/*/hooks/*.json")])
        self.assertTrue(manifests)
        declaring = [str(path.relative_to(REPO)) for path in manifests
                     if "PreToolUse" in json.loads(path.read_text(encoding="utf-8")).get("hooks", {})]
        self.assertEqual(declaring, [])


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
        self.queries = self.base / "queries.log"
        self.data = self.base / "data"
        for host in HOSTS:
            write_fake_host(self.bin, host)
        self.env = {
            "HOME": str(Path.home()),
            "CODEX_HOME": str(self.codex_home),
            "CLAUDE_CONFIG_DIR": str(self.claude_home),
            "GEAR_TEST_CODEX_LIST": str(self.codex_list),
            "GEAR_TEST_CLAUDE_LIST": str(self.claude_list),
            "GEAR_TEST_QUERIES": str(self.queries),
            "XDG_DATA_HOME": str(self.data),
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

    def _install_fake_cli(self, host: str, version: str = "1.0.0") -> Path:
        if host == "codex":
            plugin = (self.codex_home / "plugins" / "cache" / "fixture-marketplace"
                      / "cli" / version)
            plugin_id = {
                "enabled": True,
                "name": "cli",
                "marketplaceName": "fixture-marketplace",
                "version": version,
            }
            self.codex_list.write_text(json.dumps({"installed": [plugin_id], "available": []}),
                                       encoding="utf-8")
        else:
            plugin = self.claude_home / "plugins" / "cache" / "cli" / version
            self.claude_list.write_text(json.dumps([{
                "enabled": True,
                "id": "cli@fixture-marketplace",
                "installPath": str(plugin),
            }]), encoding="utf-8")
        self._write_fake_gear(plugin / "bin" / "gear")
        return plugin

    def _write_fake_gear(self, executable: Path) -> None:
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
            Path(os.environ["GEAR_TEST_CALL"]).write_text(json.dumps({
                "gear": str(Path(__file__).resolve()),
                "session": os.environ.get("BOOTGEAR_SESSION_ID"),
            }), encoding="utf-8")
            Path(os.environ["GEAR_TEST_EVENT"]).write_bytes(payload)
            if os.environ.get("GEAR_TEST_MODE") == "missing-runtime":
                print("gear: Shared runtime is missing. Run cli:setup, then retry.", file=sys.stderr)
                raise SystemExit(2)
            sys.stdout.buffer.write(b"forwarded output\\n")
            sys.stderr.buffer.write(b"forwarded warning\\n")
            raise SystemExit(7)
        """))

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
            "GEAR_TEST_CALL": str(self.base / f"{host}-gear-call.json"),
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

    def test_codex_session_without_host_routes_to_the_codex_package(self) -> None:
        root = self.base / "host-default-root"
        for registration_dir in ("plugins", "codex-plugins"):
            provider = self._plugin(root / registration_dir / "fixture-provider", "fixture-provider", "")
            self._write_executable(provider / "bin" / "probe",
                                   f'#!/bin/sh\necho "{registration_dir} $BOOTGEAR_HOST"\n')
        result = subprocess.run(
            [str(GEAR), "--root", str(root), "fixture-provider", "probe"],
            cwd=self.base, env={**self.env, "CODEX_SESSION_ID": "codex-id"},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "codex-plugins codex\n")

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

    def _gear_call(self, host: str) -> dict[str, object]:
        return json.loads((self.base / f"{host}-gear-call.json").read_text(encoding="utf-8"))

    def _query_count(self, host: str) -> int:
        return query_count(self.queries, host)

    def test_native_hook_loaders_match_the_shared_template(self) -> None:
        loaders = sorted(str(path.parent.parent.relative_to(REPO)) for path in
                         [*REPO.glob("plugins/*/hooks/gear.py"), *REPO.glob("codex-plugins/*/hooks/gear.py")])
        self.assertEqual(loaders, list(LOADER_PLUGINS))
        launcher = (REPO / "plugins" / "engine" / "hooks" / "gear").read_bytes()
        for plugin in LOADER_PLUGINS:
            with self.subTest(plugin=plugin):
                hooks = REPO / plugin / "hooks"
                self.assertEqual((hooks / "gear.py").read_bytes(), HOOK_TEMPLATE.read_bytes())
                self.assertEqual((hooks / "gear").read_bytes(), launcher)
                self.assertEqual(stat.S_IMODE((hooks / "gear").stat().st_mode), 0o755)

    def test_cli_hook_manifests_declare_session_start(self) -> None:
        for manifest, variable, host, matcher in (
            ("hooks.json", "${CLAUDE_PLUGIN_ROOT}", "claude", "startup|resume"),
            ("codex-hooks.json", "${PLUGIN_ROOT}", "codex", "^(startup|resume)$"),
        ):
            with self.subTest(manifest=manifest):
                hooks = json.loads((CLI_ROOT / "hooks" / manifest).read_text(encoding="utf-8"))["hooks"]
                self.assertEqual(sorted(hooks), ["SessionStart"])
                groups = hooks["SessionStart"]
                self.assertEqual([group.get("matcher") for group in groups], [matcher])
                self.assertEqual([hook["command"] for group in groups for hook in group["hooks"]],
                                 [f'"{variable}/hooks/gear" --host {host} session-start'])
        codex = json.loads((CLI_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(codex["hooks"], "./hooks/codex-hooks.json")

    def test_installed_hook_reuses_the_store_and_passes_the_session(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._install_fake_cli(host)
                root = self._hook_provider(host)
                for _ in range(2):
                    result = self._run_hook(host, root, payload)
                    self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                    self.assertEqual(self._gear_call(host)["session"], "session-1")
                self.assertEqual(self._query_count(host), 1)

    def test_hook_refreshes_once_when_the_stored_cli_is_gone(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                old = self._install_fake_cli(host, "1.0.0")
                root = self._hook_provider(host)
                first = self._run_hook(host, root, payload)
                self.assertEqual(first.returncode, 7, first.stdout + first.stderr)
                self.assertEqual(self._gear_call(host)["gear"], str((old / "bin" / "gear").resolve()))
                shutil.rmtree(old)
                new = self._install_fake_cli(host, "1.0.1")

                second = self._run_hook(host, root, payload)

                self.assertEqual(second.returncode, 7, second.stdout + second.stderr)
                self.assertEqual(self._gear_call(host)["gear"], str((new / "bin" / "gear").resolve()))
                self.assertEqual(self._query_count(host), 2)

    def test_hook_without_a_cli_record_queries_once(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                root = self._hook_provider(host)

                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 0, result.stderr.decode())
                context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
                self.assertIn("The shared CLI plugin is missing", context)
                self.assertEqual(self._query_count(host), 1)

    def test_hook_names_a_silent_failing_host_query(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._write_executable(self.bin / host, "#!/bin/sh\nexit 1\n")
                root = self._hook_provider(host)

                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 0, result.stderr.decode())
                context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
                self.assertEqual(context, f"Gear setup required: {host} plugin list --json failed: "
                                          "exit code 1 Invoke cli:setup, then retry.")

    def test_hook_names_a_host_query_with_invalid_json(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._write_executable(self.bin / host, "#!/bin/sh\necho 'not json'\n")
                root = self._hook_provider(host)

                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 0, result.stderr.decode())
                context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
                self.assertTrue(context.startswith(
                    f"Gear setup required: {host} plugin list --json returned invalid JSON: "), context)

    def test_hook_replaces_a_stored_inventory_of_the_wrong_type(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                cli = self._install_fake_cli(host)
                root = self._hook_provider(host)
                entry = self.data / "bootgear" / "host-plugins" / host / "session-1.json"
                entry.parent.mkdir(parents=True)
                entry.write_text('{"inventory": null}', encoding="utf-8")

                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                self.assertEqual(self._gear_call(host)["gear"], str((cli / "bin" / "gear").resolve()))
                self.assertEqual(self._query_count(host), 1)
                listed = self.claude_list if host == "claude" else self.codex_list
                self.assertEqual(json.loads(entry.read_text(encoding="utf-8")),
                                 {"inventory": json.loads(listed.read_text(encoding="utf-8"))})

    def test_hook_with_an_unsafe_session_passes_no_session_and_stores_nothing(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"../x"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._install_fake_cli(host)
                root = self._hook_provider(host)

                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                self.assertIsNone(self._gear_call(host)["session"])
                self.assertFalse((self.data / "bootgear").exists())

    def test_cli_loader_uses_its_own_gear_without_a_query(self) -> None:
        payload = b'{"hook_event_name":"SessionStart","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                root = self.base / f"{host}-cli"
                (root / "hooks").mkdir(parents=True)
                for name in ("gear", "gear.py"):
                    shutil.copyfile(CLI_ROOT / "hooks" / name, root / "hooks" / name)
                (root / "hooks" / "gear").chmod(0o755)
                (root / "gear.toml").write_text('[plugin]\nname = "cli"\n', encoding="utf-8")
                self._write_fake_gear(root / "bin" / "gear")

                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                self.assertEqual(json.loads((self.base / f"{host}-gear-args.json").read_text()),
                                 ["--host", host, "cli", "probe", "one"])
                self.assertEqual(self._gear_call(host), {
                    "gear": str((root / "bin" / "gear").resolve()), "session": "session-1"})
                self.assertEqual(self._query_count(host), 0)

    def test_hook_store_write_failure_keeps_the_call(self) -> None:
        payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._install_fake_cli(host)
                root = self._hook_provider(host)
                folder = self.data / "bootgear" / "host-plugins" / host
                folder.mkdir(parents=True)
                folder.chmod(0o500)
                self.addCleanup(folder.chmod, 0o700)

                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                self.assertEqual(result.stdout, b"forwarded output\n")
                self.assertEqual(list(folder.iterdir()), [])

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
