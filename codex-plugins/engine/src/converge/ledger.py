"""JSONL slate ledger: locked replay-validate-append, and replay on every read.

One file per slate, `<dir>/<slate-id>.jsonl`, one event per line. Every write
takes an exclusive `flock`, replays and validates the whole file, validates the
new event against the replayed state, appends one line and fsyncs. Every read
replays and validates the whole file; a malformed line refuses every command.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import model, protocol, seats
from .model import Claim, Slate

DEFAULT_DIR = Path("~/.bootgear/converge")

REQUIRED: dict[str, tuple[str, ...]] = {
    "init": ("lenses", "angles", "config", "refuters"),
    "file": ("id", "loc", "claim", "trigger", "origin"),
    "escalate": ("claim",),
    "find-run": ("lens", "angle", "tell", "searches", "positive_control", "result"),
    "angle-na": ("phase", "angle", "reason"),
    "attack": ("claim", "batch", "angle", "tell", "outcome", "evidence", "searches",
               "positive_control"),
    "reply": ("claim", "batch", "stance"),
    "verdict": ("claim", "batch", "verdict"),
    "cut": ("claim", "when", "round", *model.CUT_FIELDS, "evidence"),
    "rebut": ("claim", "when", "evidence", "evidence_sha256"),
    "accept": ("claim", "when", "round"),
    "cutoff": ("results",),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    "init": ("snapshot", "pass", "since", "seats", "advisor"),
    "file": ("lens", "angle", "depends", "rule"),
    "escalate": ("wider", "evidence"),
    "find-run": (),
    "angle-na": ("lens", "claim"),
    "attack": ("last",),
    "reply": ("evidence", "evidence_sha256", "text"),
    "verdict": ("evidence",),
    "cut": ("choice", "fix"),
    "rebut": (),
    "accept": (),
    "cutoff": (),
}
ENVELOPE = ("seq", "ts", "event", "as")


class LedgerError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def slate_path(directory: Path, slate_id: str) -> Path:
    if not model.ID_RE.match(slate_id):
        raise LedgerError([f"slate id must match {model.ID_RE.pattern}: {slate_id!r}"])
    return directory.expanduser() / f"{slate_id}.jsonl"


def evidence_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# field checks


def nonempty(event: dict[str, Any], key: str, problems: list[str]) -> str | None:
    value = event.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"`{key}` must be a non-empty string")
        return None
    return value


def enum(event: dict[str, Any], key: str, allowed: tuple[str, ...], problems: list[str]) -> str | None:
    value = event.get(key)
    if value not in allowed:
        problems.append(f"`{key}` must be one of {', '.join(allowed)}; got {value!r}")
        return None
    return value


def round_number(event: dict[str, Any], problems: list[str]) -> int | None:
    value = event.get("round")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        problems.append(f"`round` must be a positive integer; got {value!r}")
        return None
    return value


def _shape(event: dict[str, Any], problems: list[str]) -> str | None:
    kind = event.get("event")
    if kind not in model.EVENTS:
        problems.append(f"`event` must be one of {', '.join(model.EVENTS)}; got {kind!r}")
        return None
    allowed = set(ENVELOPE) | set(REQUIRED[kind]) | set(OPTIONAL[kind])
    for key in REQUIRED[kind]:
        if key not in event:
            problems.append(f"{kind}: missing required field `{key}`")
    for key in sorted(set(event) - allowed):
        problems.append(f"{kind}: unknown field `{key}`")
    agent = event.get("as")
    if not isinstance(agent, str) or not model.ID_RE.match(agent):
        problems.append(f"`as` (agent id) must match {model.ID_RE.pattern}; got {agent!r}")
    return kind


def known_claim(slate: Slate, event: dict[str, Any], problems: list[str]) -> Claim | None:
    cid = event.get("claim")
    claim = slate.claims.get(cid) if isinstance(cid, str) else None
    if claim is None:
        problems.append(f"unknown claim {cid!r}")
    return claim


def angle(slate: Slate, tag: str, angle_id: Any, problems: list[str]) -> dict[str, Any] | None:
    if not isinstance(angle_id, str) or not angle_id:
        problems.append(f"`angle` must be a {tag} angle id; got {angle_id!r}")
        return None
    row = slate.angle(tag, angle_id)
    if row is None:
        problems.append(f"unknown {tag} angle {angle_id!r} (not in this slate's init snapshot)")
    return row


def angle_lens(row: dict[str, Any] | None, lens: Any, problems: list[str]) -> None:
    if row is not None and row.get("lens") and row["lens"] != lens:
        problems.append(f"angle {row['id']!r} belongs to lens {row['lens']!r}, not {lens!r}")


def roles(slate: Slate, claim: Claim, agent: Any, kind: str, problems: list[str]) -> None:
    """The finder never judges its own claim, the orchestrator judges none, and a claim's
    refuters and cutters are disjoint."""
    state = claim.state
    if agent == claim.finder:
        problems.append(f"{kind}: {agent} filed {claim.id} and may not {kind} it")
    if agent == slate.events[0]["as"]:
        problems.append(f"{kind}: {agent} wrote init; the orchestrator never writes {kind}")
    if kind in ("attack", "verdict") and agent in state.cutters:
        problems.append(f"{kind}: {agent} cut {claim.id}; refuters and cutters are disjoint")
    if kind == "cut" and agent in state.refuters:
        problems.append(f"cut: {agent} attacked {claim.id}; refuters and cutters are disjoint")


# ---------------------------------------------------------------------------
# validate_event: the common checks, then the protocol's


def validate_event(slate: Slate, event: dict[str, Any]) -> list[str]:
    """Every problem with appending `event` to the replayed `slate`."""
    problems: list[str] = []
    kind = _shape(event, problems)
    if kind is None:
        return problems
    agent = event.get("as")
    if kind == "init":
        if slate.initialised:
            problems.append("init: the slate is already initialised (init is written once, first)")
        _validate_init(event, problems)
        return problems
    if not slate.initialised:
        problems.append(f"{kind}: the slate has no init event; run `converge init` first")
        return problems
    if agent == model.CONVERGE_AGENT and kind != "cutoff":
        problems.append(f"agent id {model.CONVERGE_AGENT!r} is reserved for computed cutoff events")
    _agent_budget(slate, agent, problems)
    protocol.validate_event(slate, event, problems)
    return problems


def _agent_budget(slate: Slate, agent: Any, problems: list[str]) -> None:
    """At most caps.agents distinct agent ids per slate, the init writer included."""
    if agent in model.NON_AGENT_IDS:
        return
    seen = slate.agent_ids()
    cap = slate.cap("agents")
    if agent not in seen and len(seen) >= cap:
        problems.append(f"agent budget: {agent} would be agent {len(seen) + 1} on this slate; "
                        f"caps.agents is {cap} ({', '.join(seen)}); reuse one of them")


def _validate_init(event: dict[str, Any], problems: list[str]) -> None:
    from .angles import validate_rows
    from .config import validate_config

    lenses = event.get("lenses")
    if not isinstance(lenses, list) or not all(isinstance(x, str) and model.ID_RE.match(x) for x in lenses):
        problems.append(f"`lenses` must be a list of ids matching {model.ID_RE.pattern}")
    elif len(set(lenses)) != len(lenses):
        problems.append("`lenses` contains duplicates")
    elif not lenses:
        problems.append("init: a slate needs at least one lens")
    angles = event.get("angles")
    if not isinstance(angles, list):
        problems.append("`angles` must be the resolved angle snapshot (a list)")
    else:
        problems.extend(f"angles snapshot: {p}" for p in validate_rows(angles, "snapshot"))
    refuters = event.get("refuters")
    if "refuters" in event and not (isinstance(refuters, int) and not isinstance(refuters, bool)
                                    and refuters in (1, 2)):
        problems.append(f"`refuters` must be 1 or 2; got {refuters!r}")
    problems.extend(f"config snapshot: {p}"
                    for p in validate_config(event.get("config"), "snapshot", complete=True))
    if "pass" in event:
        value = event["pass"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            problems.append(f"`pass` must be a positive integer; got {value!r}")
    if "snapshot" in event:
        if not (isinstance(event["snapshot"], str) and model.SHA_RE.match(event["snapshot"])):
            problems.append(f"`snapshot` must be a commit sha; got {event['snapshot']!r}")
        if "pass" not in event:
            problems.append("init: `snapshot` needs `pass`")
    if "since" in event:
        since = event["since"]
        if (not isinstance(since, dict) or set(since) != {"slate", "snapshot"}
                or not (isinstance(since["slate"], str) and model.ID_RE.match(since["slate"]))
                or not (isinstance(since["snapshot"], str) and model.SHA_RE.match(since["snapshot"]))):
            problems.append(f"`since` must be {{slate: <slate id>, snapshot: <commit sha>}}; "
                            f"got {since!r}")
        if "snapshot" not in event:
            problems.append("init: `since` needs `snapshot`")
    _validate_seats(event, problems)


def _validate_seats(event: dict[str, Any], problems: list[str]) -> None:
    def rename(field: str, old: str, new: str) -> str:
        return new + field[len(old):]

    slate_seats = event.get("seats")
    if "seats" in event:
        problems.extend(f"{rename(f, 'converge_seats', 'seats')}: {m}"
                        for f, m in seats.seat_problems(slate_seats))
    if "advisor" in event:
        problems.extend(f"{rename(f, 'advisor_roles', 'advisor')}: {m}"
                        for f, m in seats.roles_problems(event["advisor"]))
        if not (isinstance(slate_seats, dict) and slate_seats.get(seats.ADVISOR_SEAT) == "advisor"):
            problems.append("advisor: given only when seats.r2 is advisor")


def validate_cutoff(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """The computed cutoff, written in phase cutoff; its results must equal a recompute, on
    write and on every replay."""
    if event.get("as") != model.CONVERGE_AGENT:
        problems.append("cutoff is computed by `converge cutoff` only; it is rejected from --as input")
    phase = protocol.slate_phase(slate)
    if phase != "cutoff":
        problems.append(f"cutoff: the slate is in phase {phase}; cutoff needs phase cutoff")
        open_claims = slate.open_claims()
        if open_claims:
            problems.append("cutoff: open claims remain: "
                            + ", ".join(f"{c.id} ({phase})" for c, phase in open_claims))
        return
    if event.get("results") != protocol.cutoff_results(protocol.compute_cutoff(slate)):
        problems.append("cutoff: results differ from the computed cutoff")


# ---------------------------------------------------------------------------
# apply


def apply_event(slate: Slate, event: dict[str, Any]) -> None:
    slate.events.append(event)
    if event["event"] != "init":
        protocol.apply_event(slate, event)
        return
    slate.lenses = list(event["lenses"])
    slate.angles = event["angles"]
    slate.config = event["config"]
    slate.init_refuters = event["refuters"]
    slate.snapshot = event.get("snapshot")
    slate.review_pass = event.get("pass")
    slate.since = event.get("since")
    slate.seats = event.get("seats") or {}
    slate.advisor = event.get("advisor")


# ---------------------------------------------------------------------------
# read / append


def _parse(lines: list[bytes], slate_id: str) -> Slate:
    slate = Slate(slate_id)
    problems: list[str] = []
    for index, raw in enumerate(lines, start=1):
        where = f"line {index}"
        if not raw.endswith(b"\n"):
            problems.append(f"{where}: truncated (no trailing newline)")
            break
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"{where}: not valid JSON: {exc}")
            break
        if not isinstance(event, dict):
            problems.append(f"{where}: an event must be a JSON object")
            break
        if event.get("seq") != index:
            problems.append(f"{where}: seq must be {index}; got {event.get('seq')!r}")
        if not isinstance(event.get("ts"), str) or not event["ts"]:
            problems.append(f"{where}: `ts` must be an ISO-8601 timestamp")
        line_problems = validate_event(slate, event)
        problems.extend(f"{where}: {p}" for p in line_problems)
        if problems:
            break
        apply_event(slate, event)
    if problems:
        raise LedgerError(["ledger is corrupt or out of order; every command refuses it:", *problems])
    return slate


def _read_all(fd: int) -> list[bytes]:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        chunk = os.read(fd, 1 << 16)
        if not chunk:
            break
        chunks.append(chunk)
    data = b"".join(chunks)
    return data.splitlines(keepends=True)


def read(path: Path, slate_id: str) -> Slate:
    if not path.is_file():
        raise LedgerError([f"no slate {slate_id!r} in {path.parent} (expected {path})"])
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        lines = _read_all(fd)
    finally:
        os.close(fd)
    slate = _parse(lines, slate_id)
    if not slate.initialised:
        raise LedgerError([f"slate {slate_id!r} has no init event: {path}"])
    return slate


def append(path: Path, slate_id: str, event: dict[str, Any], *, create: bool = False,
           build: Any = None) -> dict[str, Any]:
    """Lock, replay, validate, append one line, fsync. Returns the written event.

    `build(slate)` may fill computed fields from the replayed state before validation.
    """
    created = False
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL, 0o644)
            created = True
        except FileExistsError:
            fd = os.open(path, os.O_RDWR | os.O_APPEND)
    else:
        if not path.is_file():
            raise LedgerError([(f"no slate {slate_id!r} in {path.parent} (expected {path}); "
                                f"run `converge init` first")])
        fd = os.open(path, os.O_RDWR | os.O_APPEND)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            slate = _parse(_read_all(fd), slate_id)
            event = dict(event)
            if build is not None:
                event.update(build(slate))
            event = {"seq": len(slate.events) + 1, "ts": now(), **event}
            problems = validate_event(slate, event)
            if problems:
                raise LedgerError(problems)
            line = json.dumps(event, sort_keys=False, ensure_ascii=False) + "\n"
            data = line.encode("utf-8")
            while data:
                data = data[os.write(fd, data):]
            os.fsync(fd)
            return event
        except BaseException:
            if created and os.fstat(fd).st_size == 0:
                path.unlink(missing_ok=True)
            raise
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
