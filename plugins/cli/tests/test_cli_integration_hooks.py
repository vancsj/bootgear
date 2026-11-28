from __future__ import annotations

import ast
import json
import stat
import subprocess

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
            ("hooks.json", "${CLAUDE_PLUGIN_ROOT}", "claude", "startup|resume|clear|compact|fork"),
            ("codex-hooks.json", "${PLUGIN_ROOT}", "codex", "^(startup|resume|clear|compact|fork)$"),
        ):
            with self.subTest(manifest=manifest):
                hooks = json.loads((CLI_ROOT / "hooks" / manifest).read_text(encoding="utf-8"))["hooks"]
                self.assertEqual(sorted(hooks), ["PreToolUse", "SessionStart"])
                self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash")
                self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"],
                                 f'"{variable}/hooks/gear" --host {host} coordination-hook')
                groups = hooks["SessionStart"]
                self.assertEqual([group.get("matcher") for group in groups], [matcher])
                self.assertEqual([hook["command"] for group in groups for hook in group["hooks"]],
                                 [f'"{variable}/hooks/gear" --host {host} session-start'])
        codex = json.loads((CLI_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(codex["hooks"], "./hooks/codex-hooks.json")

    def test_installed_hook_uses_startup_inventory_and_forwards_events(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self._install_fake_cli(host)
                root = self._hook_provider(host)
                startup = b'{"hook_event_name":"SessionStart","source":"startup","session_id":"session-1"}'
                launched = self._run_hook(host, root, startup)
                self.assertEqual(launched.returncode, 7, launched.stdout + launched.stderr)
                for _ in range(2):
                    payload = b'{"hook_event_name":"PostToolUse","session_id":"session-1"}'
                    result = self._run_hook(host, root, payload)
                    self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, b"forwarded output\n")
                    self.assertEqual(result.stderr, b"forwarded warning\n")
                    self.assertEqual(self._gear_call(host)["session"], "session-1")
                self.assertEqual(self._query_count(host), 1)

    def test_engine_denies_without_inventory_and_does_not_query(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                root = self._hook_provider(host)
                payload = b'{"hook_event_name":"PreToolUse","session_id":"missing"}'
                result = self._run_hook(host, root, payload)
                reply = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(reply["permissionDecision"], "deny")
                self.assertIn("fresh host session", reply["permissionDecisionReason"])
                self.assertEqual(self._query_count(host), 0)

    def test_engine_question_wrapper_exits_two_when_python_cannot_start(self) -> None:
        record = self.data / "bootgear/python"
        fake = self.bin / "broken"
        fake.write_text("#!/bin/sh\nexit 3\n")
        fake.chmod(0o755)
        for unusable in (self.bin / "absent", fake):
            record.write_text(f"{unusable}\n")
            for host in ("claude", "codex"):
                with self.subTest(host=host, interpreter=unusable.name):
                    hook = REPO / "plugins/engine/hooks/gear"
                    result = subprocess.run(
                        [str(hook), "--host", host, "adapter", "--handler", "question_boundary"],
                        env=self.env, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=10,
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(b"could not check the question", result.stderr)
                    self.assertEqual(self._query_count(host), 0)
