"""Replayable worker assignments from the init order and filed claim IDs."""

from __future__ import annotations

from . import finder_routing
from .model import Claim, Slate


def parallel(slate: Slate) -> bool:
    return any(slate.parallelism[seat] > 1 for seat in slate.worker_seats)


def worker_id(seat: str, index: int) -> str:
    return seat if index == 0 else f"{seat}-{index + 1}"


def workers(slate: Slate) -> dict[str, str]:
    result = {actor: "finder" for actor in slate.finder_plan.profiles} if slate.finder_plan is not None else {}
    for seat in slate.worker_seats:
        if seat != "finder" or slate.finder_plan is None:
            result.update({worker_id(seat, index): seat for index in range(slate.parallelism[seat])})
    return result


def find_angles(slate: Slate, lens: str) -> list[str]:
    return [row["id"] for row in slate.angles
            if row["tag"] == "find" and row.get("lens") in (None, lens)]


def find_owners(slate: Slate) -> dict[tuple[str, str], str]:
    if slate.finder_plan is not None:
        return slate.finder_plan.owners
    pairs = ((lens, angle) for lens in slate.lenses for angle in find_angles(slate, lens))
    count = slate.parallelism["finder"]
    return {pair: worker_id("finder", index % count) for index, pair in enumerate(pairs)}


def finder_plan(slate: Slate, host: str) -> finder_routing.Plan:
    pairs = [(lens, angle) for lens in slate.lenses for angle in find_angles(slate, lens)]
    return finder_routing.allocate(pairs, slate.config["finder_routing"], host, slate.parallelism["finder"])


def claim_owner(slate: Slate, claim: Claim, seat: str) -> str:
    filed_index = int(claim.id[1:]) - 1
    return worker_id(seat, filed_index % slate.parallelism[seat])


def needs_gap_hunt(slate: Slate) -> bool:
    return parallel(slate) and slate.init_refuters == 2 and slate.config["steps"]["gap_hunt"]
