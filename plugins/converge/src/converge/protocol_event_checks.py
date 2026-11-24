"""Validate slate events before they can be appended."""

from __future__ import annotations

from typing import Any

from . import assignments, ledger, model, native_launch
from .model import Claim, Slate
from .protocol import (
    FRESH_EYE,
    STANCE,
    VERDICT,
    WHEN,
    _find_open,
    _live,
    batch_state,
    cut_track_state,
    first_refuted,
    fresh_eye_role,
    next_batch,
    role_agents,
    slate_phase,
    table_batches,
    unverified_ids,
)
from .protocol_cut_checks import (
    _validate_accept,
    _validate_cut,
    _validate_fix_check,
    _validate_rebut,
)

# ---------------------------------------------------------------------------
# validation


def validate_event(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """Every problem with appending `event`, a kind other than init, to `slate`."""
    {"file": _validate_file, "escalate": _validate_escalate, "find-run": _validate_find_run,
     "gap-hunt-done": _validate_gap_hunt_done,
     "angle-na": _validate_angle_na, "clean": _validate_clean, "attack": _validate_attack, "reply": _validate_reply,
     "verdict": _validate_verdict, "cut": _validate_cut, "accept": _validate_accept,
     "rebut": _validate_rebut, "cutoff": ledger.validate_cutoff,
     "fix-check": _validate_fix_check,
     "launch": native_launch.validate_event, "launch-result": native_launch.validate_event,
     }[event["event"]](slate, event, problems)
    native_launch.admit(slate, event, problems)
    _gate(slate, event, problems)


def _needed_phase(event: dict[str, Any]) -> str | None:
    kind = event["event"]
    if kind == "escalate":
        return "escalate"
    if kind in ("cut", "accept", "rebut"):
        when = event.get("when")
        return f"cut-{when}" if when in WHEN else None
    if kind in ("clean", "attack", "reply", "verdict") or (kind == "angle-na"
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


ITEM_STATES = {"clean": ("open",), "attack": ("open",), "angle-na": ("open",),
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
    if assignments.parallel(slate):
        worker = assignments.claim_owner(slate, claim, role)
        if agent != worker:
            problems.append(f"{kind}: {claim.id} is assigned to {worker}")
        return
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


def _find_owner(slate: Slate, agent: Any, lens: str, angle: str, kind: str,
                problems: list[str]) -> None:
    if assignments.parallel(slate) or slate.finder_plan is not None:
        if not _find_open(slate):
            problems.append(f"{kind}: find work is closed")
        owner = assignments.find_owners(slate).get((lens, angle))
        if owner is None:
            problems.append(f"{kind}: no find assignment for {lens}/{angle}")
        elif owner != agent:
            problems.append(f"{kind}: {lens}/{angle} is assigned to {owner}")
        elif slate.finder_plan is not None and slate.native_launches.get(owner, {}).get("state") != "attempted":
            problems.append(f"{kind}: {owner} needs an active finder launch reservation")


def _validate_gap_hunt_done(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    if slate_phase(slate) != "gap-hunt":
        problems.append("gap-hunt-done: requires an open parallel gap hunt")
    if event.get("as") != "r2":
        problems.append("gap-hunt-done: only r2 owns the gap hunt")


def _validate_file(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    if _written(slate, ("escalate", "cut", "clean", "attack")):
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
    ledger.nonempty(event, "evidence", problems)
    ledger.enum(event, "tier", model.TIER, problems)
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
    if (origin == "gap-hunt" and assignments.parallel(slate)
            and (event.get("as") != "r2" or slate_phase(slate) != "gap-hunt")):
        problems.append("file: only r2 can file during the open parallel gap hunt")
    if origin == "lens" and lens is not None and row is not None:
        _find_owner(slate, event.get("as"), lens, row["id"], "file", problems)


def _validate_escalate(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """The finder widens its claim, or confirms it, once, before any cut or attack."""
    if _written(slate, ("cut", "clean", "attack")):
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
    if lens is not None and row is not None:
        _find_owner(slate, event.get("as"), lens, row["id"], "find-run", problems)
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
    ledger.one_line(event, "reason", problems)
    if phase is None:
        return
    row = ledger.angle(slate, phase, event.get("angle"), problems)
    if phase == "find":
        lens = ledger.nonempty(event, "lens", problems)
        ledger.angle_lens(row, lens, problems)
        if lens is not None and row is not None:
            _find_owner(slate, event.get("as"), lens, row["id"], "angle-na", problems)
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
    elif row is not None and row["id"] in claim.na_reasons:
        problems.append(f"angle-na: angle {row['id']!r} is already recorded not applicable "
                        f"to {claim.id}")


def _validate_attack(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    batch = _batch(event, problems)
    for key in ("tell", "evidence", "searches", "positive_control"):
        ledger.nonempty(event, key, problems)
    if "last" in event:
        if batch != FRESH_EYE:
            problems.append(f"attack: `last` is given only with batch {FRESH_EYE}")
        elif not isinstance(event["last"], bool):
            problems.append(f"attack: `last` must be true or false; got {event['last']!r}")
    if batch == FRESH_EYE:
        angle = ledger.one_line(event, "angle", problems)
        if angle is not None and angle != angle.strip():
            problems.append("attack: `angle` must not start or end with whitespace")
            angle = None
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
        message = f"attack: angle {angle!r} was already used on {claim.id}"
        if batch == FRESH_EYE:
            message += ("; choose a new angle name not listed in `used`, including names outside the fixed list; "
                       "the fixed list is not a menu for this batch")
        problems.append(message)
    elif batch != FRESH_EYE and angle in claim.na_reasons:
        problems.append(f"attack: angle {angle!r} is recorded not applicable to {claim.id}")


CHECK_FIELDS = ("angle", "tell", "evidence", "searches", "positive_control")


def _validate_clean(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    rows = event.get("checks")
    if not isinstance(rows, list) or not rows:
        problems.append("clean: `checks` must be a non-empty list")
        return
    claim = ledger.known_claim(slate, event, problems)
    batch = event.get("batch")
    if claim is not None and batch == FRESH_EYE:
        used = len(claim.state.attacks.get(FRESH_EYE, []))
        cap = slate.cap("angles_per_claim")
        if used + len(rows) > cap:
            problems.append(f"clean: {used} prior checks plus {len(rows)} checks exceed "
                            f"the fresh-eye cap {cap}")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        prefix = f"clean: checks[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        for key in sorted(set(row) - set(CHECK_FIELDS)):
            problems.append(f"{prefix}: unknown field `{key}`")
        angle = row.get("angle")
        if isinstance(angle, str):
            if angle in seen:
                problems.append(f"{prefix}: duplicate angle {angle!r}")
            seen.add(angle)
        check = {"event": "attack", "as": event.get("as"), "claim": event.get("claim"),
                 "batch": batch, **{key: row.get(key) for key in CHECK_FIELDS}}
        if "last" in event:
            check["last"] = event["last"]
        found: list[str] = []
        _validate_attack(slate, check, found)
        _gate(slate, check, found)
        problems.extend(f"{prefix}: {message}" for message in found)


def _validate_reply(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    batch = _batch(event, problems)
    stance = ledger.enum(event, "stance", STANCE, problems)
    evidence = None
    if stance == "rebut":
        evidence = ledger.rebut_evidence(event, problems)
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
    if verdict == "disagree" and not ledger.given(event, "evidence"):
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
