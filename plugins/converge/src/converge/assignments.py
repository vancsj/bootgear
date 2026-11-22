"""Replayable worker assignments from the init order and filed claim IDs."""

from __future__ import annotations

from .model import Claim, Slate


def parallel(slate: Slate) -> bool:
    return any(slate.parallelism[seat] > 1 for seat in slate.worker_seats)


def worker_id(seat: str, index: int) -> str:
    return seat if index == 0 else f"{seat}-{index + 1}"


def workers(slate: Slate) -> dict[str, str]:
    return {worker_id(seat, index): seat for seat in slate.worker_seats
            for index in range(slate.parallelism[seat])}


def find_angles(slate: Slate, lens: str) -> list[str]:
    return [row["id"] for row in slate.angles
            if row["tag"] == "find" and row.get("lens") in (None, lens)]


def find_owners(slate: Slate) -> dict[tuple[str, str], str]:
    pairs = ((lens, angle) for lens in slate.lenses for angle in find_angles(slate, lens))
    count = slate.parallelism["finder"]
    return {pair: worker_id("finder", index % count) for index, pair in enumerate(pairs)}


def claim_owner(slate: Slate, claim: Claim, seat: str) -> str:
    filed_index = int(claim.id[1:]) - 1
    return worker_id(seat, filed_index % slate.parallelism[seat])


def needs_gap_hunt(slate: Slate) -> bool:
    return parallel(slate) and slate.init_refuters == 2 and slate.config["steps"]["gap_hunt"]
