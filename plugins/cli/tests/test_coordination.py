from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from .gear_test_support import GEAR, REPO


@pytest.fixture(params=[("claude", "codex"), ("codex", "claude")])
def coordination(request, tmp_path):
    main_host, advisor_host = request.param
    root = tmp_path / "coordination"

    def call(session, *argv, participant=None, error=None, route=("cli", "coordination"), body="", bound=True):
        host = advisor_host if session.startswith("advisor") else main_host
        env = dict(os.environ, BOOTGEAR_COORDINATION_DIR=str(root))
        for name in ("BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID",
                     "BOOTGEAR_COORDINATION_PARTICIPANT"):
            env.pop(name, None)
        env["CODEX_SESSION_ID" if host == "codex" else "CLAUDE_CODE_SESSION_ID"] = session
        if bound:
            env["BOOTGEAR_COORDINATION_PARTICIPANT"] = participant or ":host"
        result = subprocess.run([str(GEAR), "--root", str(REPO), "--host", host,
                                 *route, *argv, "--json"],
                                env=env, input=body, text=True, capture_output=True, timeout=15, check=False)
        if error:
            assert result.returncode != 0, result.stdout
            detail = result.stderr or result.stdout
            assert error in detail
            return detail
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    return root, call, main_host


def test_requester_first_delivers_through_default_store(coordination):
    root, call, _ = coordination
    call("advisor-a", "poll", error="no coordination store")
    assert not root.exists()
    call("main-a", "init")
    invitation = call("main-a", "reserve", "r2", "refuter")["invitation"]
    request = call("main-a", "send", "r2", "Refute this claim")
    call("advisor-a", "join", invitation)
    assert (root / "advisor-a").is_symlink()
    assert (root / "advisor-a").resolve() == root / "main-a"
    item = call("advisor-a", "poll")
    assert item["kind"] == "assignment"
    assert item["assignment_id"] == request["assignment_id"]
    assert item["message"] == "Refute this claim"
    assert call("advisor-a", "poll") == item
    call("advisor-a", "poll", "--ack", item["delivery_id"])
    done = call("advisor-a", "complete", item["assignment_id"], "No refutation")
    assert done["status"] == "complete"
    assert call("advisor-a", "complete", item["assignment_id"], "No refutation") == done
    for _ in range(25):
        assert call("advisor-a", "poll")["status"] == "idle"
    result = call("main-a", "poll")
    assert result["kind"] == "result"
    assert result["message"] == "No refutation"
    assert result["assignment_id"] == item["assignment_id"]
    assert call("main-a", "send", "r2", "Refute this claim")["assignment_id"] == item["assignment_id"]


def test_native_participant_and_blocked_report(coordination):
    _, call, _ = coordination
    call("main-a", "init")
    invitation = call("main-a", "reserve", "finder-1", "finder")["invitation"]
    call("main-a", "join", invitation, participant="native-agent-a")
    request = call("main-a", "send", "finder-1", "Find relevant claims")
    args = {"participant": "native-agent-a"}
    item = call("main-a", "poll", **args)
    assert item["executor_seat"] == "finder-1"
    assert item["receiver_seat"] == "main"
    call("main-a", "blocked", "Evidence is unavailable", **args)
    report = call("main-a", "poll")
    assert report["kind"] == "blocked"
    assert report["seat"] == "finder-1"
    assert report["assignment_id"] == request["assignment_id"]
    assert call("main-a", "poll", **args) == item
    call("main-a", "complete", item["assignment_id"], **args)
    result = call("main-a", "poll", "--ack", report["delivery_id"])
    assert result["status"] == "complete"
    assert result["message"] is None


def test_requester_can_queue_more_than_two_assignments(coordination):
    _, call, _ = coordination
    call("main-a", "init")
    invitation = call("main-a", "reserve", "advisor", "advisor")["invitation"]
    call("advisor-a", "join", invitation)
    requests = [call("main-a", "send", "advisor", f"Request {index}") for index in range(3)]
    assert call("main-a", "send", "advisor", "Request 2") == requests[2]
    for request in requests:
        assignment = call("advisor-a", "poll")
        assert assignment["assignment_id"] == request["assignment_id"]
        call("advisor-a", "complete", assignment["assignment_id"], "Checked")


def test_live_replacement_and_wrong_seat_are_refused(coordination):
    root, call, _ = coordination
    call("main-a", "init")
    invitation = call("main-a", "reserve", "r2", "refuter")["invitation"]
    call("advisor-a", "join", invitation)
    request = call("main-a", "send", "r2", "Check the scope")
    record = root / "main-a" / "store.json"
    before = record.read_bytes()
    call("main-a", "replace", "r2", error="seat is live")
    call("main-a", "complete", request["assignment_id"], error="executor seat")
    call("main-a", "poll", participant="unbound-agent", error="participant has no seat")
    assert record.read_bytes() == before


def test_missing_tool_binding_cannot_use_the_main_seat(coordination):
    root, call, _ = coordination
    call("main-a", "init")
    record = root / "main-a" / "store.json"
    before = record.read_bytes()
    call("main-a", "reserve", "unexpected", "advisor", bound=False,
         error="no coordination caller binding")
    assert record.read_bytes() == before


def test_replacement_keeps_unread_assignment(coordination):
    _, call, _ = coordination
    call("main-a", "init")
    invitation = call("main-a", "reserve", "r2", "refuter")["invitation"]
    request = call("main-a", "send", "r2", "Check the scope")
    result = call("main-a", "replace", "r2")
    assert result["status"] == "replaced"
    assert result["seat"] == "r2"
    assert result["invitation"] != invitation
    call("advisor-a", "join", invitation, error="invitation is no longer valid")
    call("advisor-b", "join", result["invitation"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(lambda _: call("advisor-b", "poll"), range(2))
    assert first == second
    assert first["assignment_id"] == request["assignment_id"]


def test_replaced_occupant_cannot_read_its_old_result(coordination, monkeypatch):
    from bootgear_cli import coordination as store_api

    root, call, main_host = coordination
    call("main-a", "init")
    invitation = call("main-a", "reserve", "r2", "refuter")["invitation"]
    advisor_host = "codex" if main_host == "claude" else "claude"
    original = store_api.Caller(root, "advisor-a", advisor_host, None)
    now = time.time()
    with monkeypatch.context() as stale:
        stale.setattr(store_api.time, "time", lambda: now - store_api.HEARTBEAT_TTL - 1)
        store_api.join(original, invitation, store_api.DEFAULT_TIMEOUT)
        with store_api.transaction(original) as store:
            request = store_api.send(store, "main", "Supply the reference", None)
    call("main-a", "complete", request["assignment_id"], "Reference attached")
    replacement = call("main-a", "replace", "r2")
    path = root / "main-a" / "store.json"
    before = path.read_bytes()
    denied = call("advisor-a", "poll", error="participant has no seat")
    assert "Reference attached" not in denied
    assert path.read_bytes() == before
    call("advisor-b", "join", replacement["invitation"])
    unread = call("advisor-b", "poll")
    assert unread["kind"] == "result"
    assert unread["message"] == "Reference attached"


def test_planner_failure_does_not_ack_or_write(coordination):
    from bootgear_cli import coordination as store_api

    root, call, main_host = coordination
    call("main-a", "init")
    with store_api.transaction(store_api.Caller(root, "main-a", main_host, None)) as store:
        store_api.activate(store, "claims", "absent-planner", "plan")
    path = root / "main-a" / "store.json"
    before = path.read_bytes()
    call("main-a", "poll", error="coordination planner failed")
    assert path.read_bytes() == before


def test_store_plans_one_main_assignment_for_each_slate(coordination):
    root, call, _ = coordination
    converge = ("converge", "converge")
    call("main-a", "init")
    init = ("init", "--refuters", "1", "--lenses", "example")
    one = call("main-a", *init, route=converge)
    call("main-a", "init", "--refuters", "1", route=converge, error="finish the active slate")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, duplicate = pool.map(lambda _: call("main-a", "poll"), range(2))
    assert first == duplicate
    assert first["slate"] == one["slate"]
    assert first["work"]["phase"] == "cutoff"
    action = json.dumps(first["work"]["actions"][0]["input"])
    written = call("main-a", "act", "--input", "-", route=converge, body=action)
    assert written["event"] == "cutoff"
    assert call("main-a", "act", "--input", "-", route=converge, body=action) == written
    call("main-a", "complete", first["assignment_id"])
    assert call("main-a", "gate", route=converge)["ok"]
    call("main-a", "finish", route=converge)
    assert (root / "main-a" / "slates" / f"{one['slate']}.jsonl").is_file()
    two = call("main-a", *init, route=converge)
    assert two["slate"] != one["slate"]
    result = call("main-a", "poll")
    assert result["kind"] == "result"
    assert result["assignment_id"] == first["assignment_id"]
    next_work = call("main-a", "poll", "--ack", result["delivery_id"])
    assert next_work["slate"] == two["slate"]
    assert next_work["assignment_id"] != first["assignment_id"]


def test_review_coverage_and_empty_gap_hunt_share_store_with_advice(coordination, monkeypatch):
    from bootgear_cli import coordination as store_api

    root, call, main_host = coordination
    converge = ("converge", "converge")
    call("main-a", "init")
    angles = root.parent / "find.yaml"
    angles.write_text("- {id: example, tag: find, tell: sample tell, asks: sample question}\n")
    opened = call("main-a", "init", "--lenses", "example", "--angles", str(angles), route=converge)
    roster = {seat["seat"]: seat for seat in opened["participants"]}
    call("main-a", "join", roster["finder"]["invitation"], participant="native-finder")
    call("advisor-r2", "join", roster["r2"]["invitation"])
    advisor_invite = call("main-a", "reserve", "advisor", "advisor")["invitation"]
    call("advisor-a", "join", advisor_invite)
    request = call("main-a", "send", "advisor", "Check an unrelated design")
    assert call("advisor-a", "poll")["assignment_id"] == request["assignment_id"]
    call("advisor-a", "complete", request["assignment_id"], "Checked")
    finder_work = call("main-a", "poll", participant="native-finder")
    assert finder_work["work"]["phase"] == "find"
    call("main-a", "complete", finder_work["assignment_id"], participant="native-finder",
         error="finish the assignment")
    action = next(row["input"] for row in finder_work["work"]["actions"]
                  if row["input"]["action"] == "find-run")
    action.update(tell="No issue", searches="Read the sample", positive_control="Read the control", result="none")
    call("main-a", "act", "--input", "-", body=json.dumps(action), route=converge,
         participant="native-finder")
    call("main-a", "complete", finder_work["assignment_id"], participant="native-finder")
    gap = call("advisor-r2", "poll")
    assert gap["work"]["phase"] == "gap-hunt"
    result = call("main-a", "poll")
    while delivery := result.get("delivery_id"):
        result = call("main-a", "poll", "--ack", delivery)
    assert result["status"] == "idle"
    main = store_api.Caller(root, "main-a", main_host, None)
    future = time.time() + store_api.ADVISOR_WORK_TIMEOUT + 1
    with monkeypatch.context() as clock:
        clock.setattr(store_api.time, "time", lambda: future)
        with store_api.transaction(main) as store:
            stalled = store_api.poll(store, None)
    assert stalled["status"] == "blocked"
    assert stalled["seat"] == "r2"
    assert stalled["assignment_id"] == gap["assignment_id"]
    assert call("advisor-r2", "poll")["assignment_id"] == gap["assignment_id"]
    result = call("advisor-r2", "complete", gap["assignment_id"])
    assert result["assignment_id"] == gap["assignment_id"]
    assert result["status"] == "complete"
    assert call("advisor-r2", "complete", gap["assignment_id"]) == result
    assert "gap-hunt-done" not in (root / "main-a" / "slates" / f"{opened['slate']}.jsonl").read_text()
    assert call("main-a", "status", route=converge)["phase"] == "cutoff"
    state = json.loads((root / "main-a" / "store.json").read_text())
    workflow = state["slates"][opened["slate"]]["workflow"]
    assert [event["event"] for event in workflow] == ["find-run", "gap-hunt-done"]

    delivered = call("main-a", "poll")
    assert delivered["assignment_id"] == gap["assignment_id"]
    pending = call("main-a", "send", "advisor", "Check another unrelated design")
    with store_api.transaction(main) as store:
        store.state["assignments"][pending["assignment_id"]]["progress_at"] -= store_api.ADVISOR_WORK_TIMEOUT + 1
    next_work = call("main-a", "poll", "--ack", delivered["delivery_id"])
    assert next_work.get("work", {}).get("phase") == "cutoff", next_work


def test_three_claims_can_complete_successive_attack_batches(coordination):
    root, call, _ = coordination
    converge = ("converge", "converge")
    config = root.parent / "converge.yaml"
    config.write_text("steps: {cut: none, escalate: false, gap_hunt: false}\n"
                      "parallelism: {finder: 1, r1: 1, r2: 1, max_workers: 3}\n")
    angles = root.parent / "angles.yaml"
    angles.write_text("- {id: sample, tag: find, tell: sample tell, asks: sample question}\n")
    call("main-a", "init")
    review = call("main-a", "init", "--refuters", "1", "--lenses", "example", "--angles", str(angles),
                  "--config", str(config), route=converge)
    seats = {member["seat"]: member for member in review["participants"]}
    for seat in ("finder", "r1"):
        call("main-a", "join", seats[seat]["invitation"], participant=seat)

    def act(seat, action, **evidence):
        return call("main-a", "act", "--input", "-", body=json.dumps({**action, **evidence}),
                    route=converge, participant=seat)

    finding = call("main-a", "poll", participant="finder")
    actions = {row["input"]["action"]: row["input"] for row in finding["work"]["actions"]}
    claims = []
    for number in range(3):
        claim = act("finder", actions["file"], loc=f"src/example.py:{number + 1}",
                    claim=f"Caller {number + 1} loses a value.", trigger=f"Call route {number + 1}.",
                    evidence=f"Check caller {number + 1}.", tier="traced")
        claims.append(claim["id"])
    act("finder", actions["find-run"], tell="Three callers lose values.", searches="Read callers.",
        positive_control="Read the repair.", result=claims)
    call("main-a", "complete", finding["assignment_id"], participant="finder")
    first = call("main-a", "poll", participant="r1")
    first_checks = [row["input"] for row in first["work"]["actions"] if row["input"]["action"] == "clean"]
    assert len(first_checks) == 3
    call("main-a", "complete", first["assignment_id"], participant="r1", error="finish the assignment")

    for action in first_checks:
        checks = [{**check, "tell": "No contrary evidence.", "evidence": "Read the caller.",
                   "searches": "Read paths.", "positive_control": "Read the control."}
                  for check in action["checks"]]
        act("r1", action, checks=checks)
    call("main-a", "complete", first["assignment_id"], participant="r1")
    second = call("main-a", "poll", participant="r1")
    assert second["assignment_id"] != first["assignment_id"]
    assert {row["input"]["batch"] for row in second["work"]["actions"]
            if row["input"]["action"] == "clean"} == {2}
    work = second
    for _ in range(8):
        if work.get("status") == "idle":
            break
        for row in work["work"]["actions"]:
            action = row["input"]
            if action["action"] != "clean":
                continue
            checks = [{**check, "tell": "No contrary evidence.", "evidence": "Read the caller.",
                       "searches": "Read paths.", "positive_control": "Read the control."}
                      for check in action["checks"]]
            if action["batch"] == "fresh-eye":
                checks[0]["angle"] = "Validate subsequent read"
                act("r1", action, checks=checks, last=True)
            else:
                act("r1", action, checks=checks)
        call("main-a", "complete", work["assignment_id"], participant="r1")
        work = call("main-a", "poll", participant="r1")
    assert work["status"] == "idle"
    call("main-a", "cutoff", route=converge)
    assert call("main-a", "gate", route=converge)["ok"]
    call("main-a", "finish", route=converge)


@pytest.mark.parametrize("event", ["Stop", "SessionStart"])
def test_paired_hook_preserves_guard_and_store(coordination, event):
    root, call, main_host = coordination
    other_host = "claude" if main_host == "codex" else "codex"
    call("main-a", "init")
    entry = call("main-a", "reserve", "advisor", "advisor")
    call("advisor-a", "join", entry["invitation"])
    assert _advisor_event(root, other_host, "advisor-a", "Stop")["decision"] == "block"
    call("main-a", "send", "advisor", "Read the draft")
    state = root / "main-a" / "store.json"
    before = (state.read_bytes(), state.stat().st_mtime_ns)
    with (state.parent / ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        output = _advisor_event(root, other_host, "advisor-a", event)
    if event == "Stop":
        assert output.get("decision") == "block"
    else:
        assert "poll" in output.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert (state.read_bytes(), state.stat().st_mtime_ns) == before
    call("main-a", "release", "advisor")
    with (state.parent / ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        assert _advisor_event(root, other_host, "advisor-a", "Stop") == {}


def _advisor_event(root, host, session, event):
    env = dict(os.environ, BOOTGEAR_COORDINATION_DIR=str(root))
    for name in ("BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID"):
        env.pop(name, None)
    env["CODEX_SESSION_ID" if host == "codex" else "CLAUDE_CODE_SESSION_ID"] = session
    payload = {"session_id": session, "hook_event_name": event, "source": "compact"}
    result = subprocess.run([str(GEAR), "--root", str(REPO), "--host", host, "advisor", "hook"],
                            env=env, input=json.dumps(payload), text=True, capture_output=True,
                            timeout=5, check=True)
    return json.loads(result.stdout or "{}")


def test_activity_does_not_hide_a_missing_background_heartbeat(coordination, monkeypatch):
    from bootgear_cli import coordination as store_api

    root, call, main_host = coordination
    other_host = "claude" if main_host == "codex" else "codex"
    advisor = store_api.Caller(root, "advisor-a", other_host, None)
    call("main-a", "init")
    invitation = call("main-a", "reserve", "advisor", "advisor")["invitation"]
    stale = time.time() - store_api.HEARTBEAT_TTL - 1
    with monkeypatch.context() as clock:
        clock.setattr(store_api.time, "time", lambda: stale)
        store_api.join(advisor, invitation, store_api.DEFAULT_TIMEOUT)
    assert call("advisor-a", "poll")["status"] == "idle"
    state = root / "main-a" / "store.json"
    before = state.read_bytes()
    output = _advisor_event(root, other_host, "advisor-a", "UserPromptSubmit")
    assert "heartbeat --wait 6180" in output["hookSpecificOutput"]["additionalContext"]
    assert state.read_bytes() == before
    with store_api.transaction(advisor) as store:
        store_api.heartbeat(store, background=True)
    assert _advisor_event(root, other_host, "advisor-a", "PostToolUse") == {}


def test_requester_release_keeps_work_for_replacement(coordination):
    root, call, _ = coordination
    call("main-a", "init")
    invitation = call("main-a", "reserve", "advisor", "advisor")["invitation"]
    call("advisor-a", "join", invitation)
    request = call("main-a", "send", "advisor", "Read this")
    original = call("advisor-a", "poll")
    assert original["assignment_id"] == request["assignment_id"]
    call("advisor-a", "poll", "--ack", original["delivery_id"])
    call("advisor-a", "release", "advisor", error="requires the main seat")
    assert call("main-a", "release", "advisor")["status"] == "released"
    state = root / "main-a" / "store.json"
    committed = state.read_bytes()
    with (state.parent / ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        assert call("advisor-a", "poll", "--timeout", "0") == {"status": "stopped", "seat": "advisor"}
    assert state.read_bytes() == committed
    call("advisor-a", "complete", request["assignment_id"], error="participant has no seat")
    replacement = call("main-a", "replace", "advisor")
    call("advisor-b", "join", replacement["invitation"])
    resumed = call("advisor-b", "poll")
    assert resumed["assignment_id"] == request["assignment_id"]
    call("advisor-b", "complete", resumed["assignment_id"], "Read")
    assert call("main-a", "poll")["message"] == "Read"
    call("main-b", "init")
    next_invitation = call("main-b", "reserve", "advisor", "advisor")["invitation"]
    call("advisor-a", "join", next_invitation)
    assert call("advisor-a", "poll")["status"] == "idle"


@pytest.mark.parametrize("joined", [False, True])
def test_standalone_advisor_wait_is_bounded(coordination, joined):
    from bootgear_cli import coordination as store_api

    root, call, main_host = coordination
    call("main-a", "init")
    invitation = call("main-a", "reserve", "advisor", "advisor")["invitation"]
    request = call("main-a", "send", "advisor", "Check the draft")
    if joined:
        call("advisor-a", "join", invitation)
    assert call("main-a", "poll")["status"] == "idle"

    assignment_id = request["assignment_id"]
    with store_api.transaction(store_api.Caller(root, "main-a", main_host, None)) as store:
        store.state["assignments"][assignment_id]["progress_at"] -= store_api.ADVISOR_WORK_TIMEOUT + 1
    stalled = call("main-a", "poll")
    assert (stalled["status"], stalled["seat"], stalled["assignment_id"]) == ("blocked", "advisor", assignment_id)

    if joined:
        call("main-a", "release", "advisor")
        assert call("main-a", "poll")["status"] == "idle"
        invitation = call("main-a", "replace", "advisor")["invitation"]
    call("advisor-b", "join", invitation)
    assert call("main-a", "poll")["status"] == "idle"
    assert call("advisor-b", "poll")["assignment_id"] == assignment_id


@pytest.mark.parametrize("assigned", [False, True])
def test_only_idle_advisor_leaves_after_requester_grace(coordination, monkeypatch, assigned):
    from bootgear_cli import coordination as store_api

    root, call, main_host = coordination
    main = store_api.Caller(root, "main-a", main_host, None)
    before_grace = time.time() - store_api.RESTART_GRACE - 5
    request = None
    with monkeypatch.context() as offline:
        offline.setattr(store_api.time, "time", lambda: before_grace)
        store_api.initialize(main, store_api.DEFAULT_TIMEOUT)
        with store_api.transaction(main) as store:
            entry = store_api.reserve(store, "advisor", "advisor")
            if assigned:
                request = store_api.send(store, "advisor", "Read the draft", None)
    call("advisor-a", "join", entry["invitation"])
    first = call("advisor-a", "poll")
    if request is not None:
        assert first["assignment_id"] == request["assignment_id"]
        second = call("advisor-a", "poll", "--ack", first["delivery_id"])
        assert second["assignment_id"] == request["assignment_id"]
        call("advisor-a", "complete", request["assignment_id"], "Read")
        first = call("advisor-a", "poll")
    assert first == {"status": "stopped", "seat": "advisor"}


@pytest.mark.parametrize("required", [False, True])
def test_advisor_launch_is_ready_only_and_optional_gap_keeps_review(coordination, required):
    root, call, _ = coordination
    converge = ("converge", "converge")
    config = root.parent / "converge.yaml"
    config.write_text("parallelism: {finder: 1, r1: 1, r2: 1, max_workers: 3}\n")
    settlement = root.parent / "settlement.yaml"
    settlement.write_text("converge_seats: {r2: advisor}\n"
                          "advisor_roles:\n  roles: [refuter, gap-hunter]\n  brief: Act as r2.\n"
                          "  startup: deferred\n  launcher: start-advisor {seat} {invitation}\n")
    angles = root.parent / "angles.yaml"
    angles.write_text("- {id: sample, tag: find, tell: sample tell, asks: sample question}\n")
    call("main-a", "init")
    extra = ("--require-advisor",) if required else ()
    opened = call("main-a", "init", "--lenses", "example", "--angles", str(angles),
                  "--config", str(config), "--settlement", str(settlement), *extra, route=converge)
    roster = {row["seat"]: row for row in opened["participants"]}
    assert "launch" not in roster["r2"]
    assert "invitation" not in roster["r2"]
    assert "r2" not in {row["seat"] for row in call("main-a", "status", route=converge)["ready"]}
    call("main-a", "join", roster["finder"]["invitation"], participant="finder")
    finding = call("main-a", "poll", participant="finder")
    coverage = next(row["input"] for row in finding["work"]["actions"]
                    if row["input"]["action"] == "find-run")
    coverage.update(tell="Read sample", searches="Read sources", positive_control="Read control", result="none")
    call("main-a", "act", "--input", "-", body=json.dumps(coverage), participant="finder", route=converge)
    call("main-a", "complete", finding["assignment_id"], participant="finder")
    ready = next(row for row in call("main-a", "status", route=converge)["ready"] if row["seat"] == "r2")
    assert ready["launch"] == f"start-advisor r2 {ready['invitation']}"
    if required:
        call("main-a", "fallback", "r2", "launcher exited 1", route=converge,
             error="requires an external advisor")
        call("main-a", "join", ready["invitation"], participant="native-r2", error="requires an external advisor")
        return
    replacement = call("main-a", "fallback", "r2", "launcher exited 1", route=converge)
    call("advisor-a", "join", ready["invitation"], error="invitation is no longer valid")
    call("main-a", "join", replacement["invitation"], participant="native-r2")
    gap = call("main-a", "poll", participant="native-r2")
    assert gap["work"]["phase"] == "gap-hunt"
    call("main-a", "cutoff", route=converge, error="is in phase gap-hunt")
    call("main-a", "complete", gap["assignment_id"], participant="native-r2")
    status = call("main-a", "status", route=converge)
    assert status["gap_hunt_done"]
    assert status["advisor_gaps"] == {"r2": "launcher exited 1"}
    call("main-a", "cutoff", route=converge)
    assert call("main-a", "gate", route=converge)["ok"]
    call("main-a", "finish", route=converge)
    assert call("main-a", "gate", opened["slate"], "--dir", str(Path(opened["path"]).parent),
                route=converge)["ok"]
    call("main-a", "init", "--lenses", "example", "--angles", str(angles),
         "--config", str(config), "--settlement", str(settlement), "--require-advisor", route=converge,
         error="release a seated native refuter")
    reopened = call("main-a", "init", "--lenses", "example", "--angles", str(angles),
                    "--config", str(config), "--settlement", str(settlement), route=converge)
    assert reopened["task_config"] == str(config)
    reused = next(row for row in reopened["participants"] if row["seat"] == "r2")
    assert reused["status"] == "joined"
    assert reused["mechanism"] == "native_subagent"


def test_init_refuses_unknown_advisor_launcher_placeholders(coordination):
    root, call, _ = coordination
    converge = ("converge", "converge")
    settlement = root.parent / "settlement.yaml"
    settlement.write_text(
        "converge_seats: {r2: advisor}\n"
        "advisor_roles:\n"
        "  roles: [refuter, gap-hunter]\n"
        "  brief: Review the assigned work.\n"
        "  startup: deferred\n"
        "  launcher: /bin/echo --group {group} --worker {worker} --invitation {invitation}\n"
    )
    call("main-a", "init")
    state_path = root / "main-a" / "store.json"
    before = state_path.read_bytes()
    error = call("main-a", "init", "--lenses", "correctness", "--settlement", str(settlement),
                 route=converge, error="unsupported placeholders")
    assert "{group}" in error and "{worker}" in error
    assert state_path.read_bytes() == before
    assert not (state_path.parent / "slates").exists()


def test_both_gate_forms_require_external_coverage(coordination):
    root, call, _ = coordination
    converge = ("converge", "converge")
    config = root.parent / "converge.yaml"
    config.write_text("steps: {gap_hunt: false}\nparallelism: {finder: 1, r1: 1, r2: 1, max_workers: 3}\n")
    settlement = root.parent / "settlement.yaml"
    settlement.write_text("converge_seats: {r2: advisor}\n")
    angles = root.parent / "angles.yaml"
    angles.write_text("- {id: sample, tag: find, tell: sample tell, asks: sample question}\n")
    call("main-a", "init")
    opened = call("main-a", "init", "--lenses", "example", "--angles", str(angles),
                  "--config", str(config), "--settlement", str(settlement), "--require-advisor", route=converge)
    finder = next(row for row in opened["participants"] if row["seat"] == "finder")
    call("main-a", "join", finder["invitation"], participant="finder")
    finding = call("main-a", "poll", participant="finder")
    action = next(row["input"] for row in finding["work"]["actions"] if row["input"]["action"] == "find-run")
    action.update(tell="Read sample", searches="Read sources", positive_control="Read control", result="none")
    call("main-a", "act", "--input", "-", body=json.dumps(action), participant="finder", route=converge)
    call("main-a", "complete", finding["assignment_id"], participant="finder")
    call("main-a", "cutoff", route=converge)
    call("main-a", "gate", route=converge, error="requires an external advisor")
    call("main-a", "gate", opened["slate"], "--dir", str(Path(opened["path"]).parent),
         route=converge, error="requires an external advisor")
