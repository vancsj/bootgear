"""Enums, the replayed slate state, and everything computed from it.

Claim state, cutoff results and rank are computed from the event log on every
read, never typed by an agent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .protocol import ClaimState

IMPACT = ("security", "data-loss", "wrong-output", "clarity", "cosmetic")
SIZE = ("many", "one")
REACH = ("normal", "crafted", "unreachable")
# The finder's evidence basis for a filed claim.
TIER = ("reproduced", "traced", "inferred")
DIFFICULTY = ("trivial", "local", "cross-cutting", "redesign")
# A live claim's status as gate 2 reads it.
STATUS = ("survived", "disputed")
RESULT = ("fix-now", "fixed", "finding", "follow-up", "killed")
# The phases an `angle-na` event is recorded in.
PHASE = ("find", "attack")
ORIGIN = ("lens", "gap-hunt")
EVENTS = ("init", "file", "escalate", "find-run", "angle-na", "attack", "reply", "verdict", "cut",
          "rebut", "accept", "cutoff", "fix-check")

# Every cut rates these; `rate` is an integer `>= 0`. An after cut also rates `AFTER_FIELDS`.
CUT_FIELDS = ("impact", "size", "reach", "rate")
AFTER_FIELDS = ("difficulty",)
# The enum-valued cut fields; an evaluate angle of one of them carries a test per value.
FIELD_ENUMS: dict[str, tuple[str, ...]] = {
    "impact": IMPACT,
    "size": SIZE,
    "reach": REACH,
    "difficulty": DIFFICULTY,
}
# Numeric rule keys: each holds an integer and matches when the named value is at least it.
RULE_MINIMUMS = {"rate_at_least": "rate"}
# Fields a cutoff rule may constrain; `lens` values are free-form.
RULE_FIELDS: dict[str, tuple[str, ...] | None] = {
    **FIELD_ENUMS, "tier": TIER, "status": STATUS, "origin": ORIGIN, "lens": None,
    **dict.fromkeys(RULE_MINIMUMS)}
CHOICE_DIFFICULTY = ("cross-cutting", "redesign")
# The difficulty classes of a cheap fix (checks 1-6).
CHEAP_DIFFICULTY = ("trivial", "local")

ID_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,80}\Z")
CLAIM_RE = re.compile(r"\AF\d{3,}\Z")
LOC_RE = re.compile(r"\A[^:\s]+:\d+\Z")
# A git object name: SHA-1 (40 hex) or SHA-256 (64 hex).
SHA_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
# The CLI's own computed cutoff; it is not an agent and does not count toward `caps.agents`.
CONVERGE_AGENT = "converge"
NON_AGENT_IDS = (CONVERGE_AGENT,)
MAX_AGENTS = 5


def claim_id(n: int) -> str:
    return f"F{n:03d}"


@dataclass
class Claim:
    id: str
    finder: str
    lens: str | None
    angle: str | None
    loc: str
    original: str
    trigger: str
    evidence: str
    tier: str
    origin: str
    depends: list[str]
    rule: str | None
    filed_seq: int
    state: ClaimState
    text: str = ""
    escalation: dict[str, Any] | None = None
    # The `fix-check` event recorded for the claim's applied fix, if any.
    fix_check: dict[str, Any] | None = None
    used_angles: set[str] = field(default_factory=set)
    # Attack angles a refuter recorded as not applicable to this claim, with the reason.
    na_angles: set[str] = field(default_factory=set)
    na_reasons: dict[str, str] = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return self.state.status != "killed"


@dataclass
class Slate:
    slate_id: str
    lenses: list[str] = field(default_factory=list)
    angles: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    snapshot: str | None = None
    # The init's resolved --project-root, against which patch and loc paths resolve.
    project_root: str | None = None
    review_pass: int | None = None
    since: dict[str, str] | None = None
    # Seat -> mechanism from init; a seat not recorded is native_subagent.
    seats: dict[str, str] = field(default_factory=dict)
    advisor: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    claims: dict[str, Claim] = field(default_factory=dict)
    find_runs: list[dict[str, Any]] = field(default_factory=list)
    angle_na: list[dict[str, Any]] = field(default_factory=list)
    cutoff: dict[str, Any] | None = None
    cutoff_valid: bool = False
    # The init event's refuter seat count, 1 or 2.
    init_refuters: int = 2

    @property
    def initialised(self) -> bool:
        return bool(self.events)

    def mechanism(self, seat: str) -> str:
        return self.seats.get(seat, "native_subagent")

    def cap(self, name: str) -> int:
        return int(self.config["caps"][name])

    def lens_cap(self, lens: str | None) -> int:
        """The `caps.per_lens` entry for `lens`, else its `default`."""
        per_lens = self.config["caps"]["per_lens"]
        return int(per_lens[lens] if lens in per_lens else per_lens["default"])

    def lens_policy(self, lens: str | None) -> dict[str, Any]:
        """The `cutoff.lenses` table for `lens`, else its `default`."""
        lenses = self.config["cutoff"]["lenses"]
        return lenses[lens] if lens in lenses else lenses["default"]

    def counts_rate(self, lens: str | None) -> bool:
        """The lens policy has a `rate_at_least` rule, so its cuts must give `rate`."""
        policy = self.lens_policy(lens)
        return any(name in RULE_MINIMUMS for key in ("attack_if", "report_if", "choice_if")
                   for rule in policy.get(key, []) for name in rule)

    def angle(self, tag: str, angle_id: str) -> dict[str, Any] | None:
        for row in self.angles:
            if row["tag"] == tag and row["id"] == angle_id:
                return row
        return None

    def agent_ids(self) -> list[str]:
        """Distinct agent ids in first-seen order, the init writer first."""
        seen: list[str] = []
        for event in self.events:
            agent = event.get("as")
            if isinstance(agent, str) and agent not in NON_AGENT_IDS and agent not in seen:
                seen.append(agent)
        return seen

    def angle_ids(self, tag: str) -> list[str]:
        return [row["id"] for row in self.angles if row["tag"] == tag]

    def live_claims(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.live]

    def remaining_angles(self, claim: Claim) -> list[str]:
        """Attack angles neither used on nor recorded not applicable to the claim."""
        spent = claim.used_angles | claim.na_angles
        return [a for a in self.angle_ids("attack") if a not in spent]

    def open_claims(self) -> list[tuple[Claim, str]]:
        """Claims with an open item, with the first phase it is open in."""
        from .protocol import claim_phase

        result = []
        for claim in self.claims.values():
            phase = claim_phase(self, claim)
            if phase is not None:
                result.append((claim, phase))
        return result


def delta_command(slate: Slate) -> str | None:
    """`git diff <previous snapshot> <this snapshot>` for a slate started with --since."""
    if slate.since is None or slate.snapshot is None:
        return None
    return f"git diff {slate.since['snapshot']} {slate.snapshot}"


def rating_key(rating: dict[str, Any] | None, tier: str,
               claim_id: str) -> tuple[int, int, int, int, int, int]:
    """Impact, reach, size, rate descending, the finder's tier, then claim id; unrated
    claims last."""
    cut = rating or {}
    return (
        IMPACT.index(cut["impact"]) if "impact" in cut else len(IMPACT),
        REACH.index(cut["reach"]) if "reach" in cut else len(REACH),
        SIZE.index(cut["size"]) if "size" in cut else len(SIZE),
        -int(cut.get("rate", 0)),
        TIER.index(tier),
        int(claim_id[1:]),
    )


def rank_key(claim: Claim) -> tuple[int, int, int, int, int, int]:
    return rating_key(claim.state.rating, claim.tier, claim.id)


def rule_matches(rule: dict[str, Any], values: dict[str, Any]) -> bool:
    """Every key holds: set membership, or for a `RULE_MINIMUMS` key a present value at least
    the rule's integer."""
    for name, allowed in rule.items():
        if name in RULE_MINIMUMS:
            value = values.get(RULE_MINIMUMS[name])
            if not isinstance(value, int) or value < allowed:
                return False
        elif values.get(name) not in allowed:
            return False
    return True


@dataclass
class CutoffRow:
    claim: Claim
    status: str
    cut: str
    result: str
    rank: int
    reason: str
