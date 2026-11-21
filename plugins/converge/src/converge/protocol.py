"""The slate protocol: per-event validation and the replayed per-claim state.

`ledger.validate_event` runs the common checks (init present, the reserved agent id, the
agent budget) and then `validate_event`; `ledger.apply_event` hands every event after init
to `apply_event`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bootgear_cli.clikit import current_program

from . import effort, model
from .model import Claim, Slate


def _program() -> str:
    return current_program("converge", "converge")

FRESH_EYE = "fresh-eye"
FRESH_EYE_RULE = ("choose a new angle name not listed in `used`, including names outside the fixed list; "
                  "the fixed list is not a menu for this batch. "
                  "For example, use `retry after timeout`.")
WHEN = ("before", "after")
STANCE = ("rebut", "decline")
VERDICT = ("agree", "disagree")
# Status ratchet, worst last; `unverified` is outside it.
STATUS_ORDER = ("survived", "disputed", "killed")
FIX_CHECK_OUTCOME = ("pass", "fail")
# An after cut's fix facts: whether callers change, whether data or an interface migrates.
CALLERS = ("none", "changed")
MIGRATION = ("none", "needed")


@dataclass
class CutTrack:
    """The cut rounds of one claim at one `when`."""
    rounds: dict[int, dict[str, Any]] = field(default_factory=dict)
    # The latest round the finder rebutted, and the latest it accepted.
    pending: int = 0
    accepted: int = 0

    @property
    def round(self) -> int:
        return max(self.rounds, default=0)

    def latest(self) -> dict[str, Any] | None:
        return self.rounds.get(self.round)

    def awaits_finder(self) -> bool:
        last = self.round
        return last > 0 and self.accepted < last and self.pending < last


@dataclass
class ClaimState:
    # Per batch (a positive integer or `fresh-eye`), in write order.
    attacks: dict[int | str, list[dict[str, Any]]] = field(default_factory=dict)
    replies: dict[int | str, list[dict[str, Any]]] = field(default_factory=dict)
    verdicts: dict[int | str, list[dict[str, Any]]] = field(default_factory=dict)
    status: str = "survived"
    cuts: dict[str, CutTrack] = field(default_factory=lambda: {w: CutTrack() for w in WHEN})
    refuters: set[str] = field(default_factory=set)
    cutters: set[str] = field(default_factory=set)
    rebut_hashes: dict[str, set[str]] = field(default_factory=lambda: {"reply": set(), "cut": set()})

    @property
    def rating(self) -> dict[str, Any] | None:
        """The latest `after` cut round, else the latest `before` round, else None."""
        for when in ("after", "before"):
            latest = self.cuts[when].latest()
            if latest is not None:
                return latest
        return None


def worst(a: str, b: str) -> str:
    return max(a, b, key=STATUS_ORDER.index)


def first_refuted(claim: Claim, batch: int | str) -> dict[str, Any] | None:
    return next((e for e in claim.state.attacks.get(batch, []) if e["outcome"] == "refuted"), None)


# ---------------------------------------------------------------------------
# batches


def table_batches(slate: Slate) -> list[list[str]]:
    """The attack angles in snapshot order, in fixed chunks of `caps.angles_per_claim`."""
    angles = slate.angle_ids("attack")
    size = slate.cap("angles_per_claim")
    return [angles[i:i + size] for i in range(0, len(angles), size)]


def batch_ids(slate: Slate) -> list[int | str]:
    return [*range(1, len(table_batches(slate)) + 1), FRESH_EYE]


def batch_complete(slate: Slate, claim: Claim, batch: int | str) -> bool:
    """A table batch is complete when each of its angles is attacked or not applicable; the
    fresh-eye batch after `caps.angles_per_claim` attacks or one with `last: true`."""
    attacks = claim.state.attacks.get(batch, [])
    if batch == FRESH_EYE:
        return (len(attacks) >= slate.cap("angles_per_claim")
                or any(e.get("last") is True for e in attacks))
    assert isinstance(batch, int)
    attacked = {e["angle"] for e in attacks}
    return all(a in attacked or a in claim.na_reasons for a in table_batches(slate)[batch - 1])


def batch_state(slate: Slate, claim: Claim, batch: int | str) -> str:
    """`open` while the batch takes attacks, then `done`, `awaiting-reply-1`,
    `awaiting-verdict`, `awaiting-reply-2` or `killed`."""
    if not batch_complete(slate, claim, batch):
        return "open"
    if first_refuted(claim, batch) is None:
        return "done"
    replies = claim.state.replies.get(batch, [])
    verdicts = claim.state.verdicts.get(batch, [])
    if not replies:
        return "awaiting-reply-1"
    if replies[0]["stance"] == "decline":
        return "killed"
    if not verdicts:
        return "awaiting-verdict"
    if verdicts[0]["verdict"] == "agree":
        return "done"
    if len(replies) < 2:
        return "awaiting-reply-2"
    return "killed" if replies[1]["stance"] == "decline" else "done"


def next_batch(slate: Slate, claim: Claim) -> int | str | None:
    """The claim's open batch: the first one not `done`; None once the attack is finished."""
    for batch in batch_ids(slate):
        if batch_state(slate, claim, batch) != "done":
            return batch
    return None


def open_angles(slate: Slate, claim: Claim, batch: int) -> list[str]:
    """The angles of a table batch neither attacked on nor not applicable to the claim."""
    spent = claim.used_angles | claim.na_reasons.keys()
    return [a for a in table_batches(slate)[batch - 1] if a not in spent]


def used_angles(claim: Claim) -> list[str]:
    """The angles attacked on the claim, in write order."""
    events = sorted((e for batch in claim.state.attacks.values() for e in batch),
                    key=lambda e: e["seq"])
    return [e["angle"] for e in events]


def adhoc_angles(slate: Slate) -> list[dict[str, Any]]:
    """Fresh-eye attacks on any claim naming an angle outside the fixed set, in write order."""
    fixed = set(slate.angle_ids("attack"))
    rows = [{"angle": event["angle"], "claim": claim.id, "seq": event["seq"]}
            for claim in slate.claims.values()
            for event in claim.state.attacks.get(FRESH_EYE, [])
            if event["angle"] not in fixed]
    return sorted(rows, key=lambda row: row["seq"])


def fresh_eye_role(slate: Slate, claim: Claim) -> str:
    """`r2` runs the fresh-eye batch, `r1` when the slate has one refuter or `r2` filed the
    claim (a gap-hunt claim)."""
    return "r2" if slate.init_refuters == 2 and claim.origin != "gap-hunt" else "r1"


def finder_role(claim: Claim) -> str:
    return "r2" if claim.origin == "gap-hunt" else "finder"


def _attack_role(slate: Slate, event: dict[str, Any]) -> str:
    if event.get("batch") == FRESH_EYE:
        return fresh_eye_role(slate, slate.claims[event["claim"]])
    return "r1"


def role_agents(slate: Slate) -> dict[str, str]:
    """The agent id seen first in each refuter role (`r1`, `r2`)."""
    agents: dict[str, str] = {}
    for event in slate.events:
        if event["event"] in ("clean", "attack") or (event["event"] == "angle-na" and "claim" in event):
            agents.setdefault(_attack_role(slate, event), event["as"])
    return agents


# ---------------------------------------------------------------------------
# status and phases

# Phases in order; `cut-before` and `cut-after` are skipped when `steps.cut` excludes them.
PHASES = ("find", "escalate", "cut-before", "attack", "cut-after", "cutoff", "done")
CLAIM_PHASES = ("escalate", "cut-before", "attack", "cut-after")


def status(slate: Slate, claim: Claim, unverified: set[str] | None = None) -> str:
    """`killed`, `unverified`, `disputed` or `survived`."""
    if claim.state.status == "killed":
        return "killed"
    if claim.id in (unverified_ids(slate) if unverified is None else unverified):
        return "unverified"
    return claim.state.status


def _cut_steps(slate: Slate) -> tuple[str, ...]:
    mode = slate.config["steps"]["cut"]
    return tuple(w for w in WHEN if mode in (w, "both"))


def claim_open(slate: Slate, claim: Claim, phase: str, unverified: set[str]) -> bool:
    """The claim has an open item of `phase`."""
    if not claim.live:
        return False
    if phase == "escalate":
        return bool(slate.config["steps"]["escalate"]) and claim.escalation is None
    if phase == "cut-before":
        return ("before" in _cut_steps(slate)
                and cut_track_state(claim.state.cuts["before"], slate.cap("cut_rounds")) == "open")
    if claim.id in unverified:
        return False
    if phase == "attack":
        return next_batch(slate, claim) is not None
    return ("after" in _cut_steps(slate)
            and cut_track_state(claim.state.cuts["after"], slate.cap("cut_rounds")) == "open")


def claim_phase(slate: Slate, claim: Claim) -> str | None:
    """The first phase in which the claim has an open item, or None."""
    unverified = unverified_ids(slate)
    return next((p for p in CLAIM_PHASES if claim_open(slate, claim, p, unverified)), None)


def _find_open(slate: Slate) -> bool:
    from .render import coverage

    return any(row.missing for row in coverage(slate).values())


def slate_phase(slate: Slate) -> str:
    """The first phase, in `PHASES` order, with an open item."""
    if _find_open(slate):
        return "find"
    unverified = unverified_ids(slate)
    for phase in CLAIM_PHASES:
        if any(claim_open(slate, c, phase, unverified) for c in slate.claims.values()):
            return phase
    return "done" if slate.cutoff_valid else "cutoff"


# ---------------------------------------------------------------------------
# cut


def _cut_values(event: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(event.get(f) for f in (*model.CUT_FIELDS, *model.AFTER_FIELDS))


def cut_track_state(track: CutTrack, cap: int) -> str:
    """`converged` when the finder accepted the latest round and has not rebutted it, or the
    round after a rebut repeats the same values; `capped` at `cap` rounds; else `open`."""
    last = track.round
    if last == 0:
        return "open"
    if track.accepted == last and track.pending < last:
        return "converged"
    if (last >= 2 and track.pending == last - 1
            and _cut_values(track.rounds[last]) == _cut_values(track.rounds[last - 1])):
        return "converged"
    return "capped" if last >= cap else "open"


def _first_match(rules: list[dict[str, Any]], values: dict[str, Any]) -> int | None:
    return next((i for i, rule in enumerate(rules) if model.rule_matches(rule, values)), None)


def _rule_values(claim: Claim, rating: dict[str, Any], *fields: str) -> dict[str, Any]:
    """The cut's `fields` plus the claim's tier, lens and origin, for a rule match."""
    values = {f: rating.get(f) for f in fields}
    values.update(tier=claim.tier, lens=claim.lens, origin=claim.origin)
    return values


def _report_rule(slate: Slate, claim: Claim) -> str | None:
    """`report_rules[<rule>]` when the claim's rule is in `cutoff.report_rules`."""
    if claim.rule is not None and claim.rule in slate.config["cutoff"]["report_rules"]:
        return f"report_rules[{claim.rule}]"
    return None


def gate1(slate: Slate, claim: Claim, rating: dict[str, Any] | None) -> tuple[bool, str]:
    """Attack or skip, from the `before` rating: (attacked, reason). A claim under
    `report_rules` or with no before rating is attacked; otherwise the lens's `attack_if`
    decides."""
    reported = _report_rule(slate, claim)
    if reported is not None:
        return True, reported
    if rating is None:
        return True, "cut none"
    matched = _first_match(slate.lens_policy(claim.lens).get("attack_if", []),
                           _rule_values(claim, rating, *model.CUT_FIELDS))
    return (False, "no rule matched") if matched is None else (True, f"attack_if[{matched}]")


def cheap(slate: Slate, claim: Claim) -> bool:
    """A cheap fix: `cutoff.cheap.enabled`, the claim survived, and its after cut typed
    trivial or local (checks 1-5, validated at the cut) and closed by the finder's accept
    (check 6)."""
    track = claim.state.cuts["after"]
    latest = track.latest()
    return (bool(slate.config["cutoff"]["cheap"]["enabled"]) and claim.state.status == "survived"
            and latest is not None and latest.get("difficulty") in model.CHEAP_DIFFICULTY
            and track.accepted == track.round and track.pending < track.round)


def gate2(slate: Slate, claim: Claim, rating: dict[str, Any] | None) -> tuple[str, str]:
    """`fix-now`, `finding` or `follow-up` from the latest rating and the claim's status:
    (result, reason). In order: a claim under `report_rules` or with no rating is a finding; a
    cheap fix is fix-now; a `report_if` match is a finding; the rest are follow-ups. The
    per-lens cap is applied by `gate_results`."""
    reported = _report_rule(slate, claim)
    if reported is not None:
        return "finding", reported
    if rating is None:
        return "finding", "cut none"
    check = claim.fix_check
    if check is not None and check["outcome"] == "pass":
        return "fixed", "fix-check passed"
    if check is None and cheap(slate, claim):
        return "fix-now", f"cheap ({rating['difficulty']})"
    values = _rule_values(claim, rating, *model.CUT_FIELDS, *model.AFTER_FIELDS)
    values["status"] = claim.state.status
    matched = _first_match(slate.lens_policy(claim.lens).get("report_if", []), values)
    if check is not None:
        return ("follow-up" if matched is None else "finding"), "fix-check failed"
    return ("follow-up", "no rule matched") if matched is None else (
        "finding", f"report_if[{matched}]")


def unverified_ids(slate: Slate) -> set[str]:
    """Claims gate 1 skipped that were never attacked; empty unless `steps.cut` is `before`
    or `both`."""
    if "before" not in _cut_steps(slate):
        return set()
    return {claim.id for claim in slate.claims.values()
            if not gate1(slate, claim, claim.state.cuts["before"].latest())[0]
            and not claim.state.attacks}


def gate_results(slate: Slate) -> dict[str, tuple[str, str]]:
    """Per live claim, its result and reason: unverified claims are follow-ups; the rest take
    gate 2 in rank order, and a finding past its lens's `caps.per_lens` is a follow-up. Only
    findings count toward the cap, and a `report_rules` finding takes no slot."""
    unverified = unverified_ids(slate)
    counts: dict[str | None, int] = {}
    results: dict[str, tuple[str, str]] = {}
    for claim in sorted(slate.live_claims(), key=model.rank_key):
        if claim.id in unverified:
            results[claim.id] = ("follow-up", "unverified")
            continue
        result, reason = gate2(slate, claim, claim.state.rating)
        if result == "finding" and _report_rule(slate, claim) is None:
            counts[claim.lens] = counts.get(claim.lens, 0) + 1
            cap = slate.lens_cap(claim.lens)
            if counts[claim.lens] > cap:
                result, reason = "follow-up", f"per-lens cap {cap} ({claim.lens})"
        results[claim.id] = (result, reason)
    return results


def cut_reasons(slate: Slate) -> dict[str, tuple[bool, str]]:
    """Per live claim, `cut` (its result is a follow-up) and its reason."""
    return {cid: (result == "follow-up", reason)
            for cid, (result, reason) in gate_results(slate).items()}


def cut_flags(slate: Slate) -> dict[str, bool]:
    return {cid: cut for cid, (cut, _) in cut_reasons(slate).items()}


def artifact_patch_eligible(slate: Slate, claim: Claim) -> bool:
    """Measure artifact patch limits separately from implementation remedy difficulty."""
    rating = claim.state.rating or {}
    patch = rating.get("patch")
    if not isinstance(patch, str) or not patch.strip() or slate.project_root is None:
        return False
    limits = slate.config["cutoff"]["cheap"]
    root = Path(slate.project_root)
    try:
        size = effort.measure(patch, limits["test_globs"], root)
    except effort.EffortError:
        return False
    line_limit = limits["trivial_lines"] if rating.get("difficulty") == "trivial" else limits["lines"]
    loc_path = claim.loc.rsplit(":", 1)[0]
    return (size["files"] <= limits["files"] and size["test_files"] <= limits["tests"]
            and size["lines"] <= line_limit
            and all(effort.same_file(path, loc_path, root) for path in size["paths"]))


# ---------------------------------------------------------------------------
# result


def compute_cutoff(slate: Slate) -> list[model.CutoffRow]:
    """One row per claim: live claims in rank order, then killed claims."""
    results = gate_results(slate)
    unverified = unverified_ids(slate)
    live = sorted(slate.live_claims(), key=model.rank_key)
    killed = sorted((c for c in slate.claims.values() if not c.live), key=model.rank_key)
    rows: list[model.CutoffRow] = []
    for rank, claim in enumerate([*live, *killed], start=1):
        if not claim.live:
            rows.append(model.CutoffRow(claim, "killed", "no", "killed", rank, "killed"))
            continue
        result, reason = results[claim.id]
        rows.append(model.CutoffRow(claim, status(slate, claim, unverified),
                                    "yes" if result == "follow-up" else "no", result, rank,
                                    reason))
    return rows


def cutoff_results(rows: list[model.CutoffRow]) -> list[dict[str, Any]]:
    return [{"claim": row.claim.id, "status": row.status, "cut": row.cut, "result": row.result,
             "rank": row.rank, "reason": row.reason} for row in rows]


def converged(slate: Slate) -> bool:
    """The slate is done and no claim is `disputed` with `cut: no`."""
    if slate_phase(slate) != "done":
        return False
    flags = cut_flags(slate)
    return not any(claim.state.status == "disputed" and not flags[claim.id]
                   for claim in slate.live_claims())


# ---------------------------------------------------------------------------
# plan


def _plan_row(claim: Claim, action: str, role: str, batch: int | str | None = None,
              angles: list[str] | None = None, used: list[str] | None = None,
              rule: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"claim": claim.id, "action": action, "agent_role": role,
                           "batch": batch, "angles": angles or []}
    if used is not None:
        row["used"] = used
    if rule is not None:
        row["rule"] = rule
    return row


def _claim_rows(slate: Slate, claim: Claim, phase: str) -> dict[str, Any]:
    if phase == "escalate":
        return _plan_row(claim, "escalate", finder_role(claim))
    if phase in ("cut-before", "cut-after"):
        track = claim.state.cuts[phase.removeprefix("cut-")]
        if track.awaits_finder():
            return _plan_row(claim, "accept", finder_role(claim))
        return _plan_row(claim, phase, "cutter")
    batch = next_batch(slate, claim)
    assert batch is not None
    state = batch_state(slate, claim, batch)
    if state == "open":
        if batch == FRESH_EYE:
            return _plan_row(claim, "attack", fresh_eye_role(slate, claim), batch,
                             used=used_angles(claim), rule=FRESH_EYE_RULE)
        assert isinstance(batch, int)
        return _plan_row(claim, "attack", "r1", batch, open_angles(slate, claim, batch))
    if state == "awaiting-verdict":
        role = fresh_eye_role(slate, claim) if batch == FRESH_EYE else "r1"
        return _plan_row(claim, "verdict", role, batch)
    return _plan_row(claim, "reply", finder_role(claim), batch)


def batch_plan(slate: Slate) -> list[list[dict[str, Any]]]:
    """One row per open item of the current phase, in rank order, in chunks of
    `caps.batch_items`."""
    phase = slate_phase(slate)
    if phase not in CLAIM_PHASES:
        return []
    unverified = unverified_ids(slate)
    rows = [_claim_rows(slate, claim, phase)
            for claim in sorted(slate.claims.values(), key=model.rank_key)
            if claim_open(slate, claim, phase, unverified)]
    size = slate.cap("batch_items")
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def _live(claim: Claim | None, problems: list[str]) -> Claim | None:
    if claim is not None and not claim.live:
        problems.append(f"{claim.id} is killed; it accepts nothing")
        return None
    return claim
