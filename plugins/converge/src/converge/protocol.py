"""The slate protocol: per-event validation and the replayed per-claim state.

`ledger.validate_event` runs the common checks (init present, the reserved agent id, the
agent budget) and then `validate_event`; `ledger.apply_event` hands every event after init
to `apply_event`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import ledger, model
from .model import Claim, Slate

FRESH_EYE = "fresh-eye"
WHEN = ("before", "after")
ATTACK_OUTCOME = ("clean", "refuted")
STANCE = ("rebut", "decline")
VERDICT = ("agree", "disagree")
# Status ratchet, worst last; `unverified` is outside it.
STATUS_ORDER = ("survived", "disputed", "killed")
BEFORE_CONFIDENCE = "inferred"


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
    return all(a in attacked or a in claim.na_angles for a in table_batches(slate)[batch - 1])


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
    spent = claim.used_angles | claim.na_angles
    return [a for a in table_batches(slate)[batch - 1] if a not in spent]


def used_angles(claim: Claim) -> list[str]:
    """The angles attacked on the claim, in write order."""
    events = sorted((e for batch in claim.state.attacks.values() for e in batch),
                    key=lambda e: e["seq"])
    return [e["angle"] for e in events]


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
        if event["event"] == "attack" or (event["event"] == "angle-na" and "claim" in event):
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


def _values(event: dict[str, Any]) -> tuple[str, ...]:
    return tuple(event[f] for f in model.CUT_FIELDS)


def cut_track_state(track: CutTrack, cap: int) -> str:
    """`converged` when the finder accepted the latest round and has not rebutted it, or the
    round after a rebut repeats the same four values; `capped` at `cap` rounds; else `open`."""
    last = track.round
    if last == 0:
        return "open"
    if track.accepted == last and track.pending < last:
        return "converged"
    if (last >= 2 and track.pending == last - 1
            and _values(track.rounds[last]) == _values(track.rounds[last - 1])):
        return "converged"
    return "capped" if last >= cap else "open"


def _rule_reason(slate: Slate, claim: Claim, rating: dict[str, Any]) -> str | None:
    """The cutoff rule that reports the claim, or None when it is below the line."""
    cutoff = slate.config["cutoff"]
    if claim.rule is not None and claim.rule in cutoff.get("report_rules", []):
        return f"report_rules[{claim.rule}]"
    key = "report_if_gap_hunt" if claim.origin == "gap-hunt" else "report_if"
    values: dict[str, str | None] = {f: rating.get(f) for f in model.CUT_FIELDS}
    values["origin"] = claim.origin
    values["lens"] = claim.lens
    matched = next((i for i, rule in enumerate(cutoff[key]) if model.rule_matches(rule, values)),
                   None)
    return None if matched is None else f"{key}[{matched}]"


def _cut_reasons(slate: Slate, claims: list[Claim],
                 rating_of: Callable[[Claim], dict[str, Any] | None]
                 ) -> dict[str, tuple[bool, str]]:
    """Per claim, `cut` and its reason from the cutoff table and the per-lens cap, ranking the
    claims within their lens by `rating_of`. A claim whose `rule` is in `cutoff.report_rules`
    takes no rank slot and is never cut by the cap."""
    report_rules = slate.config["cutoff"].get("report_rules", [])
    ranked = sorted(claims, key=lambda c: model.rating_key(rating_of(c), c.id))
    counts: dict[str | None, int] = {}
    reasons: dict[str, tuple[bool, str]] = {}
    for claim in ranked:
        exempt = claim.rule is not None and claim.rule in report_rules
        if not exempt:
            counts[claim.lens] = counts.get(claim.lens, 0) + 1
        rating = rating_of(claim)
        if rating is None:
            reasons[claim.id] = (False, "cut none")
            continue
        rule = _rule_reason(slate, claim, rating)
        cap = slate.lens_cap(claim.lens)
        if rule is None:
            reasons[claim.id] = (True, "no rule matched")
        elif not exempt and counts[claim.lens] > cap:
            reasons[claim.id] = (True, f"per-lens cap {cap} ({claim.lens})")
        else:
            reasons[claim.id] = (False, rule)
    return reasons


def unverified_ids(slate: Slate) -> set[str]:
    """Claims cut by their `before` ratings that were never attacked; empty unless
    `steps.cut` is `before` or `both`. Every claim ranks here: none is killed before the
    attack."""
    if "before" not in _cut_steps(slate):
        return set()
    reasons = _cut_reasons(slate, list(slate.claims.values()),
                           lambda c: c.state.cuts["before"].latest())
    return {cid for cid, (cut, _) in reasons.items()
            if cut and not slate.claims[cid].state.attacks}


def cut_reasons(slate: Slate) -> dict[str, tuple[bool, str]]:
    """Per live claim, `cut` and its reason; an unverified claim is always cut."""
    reasons = _cut_reasons(slate, slate.live_claims(), lambda c: c.state.rating)
    for cid in unverified_ids(slate):
        reasons[cid] = (True, "unverified")
    return reasons


def cut_flags(slate: Slate) -> dict[str, bool]:
    return {cid: cut for cid, (cut, _) in cut_reasons(slate).items()}


# ---------------------------------------------------------------------------
# validation


def validate_event(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """Every problem with appending `event`, a kind other than init, to `slate`."""
    {"file": _validate_file, "escalate": _validate_escalate, "find-run": _validate_find_run,
     "angle-na": _validate_angle_na, "attack": _validate_attack, "reply": _validate_reply,
     "verdict": _validate_verdict, "cut": _validate_cut, "accept": _validate_accept,
     "rebut": _validate_rebut, "cutoff": ledger.validate_cutoff,
     }[event["event"]](slate, event, problems)
    _gate(slate, event, problems)


def _needed_phase(event: dict[str, Any]) -> str | None:
    kind = event["event"]
    if kind == "escalate":
        return "escalate"
    if kind in ("cut", "accept", "rebut"):
        when = event.get("when")
        return f"cut-{when}" if when in WHEN else None
    if kind in ("attack", "reply", "verdict") or (kind == "angle-na"
                                                  and event.get("phase") == "attack"):
        return "attack"
    return None


def _gate(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """The phase gate: an event is accepted only in the phase of its kind, and only for a
    claim with an open item of that phase."""
    needed = _needed_phase(event)
    if needed is None:
        return
    kind = event["event"]
    phase = slate_phase(slate)
    if phase != needed:
        problems.append(f"{kind}: the slate is in phase {phase}; {kind} needs phase {needed}")
        return
    cid = event.get("claim")
    claim = slate.claims.get(cid) if isinstance(cid, str) else None
    if claim is None or not claim.live or needed == "escalate":
        return
    if needed == "attack":
        _attack_item(slate, claim, event, problems)
    else:
        _cut_item(slate, claim, event, problems)


def _cut_item(slate: Slate, claim: Claim, event: dict[str, Any], problems: list[str]) -> None:
    kind, when = event["event"], event["when"]
    if when == "after" and claim.id in unverified_ids(slate):
        problems.append(f"{kind}: {claim.id} is unverified; it takes no after cut")
        return
    state = cut_track_state(claim.state.cuts[when], slate.cap("cut_rounds"))
    # A rebut reopens a converged cut; nothing reopens a capped one.
    allowed = ("open", "converged") if kind == "rebut" else ("open",)
    if state not in allowed:
        problems.append(f"{kind}: {claim.id} {when} cut is {state}; it takes no more {kind}")


ITEM_STATES = {"attack": ("open",), "angle-na": ("open",),
               "reply": ("awaiting-reply-1", "awaiting-reply-2"),
               "verdict": ("awaiting-verdict",)}


def _valid_batch(value: Any) -> bool:
    return value == FRESH_EYE or (isinstance(value, int) and not isinstance(value, bool)
                                  and value >= 1)


def _attack_item(slate: Slate, claim: Claim, event: dict[str, Any], problems: list[str]) -> None:
    """The event belongs to the claim's open batch, in the batch state its kind needs."""
    kind = event["event"]
    if claim.id in unverified_ids(slate):
        problems.append(f"{kind}: {claim.id} is unverified (cut before the attack); "
                        f"it takes no attack")
        return
    current = next_batch(slate, claim)
    if current is None:
        problems.append(f"{kind}: {claim.id} has finished its attack")
        return
    state = batch_state(slate, claim, current)
    if kind == "angle-na":
        if current == FRESH_EYE:
            problems.append(f"angle-na: {claim.id}'s open batch is {FRESH_EYE}; not-applicable "
                            f"angles are recorded in table batches")
            return
    else:
        batch = event.get("batch")
        if not _valid_batch(batch):
            return
        if batch != current:
            problems.append(f"{kind}: {claim.id}'s open batch is {current} ({state}); "
                            f"got batch {batch}")
            return
    needs = ITEM_STATES[kind]
    if state not in needs:
        problems.append(f"{kind}: {claim.id} batch {current} is {state}; "
                        f"{kind} needs {' or '.join(needs)}")
        return
    angle = event.get("angle")
    if kind in ("attack", "angle-na") and isinstance(current, int) and isinstance(angle, str) \
            and slate.angle("attack", angle) is not None:
        chunk = table_batches(slate)[current - 1]
        if angle not in chunk:
            problems.append(f"{kind}: angle {angle!r} is not in {claim.id}'s open batch "
                            f"{current} ({', '.join(chunk)})")


def _refuter_role(slate: Slate, claim: Claim, agent: Any, batch: Any, kind: str,
                  problems: list[str]) -> None:
    """Table batches are attacked by `r1`; the fresh-eye batch by `fresh_eye_role`."""
    role = fresh_eye_role(slate, claim) if batch == FRESH_EYE else "r1"
    agents = role_agents(slate)
    r1, r2 = agents.get("r1"), agents.get("r2")
    where = f"the fresh-eye batch of {claim.id} is" if batch == FRESH_EYE else "table batches are"
    if role == "r1":
        if r1 is not None and agent != r1:
            problems.append(f"{kind}: {where} attacked by r1 ({r1}), not {agent}")
    elif agent == r1:
        problems.append(f"{kind}: {where} attacked by r2, not r1 ({r1})")
    elif r2 is not None and agent != r2:
        problems.append(f"{kind}: {where} attacked by r2 ({r2}), not {agent}")


def _written(slate: Slate, kinds: tuple[str, ...]) -> bool:
    return any(e["event"] in kinds for e in slate.events)


def _batch(event: dict[str, Any], problems: list[str]) -> int | str | None:
    value = event.get("batch")
    if _valid_batch(value):
        return value
    problems.append(f"`batch` must be a positive integer or {FRESH_EYE}; got {value!r}")
    return None


def _live(claim: Claim | None, problems: list[str]) -> Claim | None:
    if claim is not None and not claim.live:
        problems.append(f"{claim.id} is killed; it accepts nothing")
        return None
    return claim


def _given(event: dict[str, Any], key: str) -> bool:
    value = event.get(key)
    return isinstance(value, str) and bool(value.strip())


def _rebut_evidence(event: dict[str, Any], problems: list[str]) -> str | None:
    evidence = ledger.nonempty(event, "evidence", problems)
    if evidence is not None and event.get("evidence_sha256") != ledger.evidence_hash(evidence):
        problems.append("`evidence_sha256` does not match the evidence")
    return evidence


def _validate_file(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    if _written(slate, ("escalate", "cut", "attack")):
        problems.append("file: claims are filed before the first escalate, cut or attack event")
    expected = model.claim_id(len(slate.claims) + 1)
    if event.get("id") != expected:
        problems.append(f"file: claim id must be {expected}; got {event.get('id')!r}")
    origin = ledger.enum(event, "origin", model.ORIGIN, problems)
    if origin == "gap-hunt" and slate.init_refuters != 2:
        problems.append("file: a one-refuter slate has no gap hunt; r2 files gap-hunt claims "
                        "and this slate has no r2")
    if origin == "gap-hunt" and _find_open(slate):
        problems.append("file: gap-hunt claims are filed after find coverage is complete")
    loc = event.get("loc")
    if not isinstance(loc, str) or not model.LOC_RE.match(loc):
        problems.append(f"`loc` must match path:line ({model.LOC_RE.pattern}); got {loc!r}")
    ledger.nonempty(event, "claim", problems)
    ledger.nonempty(event, "trigger", problems)
    if "rule" in event:
        ledger.nonempty(event, "rule", problems)
    depends = event.get("depends", [])
    if not isinstance(depends, list):
        problems.append("`depends` must be a list of claim ids")
    else:
        for dep in depends:
            if dep not in slate.claims:
                problems.append(f"`depends` names unknown claim {dep!r}")
    lens = ledger.nonempty(event, "lens", problems)
    row = ledger.angle(slate, "find", event.get("angle"), problems)
    ledger.angle_lens(row, lens, problems)
    if origin == "lens" and lens is not None and lens not in slate.lenses:
        problems.append(f"lens {lens!r} is not an init lens ({', '.join(slate.lenses)})")


def _validate_escalate(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """The finder widens its claim, or confirms it, once, before any cut or attack."""
    if _written(slate, ("cut", "attack")):
        problems.append("escalate: escalate comes before the first cut or attack event")
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    for key in ("wider", "evidence"):
        if key in event:
            ledger.nonempty(event, key, problems)
    if ("wider" in event) != ("evidence" in event):
        problems.append("escalate: `wider` and `evidence` are given together")
    if claim is None:
        return
    if agent != claim.finder:
        problems.append(f"escalate: only {claim.id}'s finder {claim.finder} may escalate")
    if claim.escalation is not None:
        problems.append(f"escalate: {claim.id} is already escalated")


def _validate_find_run(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    lens = ledger.nonempty(event, "lens", problems)
    row = ledger.angle(slate, "find", event.get("angle"), problems)
    ledger.angle_lens(row, lens, problems)
    for key in ("tell", "searches", "positive_control"):
        ledger.nonempty(event, key, problems)
    result = event.get("result")
    if result == "none":
        return
    if not isinstance(result, list) or not result:
        problems.append("`result` must be `none` or a non-empty list of claim ids")
        return
    for cid in result:
        claim = slate.claims.get(cid)
        if claim is None:
            problems.append(f"`result` names unknown claim {cid!r}")
        elif claim.finder != event.get("as"):
            problems.append(f"`result` claim {cid} was filed by {claim.finder}, not {event.get('as')}")


def _validate_angle_na(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """A find angle not applicable to a lens, or an attack angle not applicable to one claim."""
    phase = ledger.enum(event, "phase", model.PHASE, problems)
    ledger.nonempty(event, "reason", problems)
    if phase is None:
        return
    row = ledger.angle(slate, phase, event.get("angle"), problems)
    if phase == "find":
        lens = ledger.nonempty(event, "lens", problems)
        ledger.angle_lens(row, lens, problems)
        if "claim" in event:
            problems.append("angle-na: `claim` is only recorded for phase attack")
        return
    if "lens" in event:
        problems.append("`lens` is only recorded for phase find")
    if "claim" not in event:
        problems.append("angle-na: phase attack needs `claim`")
        return
    claim = _live(ledger.known_claim(slate, event, problems), problems)
    if claim is None:
        return
    ledger.roles(slate, claim, event.get("as"), "attack", problems)
    _refuter_role(slate, claim, event.get("as"), None, "angle-na", problems)
    if row is not None and row["id"] in claim.used_angles:
        problems.append(f"angle-na: angle {row['id']!r} was already used on {claim.id}")
    elif row is not None and row["id"] in claim.na_angles:
        problems.append(f"angle-na: angle {row['id']!r} is already recorded not applicable "
                        f"to {claim.id}")


def _validate_attack(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    batch = _batch(event, problems)
    ledger.enum(event, "outcome", ATTACK_OUTCOME, problems)
    for key in ("tell", "evidence", "searches", "positive_control"):
        ledger.nonempty(event, key, problems)
    if "last" in event:
        if batch != FRESH_EYE:
            problems.append(f"attack: `last` is given only with batch {FRESH_EYE}")
        elif not isinstance(event["last"], bool):
            problems.append(f"attack: `last` must be true or false; got {event['last']!r}")
    if batch == FRESH_EYE:
        angle = ledger.nonempty(event, "angle", problems)
    else:
        row = ledger.angle(slate, "attack", event.get("angle"), problems)
        angle = row["id"] if row is not None else None
    claim = _live(claim, problems)
    if claim is None:
        return
    ledger.roles(slate, claim, agent, "attack", problems)
    if batch is not None:
        _refuter_role(slate, claim, agent, batch, "attack", problems)
    if angle is None:
        return
    if angle in claim.used_angles:
        problems.append(f"attack: angle {angle!r} was already used on {claim.id}")
    elif batch != FRESH_EYE and angle in claim.na_angles:
        problems.append(f"attack: angle {angle!r} is recorded not applicable to {claim.id}")


def _validate_reply(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    batch = _batch(event, problems)
    stance = ledger.enum(event, "stance", STANCE, problems)
    evidence = None
    if stance == "rebut":
        evidence = _rebut_evidence(event, problems)
        if "text" in event:
            ledger.nonempty(event, "text", problems)
    elif stance == "decline":
        if "evidence" in event or "evidence_sha256" in event:
            problems.append("reply: decline carries no evidence")
        if "text" in event:
            problems.append("reply: `text` is given only with stance rebut")
    claim = _live(claim, problems)
    if claim is None or batch is None:
        return
    if agent != claim.finder:
        problems.append(f"reply: only {claim.id}'s finder {claim.finder} may reply")
    if first_refuted(claim, batch) is None:
        problems.append(f"reply: batch {batch} of {claim.id} has no refuted attack")
    if evidence is not None and ledger.evidence_hash(evidence) in claim.state.rebut_hashes["reply"]:
        problems.append(f"reply: this evidence was already given for {claim.id}; "
                        f"a rebut needs new evidence")


def _validate_verdict(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    batch = _batch(event, problems)
    verdict = ledger.enum(event, "verdict", VERDICT, problems)
    if verdict == "disagree" and not _given(event, "evidence"):
        problems.append("verdict: disagree needs `evidence`")
    elif "evidence" in event:
        ledger.nonempty(event, "evidence", problems)
    claim = _live(claim, problems)
    if claim is None or batch is None:
        return
    first = first_refuted(claim, batch)
    if first is None:
        problems.append(f"verdict: batch {batch} of {claim.id} has no refuted attack")
    elif agent != first["as"]:
        problems.append(f"verdict: only {first['as']}, who recorded the first refuted attack of "
                        f"{claim.id} batch {batch}, gives the verdict")
    ledger.roles(slate, claim, agent, "verdict", problems)


def _cut_evidence(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    evidence = event.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        problems.append("`evidence` must map evaluate angle ids to evidence text")
        return
    covered: set[str] = set()
    for key, text in evidence.items():
        row = ledger.angle(slate, "evaluate", key, problems)
        if not isinstance(text, str) or not text.strip():
            problems.append(f"evidence for {key!r} must be non-empty text")
        if row is not None and row.get("field"):
            covered.add(row["field"])
    for name in model.CUT_FIELDS:
        if name not in covered:
            problems.append(f"cut: no evidence for `{name}` (give an evaluate angle whose field is {name})")


def _validate_cut(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    when = ledger.enum(event, "when", WHEN, problems)
    rnd = ledger.round_number(event, problems)
    values = {f: ledger.enum(event, f, model.FIELD_ENUMS[f], problems) for f in model.CUT_FIELDS}
    confidence = values["confidence"]
    if when == "before" and confidence is not None and confidence != BEFORE_CONFIDENCE:
        problems.append(f"cut: a before cut has confidence {BEFORE_CONFIDENCE}; got {confidence!r}")
    for key in ("choice", "fix"):
        if key in event:
            ledger.nonempty(event, key, problems)
    _cut_evidence(slate, event, problems)
    claim = _live(claim, problems)
    if claim is None:
        return
    ledger.roles(slate, claim, agent, "cut", problems)
    if values["difficulty"] in model.CHOICE_DIFFICULTY and not _given(event, "choice"):
        problems.append(f"cut: {claim.id} has difficulty {values['difficulty']}; "
                        f"a non-empty `choice` is required")
    if when is None:
        return
    track = claim.state.cuts[when]
    if track.awaits_finder():
        problems.append(f"cut: {claim.id} {when} round {track.round} awaits its finder; "
                        f"the finder must accept or rebut it first")
    if rnd is not None:
        expected = track.round + 1
        cap = slate.cap("cut_rounds")
        if rnd > cap:
            problems.append(f"cut: round {rnd} exceeds caps.cut_rounds {cap}")
        elif rnd != expected:
            problems.append(f"cut: {claim.id} next {when} cut round is {expected}, got {rnd}")


def _validate_accept(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    when = ledger.enum(event, "when", WHEN, problems)
    rnd = ledger.round_number(event, problems)
    claim = _live(claim, problems)
    if claim is None or rnd is None or when is None:
        return
    if agent != claim.finder:
        problems.append(f"accept: only {claim.id}'s finder {claim.finder} may accept")
    track = claim.state.cuts[when]
    last = track.round
    if last == 0:
        problems.append(f"accept: {claim.id} has no {when} cut round to accept")
    elif rnd != last:
        problems.append(f"accept: {claim.id} latest {when} cut round is {last}, got {rnd}")
    elif track.accepted == last:
        problems.append(f"accept: {claim.id} {when} cut round {last} is already accepted")
    elif track.pending == last:
        problems.append(f"accept: {claim.id} {when} cut round {last} was rebutted; "
                        f"answer the next cut round")


def _validate_rebut(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """The finder challenges the latest cut round with new evidence."""
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    when = ledger.enum(event, "when", WHEN, problems)
    evidence = _rebut_evidence(event, problems)
    claim = _live(claim, problems)
    if claim is None or when is None:
        return
    if agent != claim.finder:
        problems.append(f"rebut: only {claim.id}'s finder {claim.finder} may rebut")
    if claim.state.cuts[when].round == 0:
        problems.append(f"rebut: {claim.id} has no {when} cut round to rebut")
    if evidence is not None and ledger.evidence_hash(evidence) in claim.state.rebut_hashes["cut"]:
        problems.append(f"rebut: this evidence was already given for {claim.id}; "
                        f"a rebut needs new evidence")


# ---------------------------------------------------------------------------
# apply


def apply_event(slate: Slate, event: dict[str, Any]) -> None:
    """Replay one event after init; the event is already in `slate.events`."""
    kind = event["event"]
    if kind == "cutoff":
        slate.cutoff = event
        slate.cutoff_valid = True
        return
    if kind == "file":
        slate.claims[event["id"]] = Claim(
            id=event["id"], finder=event["as"], lens=event.get("lens"), angle=event.get("angle"),
            loc=event["loc"], original=event["claim"], text=event["claim"],
            trigger=event["trigger"], origin=event["origin"], depends=list(event.get("depends", [])),
            rule=event.get("rule"), filed_seq=event["seq"], state=ClaimState(),
        )
    elif kind == "find-run":
        slate.find_runs.append(event)
    elif kind == "angle-na":
        slate.angle_na.append(event)
        if "claim" in event:
            slate.claims[event["claim"]].na_angles.add(event["angle"])
    else:
        _apply_claim_event(slate.claims[event["claim"]], event)
    if any(track.rounds for claim in slate.claims.values() for track in claim.state.cuts.values()):
        slate.cutoff_valid = False


def _apply_claim_event(claim: Claim, event: dict[str, Any]) -> None:
    kind = event["event"]
    state = claim.state
    if kind == "escalate":
        claim.escalation = event
        if "wider" in event:
            claim.text = event["wider"]
    elif kind == "attack":
        state.attacks.setdefault(event["batch"], []).append(event)
        state.refuters.add(event["as"])
        claim.used_angles.add(event["angle"])
    elif kind == "reply":
        replies = state.replies.setdefault(event["batch"], [])
        replies.append(event)
        if event["stance"] == "decline":
            state.status = "killed"
            return
        state.rebut_hashes["reply"].add(event["evidence_sha256"])
        if "text" in event:
            claim.text = event["text"]
        if len(replies) >= 2:
            state.status = worst(state.status, "disputed")
    elif kind == "verdict":
        state.verdicts.setdefault(event["batch"], []).append(event)
        if event["verdict"] == "agree":
            state.status = worst(state.status, "survived")
    elif kind == "cut":
        state.cuts[event["when"]].rounds[event["round"]] = event
        state.cutters.add(event["as"])
    elif kind == "accept":
        state.cuts[event["when"]].accepted = event["round"]
    elif kind == "rebut":
        track = state.cuts[event["when"]]
        state.rebut_hashes["cut"].add(event["evidence_sha256"])
        track.pending = track.round


# ---------------------------------------------------------------------------
# result


def compute_cutoff(slate: Slate) -> list[model.CutoffRow]:
    """One row per claim: live claims in rank order, then killed claims."""
    reasons = cut_reasons(slate)
    unverified = unverified_ids(slate)
    live = sorted(slate.live_claims(), key=model.rank_key)
    killed = sorted((c for c in slate.claims.values() if not c.live), key=model.rank_key)
    rows: list[model.CutoffRow] = []
    for rank, claim in enumerate([*live, *killed], start=1):
        if not claim.live:
            rows.append(model.CutoffRow(claim, "killed", "no", "killed", rank, "killed"))
            continue
        cut, reason = reasons[claim.id]
        rows.append(model.CutoffRow(claim, status(slate, claim, unverified), "yes" if cut else "no",
                                    "follow-up" if cut else "finding", rank, reason))
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
              angles: list[str] | None = None) -> dict[str, Any]:
    return {"claim": claim.id, "action": action, "agent_role": role, "batch": batch,
            "angles": angles or []}


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
                             used_angles(claim))
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
