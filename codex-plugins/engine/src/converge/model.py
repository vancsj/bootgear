"""Enums, the replayed slate state, and everything computed from it.

Refute state, cut state, cutoff results and rank are computed from the event
log on every read, never typed by an agent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

FREQUENCY = ("every-call", "common", "rare", "contrived")
SEVERITY = ("security", "data-loss", "wrong-behavior", "degraded", "cosmetic")
CONFIDENCE = ("reproduced", "traced", "inferred")
DIFFICULTY = ("trivial", "local", "cross-cutting", "redesign")
REFUTE_OUTCOME = ("killed", "retracted", "downgraded", "survived", "inconclusive")
PHASE = ("find", "refute", "cut")
ORIGIN = ("lens", "gap-hunt", "slate")
MODE = ("full", "refute-only")
STAGE = ("refute", "cut")
LEDGER_EVIDENCE = ("pass", "fail")
EVENTS = ("init", "file", "find-run", "angle-na", "refute", "rebut", "cut", "accept", "cutoff")

CUT_FIELDS = ("frequency", "severity", "confidence", "difficulty")
FIELD_ENUMS: dict[str, tuple[str, ...]] = {
    "frequency": FREQUENCY,
    "severity": SEVERITY,
    "confidence": CONFIDENCE,
    "difficulty": DIFFICULTY,
}
# Fields a cutoff rule may constrain; `lens` values are free-form.
RULE_FIELDS: dict[str, tuple[str, ...] | None] = {**FIELD_ENUMS, "origin": ORIGIN, "lens": None}
PHASE_TAG = {"find": "find", "refute": "attack", "cut": "evaluate"}
DEAD_OUTCOMES = ("killed", "retracted")
CHOICE_DIFFICULTY = ("cross-cutting", "redesign")

ID_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,80}\Z")
CLAIM_RE = re.compile(r"\AF\d{3,}\Z")
LOC_RE = re.compile(r"\A[^:\s]+:\d+\Z")
# A git object name: SHA-1 (40 hex) or SHA-256 (64 hex).
SHA_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SLATE_AGENT = "slate"
CONVERGE_AGENT = "converge"
# Reserved ids that are not agents: `slate` is the orchestrator filing a refute-only slate,
# `converge` is the CLI's own computed cutoff. Neither counts toward `caps.agents`.
NON_AGENT_IDS = (SLATE_AGENT, CONVERGE_AGENT)
MAX_AGENTS = 5

# Refute states a claim can be cut from.
REFUTE_DONE = ("converged", "inconclusive", "unconverged")
CUT_DONE = ("converged", "capped")


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
    text: str = ""
    stage: str = "refute"
    dead: str | None = None
    dead_event: dict[str, Any] | None = None
    downgrades: list[dict[str, Any]] = field(default_factory=list)
    refute_rounds: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    refute_pending: int = 0
    refuters: set[str] = field(default_factory=set)
    used_angles: set[str] = field(default_factory=set)
    cut_rounds: dict[int, dict[str, Any]] = field(default_factory=dict)
    cut_pending: int = 0
    accepted_round: int = 0
    cutters: set[str] = field(default_factory=set)
    rebut_hashes: dict[str, set[str]] = field(default_factory=lambda: {"refute": set(), "cut": set()})
    reopened: bool = False

    @property
    def live(self) -> bool:
        return self.dead is None

    @property
    def refute_round(self) -> int:
        return max(self.refute_rounds, default=0)

    @property
    def cut_round(self) -> int:
        return max(self.cut_rounds, default=0)

    def last_cut(self) -> dict[str, Any] | None:
        return self.cut_rounds.get(self.cut_round)


@dataclass
class Slate:
    slate_id: str
    mode: str = ""
    lenses: list[str] = field(default_factory=list)
    angles: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    snapshot: str | None = None
    review_pass: int | None = None
    since: dict[str, str] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    claims: dict[str, Claim] = field(default_factory=dict)
    find_runs: list[dict[str, Any]] = field(default_factory=list)
    angle_na: list[dict[str, Any]] = field(default_factory=list)
    cutoff: dict[str, Any] | None = None
    cutoff_valid: bool = False
    refute_started: bool = False

    @property
    def initialised(self) -> bool:
        return bool(self.events)

    def cap(self, name: str) -> int:
        return int(self.config["caps"][name])

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

    def refute_state(self, claim: Claim) -> str:
        return refute_state(claim, self.cap("refute_rounds"))

    def cut_state(self, claim: Claim) -> str:
        return cut_state(claim, self.cap("cut_rounds"))

    def live_claims(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.live]

    def open_claims(self) -> list[tuple[Claim, str]]:
        """Claims open in refute or (full mode) cut, with the phase they are open in."""
        result = []
        for claim in self.live_claims():
            if self.refute_state(claim) not in REFUTE_DONE:
                result.append((claim, "refute"))
            elif self.mode == "full" and self.cut_state(claim) not in CUT_DONE:
                result.append((claim, "cut"))
        return result


def delta_command(slate: Slate) -> str | None:
    """`git diff <previous snapshot> <this snapshot>` for a slate started with --since."""
    if slate.since is None or slate.snapshot is None:
        return None
    return f"git diff {slate.since['snapshot']} {slate.snapshot}"


def refute_state(claim: Claim, cap: int) -> str:
    """open | converged | inconclusive | unconverged | killed | retracted."""
    if claim.dead:
        return claim.dead
    last = claim.refute_round
    if last == 0:
        return "open"
    events = claim.refute_rounds[last]
    if len(events) < 2:
        return "open"
    changed = any(e["outcome"] == "downgraded" for e in events)
    if not changed and last > claim.refute_pending:
        if any(e["outcome"] == "inconclusive" for e in events):
            return "inconclusive"
        return "converged"
    if last >= cap:
        return "unconverged"
    return "open"


def cut_values(event: dict[str, Any]) -> tuple[str, ...]:
    return tuple(event[f] for f in CUT_FIELDS)


def cut_state(claim: Claim, cap: int) -> str:
    """open | converged | capped (only meaningful once refute is done).

    Converged: the finder accepted the latest cut round (and did not rebut it since), or the
    finder rebutted round N-1 and round N repeated its four fields.
    """
    last = claim.cut_round
    if last == 0:
        return "open"
    if claim.accepted_round == last and claim.cut_pending < last:
        return "converged"
    if (last >= 2 and claim.cut_pending == last - 1
            and cut_values(claim.cut_rounds[last]) == cut_values(claim.cut_rounds[last - 1])):
        return "converged"
    if last >= cap:
        return "capped"
    return "open"


def cut_note(claim: Claim, cap: int) -> str:
    """How the cut stage stands, for status and render."""
    last = claim.cut_round
    if last == 0:
        return "not cut"
    state = cut_state(claim, cap)
    if state == "converged":
        if claim.accepted_round == last and claim.cut_pending < last:
            return f"accepted round {last}"
        return f"held after rebut, round {last}"
    if state == "capped":
        return f"capped at round {last}"
    if claim.cut_pending == last:
        return f"rebutted round {last}"
    return f"awaiting accept or rebut, round {last}"


def rank_key(claim: Claim) -> tuple[int, int, int, int]:
    cut = claim.last_cut() or {}
    return (
        SEVERITY.index(cut["severity"]) if "severity" in cut else len(SEVERITY),
        FREQUENCY.index(cut["frequency"]) if "frequency" in cut else len(FREQUENCY),
        CONFIDENCE.index(cut["confidence"]) if "confidence" in cut else len(CONFIDENCE),
        int(claim.id[1:]),
    )


def rule_matches(rule: dict[str, list[str]], values: dict[str, str | None]) -> bool:
    return all(values.get(name) in allowed for name, allowed in rule.items())


@dataclass
class CutoffRow:
    claim: Claim
    result: str
    rank: int
    reason: str


def compute_cutoff(slate: Slate) -> list[CutoffRow]:
    """Reported/appendix per surviving claim, in rank order."""
    live = sorted(slate.live_claims(), key=rank_key)
    cutoff_cfg = slate.config["cutoff"]
    report_rules = cutoff_cfg.get("report_rules", [])
    per_lens = slate.cap("per_lens")
    rows: list[CutoffRow] = []
    for rank, claim in enumerate(live, start=1):
        rstate = slate.refute_state(claim)
        cstate = slate.cut_state(claim)
        cut = claim.last_cut() or {}
        values: dict[str, str | None] = {f: cut.get(f) for f in CUT_FIELDS}
        values["origin"] = claim.origin
        values["lens"] = claim.lens
        if rstate in ("inconclusive", "unconverged"):
            result, reason = "reported", rstate
        elif cstate == "capped":
            result, reason = "reported", "cut-capped"
        elif claim.rule in report_rules:
            result, reason = "reported", f"report_rules[{claim.rule}]"
        else:
            rules = cutoff_cfg["report_if_gap_hunt" if claim.origin == "gap-hunt" else "report_if"]
            matched = next((i for i, rule in enumerate(rules) if rule_matches(rule, values)), None)
            if matched is None:
                result, reason = "appendix", "no rule matched"
            else:
                key = "report_if_gap_hunt" if claim.origin == "gap-hunt" else "report_if"
                result, reason = "reported", f"{key}[{matched}]"
        rows.append(CutoffRow(claim, result, rank, reason))
    counts: dict[str | None, int] = {}
    for row in rows:
        if (row.result != "reported" or row.reason in ("inconclusive", "unconverged")
                or row.reason.startswith("report_rules[")):
            continue
        lens = row.claim.lens
        counts[lens] = counts.get(lens, 0) + 1
        if counts[lens] > per_lens:
            row.result, row.reason = "appendix", f"per-lens cap {per_lens} ({lens})"
    return rows


def cutoff_results(rows: list[CutoffRow]) -> dict[str, dict[str, Any]]:
    return {row.claim.id: {"result": row.result, "rank": row.rank} for row in rows}
