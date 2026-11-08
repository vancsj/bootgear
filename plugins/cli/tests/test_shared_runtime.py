from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from textwrap import dedent

REPO = Path(__file__).resolve().parents[3]
CLI_ROOT = REPO / "plugins" / "cli"
GEAR = CLI_ROOT / "bin" / "gear"


class SharedRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="gear-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.fake_bin = self.base / "bin"
        self.fake_bin.mkdir()
        self.codex_home = self.base / "codex-home"
        self.claude_home = self.base / "claude-config"
        self.xdg_data = self.base / "xdg-data"
        self.uv_log = self.base / "uv.log"
        self.codex_list = self.base / "codex-list.json"
        self.claude_list = self.base / "claude-list.json"
        self.codex_list.write_text('{"installed": [], "available": []}\n', encoding="utf-8")
        self.claude_list.write_text("[]\n", encoding="utf-8")
        self._write_fake_hosts()
        self._write_fake_uv()
        python_bin = Path(sys.executable).parent
        system_path = "/usr/bin:/bin"
        self.env = {
            "HOME": str(Path.home()),
            "CODEX_HOME": str(self.codex_home),
            "CLAUDE_CONFIG_DIR": str(self.claude_home),
            "XDG_DATA_HOME": str(self.xdg_data),
            "BOOTGEAR_TEST_PYTHON": sys.executable,
            "BOOTGEAR_TEST_UV_LOG": str(self.uv_log),
            "BOOTGEAR_FAKE_CODEX_LIST": str(self.codex_list),
            "BOOTGEAR_FAKE_CLAUDE_LIST": str(self.claude_list),
            "BOOTGEAR_SESSION_ID": "runtime-test-session",
            "PATH": os.pathsep.join((str(self.fake_bin), str(python_bin), system_path)),
            "LANG": "C.UTF-8",
        }

    def _write_executable(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def _write_fake_hosts(self) -> None:
        for name, variable in (("codex", "BOOTGEAR_FAKE_CODEX_LIST"),
                               ("claude", "BOOTGEAR_FAKE_CLAUDE_LIST")):
            self._write_executable(
                self.fake_bin / name,
                "#!/usr/bin/env python3\n"
                "import os\n"
                "from pathlib import Path\n"
                f"print(Path(os.environ[{variable!r}]).read_text(encoding='utf-8'), end='')\n",
            )

    def _write_fake_uv(self) -> None:
        self._write_executable(self.fake_bin / "uv", dedent("""\
            #!/usr/bin/env python3
            import os
            import subprocess
            import sys
            import time
            from pathlib import Path

            args = sys.argv[1:]
            log = Path(os.environ["BOOTGEAR_TEST_UV_LOG"])
            with log.open("a", encoding="utf-8") as stream:
                stream.write(" ".join(args[:2]) + "\\n")
            if args[:2] == ["python", "find"]:
                print(os.environ["BOOTGEAR_TEST_PYTHON"])
            elif args and args[0] == "sync":
                environment = Path(os.environ["UV_PROJECT_ENVIRONMENT"])
                subprocess.run(
                    [os.environ["BOOTGEAR_TEST_PYTHON"], "-m", "venv", str(environment), "--without-pip"],
                    check=True,
                )
                block = os.environ.get("BOOTGEAR_BLOCK_SYNC")
                if block:
                    gate = Path(block)
                    gate.mkdir(parents=True, exist_ok=True)
                    (gate / "sync-started").write_text("started\\n", encoding="utf-8")
                    deadline = time.monotonic() + 20
                    while not (gate / "release").is_file():
                        if time.monotonic() >= deadline:
                            raise SystemExit("test sync gate timed out")
                        time.sleep(0.01)
            else:
                raise SystemExit("unexpected uv command")
            """))

    def _run(self, *args: str, root: Path, cwd: Path | None = None,
             input_text: str | None = None, extra_env: dict[str, str] | None = None,
             host: str = "codex") -> subprocess.CompletedProcess[str]:
        env = {**self.env, **(extra_env or {})}
        return subprocess.run(
            [str(GEAR), "--host", host, "--root", str(root), *args],
            cwd=cwd or self.base,
            env=env,
            input=input_text,
            stdin=subprocess.DEVNULL if input_text is None else None,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def _provider(self, root: Path, name: str, version: str) -> Path:
        plugin = root / "plugins" / name
        plugin.mkdir(parents=True)
        (plugin / "gear.toml").write_text(
            f'[plugin]\nname = "{name}"\n\n'
            '[commands.probe]\nexec = ["python3", "probe.py"]\n',
            encoding="utf-8",
        )
        (plugin / "probe.py").write_text(dedent(f"""\
            import json
            import os
            import signal
            import sys
            import time
            from pathlib import Path
            from bootgear_cli import clikit

            if sys.argv[1:] == ["signal"]:
                os.kill(os.getpid(), signal.SIGTERM)

            if sys.argv[1:] == ["hold"]:
                print("provider-started", flush=True)
                time.sleep(0.2)

            print(json.dumps({{
                "version": {version!r},
                "args": sys.argv[1:],
                "stdin": sys.stdin.read(),
                "prefix": sys.prefix,
                "provider": str(Path(__file__).resolve()),
                "clikit": str(Path(clikit.__file__).resolve()),
                "cwd": os.getcwd(),
                "caller_cwd": os.environ["GEAR_CALLER_CWD"],
                "caller_path": str(clikit.caller_path("relative.txt")),
                "host": os.environ.get("BOOTGEAR_HOST"),
                "session": os.environ.get("BOOTGEAR_SESSION_ID"),
                "plugin": os.environ.get("GEAR_PLUGIN"),
                "command": os.environ.get("GEAR_COMMAND"),
            }}))
            if "--fail" in sys.argv[1:]:
                raise SystemExit(7)
        """), encoding="utf-8")
        return plugin

    def _setup(self, root: Path, *, extra_env: dict[str, str] | None = None,
               host: str = "codex") -> subprocess.CompletedProcess[str]:
        return self._run("cli", "setup", root=root, extra_env=extra_env, host=host)

    def test_missing_runtime_prints_setup_guidance_and_normal_calls_do_not_sync(self) -> None:
        roots = {host: self.base / f"provider-{host}" for host in ("claude", "codex")}
        plugins = {
            host: self._provider(root, "external-demo", host)
            for host, root in roots.items()
        }

        for host, root in roots.items():
            with self.subTest(host=host):
                missing = self._run("external-demo", "probe", root=root, host=host)
                self.assertEqual(missing.returncode, 2)
                self.assertIn("Shared runtime is missing", missing.stderr)
                self.assertIn("Run cli:setup", missing.stderr)
        self.assertFalse(self.uv_log.exists())

        setup = self._setup(roots["claude"], host="claude")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.assertIn("Shared runtime ready", setup.stdout)
        first_log = self.uv_log.read_text(encoding="utf-8")
        self.assertEqual(first_log.splitlines(), ["python find", "sync --locked"])

        caller = self.base / "caller"
        caller.mkdir()
        (caller / "relative.txt").write_text("caller file", encoding="utf-8")
        environment = str(self.xdg_data / "bootgear" / "runtimes")
        for host, root in roots.items():
            with self.subTest(host=host):
                result = self._run(
                    "external-demo", "probe", "--fail", "tail",
                    root=root,
                    cwd=caller,
                    input_text="input from caller\n",
                    host=host,
                )

                self.assertEqual(result.returncode, 7, result.stderr)
                data = json.loads(result.stdout)
                self.assertTrue(data["prefix"].startswith(environment + os.sep), data["prefix"])
                self.assertEqual(data["args"], ["--fail", "tail"])
                self.assertEqual(data["stdin"], "input from caller\n")
                self.assertEqual(data["provider"], str((plugins[host] / "probe.py").resolve()))
                self.assertEqual(data["clikit"], str((CLI_ROOT / "src" / "bootgear_cli" / "clikit.py").resolve()))
                self.assertEqual(data["cwd"], str(plugins[host].resolve()))
                self.assertEqual(data["caller_cwd"], str(caller.resolve()))
                self.assertEqual(data["caller_path"], str((caller / "relative.txt").resolve()))
                self.assertEqual(data["host"], host)
                self.assertEqual(data["session"], "runtime-test-session")
                self.assertEqual(data["plugin"], "external-demo")
                self.assertEqual(data["command"], "probe")
                signaled = self._run("external-demo", "probe", "signal",
                                     root=root, host=host)
                self.assertEqual(signaled.returncode, -signal.SIGTERM)
        self.assertEqual(self.uv_log.read_text(encoding="utf-8"), first_log)

        repeated_setup = self._setup(roots["codex"], host="codex")
        self.assertEqual(repeated_setup.returncode, 0, repeated_setup.stderr)
        self.assertEqual(self.uv_log.read_text(encoding="utf-8"), first_log)

    def test_matching_lock_shares_runtime_across_provider_versions(self) -> None:
        root_v1 = self.base / "provider-v1"
        root_v2 = self.base / "provider-v2"
        first = self._provider(root_v1, "external-demo", "v1")
        second = self._provider(root_v2, "external-demo", "v2")
        setup = self._setup(root_v1, host="claude")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        setup_log = self.uv_log.read_text(encoding="utf-8")

        results = [
            self._run("external-demo", "probe", root=root_v1, host="claude"),
            self._run("external-demo", "probe", root=root_v2, host="codex"),
        ]

        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        data_v1, data_v2 = (json.loads(result.stdout) for result in results)
        self.assertEqual(data_v1["version"], "v1")
        self.assertEqual(data_v2["version"], "v2")
        self.assertEqual(data_v1["host"], "claude")
        self.assertEqual(data_v2["host"], "codex")
        self.assertEqual(data_v1["prefix"], data_v2["prefix"])
        self.assertEqual(data_v1["provider"], str((first / "probe.py").resolve()))
        self.assertEqual(data_v2["provider"], str((second / "probe.py").resolve()))
        self.assertEqual(data_v1["clikit"], data_v2["clikit"])
        self.assertEqual(self.uv_log.read_text(encoding="utf-8"), setup_log)

    def test_sdk_routes_sibling_commands_in_the_selected_root_and_caller(self) -> None:
        roots: dict[str, Path] = {}
        callers: dict[str, Path] = {}
        for host, registration_dir in (("claude", "plugins"), ("codex", "codex-plugins")):
            root = self.base / f"sdk-root-{host}"
            base = root / registration_dir
            provider = base / "external-demo"
            sibling = base / "external-sibling"
            provider.mkdir(parents=True)
            sibling.mkdir(parents=True)
            (provider / "gear.toml").write_text(
                '[plugin]\nname = "external-demo"\n\n'
                '[commands.probe]\nexec = ["python3", "probe.py"]\n',
                encoding="utf-8",
            )
            (sibling / "gear.toml").write_text(
                '[plugin]\nname = "external-sibling"\n\n'
                '[commands.probe-only]\nexec = ["python3", "probe.py"]\n',
                encoding="utf-8",
            )
            (provider / "probe.py").write_text(dedent("""\
                import json
                import subprocess
                from bootgear_cli.gear import resolve_command

                route = resolve_command("probe-only")
                if route is None:
                    print(json.dumps({"route": None, "error": "SDK could not resolve the sibling route"}))
                else:
                    result = subprocess.run(route + ["from-provider"], capture_output=True,
                                            text=True, check=False)
                    print(json.dumps({"route": route, "returncode": result.returncode,
                                      "stdout": result.stdout, "stderr": result.stderr}))
            """), encoding="utf-8")
            (sibling / "probe.py").write_text(dedent("""\
                import json
                import os
                import sys
                from bootgear_cli.clikit import caller_path

                print(json.dumps({
                    "plugin": os.environ["GEAR_PLUGIN"],
                    "command": os.environ["GEAR_COMMAND"],
                    "root": os.environ["GEAR_ROOT"],
                    "caller_cwd": os.environ["GEAR_CALLER_CWD"],
                    "caller_path": str(caller_path("relative.txt")),
                    "args": sys.argv[1:],
                }))
            """), encoding="utf-8")
            caller = self.base / f"sdk-caller-{host}"
            caller.mkdir()
            (caller / "relative.txt").write_text("caller", encoding="utf-8")
            roots[host] = root
            callers[host] = caller

        setup = self._setup(roots["claude"], host="claude")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        setup_log = self.uv_log.read_text(encoding="utf-8")

        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = self._run(
                    "external-demo", "probe", root=roots[host],
                    cwd=callers[host], host=host,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertIsNotNone(data["route"], data.get("error"))
                self.assertIn("--root", data["route"])
                self.assertIn(str(roots[host].resolve()), data["route"])
                self.assertEqual(data["returncode"], 0, data["stderr"])
                sibling = json.loads(data["stdout"])
                self.assertEqual(sibling["plugin"], "external-sibling")
                self.assertEqual(sibling["command"], "probe-only")
                self.assertEqual(sibling["root"], str(roots[host].resolve()))
                self.assertEqual(sibling["caller_cwd"], str(callers[host].resolve()))
                self.assertEqual(sibling["caller_path"], str((callers[host] / "relative.txt").resolve()))
                self.assertEqual(sibling["args"], ["from-provider"])
        self.assertEqual(self.uv_log.read_text(encoding="utf-8"), setup_log)

    def test_provider_waits_for_explicit_setup_to_finish(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                runtime_home = self.base / f"xdg-{host}"
                uv_log = self.base / f"uv-{host}.log"
                extra_env = {
                    "XDG_DATA_HOME": str(runtime_home),
                    "BOOTGEAR_TEST_UV_LOG": str(uv_log),
                }
                provider_root = self.base / f"provider-root-{host}"
                self._provider(provider_root, "external-demo", host)
                caller = self.base / f"caller-{host}"
                caller.mkdir()
                gate = self.base / f"sync-gate-{host}"
                setup = subprocess.Popen(
                    [str(GEAR), "--host", host, "--root", str(provider_root), "cli", "setup"],
                    cwd=caller,
                    env={**self.env, **extra_env, "BOOTGEAR_BLOCK_SYNC": str(gate)},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                started = gate / "sync-started"
                deadline = time.monotonic() + 20
                while not started.is_file():
                    if setup.poll() is not None:
                        stdout, stderr = setup.communicate()
                        self.fail(f"setup exited before sync began: {setup.returncode}\n{stdout}{stderr}")
                    if time.monotonic() >= deadline:
                        setup.kill()
                        self.fail("setup did not reach the fake uv sync")
                    time.sleep(0.01)

                provider = subprocess.Popen(
                    [str(GEAR), "--host", host, "--root", str(provider_root),
                     "external-demo", "probe", "hold"],
                    cwd=caller,
                    env={**self.env, **extra_env},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        provider.wait(timeout=0.15)
                finally:
                    (gate / "release").write_text("release\n", encoding="utf-8")

                setup_stdout, setup_stderr = setup.communicate(timeout=20)
                provider_stdout, provider_stderr = provider.communicate(timeout=20)

                self.assertEqual(setup.returncode, 0, setup_stderr)
                self.assertIn("Shared runtime ready", setup_stdout)
                self.assertEqual(provider.returncode, 0, provider_stderr)
                self.assertIn("provider-started", provider_stdout)
                data = json.loads(provider_stdout.splitlines()[-1])
                self.assertTrue(data["prefix"].startswith(
                    str(runtime_home / "bootgear" / "runtimes")
                ))
                self.assertEqual(data["host"], host)
                self.assertEqual(uv_log.read_text(encoding="utf-8").splitlines(),
                                 ["python find", "sync --locked"])


if __name__ == "__main__":
    unittest.main()
