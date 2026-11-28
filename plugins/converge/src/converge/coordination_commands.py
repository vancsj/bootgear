"""Apply evidence to the current coordination assignment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from typing import Any

from bootgear_cli import clikit, coordination

from . import ledger, native_profiles, protocol, work
from .cli_actions import _review_problems
from .cli_common import _refuse


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _work_action(store: coordination.Store, value: dict[str, Any]) -> dict[str, Any]:
    active = coordination.active_slate(store)
    if active is None:
        _refuse(["no active coordination slate"])
    slate_id = active["id"]
    path = ledger.slate_path(store.path / "slates", slate_id)
    slate = ledger.read(path, slate_id, workflow=active["workflow"])
    assignment_id = value.get("assignment_id")
    assignment = store.state["assignments"].get(assignment_id) if isinstance(assignment_id, str) else None
    if not assignment or assignment.get("slate") != slate_id or assignment["executor_seat"] != store.seat:
        _refuse(["poll for an active slate assignment before submitting evidence"])
    if not any(_matches(suggestion["input"], value) for suggestion in assignment["work"]["actions"]):
        _refuse(["action is outside the current assignment"])
    action_hash = _digest(value)
    kind = value["action"]
    focus = {key: value[key] for key in ("claim", "lens", "angle", "batch", "when", "context")
             if key in value}
    if kind == "file":
        focus.update({key: value.get(key) for key in ("loc", "trigger")})
    elif kind == "clean":
        checks = value.get("checks")
        if isinstance(checks, list):
            focus["angles"] = [row.get("angle") for row in checks if isinstance(row, dict)]
    action_id = _digest([assignment["assignment_id"], kind, focus])
    for saved in slate.events:
        if saved.get("action_id") == action_id:
            if saved.get("action_hash") != action_hash:
                _refuse(["the action already exists with different evidence"])
            return saved
    if assignment["status"] != "open":
        _refuse(["this assignment is complete"])
    data = {key: field for key, field in value.items() if key != "assignment_id"}
    data.update(slate=slate_id, role=store.seat)

    def event(current):
        built = work.event(current, data, store.seat)
        if built["event"] == "fix-check" and built["outcome"] == "pass":
            review_args = argparse.Namespace(dir=path.parent, slate=slate_id, review_slate=built["review_slate"],
                                             coordination_store=store)
            problems, _ = _review_problems(review_args, current)
            if problems:
                raise ledger.LedgerError(problems)
        return {**built, "action_id": action_id, "action_hash": action_hash}

    workflow_event = kind in {"find-run", "gap-hunt-done"} or (kind == "angle-na" and value.get("phase") == "find")
    written = ledger.append(path, slate_id, {}, build=event, workflow=active["workflow"],
                            workflow_event=workflow_event)
    assignment["progress_at"] = time.time()
    return written


def _matches(suggestion: dict[str, Any], value: dict[str, Any]) -> bool:
    for field in ("action", "context", "lens", "angle", "claim", "batch", "when", "round"):
        expected = suggestion.get(field)
        if expected and value.get(field) != expected:
            return False
    return True


def cmd_act(args: argparse.Namespace) -> None:
    try:
        value = json.loads(sys.stdin.read() if args.input == "-" else clikit.caller_path(args.input).read_text())
    except (OSError, ValueError) as error:
        _refuse([str(error)], "invalid action")
    if not isinstance(value, dict):
        _refuse(["input must be one JSON object"])
    try:
        with coordination.transaction(coordination.Caller.from_environment()) as store:
            event = _work_action(store, value)
    except ledger.LedgerError as error:
        _refuse(error.problems)
    data = {key: value for key, value in event.items() if key not in ("ts", "as", "action_hash")}
    clikit.emit(args.output_mode, data, f"{event['event'].upper()} seq={event['seq']}",
                clikit.gear_command("cli", "coordination") + " poll")


def advisor_covered(store: coordination.Store, active: dict[str, Any]) -> bool:
    return (any(coordination.linked(store, seat) for seat in active.get("advisors", ()))
            or any(item.get("slate") == active["id"] and item.get("advisor_work")
                   and item["status"] == "complete" for item in store.state["assignments"].values()))


def cmd_fallback(args: argparse.Namespace) -> None:
    diagnostic = args.diagnostic.strip()
    if not diagnostic:
        _refuse(["provide the launch diagnostic"])
    with coordination.transaction(coordination.Caller.from_environment()) as store:
        store.require_main()
        active = coordination.active_slate(store)
        if not active or args.seat not in active.get("advisors", ()):
            _refuse(["this seat is not an advisor seat on the active slate"])
        if active["advisor_required"] and not advisor_covered(store, active):
            _refuse(["this task requires an external advisor", diagnostic])
        gaps = active["advisor_gaps"]
        entry = store.state["seats"][args.seat]
        slate_id = active["id"]
        path = ledger.slate_path(store.path / "slates", slate_id)
        try:
            slate = ledger.read(path, slate_id, workflow=active["workflow"])
            ready = work.package(slate, args.seat, clikit.host() or "claude", requested=entry["role"])["actions"]
        except ledger.LedgerError as error:
            _refuse(error.problems)
        if args.seat in gaps:
            if entry["occupant"]:
                clikit.emit(args.output_mode, {"seat": args.seat, "status": "joined", "diagnostic": gaps[args.seat]},
                            f"NATIVE {args.seat} joined")
                return
            reservation = coordination.reserve(store, args.seat, entry["role"])
        else:
            if entry["occupant"] or not ready:
                _refuse(["fallback needs an unoccupied advisor seat with ready work"])
            reservation = coordination.replace(store, args.seat)
            store.state["seats"][args.seat]["mechanism"] = "native_subagent"
            gaps[args.seat] = diagnostic
        result = {**reservation, "mechanism": "native_subagent", "diagnostic": gaps[args.seat],
                  "profile": native_profiles.profiles(slate, native={args.seat}).get(args.seat)}
    clikit.emit(args.output_mode, result,
                [f"ADVISOR GAP {args.seat} {result['diagnostic']}", f"INVITATION {result['invitation']}"],
                "invite an independent native participant to this seat")


def cmd_finish(args: argparse.Namespace) -> None:
    with coordination.transaction(coordination.Caller.from_environment()) as store:
        store.require_main()
        active = coordination.active_slate(store)
        if active is None:
            _refuse(["no active coordination slate"])
        slate_id = active["id"]
        path = ledger.slate_path(store.path / "slates", slate_id)
        try:
            slate = ledger.read(path, slate_id, workflow=active["workflow"])
        except ledger.LedgerError as error:
            _refuse(error.problems)
        if protocol.slate_phase(slate) != "done":
            _refuse(["finish claim work and run cutoff before finishing the slate"])
        if active.get("advisor_required") and not advisor_covered(store, active):
            _refuse(["this task requires an external advisor"])
        coordination.finish(store)
    clikit.emit(args.output_mode, {"slate": slate_id, "status": "finished"}, f"FINISHED {slate_id}")
