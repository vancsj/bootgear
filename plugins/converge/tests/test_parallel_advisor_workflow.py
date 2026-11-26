"""Exercise the public Converge and Advisor host routes together (R006)."""

from __future__ import annotations

import json
import shlex
import subprocess
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from conftest import BATCH_1, DISABLED, HOST, MAIN, Converge, gear_args

PEER_HOST = "claude" if HOST == "codex" else "codex"


def _advisor(cv: Converge, mailbox: Path, host: str, session: str,
             *argv: str, code: int = 0) -> dict[str, Any]:
    result = subprocess.run(
        [*gear_args(host)[:-2], "advisor", "channel", *argv, "--json"],
        cwd=cv.project,
        env={**cv.env, "BOOTGEAR_ADVISOR_DIR": str(mailbox), "BOOTGEAR_SESSION_ID": session},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == code, result.stderr
    return json.loads(result.stdout if code in (0, 1) else result.stderr)


def test_two_invited_advisors_each_receive_one_assignment(cv: Converge) -> None:
    listener_host = PEER_HOST
    group = "review-group"
    mailbox = cv.root / "mailbox"
    advisor = partial(_advisor, cv, mailbox)
    env = {**cv.env, "BOOTGEAR_ADVISOR_DIR": str(mailbox)}
    receiving_gear = gear_args(listener_host)[:-2]

    registration = shlex.join([*receiving_gear, "advisor", "channel", "register", "--role", "listener"])
    launcher_file = cv.root / "launch-listener"
    launcher_file.write_text(
        f'#!/bin/sh\nexec {registration} --session "listener-$2" '
        '--group "$1" --worker "$2" --invitation "$3"\n'
    )
    launcher_file.chmod(0o700)
    launcher = shlex.join([str(launcher_file), "{group}", "{worker}", "{invitation}"])
    settlement = cv.root / "approved.yaml"
    settlement.write_text(json.dumps({
        "converge_seats": {"r2": "advisor"},
        "advisor_roles": {"roles": ["refuter"], "brief": "check the assigned claims",
                          "startup": "deferred", "launcher": launcher},
    }))
    config = {"parallelism": {"r2": 2},
              "steps": {"gap_hunt": True, "escalate": True, "cut": "none"},
              "angles": {"disable": DISABLED}}
    cv.init("s1", "correctness", MAIN, "--review-group", group, "--settlement", str(settlement), config=config)
    cv.file(claim="first claim")
    cv.file(claim="second claim")
    for angle in ("changed-contract", "failure-path"):
        cv.ok("angle-na", "s1", "--as", "finder", "--phase", "find", "--lens", "correctness",
              "--angle", angle, "--reason", "coverage complete")
    channels = []
    main_work = ("work", "s1", "--as", MAIN, "--role-host", HOST, "--json")
    reply_body = cv.root / "reply.txt"
    reply_body.write_text("fresh-eye recorded\n")
    for driver, claim in zip(cv.status()["drivers"], ("F001", "F002"), strict=True):
        worker = driver["worker"]
        listener = "listener-" + worker
        key = ("--group", group, "--worker", worker)
        reservation = advisor(HOST, "asker", "reserve", *key)
        channel = reservation["channel"]
        channels.append(channel)
        advisor(HOST, "asker", "launch", *key, "--template", launcher)
        advisor(listener_host, listener, "heartbeat", "--channel", channel, "--role", "listener",
                "--interval", "0.02", "--max-age", "0.1")
        exact = advisor(HOST, "asker", "wait-listener", *key, "--timeout", "0")
        assert exact["channel"] == channel and exact["listener_host"] == listener_host

        worker_work = [*shlex.split(driver[f"work_{listener_host}"]), "--json"]
        package = json.loads(subprocess.run(worker_work, cwd=cv.project, env=env, text=True,
                                            capture_output=True, check=True).stdout)
        assert package["assignment"]["fresh_eye"] == [claim]
        assert package["role"] == worker
        body = cv.root / f"{worker}.txt"
        body.write_text(f"Check the assigned {claim} in your fresh-eye batch.\n")
        request = advisor(HOST, "asker", "send", "--channel", channel, "--from", "asker",
                          "--to", "listener", "--kind", "request", "--body-file", str(body))
        request_id = request["message_id"]
        advisor(listener_host, listener, "fetch", "--channel", channel, "--message-id", request_id)

        if worker == "r2":
            assert package["phase"] == "gap-hunt"
            cv("gap-hunt-done", "s1", "--dir", str(cv.dir), "--as", worker,
               env={"BOOTGEAR_HOST": listener_host})
            waited = json.loads(cv.ok(*main_work, "--wait", "2", "--after-seq",
                                      str(package["source_seq"]), "--active-worker", worker).stdout)
            assert (waited["wait_result"], waited["phase"]) == ("dispatch", "escalate")
            assert {row["agent"] for row in waited["items"]} == {"finder"}
            for claim_id in ("F001", "F002"):
                cv.ok("escalate", "s1", "--as", "finder", "--claim", claim_id)
            fixed = json.loads(cv.ok(*main_work, "--wait", "2", "--after-seq",
                                     str(waited["source_seq"]), "--active-worker", worker).stdout)
            assert (fixed["wait_result"], fixed["phase"]) == ("dispatch", "attack")
            assert {row["agent"] for row in fixed["items"]} == {"r1"}
            for claim_id in ("F001", "F002"):
                for angle in BATCH_1:
                    cv.check_cli(claim_id, angle)
            package = json.loads(subprocess.run(worker_work, cwd=cv.project, env=env, text=True,
                                                capture_output=True, check=True).stdout)
            assert package["items"][0]["batch"] == "fresh-eye"

        duplicate = advisor(HOST, "asker", "send", "--channel", channel, "--from", "asker",
                            "--to", "listener", "--kind", "request", "--body-file", str(body), code=2)
        assert duplicate["category"] == "request_outstanding"

        clean = next(entry["input"] for entry in package["actions"] if entry["input"]["action"] == "clean")
        clean["checks"] = [{"angle": "invitation delivery", "tell": "worker matches the reservation",
                            "searches": "read reserved channel", "evidence": "exact worker and host",
                            "positive_control": "listener owns the channel"}]
        clean["last"] = True
        subprocess.run([*gear_args(listener_host), "act", "s1", "--dir", str(cv.dir),
                        "--as", worker, "--input", "-"], cwd=cv.project, env=env, text=True,
                       input=json.dumps(clean), capture_output=True, check=True)
        response = advisor(listener_host, listener, "send", "--channel", channel, "--from", "listener",
                           "--to", "asker", "--kind", "response", "--parent-id", request_id,
                           "--body-file", str(reply_body))
        waited = cv("advisor-wait", "s1", "--dir", str(cv.dir), "--as", worker, "--channel", channel,
                    "--request", request_id, "--timeout", "0", "--json",
                    env={"BOOTGEAR_ADVISOR_DIR": str(mailbox), "BOOTGEAR_SESSION_ID": "asker"})
        assert json.loads(waited.stdout)["message_id"] == response["message_id"]
        advisor(HOST, "asker", "fetch", "--channel", channel, "--message-id", response["message_id"])

    assert len(set(channels)) == 2
    cv.init("next-visit", "correctness", MAIN, "--continue-from", "s1",
            "--settlement", str(settlement), config=config)
    assert cv.status("next-visit")["review_group"] == group
    saved = advisor(HOST, "asker", "reservations", "--group", group)
    assert [record["channel"] for record in saved["channels"]] == channels
    for channel in channels:
        closed = advisor(HOST, "asker", "close", "--channel", channel, "--role", "asker")
        assert closed["state"] == "closed"
    assert cv.ok("cutoff", "s1").returncode == 0


@pytest.mark.parametrize("spare_listener", [False, True], ids=["alone", "with-spare"])
def test_early_manual_advisor_waits_for_the_invited_worker(cv: Converge, spare_listener: bool) -> None:
    settlement = cv.root / "early.yaml"
    settlement.write_text(json.dumps({
        "converge_seats": {"r2": "advisor"},
        "advisor_roles": {"roles": ["refuter"], "brief": "check the assigned claims", "startup": "early"},
    }))
    cv.init("s1", "correctness", MAIN, "--settlement", str(settlement), config={"parallelism": {"r2": 2}})
    status = cv.status()
    assert status["claims"] == []
    driver = next(driver for driver in status["drivers"] if driver["worker"] == "r2-2")
    key = ("--group", driver["group"], "--worker", driver["worker"])
    advisor = partial(_advisor, cv, cv.root / "early-mailbox")
    spare = advisor(PEER_HOST, "spare", "register", "--role", "listener") if spare_listener else None

    reserved = advisor(HOST, "asker", "reserve", *key)
    channel = reserved["channel"]
    if spare is not None:
        assert channel != spare["channel"]
    waiting = advisor(HOST, "asker", "wait-listener", *key, "--timeout", "0", code=1)
    assert waiting["channel"] == channel and waiting["ready"] is False

    registered = advisor(PEER_HOST, "invited", "register", "--role", "listener", *key,
                         "--invitation", reserved["invitation"])
    assert registered["channel"] == channel
    advisor(PEER_HOST, "invited", "heartbeat", "--channel", channel, "--role", "listener",
            "--interval", "0.02", "--max-age", "0.1")

    ready = advisor(HOST, "asker", "wait-listener", *key, "--timeout", "0")
    assert ready["ready"] is True
    assert (ready["channel"], ready["listener_owner"], ready["listener_host"]) == (channel, "invited", PEER_HOST)
    closed = advisor(HOST, "asker", "close", "--channel", channel, "--role", "asker")
    assert closed["state"] == "closed"
