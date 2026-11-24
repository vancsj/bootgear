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
import time
import unittest
from pathlib import Path

from channel_test_support import (
    CHANNEL,
    GEAR_PREFIX,
    age_seat,
    channel_json,
    channel_liveness,
    channel_module,
    channel_output,
    channel_store,
    rewrite_record,
    run,
    seen_at,
    set_fields,
    wait_until,
)


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
             "--role", "listener", "--session", session, *extra, "--json"],
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
             "--role", "asker", "--session", "c1", "--json"],
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
            lock = channel_store.channel_lock(channel_json(self.root).parent)
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
        limit = channel_liveness.HEARTBEAT_TTL_SECONDS / 2
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
        limit = channel_liveness.HEARTBEAT_TTL_SECONDS / 2
        process = self.started("--interval", str(limit))
        process.terminate()
        self.assertEqual(self.finish(process)[0], 0)

    def test_max_age_defaults_below_the_claude_background_limit(self) -> None:
        args = channel_module.build_parser().parse_args(
            ["heartbeat", "--channel", "0001", "--role", "listener", "--session", "s1"])
        self.assertEqual(args.max_age, 6180)
        self.assertEqual(channel_liveness.RESTART_GRACE_SECONDS, 720)
        self.assertEqual(args.max_age + channel_liveness.RESTART_GRACE_SECONDS, 6900)
        self.assertLess(args.max_age + channel_liveness.RESTART_GRACE_SECONDS, 7200)
        self.assertEqual(args.interval, channel_liveness.HEARTBEAT_INTERVAL_SECONDS)

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
            [*GEAR_PREFIX, "--root", str(self.root), "heartbeat", "--channel", "0001",
             "--role", "listener", "--session", "s1", "--interval", "0.1", "--max-age", "0.3"],
        )

    def test_printed_interval_and_max_age_round_trip_exactly(self) -> None:
        for interval, max_age in ((0.1234567, 1234567.5), (0.1, 0.3), (1e-07, 2.5e-05), (4.0, 7000.0)):
            with self.subTest(interval=interval, max_age=max_age):
                args = argparse.Namespace(root=str(self.root), role="listener", session="s1",
                                          interval=interval, max_age=max_age)
                printed = shlex.split(channel_output.heartbeat_command(args, self.root, "0001"))
                parsed = channel_module.build_parser().parse_args(printed[len(GEAR_PREFIX):])
                self.assertEqual((parsed.interval, parsed.max_age), (interval, max_age))

    def test_prints_nothing_while_running(self) -> None:
        process = self.started("--interval", "0.1")
        time.sleep(0.35)
        process.terminate()
        _, stdout, stderr = self.finish(process)
        self.assertEqual(len(stdout.strip().splitlines()), 1)
        self.assert_stopped(stdout, "signal")
        self.assertEqual(stderr, "")


class ReceiveHeartbeatReminderTests(unittest.TestCase):
    """`receive` tells the caller to restart its own heartbeat when its seat is not fresh.

    Table (own seat / pending message / peer seat -> expected `next`):
      fresh / no / live        -> receive only
      stale / no / live        -> heartbeat, then receive
      restarting / no / live   -> heartbeat, then receive
      stale / yes / live       -> fetch, then heartbeat
      fresh / yes / live       -> fetch only
      stale / no / stale       -> heartbeat only
    """

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def receive(self) -> subprocess.CompletedProcess:
        return run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")

    def send_request(self) -> None:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="question", capture_output=True, text=True, check=False,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)

    def heartbeat(self) -> str:
        return f"heartbeat --channel 0001 --role listener --session s1"

    def test_fresh_seat_gets_receive_only(self) -> None:
        result = self.receive()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertNotIn("heartbeat --channel", payload["next"])
        self.assertIn("receive --channel 0001 --for listener", payload["next"])

    def test_stale_seat_gets_heartbeat_before_receive(self) -> None:
        age_seat(self.root, "listener", 600)
        result = self.receive()
        self.assertEqual(result.returncode, 1, result.stderr)
        next_text = json.loads(result.stdout)["next"]
        self.assertIn(self.heartbeat(), next_text)
        self.assertLess(next_text.index("heartbeat --channel"), next_text.index("receive --channel"))

    def test_restarting_seat_gets_heartbeat_before_receive(self) -> None:
        age_seat(self.root, "listener", 600)
        set_fields(self.root, listener_restart_until=time.time() + 100)
        result = self.receive()
        self.assertEqual(result.returncode, 1, result.stderr)
        next_text = json.loads(result.stdout)["next"]
        self.assertIn(self.heartbeat(), next_text)
        self.assertLess(next_text.index("heartbeat --channel"), next_text.index("receive --channel"))

    def test_stale_seat_with_pending_message_gets_fetch_then_heartbeat(self) -> None:
        self.send_request()
        age_seat(self.root, "listener", 600)
        result = self.receive()
        self.assertEqual(result.returncode, 0, result.stderr)
        next_text = json.loads(result.stdout)["next"]
        self.assertIn("fetch --channel 0001 --message-id", next_text)
        self.assertIn(self.heartbeat(), next_text)
        self.assertLess(next_text.index("fetch"), next_text.index("heartbeat --channel"))

    def test_fresh_seat_with_pending_message_gets_fetch_only(self) -> None:
        self.send_request()
        result = self.receive()
        self.assertEqual(result.returncode, 0, result.stderr)
        next_text = json.loads(result.stdout)["next"]
        self.assertIn("fetch --channel 0001 --message-id", next_text)
        self.assertNotIn("heartbeat --channel", next_text)

    def test_listener_restarts_its_heartbeat_then_keeps_waiting_for_a_stale_asker(self) -> None:
        age_seat(self.root, "listener", 600)
        age_seat(self.root, "asker", 600)
        result = self.receive()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(self.heartbeat(), payload["next"])
        self.assertIn("receive --channel", payload["next"])


class HookStampLivenessTests(unittest.TestCase):
    """`<role>_hook_seen_at` keeps a seat live; only `<role>_seen_at` counts as a beating heartbeat."""

    def record(self, **fields: object) -> dict[str, object]:
        return {"listener_owner": "s1", "updated_at": time.time(), **fields}

    def test_fresh_hook_stamp_alone_reads_fresh_and_live_but_not_beating(self) -> None:
        record = self.record(listener_hook_seen_at=time.time() - 1)
        self.assertIs(channel_liveness.seat_fresh(record, "listener"), True)
        self.assertIs(channel_liveness.seat_live(record, "listener"), True)
        self.assertIs(channel_liveness.seat_beating(record, "listener"), False)

    def test_aged_hook_stamp_reads_stale(self) -> None:
        aged = time.time() - channel_liveness.HEARTBEAT_TTL_SECONDS - 1
        record = self.record(listener_hook_seen_at=aged)
        self.assertIs(channel_liveness.seat_fresh(record, "listener"), False)
        self.assertIs(channel_liveness.seat_live(record, "listener"), False)

    def test_both_stamps_fresh_read_fresh_and_beating(self) -> None:
        now = time.time()
        record = self.record(listener_seen_at=now - 1, listener_hook_seen_at=now - 1)
        self.assertIs(channel_liveness.seat_fresh(record, "listener"), True)
        self.assertIs(channel_liveness.seat_beating(record, "listener"), True)

    def test_stale_heartbeat_with_fresh_hook_stamp_reads_fresh(self) -> None:
        now = time.time()
        record = self.record(listener_seen_at=now - 600, listener_hook_seen_at=now - 1)
        self.assertIs(channel_liveness.seat_fresh(record, "listener"), True)
        self.assertIs(channel_liveness.seat_beating(record, "listener"), False)

    def test_invalid_or_future_hook_stamp_reads_stale(self) -> None:
        for value in (0, "x", True, float("nan"), -5.0, None, time.time() + 60):
            with self.subTest(value=value):
                self.assertIs(channel_liveness.seat_fresh(self.record(listener_hook_seen_at=value), "listener"), False)

    def test_heartbeat_reminder_fires_with_a_fresh_hook_stamp_and_a_stale_seen_at(self) -> None:
        now = time.time()
        record = self.record(listener_seen_at=now - 600, listener_hook_seen_at=now)
        args = argparse.Namespace(root=None, recipient="listener", channel="0001")
        reminder = channel_output.heartbeat_reminder(args, Path(tempfile.mkdtemp()), record)
        self.assertIsNotNone(reminder)
        self.assertIn("heartbeat --channel 0001 --role listener --session s1", reminder)
