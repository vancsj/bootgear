from __future__ import annotations

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
    GEAR,
    GEAR_PREFIX,
    age_seat,
    channel_json,
    channel_liveness,
    quoted_command,
    run,
    wait_until,
)


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
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-", "--json"],
            input="late request", capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        return json.loads(sent.stdout)["message_id"]

    def assert_refused(self, result: subprocess.CompletedProcess, category: str) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        payload = json.loads(result.stderr)
        self.assertEqual(payload["category"], category)
        self.assertEqual(shlex.split(quoted_command(payload["next"])),
                         [*GEAR_PREFIX, "--root", str(self.root), "receive",
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
        age_seat(self.root, "asker", channel_liveness.HEARTBEAT_TTL_SECONDS + 5)
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


class ReceiveMisuseWordingTests(unittest.TestCase):
    """The text an agent copies must not suggest a loop that re-receives without fetching."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="question", capture_output=True, text=True, check=False,
        )
        self.request_id = json.loads(sent.stdout)["message_id"]

    def test_fetch_next_does_not_suggest_a_bare_while_loop(self) -> None:
        result = run(self.root, "fetch", "--channel", "0001", "--message-id", self.request_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        next_text = json.loads(result.stdout)["next"]
        self.assertNotIn("while :;", next_text)
        self.assertNotIn("infinite", next_text)
        self.assertIn("receive", next_text)

    def test_receive_note_says_fetch_before_receiving_again(self) -> None:
        result = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        note = json.loads(result.stdout)["note"]
        self.assertIn("before calling receive again", note)


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



class ListenerLoopTests(unittest.TestCase):
    """Runs the listener loop from SKILL.md against a real mailbox, with short receive waits."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        skill = (CHANNEL.parent.parent / "SKILL.md").read_text()
        loop = skill[skill.index("CHANNEL=<channel>\n"):skill.index("done\n") + len("done\n")]
        self.loop_template = (loop.replace("<mine>", "listener").replace("<peer>", "asker")
                              .replace("<message_id>", "none").replace("--timeout 300", "--timeout 0.1"))

    def start_loop(self, gear: Path = GEAR) -> subprocess.Popen[str]:
        loop = (self.loop_template.replace("<gear>", shlex.quote(str(gear))).replace("<host>", "claude")
                .replace("<channel>", "0001"))
        env = {name: value for name, value in os.environ.items() if name != "CHANNEL"}
        env["BOOTGEAR_ADVISOR_DIR"] = str(self.root)
        process = subprocess.Popen(["bash", "-c", loop], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=env, start_new_session=True)

        def stop_loop() -> None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.wait(timeout=5)
            process.communicate()

        self.addCleanup(stop_loop)
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
            "#!/usr/bin/env python3\nimport os, subprocess, sys\n"
            f"real, marker = {str(GEAR)!r}, {str(marker)!r}\n"
            "if 'close' in sys.argv[1:] and not os.path.exists(marker):\n"
            "    open(marker, 'w').close()\n"
            "    subprocess.run([real, '--host', 'claude', 'advisor', 'channel', 'register',\n"
            "                    '--channel', '0001', '--role', 'asker',\n"
            "                    '--session', 'c1'], check=True, capture_output=True)\n"
            "os.execv(real, [real, *sys.argv[1:]])\n")
        wrapper.chmod(0o755)
        process = self.start_loop(wrapper)
        self.assertTrue(wait_until(marker.exists, timeout=10))
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
