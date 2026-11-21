from __future__ import annotations

import ast
import json
import shutil
import stat

from .cli_integration_test_support import (
    CLI_ROOT,
    HOOK_TEMPLATE,
    LOADER_PLUGINS,
    REPO,
    GearIntegrationTestsCase,
)


class GearIntegrationTests(GearIntegrationTestsCase):
    def test_native_hook_loaders_share_the_common_template_surface(self) -> None:
        loaders = sorted(str(path.parent.parent.relative_to(REPO)) for path in
                         list(REPO.glob("plugins/*/hooks/gear.py")))
        self.assertEqual(loaders, list(LOADER_PLUGINS))
        launcher = (REPO / "plugins" / "engine" / "hooks" / "gear").read_bytes()
        template = HOOK_TEMPLATE.read_bytes()

        def shared_nodes(source: bytes) -> list[str]:
            tree = ast.parse(source)
            return [ast.dump(node, include_attributes=False) for node in tree.body
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or node.name not in {"_remind", "main"}]

        for plugin in LOADER_PLUGINS:
            with self.subTest(plugin=plugin):
                hooks = REPO / plugin / "hooks"
                source = (hooks / "gear.py").read_bytes()
                if plugin == "plugins/engine":
                    self.assertEqual(shared_nodes(source), shared_nodes(template))
                    self.assertIn(b'"permissionDecision": "deny"', source)
                else:
                    self.assertEqual(source, template)
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

    def test_codex_cold_hook_uses_scoped_cli_inventory(self) -> None:
        self._install_fake_cli("codex")
        root = self._hook_provider("codex")
        self.env["GEAR_TEST_CODEX_UNSCOPED_FAIL"] = "1"

        result = self._run_hook("codex", root, b'{"session_id":"cold-hook"}')

        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual(self.queries.read_text().splitlines(), [
            "codex plugin marketplace list --json",
            "codex plugin list --marketplace fixture-marketplace --json"])

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
                command = f"{host} plugin " + ("marketplace list --json" if host == "codex" else "list --json")
                self.assertEqual(context, f"Gear setup required: {command} failed: "
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
                command = f"{host} plugin " + ("marketplace list --json" if host == "codex" else "list --json")
                self.assertTrue(context.startswith(
                    f"Gear setup required: {command} returned invalid JSON: "), context)

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

    def test_native_question_hooks_deny_when_the_shared_cli_is_missing(self) -> None:
        payload = b'{"hook_event_name":"PreToolUse"}'
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                root = self._hook_provider(host)
                result = self._run_hook(host, root, payload)

                self.assertEqual(result.returncode, 0, result.stderr.decode())
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "PreToolUse")
                self.assertEqual(output["permissionDecision"], "deny")
                self.assertIn("The shared CLI plugin is missing", output["permissionDecisionReason"])

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
                self.assertEqual(output["permissionDecision"], "deny")
                self.assertIn("Shared runtime is missing", output["permissionDecisionReason"])
                self.assertIn("Invoke cli:setup", output["permissionDecisionReason"])

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
