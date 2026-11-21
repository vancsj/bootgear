from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

REPO = Path(__file__).resolve().parents[3]
CLI_ROOT = REPO / "plugins" / "cli"
GEAR = CLI_ROOT / "bin" / "gear"
HOOK_TEMPLATE = CLI_ROOT / "src" / "bootgear_cli" / "hook_loader.py"
LOADER_PLUGINS = ("plugins/advisor", "plugins/cli", "plugins/deputy",
                  "plugins/engine", "plugins/memory-ledger")
sys.path.insert(0, str(CLI_ROOT / "src"))
gear = importlib.import_module("bootgear_cli.gear")

from .host_fixture import HOSTS, query_count, write_fake_host


class GearIntegrationTestsCase(unittest.TestCase):
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
        source = REPO / "plugins" / "engine"
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

    def _gear_call(self, host: str) -> dict[str, object]:
        return json.loads((self.base / f"{host}-gear-call.json").read_text(encoding="utf-8"))

    def _query_count(self, host: str) -> int:
        return query_count(self.queries, host)

__all__ = ['HOSTS']
