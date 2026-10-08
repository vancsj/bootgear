"""Advisor roles and converge seats: the rules shared by settlement validation
and converge init.

Stdlib only and free of package imports: engine (both hosts) and converge each
ship a byte-identical copy. Every check returns `(field, message)` problems.
"""
from __future__ import annotations

from typing import Any

SEATS = ("main", "finder", "r1", "r2", "cutter")
MECHANISMS = ("advisor", "native_subagent")
ADVISOR_SEAT = "r2"
ADVISOR_ROLES = ("independent-reviewer", "adversarial-reviewer", "refuter", "gap-hunter")
# Converge roles the advisor takes on a seat; only r2 holds any.
SEAT_ROLES: dict[str, tuple[str, ...]] = {"r2": ("refuter", "gap-hunter")}
# Advisor roles that are debate parties of the same id.
PARTY_ROLES = ("independent-reviewer", "adversarial-reviewer")
STOCK_BRIEF = "Act only as this seat on this slate; do not extend the role."

Problem = tuple[str, str]


def resolved(seats: dict[str, Any]) -> dict[str, Any]:
    """Every seat native_subagent, overlaid with `seats` verbatim (unknown ids
    are kept so validation refuses them)."""
    return {**{seat: "native_subagent" for seat in SEATS}, **seats}


def roles_problems(advisor_roles: Any) -> list[Problem]:
    if advisor_roles is None:
        return []
    if not isinstance(advisor_roles, dict):
        return [("advisor_roles", "must be a mapping {roles: [...], brief: <one line>}")]
    problems: list[Problem] = []
    extra = sorted(str(key) for key in advisor_roles if key not in ("roles", "brief"))
    if extra:
        problems.append(("advisor_roles", (f"unknown fields {', '.join(extra)}; "
                                           f"only roles and brief are allowed")))
    roles = advisor_roles.get("roles")
    if not isinstance(roles, list):
        problems.append(("advisor_roles.roles",
                         f"must be a list of role ids from: {', '.join(ADVISOR_ROLES)}"))
    else:
        for role in roles:
            if role not in ADVISOR_ROLES:
                problems.append(("advisor_roles.roles",
                                 f"unknown role {role!r}; allowed: {', '.join(ADVISOR_ROLES)}"))
        duplicates = sorted({role for role in roles
                             if isinstance(role, str) and roles.count(role) > 1})
        if duplicates:
            problems.append(("advisor_roles.roles",
                             f"duplicate roles {', '.join(duplicates)}; name each role once"))
    brief = advisor_roles.get("brief")
    if not isinstance(brief, str) or not brief.strip() or "\n" in brief or "\r" in brief:
        problems.append(("advisor_roles.brief",
                         "must be a non-empty single-line string limiting the advisor to its roles"))
    return problems


def seat_problems(converge_seats: Any) -> list[Problem]:
    if converge_seats is None:
        return []
    if not isinstance(converge_seats, dict):
        return [("converge_seats",
                 f"must be a mapping of seat to mechanism; seats: {', '.join(SEATS)}")]
    problems: list[Problem] = []
    for seat, mechanism in converge_seats.items():
        if seat not in SEATS:
            problems.append(("converge_seats", f"unknown seat {seat!r}; seats: {', '.join(SEATS)}"))
            continue
        if mechanism not in MECHANISMS:
            problems.append((f"converge_seats.{seat}",
                             f"unknown mechanism {mechanism!r}; allowed: {', '.join(MECHANISMS)}"))
        elif mechanism == "advisor" and seat != ADVISOR_SEAT:
            problems.append((f"converge_seats.{seat}",
                             ("only r2 may be advisor: the advisor's converge roles "
                              "(refuter, gap-hunter) sit on r2 and one listener holds one seat; "
                              f"set converge_seats.{seat}: native_subagent")))
    return problems


def _named(advisor_roles: Any) -> list[str]:
    if not isinstance(advisor_roles, dict) or not isinstance(advisor_roles.get("roles"), list):
        return []
    return [role for role in advisor_roles["roles"] if isinstance(role, str)]


def seat_mismatch(advisor_roles: Any, converge_seats: Any) -> list[Problem]:
    """Each seat whose advisor roles are named but which is not seated advisor.
    Call only when both fields have no shape problems."""
    named = _named(advisor_roles)
    seats = resolved(converge_seats if isinstance(converge_seats, dict) else {})
    problems: list[Problem] = []
    for seat, seat_roles in SEAT_ROLES.items():
        roles = [role for role in seat_roles if role in named]
        if roles and seats[seat] != "advisor":
            joined = ", ".join(roles)
            problems.append(("advisor_roles",
                             (f"names {joined} but converge_seats.{seat} is {seats[seat]}; "
                              f"set converge_seats.{seat}: advisor, or remove {joined} "
                              f"from advisor_roles.roles")))
    return problems


def party_mismatch(advisor_roles: Any, party_config: Any, roster: Any) -> list[Problem]:
    """Each named debate-party role that is not seated advisor, missing from
    the roster, or disabled."""
    parties = party_config.get("parties") if isinstance(party_config, dict) else None
    parties = parties if isinstance(parties, dict) else {}
    problems: list[Problem] = []
    for role in PARTY_ROLES:
        if role not in _named(advisor_roles):
            continue
        config = parties.get(role)
        config = config if isinstance(config, dict) else {}
        remove = f"or remove {role} from advisor_roles.roles"
        mechanism = config.get("mechanism")
        if mechanism != "advisor":
            problems.append((f"debate_party_config.parties.{role}.mechanism",
                             (f"advisor_roles names {role} but its mechanism is "
                              f"{mechanism if mechanism is not None else 'absent'}; "
                              f"set debate_party_config.parties.{role}.mechanism: advisor, "
                              f"{remove}")))
        if isinstance(roster, list) and role not in roster:
            problems.append(("debate_roster",
                             (f"advisor_roles names {role} but debate_roster lacks it; "
                              f"add {role} to debate_roster, {remove}")))
        if config.get("enabled") is False:
            problems.append((f"debate_party_config.parties.{role}.enabled",
                             (f"advisor_roles names {role} but the party is disabled; "
                              f"remove enabled: false, {remove}")))
    return problems


def seat_roles(advisor_roles: Any, seat: str) -> tuple[list[str], str, bool]:
    """The seat's named advisor roles and the brief; the seat's default roles
    and the stock brief (defaulted=True) when none of its roles is named."""
    roles = [role for role in SEAT_ROLES.get(seat, ()) if role in _named(advisor_roles)]
    if not roles:
        return list(SEAT_ROLES.get(seat, ())), STOCK_BRIEF, True
    return roles, advisor_roles["brief"], False
