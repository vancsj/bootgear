from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from channel_test_support import CHANNEL, age_seat, run, seen_at, wait_until


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
        request = json.loads(self.send("asker", "listener").stdout)["message_id"]
        age_seat(self.root, "asker", 600)
        refused = self.send("listener", "asker", "response", "--parent-id", request)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(json.loads(refused.stderr)["category"], "peer_not_live")
        self.assertEqual(len(self.messages()), 1)

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
                output = json.loads(result.stdout)
                self.assertIn(f"--for {sender} --timeout 300", output["next"])
                self.assertIn("before running", output["next"])
                self.assertNotIn("infinite background polling", output["next"])
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


class ParentIdValidationTests(unittest.TestCase):
    """`send --parent-id` must name a request the responder was sent on this channel."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")
        self.request = self.send("asker", "listener", "request")

    def send(self, sender: str, recipient: str, kind: str, *extra: str) -> str:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", sender, "--to", recipient, "--kind", kind, *extra, "--body-file", "-"],
            input="hello", capture_output=True, text=True, check=False,
        )
        return sent

    def respond(self, parent_id: str) -> subprocess.CompletedProcess:
        return self.send("listener", "asker", "response", "--parent-id", parent_id)

    def message_count(self) -> int:
        return len(list((self.root / "channels" / "0001" / "messages").glob("*.json")))

    def test_valid_parent_id_is_accepted(self) -> None:
        request_id = json.loads(self.request.stdout)["message_id"]
        result = self.respond(request_id)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_parent_id_is_refused_before_anything_is_written(self) -> None:
        before = self.message_count()
        for bad in ("abc", "078da7b2-4e46-4f4d-88aa-f110f2c006", "A" * 32, "g" * 32, ""):
            with self.subTest(parent_id=bad):
                result = self.respond(bad)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stderr)["category"], "invalid_args")
                self.assertEqual(self.message_count(), before)

    def test_well_formed_parent_id_naming_no_message_is_refused(self) -> None:
        before = self.message_count()
        result = self.respond(uuid.uuid4().hex)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["category"], "unknown_parent_id")
        self.assertEqual(self.message_count(), before)

    def test_parent_id_naming_a_message_the_responder_did_not_receive_is_refused(self) -> None:
        # A request the listener sent to the asker is not a request the listener can answer.
        other = self.send("listener", "asker", "request")
        other_id = json.loads(other.stdout)["message_id"]
        before = self.message_count()
        result = self.respond(other_id)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["category"], "unknown_parent_id")
        self.assertEqual(self.message_count(), before)

    def test_parent_id_from_another_channel_is_refused(self) -> None:
        listener = run(self.root, "register", "--role", "listener", "--session", "s2")
        channel = json.loads(listener.stdout)["channel"]
        run(self.root, "register", "--channel", channel, "--role", "asker", "--session", "c2")
        result = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0002",
             "--from", "asker", "--to", "listener", "--kind", "request", "--body-file", "-"],
            input="other", capture_output=True, text=True, check=False,
        )
        other_id = json.loads(result.stdout)["message_id"]
        refused = self.respond(other_id)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(json.loads(refused.stderr)["category"], "unknown_parent_id")


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


class AnsweredRequestTests(unittest.TestCase):
    """A listener's `receive` marks each request it got as answered once its own response exists."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def send(self, sender: str, recipient: str, kind: str, *extra: str) -> str:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", sender, "--to", recipient, "--kind", kind, *extra, "--body-file", "-"],
            input="hello", capture_output=True, text=True, check=False,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)
        return json.loads(sent.stdout)["message_id"]

    def listed(self, message_id: str) -> dict:
        received = run(self.root, "receive", "--channel", "0001", "--for", "listener", "--timeout", "0")
        self.assertIn(received.returncode, (0, 1), received.stderr)
        return next(m for m in json.loads(received.stdout)["messages"] if m["message_id"] == message_id)

    def test_request_without_a_response_is_not_answered(self) -> None:
        request_id = self.send("asker", "listener", "request")
        self.assertIs(self.listed(request_id)["answered"], False)

    def test_request_with_a_response_is_answered(self) -> None:
        request_id = self.send("asker", "listener", "request")
        self.send("listener", "asker", "response", "--parent-id", request_id)
        self.assertIs(self.listed(request_id)["answered"], True)
