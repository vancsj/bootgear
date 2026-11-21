"""Event shapes and the replayed claim state: `attack`, `reply`, `verdict`, the `when` field
of `cut`, `accept` and `rebut`, the rules of `file`, `escalate` and `angle-na`, the common
checks, and `ClaimState`."""
from __future__ import annotations

from typing import Any

from converge import ledger, model, protocol

from conftest import CUTTER, FINDER, R1, Converge


def _reply(cv: Converge, cid: str = "F001", stance: str = "rebut", batch: Any = 1,
           evidence: str | None = "new evidence", agent: str = FINDER, **extra: Any) -> list[str]:
    fields: dict[str, Any] = {"claim": cid, "batch": batch, "stance": stance, **extra}
    if evidence is not None:
        fields.update(evidence=evidence, evidence_sha256=ledger.evidence_hash(evidence))
    return cv.append("reply", agent, **fields)


def _verdict(cv: Converge, verdict: str, cid: str = "F001", agent: str = R1, batch: Any = 1,
             **extra: Any) -> list[str]:
    return cv.append("verdict", agent, claim=cid, batch=batch, verdict=verdict, **extra)


def _cut(cv: Converge, when: str | None, rnd: int = 1, cid: str = "F001", agent: str = CUTTER,
         **extra: Any) -> list[str]:
    fields: dict[str, Any] = {"claim": cid, "round": rnd, **extra}
    if when is not None:
        fields["when"] = when
    return cv.append("cut", agent, **fields)


def _rebut(cv: Converge, evidence: str, when: str | None = "before", agent: str = FINDER,
           **extra: Any) -> list[str]:
    fields: dict[str, Any] = {"claim": "F001", "evidence": evidence, **extra}
    if when is not None:
        fields["when"] = when
    return cv.append("rebut", agent, **fields)


def _claim(cv: Converge, cid: str = "F001") -> model.Claim:
    return ledger.read(cv.path(), "s1").claims[cid]


def _state(cv: Converge, cid: str = "F001") -> protocol.ClaimState:
    return _claim(cv, cid).state


def _rating(cv: Converge) -> dict[str, Any]:
    rating = _state(cv).rating
    assert rating is not None
    return rating
