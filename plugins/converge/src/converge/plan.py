"""Offer the next review batch for a coordination seat."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from bootgear_cli import clikit

from . import ledger, protocol, work
from .model import Slate


def plan(request: dict[str, Any]) -> dict[str, Any] | None:
    active = request["slate"]
    slate_id = active["id"]
    path = ledger.slate_path(Path(request["store"]) / "slates", slate_id)
    slate = ledger.read(path, slate_id, workflow=active["workflow"])
    actor, role = request["seat"], request["role"]
    if role not in {"main", "finder", "r1", "r2", "cutter"}:
        return None
    if completion := request.get("complete"):
        return _complete(slate, actor, role, completion)
    offer = _offer(slate, actor, role)
    if offer is not None:
        if actor in active.get("advisors", ()) and active.get("advisor_scope"):
            offer["work"]["scope"] = active["advisor_scope"]
        return offer
    if role == "main":
        for seat in request.get("pending_advisors", ()):
            advisor_role = active.get("roster", {}).get(seat)
            if advisor_role and work.package(slate, seat, clikit.host() or "claude", requested=advisor_role)["actions"]:
                return {"launch": seat}
    return None


def _complete(slate: Slate, actor: str, role: str, completion: dict[str, Any]) -> dict[str, Any]:
    if completion["work"]["phase"] == "gap-hunt" and protocol.slate_phase(slate) == "gap-hunt":
        event = {"event": "gap-hunt-done", "as": actor, "seq": len(slate.events) + 1, "ts": ledger.now()}
        if problems := ledger.validate_event(slate, event):
            raise ledger.LedgerError(problems)
        return {"workflow": [event]}
    current = _offer(slate, actor, role)
    remaining = _focus(current["work"]) & _focus(completion["work"]) if current else set()
    if remaining:
        subjects = set()
        for item in sorted(remaining):
            value = json.loads(item)
            target = " ".join(f"{key} {value[key]}" for key in ("claim", "lens", "angle", "batch", "when") if key in value)
            subjects.add(target or value["action"])
        raise ledger.LedgerError(["finish the assignment's evidence before completing it", *sorted(subjects)])
    return {"workflow": []}


def _focus(work: dict[str, Any]) -> set[str]:
    """Compare required actions across batches. Attack annotations can repeat."""
    coordinates = ("action", "context", "claim", "lens", "angle", "batch", "when", "round")
    return {
        json.dumps({key: row["input"][key] for key in coordinates if key in row["input"]}, sort_keys=True)
        for row in work["actions"]
        if (row["input"]["action"], row["input"].get("phase")) != ("angle-na", "attack")
    }


def _offer(slate: Slate, actor: str, role: str) -> dict[str, Any] | None:
    package = work.package(slate, actor, clikit.host() or "claude", requested=role)
    if not package["actions"]:
        return None
    for action in package["actions"]:
        action["input"].pop("slate")
        action["input"].pop("role")
        action["input"].pop("seat")
    actions = [
        {key: value for key, value in action["input"].items() if key != "source_seq"}
        for action in package["actions"]
    ]
    identity = hashlib.sha256(json.dumps(actions, sort_keys=True).encode()).hexdigest()
    public = {key: package[key] for key in ("phase", "items", "definitions", "difficulty_basis",
                                            "caps", "steps", "policies", "patch_limits", "actions")}
    return {"batch": identity, "receiver": "main", "work": public}


def main() -> None:
    if clikit.event_help("converge", "plan", "stdin JSON from a coordination planner call.",
                         {"slate": {"id": "review-example", "workflow": []},
                          "store": "<store>", "seat": "main", "role": "main"}):
        return
    try:
        request = json.load(sys.stdin)
        print(json.dumps(plan(request)))
    except (ledger.LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
