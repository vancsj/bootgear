from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from channel_test_support import (
    CHANNEL,
    age_seat,
    channel_json,
    channel_liveness,
    restart_until,
    rewrite_record,
    run,
    seen_at,
    set_fields,
    wait_until,
)


class SeatLiveTests(unittest.TestCase):
    def record(self, **fields: object) -> dict[str, object]:
        return {"listener_owner": "s1", "updated_at": time.time(), **fields}

    def test_unowned_seat_is_none(self) -> None:
        self.assertIsNone(channel_liveness.seat_live({"listener_seen_at": time.time()}, "listener"))

    def test_fresh_seen_at_reads_live(self) -> None:
        self.assertIs(channel_liveness.seat_live(self.record(listener_seen_at=time.time() - 1), "listener"), True)

    def test_future_dated_seen_at_reads_stale(self) -> None:
        self.assertIs(channel_liveness.seat_live(self.record(listener_seen_at=time.time() + 60), "listener"), False)

    def test_invalid_seen_at_reads_stale_even_with_fresh_updated_at(self) -> None:
        for value in (0, "x", True, float("nan"), -5.0, None):
            with self.subTest(value=value):
                self.assertIs(channel_liveness.seat_live(self.record(listener_seen_at=value), "listener"), False)
        self.assertIs(channel_liveness.seat_live(self.record(), "listener"), False)

    def test_seen_at_past_ttl_reads_stale(self) -> None:
        aged = time.time() - channel_liveness.HEARTBEAT_TTL_SECONDS - 1
        self.assertIs(channel_liveness.seat_live(self.record(listener_seen_at=aged), "listener"), False)

    def test_ttl_is_ten_seconds_and_interval_fits_twice(self) -> None:
        self.assertEqual(channel_liveness.HEARTBEAT_TTL_SECONDS, 10)
        self.assertEqual(channel_liveness.HEARTBEAT_INTERVAL_SECONDS, 3)


class LivenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_aged_seen_at_with_fresh_updated_at_reads_stale(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        age_seat(self.root, "listener", channel_liveness.HEARTBEAT_TTL_SECONDS + 1)
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
             "--role", role, "--session", session, "--interval", "0.1", *extra, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        return process

    def expire(self) -> None:
        """Run the asker heartbeat to its max_age stop, then let its stamp pass the TTL."""
        process = self.heartbeat("asker", "c1", "--max-age", "0.2")
        stdout, _ = process.communicate(timeout=5)
        self.assertEqual(json.loads(stdout)["stopped"], "max_age")
        age_seat(self.root, "asker", channel_liveness.HEARTBEAT_TTL_SECONDS + 5)

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
        self.assertGreaterEqual(until, before + channel_liveness.RESTART_GRACE_SECONDS)
        self.assertLessEqual(until, time.time() + channel_liveness.RESTART_GRACE_SECONDS)

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
        age_seat(self.root, "asker", channel_liveness.HEARTBEAT_TTL_SECONDS + 5)
        self.assertIs(self.status()["asker_alive"], False)

    def test_another_session_is_still_refused_during_the_grace(self) -> None:
        self.expire()
        before = channel_json(self.root).read_bytes()
        other = run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c2")
        self.assertEqual(other.returncode, 2)
        self.assertEqual(json.loads(other.stderr)["category"], "seat_claimed")
        self.assertEqual(channel_json(self.root).read_bytes(), before)

    def test_invalid_restart_until_does_not_keep_the_seat_live(self) -> None:
        stale = time.time() - channel_liveness.HEARTBEAT_TTL_SECONDS - 5
        far = time.time() + channel_liveness.RESTART_GRACE_SECONDS + 60
        for value in ("9999999999", True, float("nan"), float("inf"), far, None, [1]):
            with self.subTest(value=value):
                record = {"asker_owner": "c1", "asker_seen_at": stale, "asker_restart_until": value}
                self.assertIs(channel_liveness.seat_live(record, "asker"), False)
        valid = {"asker_owner": "c1", "asker_seen_at": stale, "asker_restart_until": time.time() + 60}
        self.assertIs(channel_liveness.seat_live(valid, "asker"), True)
        self.assertIsNone(channel_liveness.seat_live({**valid, "asker_owner": None}, "asker"))

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


class StateClosureTests(unittest.TestCase):
    def test_closed_channel_refuses_state_updates_without_writing(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host), tempfile.TemporaryDirectory(prefix="advisor-state-") as folder:
                root = Path(folder)
                env = {"BOOTGEAR_HOST": host}
                registered = run(root, "register", "--role", "listener", "--session", "s1", env=env)
                self.assertEqual(registered.returncode, 0, registered.stderr)
                closed = run(root, "close", "--channel", "0001", "--role", "listener", env=env)
                self.assertEqual(closed.returncode, 0, closed.stderr)
                before = channel_json(root).read_bytes()
                for role in ("listener", "asker"):
                    for value in ("waiting", "busy"):
                        with self.subTest(role=role, value=value):
                            result = run(root, "state", "--channel", "0001",
                                         "--role", role, "--value", value, env=env)
                            self.assertEqual(result.returncode, 2, result.stderr)
                            self.assertEqual(result.stdout, "")
                            payload = json.loads(result.stderr)
                            self.assertEqual(payload["category"], "channel_closed")
                            self.assertIn("end listening silently" if role == "listener" else "tell the user", payload["next"])
                            self.assertEqual(channel_json(root).read_bytes(), before)

    def test_open_channel_accepts_state_changes_and_repeated_close(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host), tempfile.TemporaryDirectory(prefix="advisor-state-") as folder:
                root = Path(folder)
                env = {"BOOTGEAR_HOST": host}
                registered = run(root, "register", "--role", "listener", "--session", "s1", env=env)
                self.assertEqual(registered.returncode, 0, registered.stderr)
                for value in ("busy", "waiting", "closed", "closed"):
                    result = run(root, "state", "--channel", "0001",
                                 "--role", "listener", "--value", value, env=env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["state"], value)
