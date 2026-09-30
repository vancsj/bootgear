from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import signal
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


def run(root: Path, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHANNEL), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


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


def channel_json(root: Path, channel: str = "0001") -> Path:
    return root / "channels" / channel / "channel.json"


def age_seat(root: Path, role: str, seconds: float, channel: str = "0001") -> None:
    path = channel_json(root, channel)
    record = json.loads(path.read_text())
    record[f"{role}_seen_at"] -= seconds
    path.write_text(json.dumps(record))


def age_updated_at(root: Path, seconds: float, channel: str = "0001") -> None:
    path = channel_json(root, channel)
    record = json.loads(path.read_text())
    record["updated_at"] -= seconds
    path.write_text(json.dumps(record))


def rewrite_record(root: Path, content: str, channel: str = "0001") -> None:
    """Replace channel.json under the channel lock, as channel.py's own writers do."""
    lock = channel_module.channel_lock(channel_json(root, channel).parent)
    try:
        channel_module.atomic_write(channel_json(root, channel), content)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def seen_at(root: Path, role: str, channel: str = "0001") -> float:
    return float(json.loads(channel_json(root, channel).read_text())[f"{role}_seen_at"])


class SeatLiveTests(unittest.TestCase):
    def record(self, **fields: object) -> dict[str, object]:
        return {"listener_owner": "s1", "updated_at": time.time(), **fields}

    def test_unowned_seat_is_none(self) -> None:
        self.assertIsNone(channel_module.seat_live({"listener_seen_at": time.time()}, "listener"))

    def test_fresh_seen_at_reads_live(self) -> None:
        self.assertIs(channel_module.seat_live(self.record(listener_seen_at=time.time() - 1), "listener"), True)

    def test_future_dated_seen_at_reads_stale(self) -> None:
        self.assertIs(channel_module.seat_live(self.record(listener_seen_at=time.time() + 60), "listener"), False)

    def test_invalid_seen_at_reads_stale_even_with_fresh_updated_at(self) -> None:
        for value in (0, "x", True, float("nan"), -5.0, None):
            with self.subTest(value=value):
                self.assertIs(channel_module.seat_live(self.record(listener_seen_at=value), "listener"), False)
        self.assertIs(channel_module.seat_live(self.record(), "listener"), False)

    def test_seen_at_past_ttl_reads_stale(self) -> None:
        aged = time.time() - channel_module.HEARTBEAT_TTL_SECONDS - 1
        self.assertIs(channel_module.seat_live(self.record(listener_seen_at=aged), "listener"), False)

    def test_ttl_is_ten_seconds_and_interval_fits_twice(self) -> None:
        self.assertEqual(channel_module.HEARTBEAT_TTL_SECONDS, 10)
        self.assertEqual(channel_module.HEARTBEAT_INTERVAL_SECONDS, 3)


class LivenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_aged_seen_at_with_fresh_updated_at_reads_stale(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        age_seat(self.root, "listener", channel_module.HEARTBEAT_TTL_SECONDS + 1)
        record = json.loads(run(self.root, "status", "--channel", "0001").stdout)
        self.assertGreater(record["updated_at"], time.time() - 5)
        self.assertFalse(record["listener_alive"])

    def test_same_session_reregister_takes_stale_seat_back(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        age_seat(self.root, "listener", 600)
        again = run(self.root, "register", "--channel", "0001", "--role", "listener", "--session", "s1")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertTrue(json.loads(run(self.root, "status", "--channel", "0001").stdout)["listener_alive"])

    def test_other_session_cannot_take_stale_seat(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        age_seat(self.root, "listener", 600)
        before = channel_json(self.root).read_bytes()
        other = run(self.root, "register", "--channel", "0001", "--role", "listener", "--session", "s2")
        self.assertEqual(other.returncode, 2)
        self.assertEqual(json.loads(other.stderr)["category"], "seat_claimed")
        self.assertEqual(channel_json(self.root).read_bytes(), before)

    def test_status_closed_channel_prints_last_known(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        result = run(self.root, "status", "--channel", "0001")
        self.assertEqual(result.returncode, 0)
        record = json.loads(result.stdout)
        self.assertEqual(record["state"], "closed")


def wait_until(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


class HeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        self.processes: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        os.chmod(channel_json(self.root).parent, 0o700)
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def start(self, *extra: str, session: str = "s1") -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", "listener", "--session", session, *extra],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        return process

    def finish(self, process: subprocess.Popen, timeout: float = 5.0) -> tuple[int, str, str]:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout, stderr

    def started(self, *extra: str) -> subprocess.Popen:
        age_seat(self.root, "listener", 600)
        aged = seen_at(self.root, "listener")
        process = self.start(*extra)
        self.assertTrue(wait_until(lambda: seen_at(self.root, "listener") != aged), "no initial stamp")
        return process

    def assert_stopped(self, stdout: str, stopped: str) -> dict[str, str]:
        output = json.loads(stdout)
        self.assertEqual(output["stopped"], stopped)
        self.assertIn("next", output)
        return output

    def test_wrong_session_at_start_stops_seat_taken_and_writes_nothing(self) -> None:
        before = channel_json(self.root).read_bytes()
        code, stdout, stderr = self.finish(self.start("--interval", "0.1", session="s2"))
        self.assertEqual(code, 2)
        self.assertEqual(self.assert_stopped(stdout, "seat_taken")["category"], "seat_claimed")
        self.assertEqual(stderr, "")
        self.assertEqual(channel_json(self.root).read_bytes(), before)

    def test_unowned_seat_gets_seat_claimed(self) -> None:
        process = subprocess.Popen(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", "asker", "--session", "c1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        code, stdout, _ = self.finish(process)
        self.assertEqual(code, 2)
        self.assertEqual(self.assert_stopped(stdout, "seat_taken")["category"], "seat_claimed")
        self.assertNotIn("asker_seen_at", json.loads(channel_json(self.root).read_text()))

    def test_closed_channel_at_start_stops_without_writing(self) -> None:
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        before = channel_json(self.root).read_bytes()
        code, stdout, _ = self.finish(self.start("--interval", "0.5"))
        self.assertEqual(code, 0)
        self.assertIn("nothing to restart", self.assert_stopped(stdout, "channel_closed")["next"])
        self.assertEqual(channel_json(self.root).read_bytes(), before)

    def test_missing_channel_fails_without_creating_it(self) -> None:
        result = run(self.root, "heartbeat", "--channel", "0042", "--role", "listener", "--session", "s1",
                     timeout=5)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error"], "channel does not exist: 0042")
        self.assertEqual(payload["category"], "channel_missing")
        self.assertFalse((self.root / "channels" / "0042").exists())
        registered = run(self.root, "register", "--role", "listener", "--session", "s1")
        self.assertEqual(json.loads(registered.stdout)["channel"], "0002")

    def test_startup_stamp_failure_is_retried_then_heartbeat_failed(self) -> None:
        lock = channel_json(self.root).parent / "channel.lock"
        lock.unlink(missing_ok=True)
        lock.mkdir()
        code, stdout, stderr = self.finish(self.start("--interval", "0.1"))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        payload = json.loads(stderr)
        self.assertEqual(payload["category"], "heartbeat_failed")
        self.assertIn("next", payload)

    def test_startup_stamp_failure_recovers_at_the_next_interval(self) -> None:
        age_seat(self.root, "listener", 600)
        aged = seen_at(self.root, "listener")
        lock = channel_json(self.root).parent / "channel.lock"
        lock.unlink(missing_ok=True)
        lock.mkdir()
        process = self.start("--interval", "0.4")
        time.sleep(0.2)
        lock.rmdir()
        self.assertTrue(wait_until(lambda: seen_at(self.root, "listener") != aged, timeout=3))
        self.assertIsNone(process.poll())

    def assert_read_failure_ends_heartbeat_failed(self, damage) -> None:
        process = self.started("--interval", "0.1")
        damage()
        code, stdout, stderr = self.finish(process)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["category"], "heartbeat_failed")

    def test_missing_record_mid_run_ends_heartbeat_failed(self) -> None:
        self.assert_read_failure_ends_heartbeat_failed(lambda: channel_json(self.root).unlink())

    def test_corrupt_record_mid_run_ends_heartbeat_failed(self) -> None:
        self.assert_read_failure_ends_heartbeat_failed(lambda: rewrite_record(self.root, "{bad"))

    def test_non_utf8_record_mid_run_is_retried_then_heartbeat_failed(self) -> None:
        def damage() -> None:
            lock = channel_module.channel_lock(channel_json(self.root).parent)
            try:
                channel_json(self.root).write_bytes(b"\xff\xfe{bad")
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()

        process = self.started("--interval", "0.1")
        damage()
        code, stdout, stderr = self.finish(process)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        payload = json.loads(stderr)
        self.assertEqual(payload["category"], "heartbeat_failed")
        self.assertIn("3 times in a row", payload["error"])
        self.assertIn("next", payload)

    def test_right_session_refreshes_an_aged_seat(self) -> None:
        self.started("--interval", "0.2")
        self.assertTrue(json.loads(run(self.root, "status", "--channel", "0001").stdout)["listener_alive"])

    def test_seen_at_increases_at_each_interval(self) -> None:
        process = self.started("--interval", "0.2")
        first = seen_at(self.root, "listener")
        self.assertTrue(wait_until(lambda: seen_at(self.root, "listener") != first, timeout=2))
        second = seen_at(self.root, "listener")
        self.assertGreater(second, first)
        self.assertTrue(wait_until(lambda: seen_at(self.root, "listener") != second, timeout=2))
        self.assertGreater(seen_at(self.root, "listener"), second)
        self.assertIsNone(process.poll())

    def test_invalid_interval_and_max_age_fail_invalid_args(self) -> None:
        limit = channel_module.HEARTBEAT_TTL_SECONDS / 2
        before = channel_json(self.root).read_bytes()
        for extra in (["--interval", "0"], ["--interval", "-1"], ["--interval", str(limit + 0.1)],
                      ["--interval", "nan"], ["--interval", "inf"],
                      ["--max-age", "0"], ["--max-age", "-5"], ["--max-age", "nan"], ["--max-age", "inf"]):
            with self.subTest(extra=extra):
                code, _, stderr = self.finish(self.start(*extra))
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(stderr)["category"], "invalid_args")
        self.assertEqual(channel_json(self.root).read_bytes(), before)

    def test_interval_at_half_ttl_is_accepted(self) -> None:
        limit = channel_module.HEARTBEAT_TTL_SECONDS / 2
        process = self.started("--interval", str(limit))
        process.terminate()
        self.assertEqual(self.finish(process)[0], 0)

    def test_max_age_defaults_below_the_claude_background_limit(self) -> None:
        args = channel_module.build_parser().parse_args(
            ["heartbeat", "--channel", "0001", "--role", "listener", "--session", "s1"])
        self.assertEqual(args.max_age, 6180)
        self.assertEqual(channel_module.RESTART_GRACE_SECONDS, 720)
        self.assertEqual(args.max_age + channel_module.RESTART_GRACE_SECONDS, 6900)
        self.assertLess(args.max_age + channel_module.RESTART_GRACE_SECONDS, 7200)
        self.assertEqual(args.interval, channel_module.HEARTBEAT_INTERVAL_SECONDS)

    def test_invalid_role_fails(self) -> None:
        result = run(self.root, "heartbeat", "--channel", "0001", "--role", "boss", "--session", "s1")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["category"], "invalid_role")

    def test_sigterm_sigint_and_sighup_exit_zero_with_signal(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(sig=sig):
                process = self.started("--interval", "0.2")
                process.send_signal(sig)
                code, stdout, _ = self.finish(process)
                self.assertEqual(code, 0)
                output = self.assert_stopped(stdout, "signal")
                self.assertIn("nothing to restart", output["next"])
                self.assertIn("heartbeat --channel 0001 --role listener --session s1", output["next"])

    def test_three_consecutive_stamp_failures_exit_heartbeat_failed(self) -> None:
        process = self.started("--interval", "0.1")
        os.chmod(channel_json(self.root).parent, 0o500)
        code, stdout, stderr = self.finish(process)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["category"], "heartbeat_failed")

    def test_stamp_failure_is_retried_at_the_next_interval(self) -> None:
        process = self.started("--interval", "0.3")
        directory = channel_json(self.root).parent
        os.chmod(directory, 0o500)
        time.sleep(0.45)
        os.chmod(directory, 0o700)
        stamped = seen_at(self.root, "listener")
        self.assertTrue(wait_until(lambda: seen_at(self.root, "listener") != stamped, timeout=2))
        self.assertIsNone(process.poll())

    def test_lock_held_past_interval_reads_stale_then_recovers_after_release(self) -> None:
        process = self.started("--interval", "0.1")
        with (channel_json(self.root).parent / "channel.lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                age_seat(self.root, "listener", 600)
                held = seen_at(self.root, "listener")
                time.sleep(0.4)
                self.assertEqual(seen_at(self.root, "listener"), held)
                self.assertFalse(json.loads(run(self.root, "status", "--channel", "0001").stdout)["listener_alive"])
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        self.assertTrue(wait_until(lambda: seen_at(self.root, "listener") != held, timeout=2))
        self.assertTrue(json.loads(run(self.root, "status", "--channel", "0001").stdout)["listener_alive"])
        self.assertIsNone(process.poll())

    def test_exits_channel_closed_on_close(self) -> None:
        process = self.started("--interval", "0.1")
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        code, stdout, _ = self.finish(process)
        self.assertEqual(code, 0)
        self.assertIn("nothing to restart", self.assert_stopped(stdout, "channel_closed")["next"])

    def test_exits_seat_taken_when_owner_changes(self) -> None:
        process = self.started("--interval", "0.1")
        record = json.loads(channel_json(self.root).read_text())
        record["listener_owner"] = "s2"
        rewrite_record(self.root, json.dumps(record))
        code, stdout, _ = self.finish(process)
        self.assertEqual(code, 2)
        output = self.assert_stopped(stdout, "seat_taken")
        self.assertEqual(output["category"], "seat_claimed")
        self.assertIn("nothing to restart", output["next"])

    def test_exits_max_age_with_the_same_command_as_next(self) -> None:
        process = self.started("--interval", "0.1", "--max-age", "0.3")
        code, stdout, _ = self.finish(process)
        self.assertEqual(code, 0)
        self.assertEqual(
            shlex.split(self.assert_stopped(stdout, "max_age")["next"]),
            ["python3", str(CHANNEL.resolve()), "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", "listener", "--session", "s1", "--interval", "0.1", "--max-age", "0.3"],
        )

    def test_printed_interval_and_max_age_round_trip_exactly(self) -> None:
        for interval, max_age in ((0.1234567, 1234567.5), (0.1, 0.3), (1e-07, 2.5e-05), (4.0, 7000.0)):
            with self.subTest(interval=interval, max_age=max_age):
                args = argparse.Namespace(root=str(self.root), role="listener", session="s1",
                                          interval=interval, max_age=max_age)
                printed = shlex.split(channel_module.heartbeat_command(args, self.root, "0001"))
                parsed = channel_module.build_parser().parse_args(printed[2:])
                self.assertEqual((parsed.interval, parsed.max_age), (interval, max_age))

    def test_prints_nothing_while_running(self) -> None:
        process = self.started("--interval", "0.1")
        time.sleep(0.35)
        process.terminate()
        _, stdout, stderr = self.finish(process)
        self.assertEqual(len(stdout.strip().splitlines()), 1)
        self.assert_stopped(stdout, "signal")
        self.assertEqual(stderr, "")


def restart_until(root: Path, role: str, channel: str = "0001") -> object:
    return json.loads(channel_json(root, channel).read_text()).get(f"{role}_restart_until")


def set_fields(root: Path, channel: str = "0001", **fields: object) -> None:
    path = channel_json(root, channel)
    record = json.loads(path.read_text())
    record.update(fields)
    rewrite_record(root, json.dumps(record), channel)


class RestartGraceTests(unittest.TestCase):
    """A heartbeat that stops at --max-age keeps its seat live for the restart grace."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        self.processes: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def heartbeat(self, role: str = "asker", session: str = "c1", *extra: str) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", role, "--session", session, "--interval", "0.1", *extra],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        return process

    def expire(self) -> None:
        """Run the asker heartbeat to its max_age stop, then let its stamp pass the TTL."""
        process = self.heartbeat("asker", "c1", "--max-age", "0.2")
        stdout, _ = process.communicate(timeout=5)
        self.assertEqual(json.loads(stdout)["stopped"], "max_age")
        age_seat(self.root, "asker", channel_module.HEARTBEAT_TTL_SECONDS + 5)

    def send(self, sender: str, recipient: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", sender, "--to", recipient, "--kind", "request", "--body-file", "-"],
            input="body", capture_output=True, text=True, check=False,
        )

    def status(self) -> dict:
        return json.loads(run(self.root, "status", "--channel", "0001").stdout)

    def listener_candidates(self) -> list[str]:
        output = json.loads(run(self.root, "list", "--live-for", "listener", "--session", "s1").stdout)
        return [c["channel"] for c in output["channels"]]

    def test_max_age_stop_writes_restart_until_within_the_grace(self) -> None:
        before = time.time()
        self.expire()
        until = restart_until(self.root, "asker")
        self.assertIsInstance(until, float)
        self.assertGreaterEqual(until, before + channel_module.RESTART_GRACE_SECONDS)
        self.assertLessEqual(until, time.time() + channel_module.RESTART_GRACE_SECONDS)

    def test_peer_reads_live_through_the_grace_and_send_is_accepted(self) -> None:
        self.expire()
        self.assertIs(self.status()["asker_alive"], True)
        self.assertEqual(self.listener_candidates(), ["0001"])
        sent = self.send("listener", "asker")
        self.assertEqual(sent.returncode, 0, sent.stderr)
        received = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertEqual(received.returncode, 1, received.stderr)
        output = json.loads(received.stdout)
        self.assertIs(output["peer_live"], True)
        self.assertIn("asker is restarting its heartbeat", output["note"])
        self.assertIn("keep waiting", output["note"])
        self.assertIn("receive --channel 0001 --for listener --timeout 300", output["next"])

    def test_receive_note_is_unchanged_for_a_freshly_stamped_peer(self) -> None:
        received = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertNotIn("restarting", json.loads(received.stdout)["note"])

    def test_same_owner_stamp_clears_restart_until(self) -> None:
        for label in ("heartbeat", "register"):
            with self.subTest(restart=label):
                self.expire()
                self.assertIsNotNone(restart_until(self.root, "asker"))
                if label == "heartbeat":
                    process = self.heartbeat("asker", "c1")
                    self.assertTrue(wait_until(lambda: restart_until(self.root, "asker") is None))
                    process.terminate()
                    process.communicate(timeout=5)
                else:
                    again = run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
                    self.assertEqual(again.returncode, 0, again.stderr)
                    self.assertIsNone(restart_until(self.root, "asker"))

    def test_expired_grace_reads_dead_everywhere(self) -> None:
        self.expire()
        set_fields(self.root, asker_restart_until=time.time() - 1)
        self.assertIs(self.status()["asker_alive"], False)
        self.assertEqual(self.listener_candidates(), [])
        sent = self.send("listener", "asker")
        self.assertEqual(sent.returncode, 2)
        self.assertEqual(json.loads(sent.stderr)["category"], "peer_not_live")
        received = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertIs(json.loads(received.stdout)["peer_live"], False)

    def test_killed_heartbeat_writes_no_marker_and_reads_dead_after_the_ttl(self) -> None:
        process = self.heartbeat("asker", "c1")
        stamped = seen_at(self.root, "asker")
        self.assertTrue(wait_until(lambda: seen_at(self.root, "asker") != stamped))
        process.kill()
        process.communicate(timeout=5)
        self.assertIsNone(restart_until(self.root, "asker"))
        age_seat(self.root, "asker", channel_module.HEARTBEAT_TTL_SECONDS + 5)
        self.assertIs(self.status()["asker_alive"], False)

    def test_another_session_is_still_refused_during_the_grace(self) -> None:
        self.expire()
        before = channel_json(self.root).read_bytes()
        other = run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c2")
        self.assertEqual(other.returncode, 2)
        self.assertEqual(json.loads(other.stderr)["category"], "seat_claimed")
        self.assertEqual(channel_json(self.root).read_bytes(), before)

    def test_invalid_restart_until_does_not_keep_the_seat_live(self) -> None:
        stale = time.time() - channel_module.HEARTBEAT_TTL_SECONDS - 5
        far = time.time() + channel_module.RESTART_GRACE_SECONDS + 60
        for value in ("9999999999", True, float("nan"), float("inf"), far, None, [1]):
            with self.subTest(value=value):
                record = {"asker_owner": "c1", "asker_seen_at": stale, "asker_restart_until": value}
                self.assertIs(channel_module.seat_live(record, "asker"), False)
        valid = {"asker_owner": "c1", "asker_seen_at": stale, "asker_restart_until": time.time() + 60}
        self.assertIs(channel_module.seat_live(valid, "asker"), True)
        self.assertIsNone(channel_module.seat_live({**valid, "asker_owner": None}, "asker"))

    def test_other_stop_reasons_write_no_marker(self) -> None:
        def stops(process: subprocess.Popen) -> str:
            stdout, stderr = process.communicate(timeout=5)
            return (json.loads(stdout)["stopped"] if stdout else json.loads(stderr)["category"])

        signalled = self.heartbeat("asker", "c1")
        stamped = seen_at(self.root, "asker")
        self.assertTrue(wait_until(lambda: seen_at(self.root, "asker") != stamped))
        signalled.terminate()
        self.assertEqual(stops(signalled), "signal")
        self.assertEqual(stops(self.heartbeat("asker", "c2")), "seat_taken")
        missing = run(self.root, "heartbeat", "--channel", "0042", "--role", "asker", "--session", "c1")
        self.assertEqual(json.loads(missing.stderr)["category"], "channel_missing")
        self.assertIsNone(restart_until(self.root, "asker"))

        failing = self.heartbeat("asker", "c1")
        stamped = seen_at(self.root, "asker")
        self.assertTrue(wait_until(lambda: seen_at(self.root, "asker") != stamped))
        good = channel_json(self.root).read_text()
        rewrite_record(self.root, "{bad")
        self.assertEqual(stops(failing), "heartbeat_failed")
        rewrite_record(self.root, good)
        self.assertIsNone(restart_until(self.root, "asker"))

        closing = self.heartbeat("asker", "c1")
        stamped = seen_at(self.root, "asker")
        self.assertTrue(wait_until(lambda: seen_at(self.root, "asker") != stamped))
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        self.assertEqual(stops(closing), "channel_closed")
        self.assertIsNone(restart_until(self.root, "asker"))


    def test_close_after_a_max_age_stop_leaves_no_seat_alive(self) -> None:
        self.expire()
        self.assertIs(self.status()["asker_alive"], True)
        closed = run(self.root, "close", "--role", "listener", "--channel", "0001")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertIsNone(restart_until(self.root, "asker"))
        age_seat(self.root, "asker", 60)
        age_seat(self.root, "listener", 60)
        status = self.status()
        self.assertEqual(status["state"], "closed")
        self.assertIs(status["asker_alive"], False)
        self.assertIs(status["listener_alive"], False)


class ConditionalCloseTests(unittest.TestCase):
    """`close --if-peer-stale` closes only while the peer is not live and nothing unread waits for the closer."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        self.processes: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def close(self) -> subprocess.CompletedProcess:
        return run(self.root, "close", "--role", "listener", "--channel", "0001", "--if-peer-stale", timeout=5)

    def state(self) -> str:
        return json.loads(channel_json(self.root).read_text())["state"]

    def request(self) -> str:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="late request", capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        return json.loads(sent.stdout)["message_id"]

    def assert_refused(self, result: subprocess.CompletedProcess, category: str) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        payload = json.loads(result.stderr)
        self.assertEqual(payload["category"], category)
        self.assertEqual(shlex.split(quoted_command(payload["next"])),
                         ["python3", str(CHANNEL.resolve()), "--root", str(self.root), "receive",
                          "--channel", "0001", "--for", "listener", "--timeout", "300"])
        self.assertNotEqual(self.state(), "closed")

    def test_refuses_while_the_peer_is_live(self) -> None:
        self.assert_refused(self.close(), "peer_live")

    def test_a_peer_back_after_a_stale_receive_keeps_the_channel_open(self) -> None:
        age_seat(self.root, "asker", 600)
        received = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertIs(json.loads(received.stdout)["peer_live"], False)
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        message_id = self.request()
        self.assert_refused(self.close(), "peer_live")
        again = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn(f"--message-id {message_id}", json.loads(again.stdout)["next"])

    def test_an_unread_request_keeps_the_channel_open_and_receivable(self) -> None:
        age_seat(self.root, "asker", 600)
        message_id = self.request()
        self.assert_refused(self.close(), "unread_message")
        again = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["new_since_call"], 1)
        fetched = run(self.root, "fetch", "--channel", "0001", "--message-id", message_id)
        self.assertEqual(json.loads(fetched.stdout)["body"], "late request")

    def test_a_peer_in_its_restart_grace_is_live(self) -> None:
        expired = run(self.root, "heartbeat", "--channel", "0001", "--role", "asker", "--session", "c1",
                      "--interval", "0.1", "--max-age", "0.2", timeout=5)
        self.assertEqual(json.loads(expired.stdout)["stopped"], "max_age")
        age_seat(self.root, "asker", channel_module.HEARTBEAT_TTL_SECONDS + 5)
        self.assert_refused(self.close(), "peer_live")

    def test_closes_on_a_stale_peer_and_an_empty_inbox_and_ends_the_heartbeat(self) -> None:
        message_id = self.request()
        run(self.root, "fetch", "--channel", "0001", "--message-id", message_id)
        heartbeat = subprocess.Popen(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", "listener", "--session", "s1", "--interval", "0.1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(heartbeat)
        age_seat(self.root, "asker", 600)
        closed = self.close()
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertEqual(json.loads(closed.stdout)["state"], "closed")
        stdout, _ = heartbeat.communicate(timeout=5)
        self.assertEqual(json.loads(stdout)["stopped"], "channel_closed")

    def test_plain_close_still_closes_with_a_live_peer(self) -> None:
        closed = run(self.root, "close", "--role", "listener", "--channel", "0001")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertEqual(self.state(), "closed")


def quoted_command(text: str) -> str:
    """The command a `next` quotes between backticks."""
    return text.split("`")[1]


def root_variants() -> list[tuple[str, list[str], dict[str, str], Path]]:
    """(label, root flag, env, resolved root) for the default, an explicit and a relative `--root`."""
    fake_home = Path(tempfile.mkdtemp(prefix="advisor-test-home-"))
    caller = Path(tempfile.mkdtemp(prefix="advisor-test-caller-"))
    explicit = Path(tempfile.mkdtemp(prefix="advisor-test-")) / "a root"
    base = {k: v for k, v in os.environ.items() if k != "BOOTGEAR_ADVISOR_DIR"}
    return [
        ("default", [], {**base, "HOME": str(fake_home)}, fake_home / ".bootgear" / "advisor"),
        ("explicit", ["--root", str(explicit)], base, explicit),
        ("relative", ["--root", "mbox"], {**base, "GEAR_CALLER_CWD": str(caller)}, caller / "mbox"),
    ]


def run_in(root_flag: list[str], env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHANNEL), *root_flag, *args],
                          capture_output=True, text=True, check=False, env=env)


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
                    ["python3", str(CHANNEL.resolve()),
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


class LiveCandidateScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_finds_live_listener(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        result = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        found = json.loads(result.stdout)["channels"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["channel"], "0001")

    def test_excludes_peer_with_stale_heartbeat(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        age_seat(self.root, "listener", 600)
        result = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        self.assertEqual(json.loads(result.stdout)["channels"], [])

    def test_receive_leaves_channel_json_unchanged(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        before = channel_json(self.root).read_bytes()
        for timeout in ("0", "0.3"):
            with self.subTest(timeout=timeout):
                result = run(self.root, "receive", "--channel", "0001", "--for", "listener",
                             "--timeout", timeout, "--poll", "0.05")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(channel_json(self.root).read_bytes(), before)

    def test_foreign_receive_does_not_revive_aged_seat(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        age_seat(self.root, "listener", 600)
        run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        record = json.loads(run(self.root, "status", "--channel", "0001").stdout)
        self.assertFalse(record["listener_alive"])

    def test_status_reports_heartbeat_liveness(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        record = json.loads(run(self.root, "status", "--channel", "0001").stdout)
        self.assertTrue(record["listener_alive"])
        self.assertIsNone(record["asker_alive"])
        age_seat(self.root, "listener", 600)
        record = json.loads(run(self.root, "status", "--channel", "0001").stdout)
        self.assertFalse(record["listener_alive"])

    def test_excludes_closed_channel(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        result = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        self.assertEqual(json.loads(result.stdout)["channels"], [])

    def test_excludes_channel_outside_48h_window(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        stale = time.time() - 49 * 3600
        record["created_at"] = stale
        record["updated_at"] = stale
        path.write_text(json.dumps(record))
        result = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        self.assertEqual(json.loads(result.stdout)["channels"], [])

    def test_includes_channel_just_inside_48h_window(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        fresh = time.time() - 47 * 3600
        record["created_at"] = fresh
        record["updated_at"] = fresh
        path.write_text(json.dumps(record))
        result = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        found = json.loads(result.stdout)["channels"]
        self.assertEqual(len(found), 1)

    def test_excludes_old_schema_record_with_no_listener_owner_field(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        path = self.root / "channels" / "0001" / "channel.json"
        record = json.loads(path.read_text())
        del record["listener_owner"]
        path.write_text(json.dumps(record))
        result = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        self.assertEqual(json.loads(result.stdout)["channels"], [])


class ListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        self.script = ["python3", str(CHANNEL.resolve()), "--root", str(self.root)]

    def scan(self, *extra: str) -> subprocess.CompletedProcess:
        return run(self.root, "list", "--live-for", "asker", "--session", "c1", *extra)

    def test_without_live_for_prints_all_channels_as_an_object(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "close", "--role", "listener", "--channel", "0001")
        result = run(self.root, "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {"channels"})
        self.assertEqual([c["channel"] for c in output["channels"]], ["0001"])

    def test_candidates_sorted_most_recent_first_and_next_claims_it(self) -> None:
        for _ in range(3):
            run(self.root, "register", "--role", "listener", "--session", "s1")
        age_updated_at(self.root, 300, "0001")
        age_updated_at(self.root, 100, "0003")
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual([c["channel"] for c in output["channels"]], ["0002", "0003", "0001"])
        self.assertEqual(shlex.split(output["next"]),
                         [*self.script, "register", "--role", "asker", "--channel", "0002", "--session", "c1"])

    def test_owned_asker_seat_is_not_offered_to_another_session(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--role", "listener", "--session", "s2")
        run(self.root, "register", "--channel", "0002", "--role", "asker", "--session", "c9")
        run(self.root, "state", "--channel", "0002", "--role", "listener", "--value", "busy")
        output = json.loads(self.scan().stdout)
        self.assertEqual([c["channel"] for c in output["channels"]], ["0001"])
        self.assertEqual(shlex.split(output["next"]),
                         [*self.script, "register", "--role", "asker", "--channel", "0001", "--session", "c1"])

    def test_seat_held_by_this_session_is_still_offered(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        output = json.loads(self.scan().stdout)
        self.assertEqual([c["channel"] for c in output["channels"]], ["0001"])

    def test_wait_does_not_return_on_an_owned_seat(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c9")
        result = self.scan("--wait", "0.3")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["channels"], [])

    def test_live_for_listener_offers_the_listener_seat(self) -> None:
        run(self.root, "register", "--role", "asker", "--session", "c1")
        output = json.loads(run(self.root, "list", "--live-for", "listener", "--session", "s 1").stdout)
        self.assertEqual([c["channel"] for c in output["channels"]], ["0001"])
        self.assertEqual(shlex.split(output["next"]),
                         [*self.script, "register", "--role", "listener", "--channel", "0001", "--session", "s 1"])

    def test_empty_without_wait_exits_zero_with_note_and_both_branches_in_next(self) -> None:
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["channels"], [])
        self.assertEqual(output["note"], "no live listener found")
        self.assertEqual(len(output["next"].splitlines()), 1)
        self.assertIn("only if you started the listener yourself or the user said one is starting",
                      output["next"])
        self.assertIn("otherwise tell the user to start a listener and stop", output["next"])
        self.assertEqual(shlex.split(quoted_command(output["next"])),
                         [*self.script, "list", "--live-for", "asker", "--session", "c1", "--wait", "120"])

    def test_wait_timeout_exits_one_without_next(self) -> None:
        result = self.scan("--wait", "0.3")
        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["channels"], [])
        self.assertEqual(output["note"], "no listener appeared within 0.3s; tell the user to start one")
        self.assertNotIn("next", output)

    def test_wait_ignores_a_stale_listener(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        age_seat(self.root, "listener", 600)
        self.assertEqual(self.scan("--wait", "0.3").returncode, 1)

    def test_wait_returns_once_a_listener_registers(self) -> None:
        process = subprocess.Popen(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "list", "--live-for", "asker",
             "--session", "c1", "--wait", "20"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        time.sleep(0.3)
        started = time.monotonic()
        run(self.root, "register", "--role", "listener", "--session", "s1")
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertLess(time.monotonic() - started, 3)
        output = json.loads(stdout)
        self.assertEqual([c["channel"] for c in output["channels"]], ["0001"])
        self.assertIn("register --role asker --channel 0001", output["next"])

    def test_wait_returns_within_n_seconds_plus_one_poll(self) -> None:
        started = time.monotonic()
        result = self.scan("--wait", "1.5")
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertGreaterEqual(elapsed, 1.5)
        self.assertLess(elapsed, 1.5 + 1 + 0.5)

    def test_wait_without_live_for_fails(self) -> None:
        result = run(self.root, "list", "--wait", "5")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["category"], "invalid_args")

    def test_live_for_without_session_fails(self) -> None:
        result = run(self.root, "list", "--live-for", "asker")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["category"], "invalid_args")

    def test_negative_or_non_finite_wait_fails(self) -> None:
        for value in ("-1", "nan", "inf"):
            with self.subTest(wait=value):
                result = run(self.root, "list", "--live-for", "asker", "--session", "c1", "--wait", value,
                             timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stderr)["category"], "invalid_args")

    def test_printed_next_commands_run_as_printed_for_each_root(self) -> None:
        clean = {k: v for k, v in os.environ.items() if k not in {"BOOTGEAR_ADVISOR_DIR", "GEAR_CALLER_CWD"}}
        for label, root_flag, env, _ in root_variants():
            with self.subTest(root=label):
                empty = run_in(root_flag, env, "list", "--live-for", "asker", "--session", "c1")
                wait = shlex.split(quoted_command(json.loads(empty.stdout)["next"]))
                self.assertEqual("--root" in wait, label != "default")
                run_in(root_flag, env, "register", "--role", "listener", "--session", "s1")
                run_env = {**clean, "HOME": env["HOME"]} if label == "default" else clean
                waited = subprocess.run(wait, capture_output=True, text=True, check=False, env=run_env, timeout=10)
                self.assertEqual(waited.returncode, 0, waited.stderr)
                claim = shlex.split(json.loads(waited.stdout)["next"])
                claimed = subprocess.run(claim, capture_output=True, text=True, check=False, env=run_env)
                self.assertEqual(claimed.returncode, 0, claimed.stderr)
                self.assertEqual(json.loads(claimed.stdout)["asker_owner"], "c1")


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
                self.assertEqual(example[:4], ["python3", str(CHANNEL.resolve()), "--root", str(self.root)])
                self.assertEqual(parser.parse_args(example[2:]).command, command)
                self.assertEqual(payload["commands"].split(", "),
                                 [c for c in channel_module.COMMANDS if c != command])
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
        self.assertEqual(payload["commands"].split(", "), list(channel_module.COMMANDS))
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
                ran = subprocess.run(["bash", "-c", example], capture_output=True, text=True, check=False,
                                     env={**base, "SESSION_ID": "c1"}, cwd=elsewhere, timeout=10)
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
                self.assertEqual(example[2:], ["--root", str(self.root), "status", "--channel", "0001"])
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
        self.assertEqual(sorted(channel_module.COMMANDS), sorted(subparsers.choices))

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


class SendLivenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        self.processes: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def send(self, sender: str, recipient: str, kind: str = "request", *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", sender, "--to", recipient, "--kind", kind, *extra, "--body-file", "-"],
            input="body", capture_output=True, text=True, check=False,
        )

    def messages(self) -> list[Path]:
        return sorted((self.root / "channels" / "0001" / "messages").glob("*.json"))

    def assert_refused(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["category"], "peer_not_live")
        self.assertIn("tell the user", payload["next"])
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.messages(), [])

    def test_send_to_unowned_recipient_fails_peer_not_live(self) -> None:
        self.assert_refused(self.send("listener", "asker"))

    def test_send_to_stale_recipient_fails_peer_not_live(self) -> None:
        age_seat(self.root, "listener", 600)
        self.assert_refused(self.send("asker", "listener"))

    def test_response_to_stale_asker_is_refused(self) -> None:
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        age_seat(self.root, "asker", 600)
        self.assert_refused(self.send("listener", "asker", "response", "--parent-id", "abc"))

    def test_stop_is_accepted_by_a_stale_or_unowned_recipient(self) -> None:
        age_seat(self.root, "listener", 600)
        for recipient, sender in (("listener", "asker"), ("asker", "listener")):
            with self.subTest(recipient=recipient):
                result = self.send(sender, recipient, "stop")
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.messages()), 2)

    def test_send_right_after_register_succeeds(self) -> None:
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        for sender, recipient in (("asker", "listener"), ("listener", "asker")):
            with self.subTest(recipient=recipient):
                result = self.send(sender, recipient)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.messages()), 2)

    def test_busy_heartbeating_listener_accepts_a_request(self) -> None:
        age_seat(self.root, "listener", 600)
        aged = seen_at(self.root, "listener")
        process = subprocess.Popen(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", "listener", "--session", "s1", "--interval", "0.2"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        self.assertTrue(wait_until(lambda: seen_at(self.root, "listener") != aged))
        run(self.root, "state", "--channel", "0001", "--role", "listener", "--value", "busy")
        result = self.send("asker", "listener")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.messages()), 1)


class ConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_state_and_register_do_not_clobber(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )

        results: dict[str, subprocess.CompletedProcess] = {}

        def do_state() -> None:
            results["state"] = run(self.root, "state", "--channel", "0001", "--role", "listener", "--value", "busy")

        def do_register() -> None:
            results["register"] = run(
                self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
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

    def test_asker_finds_and_joins_live_listener(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        scan = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        candidates = json.loads(scan.stdout)["channels"]
        self.assertEqual(len(candidates), 1)
        channel = candidates[0]["channel"]
        claim = run(
            self.root, "register", "--channel", channel, "--role", "asker", "--session", "c1",
        )
        self.assertEqual(claim.returncode, 0)
        record = json.loads(claim.stdout)
        self.assertEqual(record["asker_owner"], "c1")
        self.assertEqual(record["listener_owner"], "s1")

    def test_asker_finds_none_tells_user_stops(self) -> None:
        scan = run(self.root, "list", "--live-for", "asker", "--session", "c1")
        self.assertEqual(json.loads(scan.stdout)["channels"], [])

    def test_retry_second_claim_also_loses(self) -> None:
        run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        first_claim = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1",
        )
        self.assertEqual(first_claim.returncode, 0)

        # A second asker's claim on a seat the first asker holds loses.
        retry_claim = run(
            self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c2",
        )
        self.assertEqual(retry_claim.returncode, 2)
        payload = json.loads(retry_claim.stderr)
        self.assertEqual(payload["category"], "seat_claimed")

    def test_simultaneous_listener_cold_start_creates_two_channels(self) -> None:
        first = run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        second = run(
            self.root, "register", "--role", "listener", "--session", "s2",
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
        registered = run(
            self.root, "register", "--role", "listener", "--session", "s1",
        )
        self.channel = json.loads(registered.stdout)["channel"]
        run(self.root, "register", "--channel", self.channel, "--role", "asker", "--session", "c1")

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
        self.assertIs(output["peer_live"], True)
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

        registered = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(default_root), "register",
             "--role", "listener", "--session", "s1"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        channel = json.loads(registered.stdout)["channel"]
        asker = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(default_root), "register",
             "--channel", channel, "--role", "asker", "--session", "c1"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(asker.returncode, 0, asker.stderr)

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

        registered = subprocess.run(
            [sys.executable, str(CHANNEL), "register",
             "--role", "listener", "--session", "s1"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        channel = json.loads(registered.stdout)["channel"]
        asker = subprocess.run(
            [sys.executable, str(CHANNEL), "register",
             "--channel", channel, "--role", "asker", "--session", "c1"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(asker.returncode, 0, asker.stderr)

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

        registered = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", "mbox", "register",
             "--role", "listener", "--session", "s1"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(registered.returncode, 0, registered.stderr)
        channel = json.loads(registered.stdout)["channel"]
        asker = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", "mbox", "register",
             "--channel", channel, "--role", "asker", "--session", "c1"],
            capture_output=True, text=True, check=False, env=env,
        )
        self.assertEqual(asker.returncode, 0, asker.stderr)

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

    def test_stale_peer_without_message_says_tell_the_user_and_omits_next(self) -> None:
        age_seat(self.root, "listener", 600, self.channel)
        result = self._receive()
        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertIs(output["peer_live"], False)
        self.assertIn("no new message for asker", output["note"])
        self.assertIn("peer heartbeat stale; tell the user instead of waiting again", output["note"])
        self.assertNotIn("up to 5 waits", output["note"])
        self.assertNotIn("next", output)

    def test_stale_peer_with_new_message_still_points_at_fetch(self) -> None:
        message_id = self._send_to_asker()
        age_seat(self.root, "listener", 600, self.channel)
        result = self._receive()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertIs(output["peer_live"], False)
        self.assertIn(f"fetch --channel {self.channel} --message-id {message_id}", output["next"])

    def test_new_message_output_reports_peer_live(self) -> None:
        self._send_to_asker()
        self.assertIs(json.loads(self._receive().stdout)["peer_live"], True)

    def test_listener_before_any_asker_gets_null_peer_live_and_keeps_waiting(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s2")
        result = run(self.root, "receive", "--channel", "0002", "--for", "listener", "--timeout", "0")
        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertIn("peer_live", output)
        self.assertIsNone(output["peer_live"])
        self.assertNotIn("stale", output["note"])
        self.assertIn("a request can come at any time", output["note"])
        self.assertIn("receive --channel 0002 --for listener --timeout 300", output["next"])

    def test_listener_with_stale_asker_gets_the_stale_note(self) -> None:
        age_seat(self.root, "asker", 600, self.channel)
        result = run(self.root, "receive", "--channel", self.channel, "--for", "listener", "--timeout", "0")
        output = json.loads(result.stdout)
        self.assertIs(output["peer_live"], False)
        self.assertIn("peer heartbeat stale; tell the user instead of waiting again", output["note"])
        self.assertNotIn("next", output)



class ListenerLoopTests(unittest.TestCase):
    """Runs the listener loop from SKILL.md against a real mailbox, with short receive waits."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        skill = (CHANNEL.parent.parent / "SKILL.md").read_text()
        loop = skill[skill.index("while :; do"):skill.index("done\n") + len("done\n")]
        self.loop = (loop.replace("<mine>", "listener").replace("<peer>", "asker")
                     .replace("<message_id>", "none").replace("--timeout 300", "--timeout 0.1"))

    def start_loop(self) -> subprocess.Popen[str]:
        env = {**os.environ, "BOOTGEAR_ADVISOR_DIR": str(self.root), "CHANNEL_SCRIPT": str(CHANNEL),
               "CHANNEL": "0001"}
        process = subprocess.Popen(["bash", "-c", self.loop], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=env)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.communicate()))
        return process

    def test_stops_when_the_asker_heartbeat_is_stale(self) -> None:
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        age_seat(self.root, "asker", 600)
        process = self.start_loop()
        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)

    def test_stopping_on_a_stale_asker_closes_the_channel_and_ends_the_heartbeat(self) -> None:
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        heartbeat = subprocess.Popen(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", "listener", "--session", "s1", "--interval", "0.1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(lambda: (heartbeat.poll() is None and heartbeat.kill(), heartbeat.communicate()))
        age_seat(self.root, "asker", 600)
        process = self.start_loop()
        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(channel_json(self.root).read_text())["state"], "closed")
        stdout, _ = heartbeat.communicate(timeout=5)
        self.assertEqual(json.loads(stdout)["stopped"], "channel_closed")

    def test_keeps_waiting_while_the_asker_restarts_its_heartbeat(self) -> None:
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        expired = run(self.root, "heartbeat", "--channel", "0001", "--role", "asker", "--session", "c1",
                      "--interval", "0.1", "--max-age", "0.2", timeout=5)
        self.assertEqual(json.loads(expired.stdout)["stopped"], "max_age")
        age_seat(self.root, "asker", 600)
        process = self.start_loop()
        time.sleep(1.5)
        running = process.poll() is None
        process.kill()
        _, stderr = process.communicate()
        self.assertTrue(running, stderr)
        self.assertNotEqual(json.loads(channel_json(self.root).read_text())["state"], "closed")

    def test_keeps_listening_when_the_asker_returns_before_the_close(self) -> None:
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        age_seat(self.root, "asker", 600)
        marker = self.root / "asker-returned"
        wrapper = self.root / "channel-wrapper.py"
        wrapper.write_text(
            "import os, subprocess, sys\n"
            f"real, marker = {str(CHANNEL)!r}, {str(marker)!r}\n"
            "if 'close' in sys.argv[1:] and not os.path.exists(marker):\n"
            "    open(marker, 'w').close()\n"
            "    subprocess.run([sys.executable, real, 'register', '--channel', '0001', '--role', 'asker',\n"
            "                    '--session', 'c1'], check=True, capture_output=True)\n"
            "os.execv(sys.executable, [sys.executable, real, *sys.argv[1:]])\n")
        env = {**os.environ, "BOOTGEAR_ADVISOR_DIR": str(self.root), "CHANNEL_SCRIPT": str(wrapper),
               "CHANNEL": "0001"}
        process = subprocess.Popen(["bash", "-c", self.loop], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=env)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.communicate()))
        time.sleep(1.5)
        running = process.poll() is None
        process.kill()
        _, stderr = process.communicate()
        self.assertTrue(marker.exists(), stderr)
        self.assertTrue(running, stderr)
        self.assertNotEqual(json.loads(channel_json(self.root).read_text())["state"], "closed")

    def test_keeps_waiting_while_the_asker_is_live_or_absent(self) -> None:
        for label in ("absent", "live"):
            with self.subTest(asker=label):
                if label == "live":
                    run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
                process = self.start_loop()
                time.sleep(1.5)
                running = process.poll() is None
                process.kill()
                _, stderr = process.communicate()
                self.assertTrue(running, stderr)


if __name__ == "__main__":
    unittest.main()
