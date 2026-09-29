from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
CHANNEL = PLUGIN / "skills" / "advisor" / "scripts" / "channel.py"

sys.path.insert(0, str(CHANNEL.parent))
import channel as channel_module  # pyright: ignore[reportMissingImports]


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHANNEL), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def own_pid_and_start() -> tuple[int, float]:
    pid = os.getpid()
    return pid, channel_module.read_process_start_time(pid)


def spawn_and_kill_process() -> tuple[int, float]:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    start = channel_module.read_process_start_time(proc.pid)
    proc.terminate()
    proc.wait()
    return proc.pid, start


class RegisterSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        self.pid, self.started = own_pid_and_start()

    def test_register_sets_pid_started_at(self) -> None:
        result = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["listener_pid"], self.pid)
        self.assertEqual(record["listener_pid_started_at"], self.started)

    def test_register_missing_pid_rejected(self) -> None:
        result = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid-started-at", str(self.started),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_register_missing_pid_started_at_rejected(self) -> None:
        result = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_register_pid_zero_rejected(self) -> None:
        result = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", "0", "--pid-started-at", str(self.started),
        )
        self.assertEqual(result.returncode, 2)

    def test_register_pid_negative_rejected(self) -> None:
        result = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", "-1", "--pid-started-at", str(self.started),
        )
        self.assertEqual(result.returncode, 2)

    def test_listener_always_creates_fresh(self) -> None:
        first = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        second = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        first_channel = json.loads(first.stdout)["channel"]
        second_channel = json.loads(second.stdout)["channel"]
        self.assertNotEqual(first_channel, second_channel)

    def test_seat_claim_race_distinguishable(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        second = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c2",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(second.returncode, 2)
        payload = json.loads(second.stderr)
        self.assertEqual(payload["category"], "seat_claimed")

    def test_same_session_reregister_overwrites_pid_and_start(self) -> None:
        dead_pid, dead_start = spawn_and_kill_process()
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
            "--pid", str(dead_pid), "--pid-started-at", str(dead_start),
        )
        again = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        record = json.loads(again.stdout)
        self.assertEqual(record["asker_pid"], self.pid)
        self.assertEqual(record["asker_pid_started_at"], self.started)
        self.assertNotEqual(record["asker_pid"], dead_pid)

    def test_dead_holder_seat_still_claimed_by_other_session(self) -> None:
        dead_pid, dead_start = spawn_and_kill_process()
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        first = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
            "--pid", str(dead_pid), "--pid-started-at", str(dead_start),
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        second = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c2",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(second.returncode, 2)
        self.assertEqual(json.loads(second.stderr)["category"], "seat_claimed")

    def test_closed_channel_registration_rejected(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        result = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["category"], "channel_closed")

    def test_close_records_role_not_hardcoded(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        result = run(self.root, "close", "--role", "asker", "--channel", "0001")
        record = json.loads(result.stdout)
        self.assertEqual(record["state_role"], "asker")
        self.assertEqual(record["state"], "closed")

    def test_close_missing_role_rejected(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        result = run(self.root, "close", "--channel", "0001")
        self.assertNotEqual(result.returncode, 0)


class LivenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        self.pid, self.started = own_pid_and_start()

    def test_status_live_pid_matching_start(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        result = run(self.root, "status", "--channel", "0001")
        record = json.loads(result.stdout)
        self.assertTrue(record["listener_alive"])
        self.assertIsNone(record["asker_alive"])

    def test_status_dead_pid(self) -> None:
        dead_pid, dead_started = spawn_and_kill_process()
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(dead_pid), "--pid-started-at", str(dead_started),
        )
        result = run(self.root, "status", "--channel", "0001")
        record = json.loads(result.stdout)
        self.assertFalse(record["listener_alive"])

    def test_status_reused_pid_mismatched_start_time(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started - 1000),
        )
        result = run(self.root, "status", "--channel", "0001")
        record = json.loads(result.stdout)
        self.assertFalse(record["listener_alive"])

    def test_status_closed_channel_prints_last_known(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        result = run(self.root, "status", "--channel", "0001")
        self.assertEqual(result.returncode, 0)
        record = json.loads(result.stdout)
        self.assertEqual(record["state"], "closed")

    def test_whoami_matches_own_pid_and_start(self) -> None:
        result = run(self.root, "whoami", "--pid", str(self.pid))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["pid"], self.pid)
        self.assertEqual(payload["pid_started_at"], self.started)

    def test_whoami_dead_pid_rejected(self) -> None:
        dead_pid, _ = spawn_and_kill_process()
        result = run(self.root, "whoami", "--pid", str(dead_pid))
        self.assertNotEqual(result.returncode, 0)

    def test_whoami_output_round_trips_through_is_alive(self) -> None:
        whoami_result = run(self.root, "whoami", "--pid", str(self.pid))
        started_at = json.loads(whoami_result.stdout)["pid_started_at"]
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(started_at),
        )
        status_result = run(self.root, "status", "--channel", "0001")
        record = json.loads(status_result.stdout)
        self.assertTrue(record["listener_alive"])


class LiveCandidateScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        self.pid, self.started = own_pid_and_start()

    def test_finds_live_listener(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        result = run(self.root, "list", "--live-for", "asker")
        found = json.loads(result.stdout)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["channel"], "0001")

    def test_excludes_confirmed_dead_peer(self) -> None:
        dead_pid, dead_started = spawn_and_kill_process()
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(dead_pid), "--pid-started-at", str(dead_started),
        )
        result = run(self.root, "list", "--live-for", "asker")
        self.assertEqual(json.loads(result.stdout), [])

    def test_includes_unknown_liveness_peer(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        record["listener_pid_started_at"] = None
        path.write_text(json.dumps(record))
        result = run(self.root, "list", "--live-for", "asker")
        found = json.loads(result.stdout)
        self.assertEqual(len(found), 1)

    def test_excludes_closed_channel(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        result = run(self.root, "list", "--live-for", "asker")
        self.assertEqual(json.loads(result.stdout), [])

    def test_excludes_channel_outside_48h_window(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        stale = time.time() - 49 * 3600
        record["created_at"] = stale
        record["updated_at"] = stale
        path.write_text(json.dumps(record))
        result = run(self.root, "list", "--live-for", "asker")
        self.assertEqual(json.loads(result.stdout), [])

    def test_includes_channel_just_inside_48h_window(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        fresh = time.time() - 47 * 3600
        record["created_at"] = fresh
        record["updated_at"] = fresh
        path.write_text(json.dumps(record))
        result = run(self.root, "list", "--live-for", "asker")
        found = json.loads(result.stdout)
        self.assertEqual(len(found), 1)

    def test_excludes_old_schema_record_with_no_listener_owner_field(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        del record["listener_owner"]
        path.write_text(json.dumps(record))
        result = run(self.root, "list", "--live-for", "asker")
        self.assertEqual(json.loads(result.stdout), [])


class ConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        self.pid, self.started = own_pid_and_start()

    def test_state_and_register_do_not_clobber(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )

        results: dict[str, subprocess.CompletedProcess] = {}

        def do_state() -> None:
            results["state"] = run(self.root, "state", "--channel", "0001", "--role", "listener", "--value", "busy")

        def do_register() -> None:
            results["register"] = run(
                self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
                "--pid", str(self.pid), "--pid-started-at", str(self.started),
            )

        t1 = threading.Thread(target=do_state)
        t2 = threading.Thread(target=do_register)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results["state"].returncode, 0)
        self.assertEqual(results["register"].returncode, 0)

        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        self.assertEqual(record["asker_owner"], "c1")
        self.assertIn(record["state"], {"busy", "waiting"})


class PairingEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        self.pid, self.started = own_pid_and_start()

    def test_asker_finds_and_joins_live_listener(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        scan = run(self.root, "list", "--live-for", "asker")
        candidates = json.loads(scan.stdout)
        self.assertEqual(len(candidates), 1)
        channel = candidates[0]["channel"]
        claim = run(
            self.root, "register", "--channel", channel, "--role", "asker", "--session", "c1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(claim.returncode, 0)
        record = json.loads(claim.stdout)
        self.assertEqual(record["asker_owner"], "c1")
        self.assertEqual(record["listener_owner"], "s1")

    def test_asker_finds_none_tells_user_stops(self) -> None:
        scan = run(self.root, "list", "--live-for", "asker")
        self.assertEqual(json.loads(scan.stdout), [])

    def test_retry_second_claim_also_loses(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        first_claim = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(first_claim.returncode, 0)

        # Simulate the asker's retry: rescan finds nothing new to claim (seat taken),
        # so the retry's own claim attempt against the same channel also loses.
        retry_claim = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c2",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        self.assertEqual(retry_claim.returncode, 2)
        payload = json.loads(retry_claim.stderr)
        self.assertEqual(payload["category"], "seat_claimed")

    def test_simultaneous_listener_cold_start_creates_two_channels(self) -> None:
        first = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        second = run(
            self.root, "register", "--role", "listener", "--session", "s2",
            "--pid", str(self.pid), "--pid-started-at", str(self.started),
        )
        first_channel = json.loads(first.stdout)["channel"]
        second_channel = json.loads(second.stdout)["channel"]
        self.assertNotEqual(first_channel, second_channel)


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
                self.assertEqual(channel_module.read_body("body.txt"), "hello")
            finally:
                os.chdir(old_cwd)
                if old_env is None:
                    os.environ.pop("GEAR_CALLER_CWD")
                else:
                    os.environ["GEAR_CALLER_CWD"] = old_env



class ReceiveNoNewMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        pid, started = own_pid_and_start()
        registered = run(
            self.root, "register", "--role", "listener", "--session", "s1",
            "--pid", str(pid), "--pid-started-at", str(started),
        )
        self.channel = json.loads(registered.stdout)["channel"]

    def _send_to_asker(self) -> str:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", self.channel,
             "--from", "listener", "--to", "asker", "--kind", "request", "--body-file", "-"],
            input="hello asker", capture_output=True, text=True, check=False,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)
        return json.loads(sent.stdout)["message_id"]

    def _receive(self) -> subprocess.CompletedProcess:
        return run(self.root, "receive", "--channel", self.channel, "--for", "asker", "--timeout", "0")

    def _assert_no_new(self, result: subprocess.CompletedProcess) -> dict:
        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["new_since_call"], 0)
        self.assertIn("no new message for asker", output["note"])
        self.assertIn("many minutes", output["note"])
        self.assertIn("instead of giving up or resending", output["note"])
        self.assertIn("up to 5 waits of 300s", output["note"])
        self.assertIn(f"receive --channel {self.channel} --for asker --timeout 300", output["next"])
        return output

    def test_empty_inbox_says_no_new_message(self) -> None:
        output = self._assert_no_new(self._receive())
        self.assertEqual(output["messages"], [])

    def test_only_read_messages_say_no_new_message_and_keep_history(self) -> None:
        message_id = self._send_to_asker()
        fetched = run(self.root, "fetch", "--channel", self.channel, "--message-id", message_id)
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        output = self._assert_no_new(self._receive())
        self.assertEqual([m["message_id"] for m in output["messages"]], [message_id])

    def test_new_message_is_exit_zero_with_fetch_note(self) -> None:
        message_id = self._send_to_asker()
        result = self._receive()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["new_since_call"], 1)
        self.assertEqual(output["messages"][0]["message_id"], message_id)
        self.assertIn("fetch", output["note"])
        self.assertIn(f"fetch --channel {self.channel} --message-id {message_id}", output["next"])

    def test_timed_wait_expires_with_the_note(self) -> None:
        result = run(self.root, "receive", "--channel", self.channel, "--for", "asker",
                     "--timeout", "0.2", "--poll", "0.05")
        output = self._assert_no_new(result)
        self.assertIn("within 0.2s", output["note"])

    def test_listener_note_after_answering_does_not_ask_to_answer_again(self) -> None:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", self.channel,
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="question", capture_output=True, text=True, check=False,
        )
        request_id = json.loads(sent.stdout)["message_id"]
        run(self.root, "fetch", "--channel", self.channel, "--message-id", request_id)
        answered = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", self.channel,
             "--from", "listener", "--to", "asker", "--kind", "response", "--parent-id", request_id,
             "--body-file", "-"],
            input="answer", capture_output=True, text=True, check=False,
        )
        self.assertEqual(answered.returncode, 0, answered.stderr)
        result = run(self.root, "receive", "--channel", self.channel, "--for", "listener",
                     "--timeout", "0")
        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertIn("no new message for listener", output["note"])
        self.assertNotIn("answer", output["note"])
        self.assertNotIn("resending", output["note"])
        self.assertIn(f"receive --channel {self.channel} --for listener --timeout 300", output["next"])

    def test_printed_next_commands_run(self) -> None:
        self._send_to_asker()
        env = {**os.environ, "BOOTGEAR_ADVISOR_DIR": str(self.root)}
        received = subprocess.run(
            [sys.executable, str(CHANNEL), "receive", "--channel", self.channel, "--for", "asker",
             "--timeout", "0"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(received.returncode, 0, received.stderr)
        fetch = shlex.split(json.loads(received.stdout)["next"])
        self.assertEqual(fetch[fetch.index("--root") + 1], str(self.root))
        # Positive control: the hint must be runnable on its own, without the
        # env var that produced it -- proves --root is genuinely embedded,
        # not merely tolerated because the env var is still inherited below.
        env_without_root_var = {k: v for k, v in env.items() if k != "BOOTGEAR_ADVISOR_DIR"}
        fetched = subprocess.run(fetch, capture_output=True, text=True, check=False,
                                  env=env_without_root_var)
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        self.assertEqual(json.loads(fetched.stdout)["body"], "hello asker")

        spaced = Path(tempfile.mkdtemp(prefix="advisor-test-")) / "a root"
        spaced.symlink_to(self.root)
        output = json.loads(run(spaced, "receive", "--channel", self.channel, "--for", "asker",
                                "--timeout", "0").stdout)
        wait = shlex.split(output["next"])
        self.assertEqual(wait[wait.index("--root") + 1], str(spaced))
        wait[wait.index("--timeout") + 1] = "0"
        again = subprocess.run(wait, capture_output=True, text=True, check=False)
        self._assert_no_new(again)

    def test_printed_next_keeps_explicit_root_flag_equal_to_default(self) -> None:
        # An explicit --root must always appear in the hint, even if its
        # value equals DEFAULT_ROOT -- `root != DEFAULT_ROOT` alone would miss this case. DEFAULT_ROOT is
        # Path.home() / ".bootgear" / "advisor"; a fake HOME isolates this
        # from the real default mailbox instead of touching it.
        fake_home = Path(tempfile.mkdtemp(prefix="advisor-test-home-"))
        default_root = fake_home / ".bootgear" / "advisor"
        env = {**os.environ, "HOME": str(fake_home)}
        env.pop("BOOTGEAR_ADVISOR_DIR", None)

        pid, started = own_pid_and_start()
        registered = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(default_root), "register",
             "--role", "listener", "--session", "s1", "--pid", str(pid),
             "--pid-started-at", str(started)],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        channel = json.loads(registered.stdout)["channel"]

        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(default_root), "send",
             "--channel", channel, "--from", "listener", "--to", "asker",
             "--kind", "request", "--body-file", "-"],
            input="hello asker", capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)

        received = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(default_root), "receive",
             "--channel", channel, "--for", "asker", "--timeout", "0"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(received.returncode, 0, received.stderr)
        fetch = shlex.split(json.loads(received.stdout)["next"])
        self.assertIn("--root", fetch)
        self.assertEqual(fetch[fetch.index("--root") + 1], str(default_root))

    def test_printed_next_omits_root_when_neither_source_set(self) -> None:
        # With neither --root nor BOOTGEAR_ADVISOR_DIR set, the hint must
        # omit --root -- the true default-root case (every other test
        # passes an explicit --root or sets the env var). Fake HOME isolates
        # this from the real default mailbox, same pattern as the sibling
        # test above; no --root flag or BOOTGEAR_ADVISOR_DIR is set anywhere.
        fake_home = Path(tempfile.mkdtemp(prefix="advisor-test-home-"))
        env = {**os.environ, "HOME": str(fake_home)}
        env.pop("BOOTGEAR_ADVISOR_DIR", None)

        pid, started = own_pid_and_start()
        registered = subprocess.run(
            [sys.executable, str(CHANNEL), "register",
             "--role", "listener", "--session", "s1", "--pid", str(pid),
             "--pid-started-at", str(started)],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        channel = json.loads(registered.stdout)["channel"]

        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "send",
             "--channel", channel, "--from", "listener", "--to", "asker",
             "--kind", "request", "--body-file", "-"],
            input="hello asker", capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)

        received = subprocess.run(
            [sys.executable, str(CHANNEL), "receive",
             "--channel", channel, "--for", "asker", "--timeout", "0"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(received.returncode, 0, received.stderr)
        fetch = shlex.split(json.loads(received.stdout)["next"])
        self.assertNotIn("--root", fetch)

    def test_printed_next_root_matches_relative_root_flag(self) -> None:
        # The printed hint for a relative --root needs no further caller_path()
        # call: root_from already resolves it against GEAR_CALLER_CWD/cwd
        # before receive() ever builds the hint.
        caller = Path(tempfile.mkdtemp(prefix="advisor-test-caller-"))
        env = {**os.environ, "GEAR_CALLER_CWD": str(caller)}
        env.pop("BOOTGEAR_ADVISOR_DIR", None)

        pid, started = own_pid_and_start()
        registered = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", "mbox", "register",
             "--role", "listener", "--session", "s1", "--pid", str(pid),
             "--pid-started-at", str(started)],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        channel = json.loads(registered.stdout)["channel"]

        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", "mbox", "send",
             "--channel", channel, "--from", "listener", "--to", "asker",
             "--kind", "request", "--body-file", "-"],
            input="hello asker", capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)

        received = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", "mbox", "receive",
             "--channel", channel, "--for", "asker", "--timeout", "0"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(received.returncode, 0, received.stderr)
        fetch = shlex.split(json.loads(received.stdout)["next"])
        self.assertIn("--root", fetch)
        self.assertEqual(fetch[fetch.index("--root") + 1], str(caller / "mbox"))

    def test_listener_loop_waits_again_on_exit_1(self) -> None:
        skill = (CHANNEL.parent.parent / "SKILL.md").read_text()
        loop = skill[skill.index("while :; do"):skill.index("done\n")]
        self.assertIn('if [ "$RECEIVE_STATUS" -eq 1 ]; then continue; fi', loop)


if __name__ == "__main__":
    unittest.main()
