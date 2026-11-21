from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from channel_test_support import (
    CHANNEL,
    GEAR_PREFIX,
    age_seat,
    age_updated_at,
    channel_json,
    channel_liveness,
    channel_output,
    channel_seats,
    quoted_command,
    root_variants,
    run,
    run_in,
    write_channel,
)


class StatusReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def test_status_on_missing_channel_leaves_no_directory(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        missing = run(self.root, "status", "--channel", "7777")
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertEqual(json.loads(missing.stderr)["error"], "channel does not exist: 7777")
        self.assertFalse((self.root / "channels" / "7777").exists())

    def test_status_on_missing_channel_does_not_move_next_number(self) -> None:
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "status", "--channel", "7777")
        run(self.root, "register", "--role", "asker", "--session", "c1")
        numbers = sorted(p.name for p in (self.root / "channels").iterdir())
        self.assertEqual(numbers, ["0001", "0002"])


class ListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        self.script = [*GEAR_PREFIX, "--root", str(self.root)]

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


class OwnedChannelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def owned(self, session: str = "s1") -> list[tuple[str, str]]:
        return [(str(record["channel"]), role) for record, role in channel_liveness.owned_channels(self.root, session)]

    def test_open_owned_listener_seat_is_returned(self) -> None:
        write_channel(self.root, "0001", listener_owner="s1")
        self.assertEqual(self.owned(), [("0001", "listener")])

    def test_closed_channel_is_skipped(self) -> None:
        write_channel(self.root, "0001", listener_owner="s1", state="closed")
        self.assertEqual(self.owned(), [])

    def test_channel_49_hours_old_is_skipped(self) -> None:
        old = time.time() - 49 * 3600
        write_channel(self.root, "0001", listener_owner="s1", created_at=old, updated_at=old)
        self.assertEqual(self.owned(), [])

    def test_unreadable_records_are_skipped(self) -> None:
        write_channel(self.root, "0001", listener_owner="s1", updated_at=time.time() - 10)
        (write_channel(self.root, "0002") / "channel.json").write_text("{not json")
        (write_channel(self.root, "0003") / "channel.json").write_text("[1, 2]")
        (write_channel(self.root, "0004") / "channel.json").write_bytes(b"\xff\xfe")
        (self.root / "channels" / "0005").mkdir()
        (self.root / "channels" / "notes").mkdir()
        self.assertEqual(self.owned(), [("0001", "listener")])

    def test_missing_root_returns_nothing(self) -> None:
        self.assertEqual(channel_liveness.owned_channels(self.root / "absent", "s1"), [])

    def test_seat_of_another_session_is_skipped(self) -> None:
        write_channel(self.root, "0001", listener_owner="s2", asker_owner="c1")
        self.assertEqual(self.owned(), [])

    def test_each_session_gets_its_own_seat(self) -> None:
        write_channel(self.root, "0001", listener_owner="s1", asker_owner="c1")
        self.assertEqual(self.owned("s1"), [("0001", "listener")])
        self.assertEqual(self.owned("c1"), [("0001", "asker")])

    def test_one_session_on_both_seats_gets_one_entry(self) -> None:
        write_channel(self.root, "0001", listener_owner="s1", asker_owner="s1")
        self.assertEqual(len(self.owned()), 1)

    def test_two_qualifying_channels_return_only_the_newer(self) -> None:
        now = time.time()
        write_channel(self.root, "0001", asker_owner="s1", updated_at=now - 5)
        write_channel(self.root, "0002", listener_owner="s1", updated_at=now - 60)
        self.assertEqual(self.owned(), [("0001", "asker")])

    def test_tied_updated_at_returns_the_higher_channel(self) -> None:
        now = time.time()
        write_channel(self.root, "0002", listener_owner="s1", updated_at=now)
        write_channel(self.root, "0010", listener_owner="s1", updated_at=now)
        self.assertEqual(self.owned(), [("0010", "listener")])


class ChannelStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def send(self, sender: str, recipient: str, kind: str = "request", *extra: str) -> str:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", sender, "--to", recipient, "--kind", kind, *extra, "--body-file", "-", "--json"],
            input="body", capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        return json.loads(sent.stdout)["message_id"]

    def fetch(self, message_id: str) -> None:
        self.assertEqual(run(self.root, "fetch", "--channel", "0001", "--message-id", message_id).returncode, 0)

    def status(self, role: str = "listener") -> dict[str, object]:
        record = json.loads(channel_json(self.root).read_text())
        return channel_seats.channel_status(self.root, record, role)

    def test_fields_for_an_idle_seat(self) -> None:
        status = self.status()
        self.assertEqual(list(status), ["channel", "role", "state", "peer_live", "heartbeat", "unread",
                                        "last_read", "owed", "next"])
        self.assertEqual((status["channel"], status["role"], status["state"]), ("0001", "listener", "waiting"))
        self.assertIs(status["peer_live"], True)
        self.assertIs(status["heartbeat"], True)
        self.assertEqual(status["unread"], 0)
        self.assertIsNone(status["last_read"])
        self.assertIsNone(status["owed"])
        self.assertTrue(str(status["next"]).startswith(f"{shlex.join(GEAR_PREFIX)} "))
        self.assertIn("receive --channel 0001 --for listener --timeout 300", str(status["next"]))

    def test_unread_counts_messages_to_the_role_only(self) -> None:
        self.send("asker", "listener")
        self.send("listener", "asker")
        self.assertEqual(self.status()["unread"], 1)
        self.assertEqual(self.status("asker")["unread"], 1)

    def test_last_read_is_the_newest_read_message_by_created_at(self) -> None:
        first = self.send("asker", "listener")
        second = self.send("asker", "listener")
        self.fetch(second)
        self.fetch(first)
        self.assertEqual(self.status()["last_read"], second)

    def test_owed_names_a_read_request_without_a_response(self) -> None:
        request = self.send("asker", "listener")
        self.assertIsNone(self.status()["owed"])
        self.fetch(request)
        status = self.status()
        self.assertEqual(status["owed"], request)
        self.assertEqual(status["next"], f"answer request {request}: fetch it again and send the response")

    def test_owed_clears_once_the_role_responds(self) -> None:
        request = self.send("asker", "listener")
        self.fetch(request)
        self.send("listener", "asker", "response", "--parent-id", request)
        status = self.status()
        self.assertIsNone(status["owed"])
        self.assertIn("receive --channel 0001 --for listener --timeout 300", str(status["next"]))

    def test_stopped_heartbeat_puts_the_restart_line_first(self) -> None:
        age_seat(self.root, "listener", 600)
        status = self.status()
        self.assertIs(status["heartbeat"], False)
        first, second = str(status["next"]).split("\n")
        self.assertIn("heartbeat --channel 0001 --role listener --session s1", first)
        self.assertTrue(second.startswith("then: "))
        self.assertIn("receive --channel 0001 --for listener --timeout 300", second)

    def test_unreadable_message_files_are_skipped(self) -> None:
        self.send("asker", "listener")
        (channel_json(self.root).parent / "messages" / f"{uuid.uuid4().hex}.json").write_text("{bad")
        self.assertEqual(self.status()["unread"], 1)


class WhoamiTests(unittest.TestCase):
    KEYS = ["channel", "role", "state", "peer_live", "heartbeat", "unread", "last_read", "owed", "next"]

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")

    def whoami(self, session: str = "s1", output: str = "--json") -> subprocess.CompletedProcess:
        return run(self.root, "whoami", "--session", session, output=output, timeout=5)

    def test_prose_prints_every_field_in_order_with_null_as_none(self) -> None:
        result = self.whoami(output="--prose")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual([line.split(": ", 1)[0] for line in lines], self.KEYS)
        self.assertEqual(lines[3], "peer_live: none")
        self.assertEqual(lines[6], "last_read: none")
        self.assertEqual(lines[7], "owed: none")
        self.assertIn("receive --channel 0001 --for listener --timeout 300", lines[-1])

    def test_prose_next_is_last_and_spans_lines_when_the_heartbeat_stopped(self) -> None:
        age_seat(self.root, "listener", 600)
        lines = self.whoami(output="--prose").stdout.splitlines()
        self.assertEqual(lines[4], "heartbeat: false")
        self.assertTrue(lines[-2].startswith("next: "))
        self.assertIn("heartbeat --channel 0001", lines[-2])
        self.assertTrue(lines[-1].startswith("then: "))

    def test_json_lists_the_channel_status(self) -> None:
        result = self.whoami()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(list(payload), ["channels"])
        self.assertEqual(list(payload["channels"][0]), self.KEYS)
        self.assertEqual(payload["channels"][0]["role"], "listener")

    def test_no_channel_exits_zero_with_a_note(self) -> None:
        result = self.whoami("nobody")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"channels": [], "note": "no open channel for this session"})
        prose = self.whoami("nobody", output="--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertIn("note: no open channel for this session", prose.stdout)

    def test_render_status_separates_channels_with_a_blank_line(self) -> None:
        status = {key: None for key in self.KEYS}
        text = channel_seats.render_status([{**status, "channel": "0001"}, {**status, "channel": "0002"}])
        blocks = text.split("\n\n")
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[1].startswith("channel: 0002"))

    def test_list_item_keys_are_unchanged(self) -> None:
        self.assertEqual(channel_output.ITEM_KEYS, {
            "message_id": ("message_id", "sender", "kind", "parent_id", "preview", "answered"),
            "channel": ("channel", "state", "listener_owner", "asker_owner"),
        })

    def test_example_runs(self) -> None:
        example = shlex.split(channel_output.EXAMPLES["whoami"])
        result = run(self.root, *example, timeout=5, env={"CODEX_SESSION_ID": "s1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c["channel"] for c in json.loads(result.stdout)["channels"]], ["0001"])

    def test_session_examples_print_no_session_flag(self) -> None:
        for command in ("register", "heartbeat", "list", "whoami"):
            with self.subTest(command=command):
                self.assertNotIn("--session", channel_output.EXAMPLES[command])
                self.assertNotIn("$", channel_output.EXAMPLES[command])


class OwnedChannelsWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))

    def owned(self) -> list[str]:
        return [str(record["channel"]) for record, _ in channel_liveness.owned_channels(self.root, "s1")]

    def test_channel_47_hours_old_qualifies(self) -> None:
        old = time.time() - 47 * 3600
        write_channel(self.root, "0001", listener_owner="s1", created_at=old, updated_at=old)
        self.assertEqual(self.owned(), ["0001"])

    def test_old_creation_with_a_recent_update_qualifies(self) -> None:
        write_channel(self.root, "0001", listener_owner="s1", created_at=time.time() - 72 * 3600)
        self.assertEqual(self.owned(), ["0001"])

    def test_recent_creation_with_an_old_update_qualifies(self) -> None:
        write_channel(self.root, "0001", listener_owner="s1", updated_at=time.time() - 72 * 3600)
        self.assertEqual(self.owned(), ["0001"])

    def test_a_newer_closed_channel_does_not_hide_the_open_one(self) -> None:
        now = time.time()
        write_channel(self.root, "0001", listener_owner="s1", updated_at=now - 60)
        write_channel(self.root, "0002", listener_owner="s1", updated_at=now, state="closed")
        self.assertEqual(self.owned(), ["0001"])


class ChannelStatusOwedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="advisor-test-"))
        run(self.root, "register", "--role", "listener", "--session", "s1")
        run(self.root, "register", "--channel", "0001", "--role", "asker", "--session", "c1")

    def send(self, sender: str, recipient: str, kind: str = "request", *extra: str) -> str:
        sent = subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), "send", "--channel", "0001",
             "--from", sender, "--to", recipient, "--kind", kind, *extra, "--body-file", "-", "--json"],
            input="body", capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        message_id = json.loads(sent.stdout)["message_id"]
        self.assertEqual(run(self.root, "fetch", "--channel", "0001", "--message-id", message_id).returncode, 0)
        return message_id

    def status(self, role: str = "listener") -> dict[str, object]:
        record = json.loads(channel_json(self.root).read_text())
        return channel_seats.channel_status(self.root, record, role)

    def test_owed_names_the_newest_of_several_unanswered_requests(self) -> None:
        self.send("asker", "listener")
        second = self.send("asker", "listener")
        self.assertEqual(self.status()["owed"], second)

    def test_a_response_to_another_request_leaves_the_owed_one(self) -> None:
        first = self.send("asker", "listener")
        second = self.send("asker", "listener")
        self.send("listener", "asker", "response", "--parent-id", second)
        self.assertEqual(self.status()["owed"], first)

    def test_a_response_from_the_peer_does_not_answer_the_request(self) -> None:
        request = self.send("asker", "listener")
        self.send("listener", "asker", "response", "--parent-id", request)
        self.assertIsNone(self.status()["owed"])
        self.assertIsNone(self.status("asker")["owed"])

    def test_a_read_response_is_never_owed(self) -> None:
        request = self.send("asker", "listener")
        response = self.send("listener", "asker", "response", "--parent-id", request)
        status = self.status("asker")
        self.assertIsNone(status["owed"])
        self.assertEqual(status["last_read"], response)
        self.assertEqual(status["unread"], 0)

    def test_owed_applies_to_the_asker_seat_too(self) -> None:
        request = self.send("listener", "asker")
        status = self.status("asker")
        self.assertEqual(status["owed"], request)
        self.assertEqual(status["next"], f"answer request {request}: fetch it again and send the response")

    def test_peer_live_is_false_once_the_peer_heartbeat_stopped(self) -> None:
        age_seat(self.root, "asker", 600)
        self.assertIs(self.status()["peer_live"], False)
