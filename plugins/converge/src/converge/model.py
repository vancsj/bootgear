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

FREQUENCY = ("every-call", "common", "rare", "contrived")
SEVERITY = ("security", "data-loss", "wrong-behavior", "degraded", "cosmetic")
CONFIDENCE = ("reproduced", "traced", "inferred")
DIFFICULTY = ("trivial", "local", "cross-cutting", "redesign")
# The phases an `angle-na` event is recorded in.
PHASE = ("find", "attack")
ORIGIN = ("lens", "gap-hunt")
EVENTS = ("init", "file", "escalate", "find-run", "angle-na", "attack", "reply", "verdict", "cut",
          "rebut", "accept", "cutoff")

CUT_FIELDS = ("frequency", "severity", "confidence", "difficulty")
FIELD_ENUMS: dict[str, tuple[str, ...]] = {
    "frequency": FREQUENCY,
    "severity": SEVERITY,
    "confidence": CONFIDENCE,
    "difficulty": DIFFICULTY,
}
# Fields a cutoff rule may constrain; `lens` values are free-form.
RULE_FIELDS: dict[str, tuple[str, ...] | None] = {**FIELD_ENUMS, "origin": ORIGIN, "lens": None}
CHOICE_DIFFICULTY = ("cross-cutting", "redesign")

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
    origin: str
    depends: list[str]
    rule: str | None
    filed_seq: int
    state: ClaimState
    text: str = ""
    escalation: dict[str, Any] | None = None
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


def rating_key(rating: dict[str, Any] | None, claim_id: str) -> tuple[int, int, int, int]:
    """Severity, then frequency, then confidence, then claim id; unrated claims last."""
    cut = rating or {}
    return (
        SEVERITY.index(cut["severity"]) if "severity" in cut else len(SEVERITY),
        FREQUENCY.index(cut["frequency"]) if "frequency" in cut else len(FREQUENCY),
        CONFIDENCE.index(cut["confidence"]) if "confidence" in cut else len(CONFIDENCE),
        int(claim_id[1:]),
    )


def rank_key(claim: Claim) -> tuple[int, int, int, int]:
    return rating_key(claim.state.rating, claim.id)


def rule_matches(rule: dict[str, list[str]], values: dict[str, str | None]) -> bool:
    return all(values.get(name) in allowed for name, allowed in rule.items())


@dataclass
class CutoffRow:
    claim: Claim
    status: str
    cut: str
    result: str
    rank: int
    reason: str
