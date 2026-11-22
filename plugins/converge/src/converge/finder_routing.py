"""Validate finder profiles and allocate the saved lens and angle pairs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import ID_RE

EFFORTS = {
    "claude": ("low", "medium", "high", "xhigh", "max"),
    "codex": ("none", "minimal", "low", "medium", "high", "xhigh"),
}
CLAUDE_MODELS = ("haiku", "sonnet", "opus")
PROFILE_FIELDS = ("model", "effort")
Pair = tuple[str, str]


def _mapping(value: Any, fields: tuple[str, ...], where: str, problems: list[str],
             *, complete: bool) -> bool:
    if not isinstance(value, dict):
        problems.append(f"{where} must be a mapping")
        return False
    for key in value:
        if key not in fields:
            problems.append(f"{where}: unknown field {key!r}")
    if complete:
        for key in fields:
            if key not in value:
                problems.append(f"{where}.{key} is missing")
    return True


def _profile(value: dict[str, Any], host: str, where: str, problems: list[str]) -> None:
    if "model" in value:
        model = value["model"]
        if host == "claude":
            if model not in CLAUDE_MODELS:
                problems.append(f"{where}.model must be one of {', '.join(CLAUDE_MODELS)}; got {model!r}")
        elif (not isinstance(model, str) or not model or model.startswith("-")
              or any(char.isspace() for char in model)):
            problems.append(f"{where}.model must be a nonempty model ID; got {model!r}")
    if "effort" in value and value["effort"] not in EFFORTS[host]:
        problems.append(f"{where}.effort must be one of {', '.join(EFFORTS[host])}; got {value['effort']!r}")


def validate(value: Any, host: str, where: str, *, complete: bool) -> list[str]:
    if value is None:
        return []
    if not isinstance(host, str) or host not in EFFORTS:
        return [f"{where}: expected a Claude or Codex host; got {host!r}"]
    problems: list[str] = []
    if not _mapping(value, ("default", "groups"), where, problems, complete=False):
        return problems
    if "default" in value:
        profile = value["default"]
        if _mapping(profile, PROFILE_FIELDS, f"{where}.default", problems, complete=complete):
            _profile(profile, host, f"{where}.default", problems)
    elif complete:
        problems.append(f"{where}.default is missing")
    groups = value.get("groups", [])
    if not isinstance(groups, list):
        return [*problems, f"{where}.groups must be a list"]
    seen: set[str] = set()
    for index, group in enumerate(groups, 1):
        item = f"{where}.groups[{index}]"
        if not _mapping(group, (*PROFILE_FIELDS, "workers", "lenses"), item, problems, complete=True):
            continue
        _profile(group, host, item, problems)
        count = group.get("workers")
        if "workers" in group and (type(count) is not int or count < 1):
            problems.append(f"{item}.workers must be a positive integer; got {count!r}")
        if "lenses" not in group:
            continue
        lenses = group["lenses"]
        if not isinstance(lenses, list) or not lenses:
            problems.append(f"{item}.lenses must be a nonempty list of lens IDs")
            continue
        for lens in lenses:
            if not isinstance(lens, str) or not ID_RE.fullmatch(lens):
                problems.append(f"{item}.lenses: invalid lens ID {lens!r}")
            elif lens in seen:
                problems.append(f"{item}.lenses: duplicate lens {lens!r}")
            else:
                seen.add(lens)
    return problems


@dataclass
class Plan:
    owners: dict[Pair, str] = field(default_factory=dict)
    profiles: dict[str, dict[str, str]] = field(default_factory=dict)
    unused_lenses: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def allocate(pairs: list[Pair], policy: dict[str, Any], host: str, budget: int) -> Plan:
    from .assignments import worker_id

    plan = Plan()
    groups = []
    configured_lenses = set()
    for group in policy.get("groups", []):
        members = [pair for pair in pairs if pair[0] in group["lenses"]]
        used_lenses = {lens for lens, _ in members}
        plan.unused_lenses.extend(lens for lens in group["lenses"] if lens not in used_lenses)
        configured_lenses.update(group["lenses"])
        groups.append((group, members, min(group["workers"], len(members))))
    defaults = [pair for pair in pairs if pair[0] not in configured_lenses]
    total = sum(count for _, _, count in groups)
    if total > budget:
        plan.problems.append(f"finder_routing: active groups need {total} workers, above finder budget {budget}")
    if defaults and total >= budget:
        plan.problems.append(f"finder_routing: default angles need a worker within finder budget {budget}")
    if plan.problems:
        return plan
    groups.append((policy["default"], defaults, min(budget - total, len(defaults))))
    for group, members, count in groups:
        ids = [worker_id("finder", len(plan.profiles) + index) for index in range(count)]
        for actor in ids:
            plan.profiles[actor] = {"host": host, **{key: group[key] for key in PROFILE_FIELDS}}
        for index, pair in enumerate(members):
            plan.owners[pair] = ids[index % count]
    return plan
