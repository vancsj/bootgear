"""Record native finder turns against their saved work assignments."""
from __future__ import annotations

from typing import Any, TypeGuard

from .finder_routing import PROFILE_FIELDS
from .model import Slate

LAUNCH_FIELDS = ("id", "host", *PROFILE_FIELDS)
OUTCOME_FIELDS = ("id", "state", "handle", "receipt_worker", "effective", "reason")


def saved_host(slate: Slate) -> str | None:
    return slate.events[0]["finder_host"] if slate.finder_plan is not None else None


def _text(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value


def _entries(slate: Slate, values: Any, fields: tuple[str, ...], command: str,
             problems: list[str]) -> list[tuple[dict[str, Any], str, dict[str, str]]]:
    if not isinstance(values, list) or not values:
        problems.append(f"{command}: expected a nonempty list")
        return []
    profiles = slate.finder_plan.profiles if slate.finder_plan is not None else {}
    seen: set[str] = set()
    entries = []
    for index, row in enumerate(values, 1):
        label = f"{command}[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label}: expected an object")
            continue
        actor = row.get("id")
        if isinstance(actor, str):
            label = f"{label} {actor}"
        for field in row:
            if field not in fields:
                problems.append(f"{label}: unknown field {field!r}")
        if not isinstance(actor, str) or actor not in profiles:
            problems.append(f"{label}: {actor!r} has no routed finder assignment")
            continue
        if actor in seen:
            problems.append(f"{label}: duplicate worker")
        seen.add(actor)
        entries.append((row, label, profiles[actor]))
    return entries


def launch_problems(slate: Slate, values: Any) -> list[str]:
    problems = blocked(slate)
    for row, label, profile in _entries(slate, values, LAUNCH_FIELDS, "launch", problems):
        if row["id"] in slate.finder_launches:
            problems.append(f"{label}: worker already has a launch attempt")
        for field, expected in profile.items():
            if row.get(field) != expected:
                problems.append(f"{label}: {field} must be {expected!r}; got {row.get(field)!r}")
    return problems


def native_arguments(entry: dict[str, str]) -> dict[str, str]:
    effort = "reasoning_effort" if entry["host"] == "codex" else "effort"
    return {"model": entry["model"], effort: entry["effort"]}


def _mismatches(profile: dict[str, str], effective: dict[str, str]) -> list[str]:
    mismatches = []
    for field, value in effective.items():
        expected = profile[field]
        if value == expected:
            continue
        if field == "model" and profile["host"] == "claude" and value.startswith(f"claude-{expected}-"):
            continue
        mismatches.append(f"effective {field} is {value!r}, expected {expected!r}")
    return mismatches


def _receipt(row: dict[str, Any], label: str, previous: dict[str, Any], handles: dict[str, str],
             problems: list[str]) -> None:
    has_receipt = row["state"] == "finished" or any(key in row for key in ("handle", "effective", "receipt_worker"))
    if not has_receipt:
        return
    if row.get("receipt_worker") != row["id"]:
        problems.append(f"{label}: receipt_worker must be {row['id']!r} from the original native call")
    handle = row.get("handle")
    if not _text(handle) or handle.startswith("-"):
        problems.append(f"{label}: a native handle is required with the receipt")
        return
    if "handle" in previous and handle != previous["handle"]:
        problems.append(f"{label}: use the saved handle from the original native call")
    if handle in handles and handles[handle] != row["id"]:
        problems.append(f"{label}: handle already belongs to {handles[handle]}")
    else:
        handles[handle] = row["id"]


def outcomes(slate: Slate, values: Any) -> tuple[list[dict[str, Any]], list[str]]:
    from .render import coverage

    problems: list[str] = []
    results = []
    entries = _entries(slate, values, OUTCOME_FIELDS, "launch-result", problems)
    plan = slate.finder_plan
    if plan is None:
        return results, problems
    handles = {row["handle"]: actor for actor, row in slate.finder_launches.items() if "handle" in row}
    missing = {(lens, angle) for lens, row in coverage(slate).items() for angle in row.missing}
    for row, label, profile in entries:
        actor = row["id"]
        previous = slate.finder_launches.get(actor, {})
        state = row.get("state")
        if state not in ("finished", "blocked"):
            problems.append(f"{label}: state must be finished or blocked; got {state!r}")
            continue
        _receipt(row, label, previous, handles, problems)
        effective = row.get("effective", {})
        if not isinstance(effective, dict) or any(
                key not in PROFILE_FIELDS or not _text(value) for key, value in effective.items()):
            problems.append(f"{label}: effective must contain only observed model or effort strings")
            continue
        mismatches = _mismatches(profile, effective)
        if state == "finished" and "reason" in row:
            problems.append(f"{label}: a finished outcome does not take a reason")
        if mismatches:
            row = {**row, "state": "blocked", "reason": ". ".join(mismatches)}
        elif state == "blocked" and not _text(row.get("reason")):
            problems.append(f"{label}: a blocked outcome requires a reason")
        if previous.get("state") != "attempted" and not (previous.get("state") == "finished" and mismatches):
            problems.append(f"{label}: requires an attempted worker or a later mismatch for a finished worker")
        if row["state"] == "finished":
            incomplete = [f"{lens}/{angle}" for (lens, angle), owner in plan.owners.items()
                          if owner == actor and (lens, angle) in missing]
            if incomplete:
                problems.append(f"{label}: assigned coverage missing for {', '.join(incomplete)}")
        results.append(row)
    return results, problems


def validate_event(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    kind = event["event"]
    if event.get("as") != slate.events[0]["as"]:
        problems.append(f"{kind}: only the slate's main actor can record native finder turns")
    if kind == "launch":
        problems.extend(launch_problems(slate, event.get("launches")))
        return
    rows, found = outcomes(slate, event.get("outcomes"))
    problems.extend(found)
    if not found and rows != event["outcomes"]:
        problems.append("launch-result: record observed mismatches as blocked with their reason")


def apply_event(slate: Slate, event: dict[str, Any]) -> None:
    if event["event"] == "launch":
        for row in event["launches"]:
            slate.finder_launches[row["id"]] = {"state": "attempted"}
    else:
        for row in event["outcomes"]:
            slate.finder_launches[row["id"]] = {key: value for key, value in row.items() if key != "id"}
        slate.cutoff_valid = False


def work_state(slate: Slate, actor: str) -> dict[str, Any]:
    current = slate.finder_launches.get(actor, {"state": "ready"})
    if current["state"] not in ("finished", "blocked"):
        return current
    effective = current.get("effective", {})
    plan = slate.finder_plan
    assert plan is not None
    profile = plan.profiles[actor]
    evidence = ("mismatch" if _mismatches(profile, effective) else
                "verified" if len(effective) == len(PROFILE_FIELDS) else "unverified")
    return {**current, "evidence": evidence}


def blocked(slate: Slate) -> list[str]:
    return [f"{actor} blocked: {row['reason']}" for actor, row in slate.finder_launches.items()
            if row["state"] == "blocked"]


def unfinished(slate: Slate) -> list[str]:
    if slate.finder_plan is None:
        return []
    return [actor for actor in slate.finder_plan.profiles
            if slate.finder_launches.get(actor, {}).get("state") != "finished"]


def pending(slate: Slate) -> list[str]:
    problems = blocked(slate)
    problems.extend(f"{actor} needs a finished native finder turn" for actor in unfinished(slate)
                    if slate.finder_launches.get(actor, {}).get("state") != "blocked")
    return problems
