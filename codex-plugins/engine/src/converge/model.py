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
EVENTS = ("init", "file", "escalate", "find-run", "angle-na", "refute", "rebut", "cut", "accept", "cutoff")

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
# An unconverged claim blocks only at this severity and frequency; below, it is follow-up.
BLOCKING_SEVERITY = ("security", "data-loss", "wrong-behavior")
BLOCKING_FREQUENCY = ("every-call", "common")
# A claim whose done cut has this severity is parked: never refuted, listed as follow-up.
PARK_SEVERITY = "cosmetic"

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
    escalation: dict[str, Any] | None = None
    # Attack angles a refuter recorded as not applicable to this claim.
    na_angles: set[str] = field(default_factory=set)
    # Seq of the last rebut --stage refute or dependency reset; a cut older than it is stale.
    stale_seq: int = 0

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
    # Seat -> mechanism from init; a seat not recorded is native_subagent.
    seats: dict[str, str] = field(default_factory=dict)
    advisor: dict[str, Any] | None = None
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

    def mechanism(self, seat: str) -> str:
        return self.seats.get(seat, "native_subagent")

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

    @property
    def v2(self) -> bool:
        """The init config has a `steps` section; without it every rule is the legacy one."""
        return "steps" in self.config

    def step(self, name: str) -> bool:
        return bool(self.config.get("steps", {}).get(name, False))

    def refute_state(self, claim: Claim) -> str:
        attack_total = len(self.angle_ids("attack")) if self.v2 else None
        return refute_state(claim, self.cap("refute_rounds"), attack_total)

    def cut_state(self, claim: Claim) -> str:
        return cut_state(claim, self.cap("cut_rounds"), self.v2)

    def live_claims(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.live]

    def remaining_angles(self, claim: Claim) -> list[str]:
        """Attack angles neither used on nor recorded not applicable to the claim."""
        spent = claim.used_angles | claim.na_angles
        return [a for a in self.angle_ids("attack") if a not in spent]

    def refute_round_complete(self, claim: Claim) -> bool:
        """No round yet, or the last round has two events, or no attack angle remains."""
        if claim.refute_round == 0 or len(claim.refute_rounds[claim.refute_round]) >= 2:
            return True
        return not self.remaining_angles(claim)

    def report_rule(self, claim: Claim) -> bool:
        """The claim is tagged with a rule in `cutoff.report_rules`: it is always reported."""
        return claim.rule in self.config["cutoff"].get("report_rules", [])

    def needs_escalate(self, claim: Claim) -> bool:
        """The escalate step is on and the claim has had no escalate, cut or refute yet."""
        return (self.v2 and self.mode == "full" and self.step("escalate")
                and claim.escalation is None and not claim.cut_rounds
                and claim.refute_round == 0)

    def awaits_accept(self, claim: Claim) -> bool:
        """The latest cut is current and its finder has neither accepted nor rebutted it."""
        last = claim.cut_round
        return (last > 0 and not (self.v2 and cut_stale(claim))
                and claim.accepted_round < last and claim.cut_pending < last)

    def parked(self, claim: Claim) -> bool:
        """A done cosmetic cut on a claim not yet refuted: it skips refutation. A claim
        tagged with a report rule is always refuted and reported."""
        if not self.v2 or not claim.live or claim.cut_round == 0:
            return False
        return (self.cut_state(claim) in CUT_DONE
                and claim.cut_rounds[claim.cut_round]["severity"] == PARK_SEVERITY
                and self.refute_state(claim) not in REFUTE_DONE
                and not self.report_rule(claim))

    def phase(self, claim: Claim) -> str | None:
        """The step a claim is open in: "cut", "refute", or None when it needs nothing."""
        if not claim.live or self.parked(claim):
            return None
        refute_done = self.refute_state(claim) in REFUTE_DONE
        if self.mode != "full":
            return None if refute_done else "refute"
        cut_done = self.cut_state(claim) in CUT_DONE
        if self.v2 and self.step("early_cut"):
            if not cut_done:
                return "cut" if self.refute_round_complete(claim) else "refute"
            return None if refute_done else "refute"
        if not refute_done:
            return "refute"
        return None if cut_done else "cut"

    def open_claims(self) -> list[tuple[Claim, str]]:
        """Live claims open in refute or (full mode) cut, with the phase they are open in."""
        result = []
        for claim in self.live_claims():
            phase = self.phase(claim)
            if phase is not None:
                result.append((claim, phase))
        return result


def delta_command(slate: Slate) -> str | None:
    """`git diff <previous snapshot> <this snapshot>` for a slate started with --since."""
    if slate.since is None or slate.snapshot is None:
        return None
    return f"git diff {slate.since['snapshot']} {slate.snapshot}"


def refute_state(claim: Claim, cap: int, attack_total: int | None = None) -> str:
    """open | converged | inconclusive | unconverged | killed | retracted.

    With `attack_total` (a `steps` slate), a claim not converged is also unconverged once
    every attack angle is used on it or recorded not applicable to it.
    """
    if claim.dead:
        return claim.dead
    exhausted = (attack_total is not None
                 and len(claim.used_angles | claim.na_angles) >= attack_total)
    last = claim.refute_round
    if last == 0:
        return "unconverged" if exhausted else "open"
    events = claim.refute_rounds[last]
    if len(events) >= 2:
        changed = any(e["outcome"] == "downgraded" for e in events)
        if not changed and last > claim.refute_pending:
            if any(e["outcome"] == "inconclusive" for e in events):
                return "inconclusive"
            return "converged"
        if last >= cap:
            return "unconverged"
    return "unconverged" if exhausted else "open"


def cut_values(event: dict[str, Any]) -> tuple[str, ...]:
    return tuple(event[f] for f in CUT_FIELDS)


def cut_stale(claim: Claim) -> bool:
    """A downgrade, a rebut --stage refute or a dependency reset came after the last cut."""
    if claim.cut_round == 0:
        return False
    changed = max(claim.downgrades[-1]["seq"] if claim.downgrades else 0, claim.stale_seq)
    return changed > claim.cut_rounds[claim.cut_round]["seq"]


def cut_state(claim: Claim, cap: int, v2: bool = False) -> str:
    """open | converged | capped (on a legacy slate only meaningful once refute is done).

    Converged: the finder accepted the latest cut round (and did not rebut it since), or the
    finder rebutted round N-1 and round N repeated its four fields. With `v2`, a stale cut
    is never converged: it is capped at the round cap and open below it.
    """
    last = claim.cut_round
    if last == 0:
        return "open"
    if not (v2 and cut_stale(claim)):
        if claim.accepted_round == last and claim.cut_pending < last:
            return "converged"
        if (last >= 2 and claim.cut_pending == last - 1
                and cut_values(claim.cut_rounds[last]) == cut_values(claim.cut_rounds[last - 1])):
            return "converged"
    if last >= cap:
        return "capped"
    return "open"


def cut_note(claim: Claim, cap: int, v2: bool = False) -> str:
    """How the cut stage stands, for status and render."""
    last = claim.cut_round
    if last == 0:
        return "not cut"
    state = cut_state(claim, cap, v2)
    if state == "converged":
        if claim.accepted_round == last and claim.cut_pending < last:
            return f"accepted round {last}"
        return f"held after rebut, round {last}"
    if state == "capped":
        return f"capped at round {last}"
    if v2 and cut_stale(claim):
        return f"stale after refute, round {last}"
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
        blocking = (cut.get("severity") in BLOCKING_SEVERITY
                    and cut.get("frequency") in BLOCKING_FREQUENCY)
        if slate.v2 and slate.parked(claim):
            result, reason = "follow-up", "unverified"
        elif (slate.v2 and rstate == "unconverged" and not blocking
              and not slate.report_rule(claim)):
            result, reason = "follow-up", "unconverged"
        elif rstate in ("inconclusive", "unconverged"):
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


def batch_plan(slate: Slate) -> dict[str, list[list[dict[str, Any]]]]:
    """Per step, the live eligible claims in rank order, in batches of `caps.batch_items`.

    An item is one claim for escalate, cut and rebut, and one claim x attack angle for
    refute: a refute batch of m claims gives each `min(angles_per_claim, batch_items // m)`
    angles, the remainder going to the highest-ranked claims.
    """
    plan: dict[str, list[list[dict[str, Any]]]] = {
        "escalate": [], "cut": [], "refute": [], "rebut": []}
    if not slate.v2:
        return plan
    cap, per = slate.cap("batch_items"), slate.cap("angles_per_claim")
    claims = sorted(slate.live_claims(), key=rank_key)
    rows: dict[str, list[dict[str, Any]]] = {step: [] for step in plan}
    for claim in claims:
        base = {"claim": claim.id, "finder": claim.finder}
        phase = slate.phase(claim)
        if slate.needs_escalate(claim):
            rows["escalate"].append(dict(base))
        if phase == "cut":
            rows["cut"].append(dict(base))
        elif phase == "refute":
            last = claim.refute_round
            complete = last == 0 or len(claim.refute_rounds[last]) >= 2
            rows["refute"].append({**base, "round": last + 1 if complete else last})
        if slate.mode == "full" and not slate.parked(claim) and _rebuttable(slate, claim):
            rows["rebut"].append(dict(base))
    for step, items in rows.items():
        plan[step] = [items[i:i + cap] for i in range(0, len(items), cap)]
    for batch in plan["refute"]:
        share, extra = divmod(cap, len(batch))
        for index, row in enumerate(batch):
            angles = per if share >= per else share + (1 if index < extra else 0)
            claim = slate.claims[row["claim"]]
            room = per - len(claim.refute_rounds.get(row["round"], []))
            row["angles"] = min(angles, room, len(slate.remaining_angles(claim)))
    return plan


def _rebuttable(slate: Slate, claim: Claim) -> bool:
    """The last refute round holds a downgrade not yet rebutted and not yet followed by an
    accepted cut."""
    if claim.refute_round <= claim.refute_pending:
        return False
    events = claim.refute_rounds[claim.refute_round]
    if not any(e["outcome"] == "downgraded" for e in events):
        return False
    last_cut = claim.cut_rounds.get(claim.cut_round)
    recut = (last_cut is not None and last_cut["seq"] > max(e["seq"] for e in events)
             and slate.cut_state(claim) == "converged")
    return not recut


def cutoff_results(rows: list[CutoffRow]) -> dict[str, dict[str, Any]]:
    return {row.claim.id: {"result": row.result, "rank": row.rank} for row in rows}
