"""Apply accepted events to the in-memory slate."""

from __future__ import annotations

from typing import Any

from .model import Claim, Slate
from .protocol import ClaimState, worst

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
            trigger=event["trigger"], evidence=event["evidence"], tier=event["tier"],
            origin=event["origin"], depends=list(event.get("depends", [])),
            rule=event.get("rule"), filed_seq=event["seq"], state=ClaimState(),
        )
    elif kind == "find-run":
        slate.find_runs.append(event)
    elif kind == "angle-na":
        slate.angle_na.append(event)
        if "claim" in event:
            claim = slate.claims[event["claim"]]
            claim.na_reasons[event["angle"]] = event["reason"]
    else:
        _apply_claim_event(slate.claims[event["claim"]], event)
    if kind == "fix-check":
        slate.cutoff_valid = False
    if any(track.rounds for claim in slate.claims.values() for track in claim.state.cuts.values()):
        slate.cutoff_valid = False


def _apply_claim_event(claim: Claim, event: dict[str, Any]) -> None:
    kind = event["event"]
    state = claim.state
    if kind == "escalate":
        claim.escalation = event
        if "wider" in event:
            claim.text = event["wider"]
    elif kind in ("clean", "attack"):
        rows = event["checks"] if kind == "clean" else [{}]
        for index, row in enumerate(rows):
            check = {key: value for key, value in event.items() if key not in ("checks", "last")}
            check.update(row, outcome="clean" if kind == "clean" else "refuted")
            if index == len(rows) - 1 and "last" in event:
                check["last"] = event["last"]
            state.attacks.setdefault(event["batch"], []).append(check)
            claim.used_angles.add(check["angle"])
        state.refuters.add(event["as"])
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
        # A cut without `rate` rates it 0.
        state.cuts[event["when"]].rounds[event["round"]] = {"rate": 0, **event}
        state.cutters.add(event["as"])
    elif kind == "accept":
        state.cuts[event["when"]].accepted = event["round"]
    elif kind == "fix-check":
        claim.fix_check = event
    elif kind == "rebut":
        track = state.cuts[event["when"]]
        state.rebut_hashes["cut"].add(event["evidence_sha256"])
        track.pending = track.round
