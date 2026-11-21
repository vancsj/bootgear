from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from channel_test_support import (
    CHANNEL,
    GEAR_PREFIX,
    SESSION_ENV,
    age_seat,
    channel_json,
    channel_module,
    channel_output,
    channel_store,
    clikit,
    root_variants,
    run,
    run_in,
    seen_at,
    wait_until,
)


class OutputModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def register(self, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "register", "--role", "listener",
             "--session", "s1", *extra],
            capture_output=True, text=True, check=False, env={**os.environ, **(env or {})})

    def test_prose_is_the_default_and_ends_with_next(self) -> None:
        result = self.register(env={"BOOTGEAR_OUTPUT": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "channel: 0001")
        self.assertTrue(lines[-1].startswith(f"next: {shlex.join(GEAR_PREFIX)} "))
        with self.assertRaises(json.JSONDecodeError):
            json.loads(result.stdout)

    def test_json_flag_prints_json(self) -> None:
        payload = json.loads(self.register("--json").stdout)
        self.assertEqual(payload["channel"], "0001")
        self.assertIn("next", payload)

    def test_environment_selects_json_and_a_flag_overrides_it(self) -> None:
        self.assertEqual(json.loads(self.register(env={"BOOTGEAR_OUTPUT": "json"}).stdout)["channel"], "0001")
        prose = self.register("--prose", env={"BOOTGEAR_OUTPUT": "json"})
        self.assertTrue(prose.stdout.startswith("channel: 0002"))

    def test_list_prose_shows_one_line_per_channel(self) -> None:
        self.register()
        listing = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "list"],
            capture_output=True, text=True, check=False, env={**os.environ, "BOOTGEAR_OUTPUT": ""},
        ).stdout.splitlines()
        self.assertEqual(listing[0], "channels:")
        self.assertTrue(listing[1].startswith("  - channel=0001 state=waiting"))


class RegisterSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_listener_always_creates_fresh(self) -> None:
        first = run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        second = run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        first_channel = json.loads(first.stdout)["channel"]
        second_channel = json.loads(second.stdout)["channel"]
        self.assertNotEqual(first_channel, second_channel)

    def test_seat_claim_race_distinguishable(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
        )
        second = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c2",
        )
        self.assertEqual(second.returncode, 2)
        payload = json.loads(second.stderr)
        self.assertEqual(payload["category"], "seat_claimed")

    def test_closed_channel_registration_rejected(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        result = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["category"], "channel_closed")

    def test_close_records_role_not_hardcoded(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        result = run(self.root, "close", "--role", "asker", "--channel", "0001")
        record = json.loads(result.stdout)
        self.assertEqual(record["state_role"], "asker")
        self.assertEqual(record["state"], "closed")

    def test_close_missing_role_rejected(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        result = run(self.root, "close", "--channel", "0001")
        self.assertNotEqual(result.returncode, 0)


class RegisterNextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_register_next_starts_the_heartbeat_for_both_roles(self) -> None:
        listener = run(self.root, "register", "--role", "listener", "--session", "s1")
        asker = run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c 1")
        for result, role, session in ((listener, "listener", "s1"), (asker, "asker", "c 1")):
            with self.subTest(role=role):
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(
                    shlex.split(output["next"]),
                    [*GEAR_PREFIX,
                     "--root", str(self.root), "heartbeat", "--channel", "0001", "--role", role,
                     "--session", session],
                )
                self.assertIn("background", output["note"])

    def test_register_still_stamps_seen_at(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        stamped = json.loads(channel_json(self.root).read_text())["listener_seen_at"]
        self.assertIsInstance(stamped, float)
        self.assertGreater(float(stamped), time.time() - 5)

    def test_printed_heartbeat_runs_as_printed_for_each_root(self) -> None:
        for label, root_flag, env, resolved in root_variants():
            with self.subTest(root=label):
                registered = run_in(root_flag, env, "register", "--role", "listener", "--session", "s1")
                self.assertEqual(registered.returncode, 0, registered.stderr)
                command = shlex.split(json.loads(registered.stdout)["next"])
                self.assertEqual("--root" in command, label != "default")
                age_seat(resolved, "listener", 600)
                aged = seen_at(resolved, "listener")
                clean_env = {k: v for k, v in os.environ.items()
                             if k not in {"BOOTGEAR_ADVISOR_DIR", "GEAR_CALLER_CWD"}}
                if label == "default":
                    clean_env["HOME"] = env["HOME"]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, env=clean_env)
                try:
                    self.assertTrue(wait_until(
                        lambda resolved=resolved, aged=aged: seen_at(resolved, "listener") != aged))
                finally:
                    process.terminate()
                    stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(json.loads(stdout)["stopped"], "signal")


class ArgumentRefusalTests(unittest.TestCase):
    REFUSALS = (
        ("register", ["register", "--role", "boss", "--session", "s1"], "invalid_role"),
        ("register", ["register", "--role", "listener", "--session=-dash"], "invalid_args"),
        ("heartbeat", ["heartbeat", "--channel", "0001", "--role", "boss", "--session", "s1"], "invalid_role"),
        ("heartbeat", ["heartbeat", "--channel", "0001", "--role", "listener", "--session=-dash"], "invalid_args"),
        ("heartbeat", ["heartbeat", "--channel", "0001", "--role", "listener", "--session", "s1",
                       "--interval", "0"], "invalid_args"),
        ("heartbeat", ["heartbeat", "--channel", "0001", "--role", "listener", "--session", "s1",
                       "--max-age", "0"], "invalid_args"),
        ("list", ["list", "--wait", "5"], "invalid_args"),
        ("list", ["list", "--live-for", "asker"], "invalid_args"),
        ("list", ["list", "--live-for", "boss", "--session", "s1"], "invalid_role"),
        ("list", ["list", "--live-for", "asker", "--session=-dash"], "invalid_args"),
        ("list", ["list", "--live-for", "asker", "--session", "c1", "--wait", "-1"], "invalid_args"),
        ("heartbeat", ["heartbeat", "--channel", "abc", "--role", "listener", "--session", "s1"], "invalid_args"),
        ("register", ["register", "--role", "asker", "--channel", "xx", "--session", "c1"], "invalid_args"),
        ("status", ["status", "--channel", "1"], "invalid_args"),
        ("heartbeat", ["heartbeat", "--channel", "0001", "--role", "listener"], "invalid_args"),
        ("register", ["register", "--role", "asker"], "invalid_args"),
        ("heartbeat", ["heartbeat", "--channel", "0001", "--role", "listener", "--session", "s1",
                       "--interval", "abc"], "invalid_args"),
        ("list", ["list", "--live-for", "asker", "--session", "c1", "--wait", "abc"], "invalid_args"),
        ("send", ["send", "--channel", "0001"], "invalid_args"),
        ("receive", ["receive", "--channel", "0001", "--for", "asker", "--timeout", "x"], "invalid_args"),
        ("status", ["status", "--channel", "0001", "--bogus", "x"], "invalid_args"),
        ("receive", ["receive", "--channel", "0001", "--for", "asker", "--timout", "300"], "invalid_args"),
        ("close", ["close", "--channel", "0001", "--role", "listener", "--if-peer-stale", "--bogus"],
         "invalid_args"),
        ("close", ["close", "--channel", "0001", "--role", "listener", "--if-peer-stale=yes"], "invalid_args"),
        ("close", ["close", "--channel", "0001", "--role", "boss", "--if-peer-stale"], "invalid_role"),
        ("send", ["send", "--channel", "0001", "--from", "boss", "--to", "listener", "--kind", "request",
                  "--body-file", "-"], "invalid_role"),
        ("send", ["send", "--channel", "0001", "--from", "asker", "--to", "asker", "--kind", "request",
                  "--body-file", "-"], "invalid_role"),
        ("send", ["send", "--channel", "0001", "--from", "asker", "--to", "listener", "--kind", "bogus",
                  "--body-file", "-"], "invalid_args"),
        ("send", ["send", "--channel", "0001", "--from", "listener", "--to", "asker", "--kind", "response",
                  "--body-file", "-"], "invalid_args"),
        ("state", ["state", "--channel", "0001", "--role", "boss", "--value", "busy"], "invalid_role"),
        ("state", ["state", "--channel", "0001", "--role", "listener", "--value", "nope"], "invalid_args"),
        ("close", ["close", "--channel", "0001", "--role", "boss"], "invalid_role"),
        ("receive", ["receive", "--channel", "0001", "--for", "boss"], "invalid_role"),
        ("fetch", ["fetch", "--channel", "0001", "--message-id", "../x"], "invalid_args"),
        ("whoami", ["whoami"], "invalid_args"),
        ("whoami", ["whoami", "--session=-dash"], "invalid_args"),
    )

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_refusals_print_a_parsable_example_and_the_other_subcommands(self) -> None:
        parser = channel_module.build_parser()
        for command, argv, category in self.REFUSALS:
            with self.subTest(argv=argv):
                result = run(self.root, *argv, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                payload = json.loads(result.stderr)
                self.assertEqual(payload["category"], category)
                example = shlex.split(payload["example"])
                self.assertEqual(example[:len(GEAR_PREFIX) + 2],
                                 [*GEAR_PREFIX, "--root", str(self.root)])
                self.assertEqual(parser.parse_args(example[len(GEAR_PREFIX):]).command, command)
                self.assertEqual(payload["commands"].split(", "),
                                 [c for c in channel_output.COMMANDS if c != command])
                if payload["error"] == clikit.missing_session("--session"):
                    self.assertEqual(payload["next"], channel_output.MISSING_SESSION_NEXT)
                else:
                    self.assertIn("example", payload["next"])

    def test_malformed_channel_writes_nothing(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        before = sorted(p.name for p in (self.root / "channels").iterdir())
        run(self.root, "register", "--role", "asker", "--channel", "xx", "--session", "c1")
        self.assertEqual(sorted(p.name for p in (self.root / "channels").iterdir()), before)

    def test_unknown_subcommand_is_a_json_refusal(self) -> None:
        result = run(self.root, "bogus", timeout=5)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["category"], "invalid_args")
        self.assertEqual(payload["commands"].split(", "), list(channel_output.COMMANDS))
        self.assertIn("example", payload)

    def test_printed_example_runs_for_a_dash_leading_or_env_root(self) -> None:
        caller = Path(tempfile.mkdtemp(prefix="advisor-test-caller-"))
        elsewhere = Path(tempfile.mkdtemp(prefix="advisor-test-other-"))
        env_root = Path(tempfile.mkdtemp(prefix="advisor-test-")) / "env root"
        base = {k: v for k, v in os.environ.items() if k not in {"BOOTGEAR_ADVISOR_DIR", "GEAR_CALLER_CWD"}}
        for label, root_flag, env in (("dash", ["--root=-dashroot"], base),
                                      ("env", [], {**base, "BOOTGEAR_ADVISOR_DIR": str(env_root)})):
            with self.subTest(root=label):
                def channel(*args: str, env: dict[str, str] = env) -> subprocess.CompletedProcess:
                    return subprocess.run([sys.executable, str(CHANNEL), *root_flag, *args], capture_output=True,
                                          text=True, check=False, env=env, cwd=caller, timeout=10)

                self.assertEqual(channel("register", "--role", "listener", "--session", "s1").returncode, 0)
                refused = channel("list", "--wait", "3")
                self.assertEqual(refused.returncode, 2)
                example = json.loads(refused.stderr)["example"]
                caller_env = {k: v for k, v in base.items() if k not in SESSION_ENV}
                ran = subprocess.run(["bash", "-c", example], capture_output=True, text=True, check=False,
                                     env={**caller_env, "CODEX_SESSION_ID": "c1"}, cwd=elsewhere, timeout=10)
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertEqual([c["channel"] for c in json.loads(ran.stdout)["channels"]], ["0001"])

    def test_abbreviated_root_is_kept_in_the_example_and_the_example_runs(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        for flag in (["--ro", str(self.root)], [f"--roo={self.root}"], ["--r", str(self.root)]):
            with self.subTest(flag=flag):
                refused = subprocess.run([sys.executable, str(CHANNEL), *flag, "status", "--channel", "0001",
                                          "--bogus", "x"], capture_output=True, text=True, check=False, timeout=5)
                self.assertEqual(refused.returncode, 2)
                payload = json.loads(refused.stderr)
                example = shlex.split(payload["example"])
                self.assertEqual(example[:len(GEAR_PREFIX)], GEAR_PREFIX)
                self.assertEqual(example[len(GEAR_PREFIX):],
                                 ["--root", str(self.root), "status", "--channel", "0001"])
                self.assertNotIn("status", payload["commands"].split(", "))
                ran = subprocess.run(example, capture_output=True, text=True, check=False, timeout=10)
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertEqual(json.loads(ran.stdout)["channel"], "0001")

    def test_argument_refusals_write_nothing(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        before = channel_json(self.root).read_bytes()
        for _, argv, _ in self.REFUSALS:
            if argv[0] in {"send", "state", "close", "receive", "fetch"}:
                with self.subTest(argv=argv):
                    self.assertEqual(run(self.root, *argv, timeout=5).returncode, 2)
        self.assertEqual(channel_json(self.root).read_bytes(), before)
        self.assertEqual(list((channel_json(self.root).parent / "messages").iterdir()), [])

    def test_empty_body_is_an_argument_refusal(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        result = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="  \n", capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["category"], "invalid_args")
        self.assertIn("send --channel", payload["example"])

    def test_send_and_receive_on_a_closed_channel_say_channel_closed(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="body", capture_output=True, text=True, check=False, timeout=5)
        received = run(self.root, "receive", "--channel", "0001", "--for", "asker", "--timeout", "0")
        for label, result in (("send", sent), ("receive", received)):
            with self.subTest(command=label):
                self.assertEqual(result.returncode, 2)
                payload = json.loads(result.stderr)
                self.assertEqual(payload["category"], "channel_closed")
                self.assertIn("tell the user", payload["next"])

    def test_commands_list_matches_the_parser(self) -> None:
        subparsers = next(a for a in channel_module.build_parser()._actions
                          if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(sorted(channel_output.COMMANDS), sorted(subparsers.choices))

    def test_dash_session_is_refused_before_anything_is_written(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        before = channel_json(self.root).read_bytes()
        for argv in (["register", "--role", "listener", "--session=-dash"],
                     ["register", "--channel", "0001", "--role", "asker", "--session=-dash"],
                     ["heartbeat", "--channel", "0001", "--role", "listener", "--session=-dash"],
                     ["list", "--live-for", "asker", "--session=-dash"],
                     ["list", "--session=-dash"]):
            with self.subTest(argv=argv):
                result = run(self.root, *argv, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stderr)["category"], "invalid_args")
        self.assertEqual(channel_json(self.root).read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.root / "channels").iterdir()), ["0001"])


class CallerPathTests(unittest.TestCase):
    """Under gear the child runs from the plugin root; relative paths follow
    the caller's cwd in GEAR_CALLER_CWD."""

    def test_relative_root_and_body_file_resolve_against_caller_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as caller, tempfile.TemporaryDirectory() as plugin:
            env = {**os.environ, "GEAR_CALLER_CWD": caller}
            env.pop("BOOTGEAR_ADVISOR_DIR", None)
            result = subprocess.run(
                [sys.executable, str(CHANNEL), "--root", "mbox", "init", "--channel", "0001"],
                capture_output=True, text=True, check=False, cwd=plugin, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(caller) / "mbox" / "channels").is_dir())
            self.assertFalse((Path(plugin) / "mbox").exists())
            (Path(caller) / "body.txt").write_text("hello\n")
            old_cwd, old_env = os.getcwd(), os.environ.get("GEAR_CALLER_CWD")
            os.chdir(plugin)
            os.environ["GEAR_CALLER_CWD"] = caller
            try:
                self.assertEqual(channel_store.read_body("body.txt"), "hello")
            finally:
                os.chdir(old_cwd)
                if old_env is None:
                    os.environ.pop("GEAR_CALLER_CWD")
                else:
                    os.environ["GEAR_CALLER_CWD"] = old_env


class WhoamiDefaultOutputTests(unittest.TestCase):
    def test_prose_is_the_default_output(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(root, "register", "--role", "listener", "--session", "s1")
        result = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(root), "whoami", "--session", "s1"],
            capture_output=True, text=True, check=False, env={**os.environ, "BOOTGEAR_OUTPUT": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("channel: 0001\nrole: listener\n"))


if __name__ == "__main__":
    unittest.main()
