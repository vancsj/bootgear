"""Gate 1 on the claims of two recorded review slates, under the review skill's cutoff."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import CUTTER, FINDER, MAIN, R2, Converge
from converge import ledger, protocol

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REVIEW_CUTOFF = (Path(__file__).resolve().parents[3]
                 / "plugins/review/skills/review/references/cutoff.yaml")
LENSES = ("correctness", "security", "architecture", "tests", "simplicity", "contract")
FIND_ANGLES = (("changed-contract", None), ("failure-path", None), ("god-object", "architecture"))
RATE_EVIDENCE = ("--evidence", "call-site-count=rg finds the call sites")

# Per fixture: its review pass, and per claim the gate-1 outcome (attacked, reason).
GOLDEN = {
    "53e142d4-review-1": (1, {
        "F001": (True, "attack_if[0]"),
        "F002": (False, "no rule matched"),
        "F003": (False, "no rule matched"),
        "F004": (True, "attack_if[0]"),
        "F005": (True, "attack_if[0]"),
        "F006": (True, "attack_if[1]"),
        "F007": (True, "attack_if[0]"),
        "F008": (True, "attack_if[0]"),
        "F009": (True, "attack_if[0]"),
    }),
    "53e142d4-review-2": (2, {
        "F001": (False, "no rule matched"),
        "F002": (False, "no rule matched"),
        "F003": (False, "no rule matched"),
        "F004": (False, "no rule matched"),
        "F005": (False, "no rule matched"),
    }),
}


def _hydrate(cv: Converge, slate: str, review_pass: int, rows: list[dict[str, object]]) -> None:
    """A slate with each row filed, find coverage complete, and its before cut accepted."""
    angles = cv.root / "replay-angles.yaml"
    angles.write_text("".join(
        f"- id: {angle}\n  tag: find\n  tell: t\n  asks: a\n" + (f"  lens: {lens}\n" if lens else "")
        for angle, lens in FIND_ANGLES))
    task = cv.root / f"{slate}.task.yaml"
    task.write_text("steps: {escalate: false, cut: before}\n")
    cv.ok("init", slate, "--as", MAIN, "--project-root", str(cv.project), "--lenses",
          ",".join(LENSES), "--angles", str(angles), "--pass", str(review_pass),
          "--defaults", str(REVIEW_CUTOFF), "--config", str(task))
    finders = {}
    lens_rows = [row for row in rows if row["origin"] == "lens"]
    gap_rows = [row for row in rows if row["origin"] == "gap-hunt"]
    for row in lens_rows:
        finders[row["id"]] = FINDER
        assert cv.file(slate, FINDER, str(row["lens"]), claim=str(row["claim"]),
                       tier=str(row["tier"])) == row["id"]
    for lens in LENSES:
        for angle, only in FIND_ANGLES:
            if only in (None, lens):
                cv.ok("angle-na", slate, "--as", FINDER, "--phase", "find", "--angle", angle,
                      "--lens", lens, "--reason", "not in the diff")
    for row in gap_rows:
        finders[row["id"]] = R2
        assert cv.file(slate, R2, str(row["lens"]), origin="gap-hunt", claim=str(row["claim"]),
                       tier=str(row["tier"])) == row["id"]
    for row in rows:
        cid = str(row["id"])
        cv.cut(cid, 1, CUTTER, "before", str(row["impact"]), str(row["size"]), str(row["reach"]),
               "cross-cutting", "--rate", str(row["rate"]), *RATE_EVIDENCE, slate=slate)
        cv.accept(cid, 1, finders[cid], "before", slate=slate)


def test_replay_53e142d4_golden(cv: Converge) -> None:
    attacked_any = False
    for name, (review_pass, expected) in GOLDEN.items():
        rows = [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines()]
        assert [row["id"] for row in rows] == list(expected)
        _hydrate(cv, name, review_pass, rows)
        slate = ledger.read(cv.path(name), name)
        got = {cid: protocol.gate1(slate, claim, claim.state.cuts["before"].latest())
               for cid, claim in slate.claims.items()}
        assert got == expected, name
        statuses = {cid: claim["status"] for cid, claim in cv.status(name)["by_id"].items()}
        assert statuses == {cid: "survived" if attacked else "unverified"
                            for cid, (attacked, _) in expected.items()}, name
        attacked_any = attacked_any or any(attacked for attacked, _ in expected.values())
    assert attacked_any
