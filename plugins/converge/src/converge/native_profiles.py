"""Resolve native participant profiles from the saved slate configuration."""

from __future__ import annotations

from collections.abc import Collection

from .model import Slate


def saved_host(slate: Slate) -> str | None:
    return slate.events[0].get("native_host")


def profiles(slate: Slate, *, native: Collection[str] = ()) -> dict[str, dict[str, str]]:
    from . import assignments

    result = dict(slate.finder_plan.profiles) if slate.finder_plan is not None else {}
    policy = slate.config.get("native_profiles") or {}
    for actor, seat in {**assignments.workers(slate), "cutter": "cutter"}.items():
        profile = policy.get(seat)
        if profile and (slate.mechanism(seat) == "native_subagent" or actor in native):
            native_host = saved_host(slate)
            assert native_host is not None
            result[actor] = {"host": native_host, **profile}
    return result
