"""Parallel advice timing with real slate progress (test-standard R006)."""

from __future__ import annotations

import pytest
from converge import advisor_wait, ledger

from conftest import BATCH_1, Converge


def test_relevant_progress_allows_more_than_five_receives(cv: Converge) -> None:
    cv.ready(config={"parallelism": {"r2": 2}})
    cycles = 0

    def call(*argv: str):
        nonlocal cycles
        assert argv[0] == "receive"
        cycles += 1
        if cycles <= len(BATCH_1):
            cv.check_cli("F001", BATCH_1[cycles - 1])
        elif cycles <= 7:
            cv.check_cli("F001", f"extra progress {cycles}", agent="r2", batch="fresh-eye")
        else:
            message = {"kind": "response", "parent_id": "request", "message_id": "reply"}
            return 0, {"peer_live": True, "unread": [message], "messages": [message]}
        return 1, {"peer_live": True, "messages": [], "unread": []}

    result = advisor_wait.receive_reply(lambda: ledger.read(cv.path(), "s1"), call,
                                        "r2", "0001", "request", 0)
    assert result["message_id"] == "reply"
    assert cycles == 8


def test_unrelated_claim_events_do_not_reset_quiet_receives(cv: Converge) -> None:
    cv.ready(claims=2, config={"parallelism": {"r2": 2}})
    cycles = 0

    def call(*argv: str):
        nonlocal cycles
        assert argv[0] == "receive"
        cv.check_cli("F002", BATCH_1[cycles])
        cycles += 1
        return 1, {"peer_live": True, "messages": [], "unread": []}

    with pytest.raises(ledger.LedgerError, match="five receives without relevant progress"):
        advisor_wait.receive_reply(lambda: ledger.read(cv.path(), "s1"), call,
                                   "r2", "0001", "request", 0)
    assert cycles == 5
