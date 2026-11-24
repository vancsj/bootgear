from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from channel_test_support import (
    CHANNEL,
    age_seat,
    channel_json,
    channel_liveness,
    channel_messages,
    channel_module,
    rewrite_record,
    run,
)


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
        self.assertIn("up to 12 waits of 300s", output["note"])
        self.assertIn(f"receive --channel {self.channel} --for asker --timeout 300", output["next"])
        return output

    def test_busy_listener_extends_the_wait(self) -> None:
        run(self.root, "state", "--channel", self.channel, "--role", "listener", "--value", "busy")
        result = self._receive()
        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertIs(output["peer_live"], True)
        self.assertIn("the listener is busy on this request", output["note"])
        self.assertIn("busy waits do not count toward the 12 quiet waits", output["note"])
        self.assertNotIn("up to 12 waits", output["note"])

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

    def test_fetch_reminds_caller_to_keep_receiving(self) -> None:
        message_id = self._send_to_asker()
        fetched = run(self.root, "fetch", "--channel", self.channel, "--message-id", message_id)
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        output = json.loads(fetched.stdout)
        self.assertIn(f"--for asker --timeout 300", output["next"])
        self.assertIn("before running", output["next"])
        self.assertNotIn("infinite background polling", output["next"])

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

    def _receive_with_poll_clock(self, channel: str, recipient: str,
                                 after_poll: Callable[[], None] | None = None, timeout: int = 5
                                 ) -> tuple[dict, float, int | str | None]:
        elapsed = 0.0

        def poll(seconds: float) -> None:
            nonlocal elapsed
            elapsed += seconds
            if after_poll is not None and elapsed == 1:
                after_poll()

        args = channel_module.build_parser().parse_args([
            "--root", str(self.root), "receive", "--channel", channel, "--for", recipient,
            "--timeout", str(timeout), "--poll", "1", "--json",
        ])
        clock = mock.Mock(wraps=time, monotonic=lambda: elapsed, sleep=poll)
        stdout = io.StringIO()
        with mock.patch.object(channel_messages, "time", clock), mock.patch("sys.stdout", stdout):
            try:
                channel_messages.receive(args)
            except SystemExit as exit_status:
                return json.loads(stdout.getvalue()), elapsed, exit_status.code
        return json.loads(stdout.getvalue()), elapsed, 0

    def test_receive_returns_on_the_poll_that_sees_a_stale_peer(self) -> None:
        def expire_listener() -> None:
            age_seat(self.root, "listener", 600, self.channel)

        output, elapsed, status = self._receive_with_poll_clock(self.channel, "asker", expire_listener)
        self.assertEqual(elapsed, 1)
        self.assertEqual(status, 1)
        self.assertEqual(output["new_since_call"], 0)
        self.assertIs(output["peer_live"], False)
        self.assertIn("peer heartbeat stale; tell the user instead of waiting again", output["note"])

    def test_receive_waits_through_restart_grace_and_before_peer_registration(self) -> None:
        age_seat(self.root, "listener", 600, self.channel)
        record_path = channel_json(self.root, self.channel)
        record = json.loads(record_path.read_text())
        record["listener_restart_until"] = time.time() + channel_liveness.RESTART_GRACE_SECONDS / 2
        rewrite_record(self.root, json.dumps(record), self.channel)
        registered = run(self.root, "register", "--role", "listener", "--session", "s2")
        unpaired = json.loads(registered.stdout)["channel"]

        for channel, recipient, peer_live in ((self.channel, "asker", True), (unpaired, "listener", None)):
            with self.subTest(peer_live=peer_live):
                output, elapsed, status = self._receive_with_poll_clock(channel, recipient)
                self.assertEqual(elapsed, 5)
                self.assertEqual(status, 1)
                self.assertIs(output["peer_live"], peer_live)
                guidance = "keep waiting" if peer_live else "a request can come at any time"
                self.assertIn(guidance, output["note"])

    def test_stale_peer_without_message_says_tell_the_user_and_omits_next(self) -> None:
        age_seat(self.root, "listener", 600, self.channel)
        result = self._receive()
        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertIs(output["peer_live"], False)
        self.assertIn("no new message for asker", output["note"])
        self.assertIn("peer heartbeat stale; tell the user instead of waiting again", output["note"])
        self.assertNotIn("up to 12 waits", output["note"])
        self.assertNotIn("next", output)

    def test_stale_peer_with_new_message_still_points_at_fetch(self) -> None:
        message_id = self._send_to_asker()
        age_seat(self.root, "listener", 600, self.channel)
        output, elapsed, status = self._receive_with_poll_clock(self.channel, "asker")
        self.assertEqual(elapsed, 0)
        self.assertEqual(status, 0)
        self.assertEqual(output["new_since_call"], 1)
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

    def test_listener_counts_full_rounds_even_with_a_stale_asker(self) -> None:
        age_seat(self.root, "asker", 600, self.channel)
        for count in range(1, 25):
            output, elapsed, status = self._receive_with_poll_clock(self.channel, "listener", timeout=300)
            self.assertEqual((elapsed, status), (300, 1))
            self.assertEqual(output["listener_idle_rounds"], count)
            self.assertIs(output["peer_live"], False)
            if count < 24:
                self.assertIn("--for listener --timeout 300", output["next"])
            else:
                self.assertIn("ask the user whether to keep listening", output["next"])
        probe, _, _ = self._receive_with_poll_clock(self.channel, "listener")
        self.assertEqual(probe["listener_idle_rounds"], 24)
        resumed, _, _ = self._receive_with_poll_clock(self.channel, "listener", timeout=300)
        self.assertEqual(resumed["listener_idle_rounds"], 1)

    def test_asker_message_resets_idle_rounds_even_after_fetch(self) -> None:
        output, _, _ = self._receive_with_poll_clock(self.channel, "listener", timeout=300)
        self.assertEqual(output["listener_idle_rounds"], 1)

        def send_and_fetch() -> None:
            body = self.root / "question.txt"
            body.write_text("new request")
            sent = run(self.root, "send", "--channel", self.channel, "--from", "asker", "--to", "listener",
                       "--kind", "request", "--body-file", str(body))
            self.assertEqual(sent.returncode, 0, sent.stderr)
            result = run(self.root, "fetch", "--channel", self.channel,
                         "--message-id", json.loads(sent.stdout)["message_id"])
            self.assertEqual(result.returncode, 0, result.stderr)

        output, _, _ = self._receive_with_poll_clock(self.channel, "listener", send_and_fetch, timeout=300)
        self.assertEqual(output["listener_idle_rounds"], 0)
