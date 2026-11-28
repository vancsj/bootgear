"""Apply evidence to the current coordination assignment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import replace
from typing import Any, NoReturn

from bootgear_cli import clikit, coordination

from . import ledger, native_profiles, protocol, work
from .cli_actions import _review_problems
from .cli_common import CATALOG, EXAMPLES, _refuse, _refuse_next

ACTIVE_ACT_CATALOG = replace(CATALOG, examples={"act": EXAMPLES["act"]}, frequent=())


def refuse_active_action(args: argparse.Namespace, message: str, problems: list[str]) -> NoReturn:
    _refuse_next(args, message, problems,
                 "refresh the current work: " + clikit.gear_command("cli", "coordination") + " poll",
                 catalog=ACTIVE_ACT_CATALOG)


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
    if not isinstance(assignment_id, str) or not re.fullmatch(r"a[1-9][0-9]*", assignment_id):
        _refuse(["provide assignment_id from the poll result, such as a1"])
    assignment = store.state["assignments"].get(assignment_id)
    if not assignment or assignment["executor_seat"] != store.seat:
        _refuse([f"assignment_id {assignment_id} does not belong to this seat"])
    if assignment.get("slate") != slate_id:
        _refuse([f"assignment_id {assignment_id} does not hold work for the active slate"])
    if not any(_matches(suggestion["input"], value) for suggestion in assignment["work"]["actions"]):
        _refuse([f"action or context does not match the work in assignment_id {assignment_id}"])
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
    active["claim_seq"] = written["seq"]
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
        refuse_active_action(args, "invalid action", [str(error)])
    if not isinstance(value, dict):
        refuse_active_action(args, "invalid action", ["input must be one JSON object"])
    try:
        with coordination.transaction(coordination.Caller.from_environment()) as store:
            event = _work_action(store, value)
    except ledger.LedgerError as error:
        refuse_active_action(args, "refused", error.problems)
    except clikit.Refusal as error:
        refuse_active_action(args, "refused", [problem for _, problem in error.problems] or [error.message])
    data = {key: value for key, value in event.items()
            if key not in ("ts", "as", "action_id", "action_hash", "evidence_sha256")}
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
