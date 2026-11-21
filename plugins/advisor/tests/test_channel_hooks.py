from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from channel_test_support import (
    CHANNEL,
    age_seat,
    channel_json,
    channel_liveness,
    run,
    set_fields,
)


class HookStampChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def test_receive_still_says_restarting_when_the_peer_has_only_a_hook_stamp(self) -> None:
        age_seat(self.root, "asker", 600)
        set_fields(self.root, asker_restart_until=time.time() + 100, asker_hook_seen_at=time.time())
        received = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        output = json.loads(received.stdout)
        self.assertIs(output["peer_live"], True)
        self.assertIn("asker is restarting its heartbeat", output["note"])

    def test_send_accepts_a_recipient_live_by_its_hook_stamp(self) -> None:
        age_seat(self.root, "listener", 600)
        set_fields(self.root, listener_hook_seen_at=time.time())
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="question", capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)


class HookTouchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def record(self) -> dict[str, object]:
        return json.loads(channel_json(self.root).read_text())

    def touch(self, now: float | None = None) -> list[tuple[str, str]]:
        result = channel_liveness.hook_touch(self.root, "s1", time.time() if now is None else now)
        return [(str(record["channel"]), role) for record, role in result]

    def test_stamps_the_hook_field_and_leaves_the_heartbeat_fields(self) -> None:
        set_fields(self.root, listener_restart_until=time.time() + 100)
        before = self.record()
        now = time.time()
        self.assertEqual(self.touch(now), [])
        after = self.record()
        self.assertEqual(after["listener_hook_seen_at"], now)
        for key in ("listener_seen_at", "updated_at", "listener_restart_until"):
            self.assertEqual(after[key], before[key], key)
        self.assertNotIn("listener_hook_nudged_at", after)

    def test_stamp_only_neither_returns_nor_marks_the_reminder(self) -> None:
        age_seat(self.root, "listener", 600)
        now = time.time()
        result = channel_liveness.hook_touch(self.root, "s1", now, remind=False)
        self.assertEqual(result, [])
        after = self.record()
        self.assertEqual(after["listener_hook_seen_at"], now)
        self.assertNotIn("listener_hook_nudged_at", after)

    def test_stopped_heartbeat_is_returned_and_marks_the_reminder(self) -> None:
        age_seat(self.root, "listener", 600)
        now = time.time()
        self.assertEqual(self.touch(now), [("0001", "listener")])
        self.assertEqual(self.record()["listener_hook_nudged_at"], now)

    def test_reminder_waits_60_seconds(self) -> None:
        age_seat(self.root, "listener", 600)
        now = time.time()
        set_fields(self.root, listener_hook_nudged_at=now - 59)
        self.assertEqual(self.touch(now), [])
        self.assertEqual(self.record()["listener_hook_nudged_at"], now - 59)
        set_fields(self.root, listener_hook_nudged_at=now - 60)
        self.assertEqual(self.touch(now), [("0001", "listener")])
        self.assertEqual(self.record()["listener_hook_nudged_at"], now)

    def test_invalid_reminder_stamp_counts_as_absent(self) -> None:
        age_seat(self.root, "listener", 600)
        set_fields(self.root, listener_hook_nudged_at="x")
        self.assertEqual(self.touch(), [("0001", "listener")])

    def test_recent_hook_stamp_skips_the_write(self) -> None:
        now = time.time()
        set_fields(self.root, listener_hook_seen_at=now - 1)
        before = channel_json(self.root).read_bytes()
        self.assertEqual(self.touch(now), [])
        self.assertEqual(channel_json(self.root).read_bytes(), before)
        set_fields(self.root, listener_hook_seen_at=now - channel_liveness.HEARTBEAT_INTERVAL_SECONDS)
        self.touch(now)
        self.assertEqual(self.record()["listener_hook_seen_at"], now)

    def test_recent_hook_stamp_still_writes_a_due_reminder(self) -> None:
        age_seat(self.root, "listener", 600)
        now = time.time()
        set_fields(self.root, listener_hook_seen_at=now - 1)
        self.assertEqual(self.touch(now), [("0001", "listener")])

    def test_closed_channel_is_not_stamped(self) -> None:
        run(self.root, "close", "--channel", "0001", "--role", "asker")
        self.assertEqual(self.touch(), [])
        self.assertNotIn("listener_hook_seen_at", self.record())

    def assert_skipped_under_lock(self, **change: object) -> None:
        stale = self.record()
        set_fields(self.root, **change)
        age_seat(self.root, "listener", 600)
        with mock.patch.object(channel_liveness, "owned_channels", return_value=[(stale, "listener")]):
            self.assertEqual(self.touch(), [])
        self.assertNotIn("listener_hook_seen_at", self.record())

    def test_channel_closed_after_the_scan_is_not_stamped(self) -> None:
        self.assert_skipped_under_lock(state="closed")

    def test_seat_taken_after_the_scan_is_not_stamped(self) -> None:
        self.assert_skipped_under_lock(listener_owner="s2")

    def test_no_channel_returns_nothing(self) -> None:
        self.assertEqual(channel_liveness.hook_touch(self.root, "nobody", time.time()), [])


class HookStampCommandTests(unittest.TestCase):
    """Commands that read liveness count a seat held only by its hook stamp as live."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def hook_only(self, role: str) -> None:
        age_seat(self.root, role, 600)
        set_fields(self.root, **{f"{role}_hook_seen_at": time.time()})

    def test_status_reports_the_hook_only_seat_alive(self) -> None:
        self.hook_only("listener")
        output = json.loads(run(self.root, "status", "--channel", "0001").stdout)
        self.assertIs(output["listener_alive"], True)

    def test_list_live_for_finds_a_hook_only_listener(self) -> None:
        self.hook_only("listener")
        found = json.loads(run(self.root, "list", "--live-for", "asker", "--session", "c1").stdout)["channels"]
        self.assertEqual([c["channel"] for c in found], ["0001"])

    def test_conditional_close_refuses_while_the_peer_has_only_a_hook_stamp(self) -> None:
        self.hook_only("asker")
        result = run(self.root, "close", "--role", "listener", "--channel", "0001", "--if-peer-stale", timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["category"], "peer_live")

    def test_receive_still_reminds_the_owner_whose_heartbeat_stopped(self) -> None:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-", "--json"],
            input="question", capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.hook_only("listener")
        received = json.loads(run(self.root, "receive", "--channel", "0001", "--for", "listener",
                                  "--timeout", "0").stdout)
        self.assertIn("then: your heartbeat is not running", received["next"])
        self.assertIn("heartbeat --channel 0001 --role listener --session s1", received["next"])
