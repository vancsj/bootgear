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
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import model
from .model import Claim, Slate

DEFAULT_DIR = Path("~/.bootgear/converge")
SOURCE_RE = re.compile(r"\Aledger:\S+\Z")

REQUIRED: dict[str, tuple[str, ...]] = {
    "init": ("mode", "lenses", "angles", "config"),
    "file": ("id", "loc", "claim", "trigger", "origin"),
    "find-run": ("lens", "angle", "tell", "searches", "positive_control", "result"),
    "angle-na": ("phase", "angle", "reason"),
    "refute": ("claim", "round", "angle", "tell", "outcome", "evidence", "searches",
               "positive_control"),
    "rebut": ("claim", "stage", "evidence", "evidence_sha256"),
    "cut": ("claim", "round", *model.CUT_FIELDS, "evidence"),
    "accept": ("claim", "round"),
    "cutoff": ("results",),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    "init": ("snapshot", "pass", "since"),
    "file": ("lens", "angle", "depends", "rule"),
    "find-run": (),
    "angle-na": ("lens",),
    "refute": ("narrowed", "source", "ledger_evidence"),
    "rebut": (),
    "cut": ("choice",),
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


def _nonempty(event: dict[str, Any], key: str, problems: list[str]) -> str | None:
    value = event.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"`{key}` must be a non-empty string")
        return None
    return value


def _enum(event: dict[str, Any], key: str, allowed: tuple[str, ...], problems: list[str]) -> str | None:
    value = event.get(key)
    if value not in allowed:
        problems.append(f"`{key}` must be one of {', '.join(allowed)}; got {value!r}")
        return None
    return value


def _round(event: dict[str, Any], problems: list[str]) -> int | None:
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


def _known_claim(slate: Slate, event: dict[str, Any], problems: list[str]) -> Claim | None:
    cid = event.get("claim")
    claim = slate.claims.get(cid) if isinstance(cid, str) else None
    if claim is None:
        problems.append(f"unknown claim {cid!r}")
    return claim


def _angle(slate: Slate, tag: str, angle_id: Any, problems: list[str]) -> dict[str, Any] | None:
    if not isinstance(angle_id, str) or not angle_id:
        problems.append(f"`angle` must be a {tag} angle id; got {angle_id!r}")
        return None
    row = slate.angle(tag, angle_id)
    if row is None:
        problems.append(f"unknown {tag} angle {angle_id!r} (not in this slate's init snapshot)")
    return row


def _angle_lens(row: dict[str, Any] | None, lens: Any, problems: list[str]) -> None:
    if row is not None and row.get("lens") and row["lens"] != lens:
        problems.append(f"angle {row['id']!r} belongs to lens {row['lens']!r}, not {lens!r}")


# ---------------------------------------------------------------------------
# validate_event: the ledger's validation rules


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
    if slate.cutoff_valid and kind not in ("rebut", "refute", "cutoff"):
        problems.append(f"{kind}: a cutoff is current; only a new rebut or refute reopens the slate")
    _agent_budget(slate, agent, problems)

    handler = {
        "file": _validate_file,
        "find-run": _validate_find_run,
        "angle-na": _validate_angle_na,
        "refute": _validate_refute,
        "rebut": _validate_rebut,
        "cut": _validate_cut,
        "accept": _validate_accept,
        "cutoff": _validate_cutoff,
    }[kind]
    handler(slate, event, problems)
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

    mode = _enum(event, "mode", model.MODE, problems)
    lenses = event.get("lenses")
    if not isinstance(lenses, list) or not all(isinstance(x, str) and model.ID_RE.match(x) for x in lenses):
        problems.append(f"`lenses` must be a list of ids matching {model.ID_RE.pattern}")
    elif len(set(lenses)) != len(lenses):
        problems.append("`lenses` contains duplicates")
    elif mode == "full" and not lenses:
        problems.append("init: full mode needs at least one lens")
    angles = event.get("angles")
    if not isinstance(angles, list):
        problems.append("`angles` must be the resolved angle snapshot (a list)")
    else:
        problems.extend(f"angles snapshot: {p}" for p in validate_rows(angles, "snapshot"))
    config = event.get("config")
    problems.extend(f"config snapshot: {p}" for p in validate_config(config, "snapshot", complete=True))
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


def _validate_file(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    expected = model.claim_id(len(slate.claims) + 1)
    if event.get("id") != expected:
        problems.append(f"file: claim id must be {expected}; got {event.get('id')!r}")
    origin = _enum(event, "origin", model.ORIGIN, problems)
    loc = event.get("loc")
    if not isinstance(loc, str) or not model.LOC_RE.match(loc):
        problems.append(f"`loc` must match path:line ({model.LOC_RE.pattern}); got {loc!r}")
    _nonempty(event, "claim", problems)
    _nonempty(event, "trigger", problems)
    if "rule" in event:
        _nonempty(event, "rule", problems)
    depends = event.get("depends", [])
    if not isinstance(depends, list):
        problems.append("`depends` must be a list of claim ids")
    else:
        for dep in depends:
            if dep not in slate.claims:
                problems.append(f"`depends` names unknown claim {dep!r}")
    if slate.mode == "refute-only":
        if agent != model.SLATE_AGENT:
            problems.append("refute-only: file is written only with --as slate")
        if origin is not None and origin != "slate":
            problems.append("refute-only: file needs origin slate")
        if slate.refute_started:
            problems.append("refute-only: the slate is filed before the first refute")
        for key in ("lens", "angle"):
            if key in event:
                _nonempty(event, key, problems)
        if "angle" in event:
            _angle(slate, "find", event["angle"], problems)
        return
    if agent == model.SLATE_AGENT:
        problems.append("full mode: agent id 'slate' is reserved for refute-only slates")
    if origin == "slate":
        problems.append("full mode: origin slate is only for refute-only slates")
    lens = _nonempty(event, "lens", problems)
    row = _angle(slate, "find", event.get("angle"), problems)
    _angle_lens(row, lens, problems)
    if origin == "lens" and lens is not None and lens not in slate.lenses:
        problems.append(f"lens {lens!r} is not an init lens ({', '.join(slate.lenses)})")


def _validate_find_run(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    if event.get("as") == model.SLATE_AGENT:
        problems.append("agent 'slate' may not write find-run")
    lens = _nonempty(event, "lens", problems)
    row = _angle(slate, "find", event.get("angle"), problems)
    _angle_lens(row, lens, problems)
    for key in ("tell", "searches", "positive_control"):
        _nonempty(event, key, problems)
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
    phase = _enum(event, "phase", model.PHASE, problems)
    _nonempty(event, "reason", problems)
    if phase is None:
        return
    row = _angle(slate, model.PHASE_TAG[phase], event.get("angle"), problems)
    if phase == "find":
        lens = _nonempty(event, "lens", problems)
        _angle_lens(row, lens, problems)
    elif "lens" in event:
        problems.append("`lens` is only recorded for phase find")


def _roles(slate: Slate, claim: Claim, agent: Any, kind: str, problems: list[str]) -> None:
    if agent == claim.finder:
        problems.append(f"{kind}: {agent} filed {claim.id} and may not {kind} it")
    if agent == slate.events[0]["as"]:
        problems.append(f"{kind}: {agent} wrote init; the orchestrator never writes {kind}")
    if kind == "refute" and agent in claim.cutters:
        problems.append(f"refute: {agent} cut {claim.id}; refuters and cutters are disjoint")
    if kind == "cut" and agent in claim.refuters:
        problems.append(f"cut: {agent} refuted {claim.id}; refuters and cutters are disjoint")


def _validate_refute(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = _known_claim(slate, event, problems)
    rnd = _round(event, problems)
    row = _angle(slate, "attack", event.get("angle"), problems)
    outcome = _enum(event, "outcome", model.REFUTE_OUTCOME, problems)
    for key in ("tell", "evidence", "searches", "positive_control"):
        _nonempty(event, key, problems)
    if outcome == "downgraded":
        _nonempty(event, "narrowed", problems)
    elif "narrowed" in event:
        problems.append("`narrowed` is given only with outcome downgraded")
    if ("source" in event) != ("ledger_evidence" in event):
        problems.append("`source` and `ledger_evidence` are given together")
    if "source" in event and not (isinstance(event["source"], str) and SOURCE_RE.match(event["source"])):
        problems.append(f"`source` must be ledger:<slug>; got {event['source']!r}")
    if "ledger_evidence" in event:
        _enum(event, "ledger_evidence", model.LEDGER_EVIDENCE, problems)
    if agent == model.SLATE_AGENT:
        problems.append("agent 'slate' may not write refute")
    if claim is None:
        return
    if claim.dead:
        problems.append(f"{claim.id} is {claim.dead}; it accepts nothing")
        return
    if claim.stage != "refute":
        problems.append(f"refute: {claim.id} is in stage {claim.stage}; a rebut --stage refute reopens refute")
    _roles(slate, claim, agent, "refute", problems)
    if row is not None and row["id"] in claim.used_angles:
        problems.append(f"refute: angle {row['id']!r} was already used on {claim.id}; pick an unused angle")
    if rnd is not None:
        last = claim.refute_round
        cap = slate.cap("refute_rounds")
        if rnd > cap:
            problems.append(f"refute: round {rnd} exceeds caps.refute_rounds {cap}")
        elif last == 0 and rnd != 1:
            problems.append(f"refute: {claim.id} has no rounds; round must be 1, got {rnd}")
        elif last and rnd < last:
            problems.append(f"refute: {claim.id} is at round {last}; rounds never decrease")
        elif last and rnd > last + 1:
            problems.append(f"refute: {claim.id} is at round {last}; next round is {last + 1}")
        elif last and rnd == last + 1 and len(claim.refute_rounds[last]) < 2:
            problems.append(f"refute: round {last} of {claim.id} has "
                            f"{len(claim.refute_rounds[last])} refute event(s); a round needs ≥2")


def _validate_rebut(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    if slate.mode == "refute-only":
        problems.append("refute-only: there is no finder, so rebut is refused")
    claim = _known_claim(slate, event, problems)
    stage = _enum(event, "stage", model.STAGE, problems)
    evidence = _nonempty(event, "evidence", problems)
    if evidence is not None and event.get("evidence_sha256") != evidence_hash(evidence):
        problems.append("`evidence_sha256` does not match the evidence")
    if claim is None or stage is None:
        return
    if claim.dead:
        problems.append(f"{claim.id} is {claim.dead}; it accepts nothing")
        return
    if agent != claim.finder:
        problems.append(f"rebut: only {claim.id}'s finder {claim.finder} may rebut")
    if stage == "refute" and not claim.refute_rounds:
        problems.append(f"rebut: {claim.id} has no refute event to rebut")
    if stage == "cut" and not claim.cut_rounds:
        problems.append(f"rebut: {claim.id} has no cut round to rebut")
    if evidence is not None and evidence_hash(evidence) in claim.rebut_hashes[stage]:
        problems.append(f"rebut: this evidence was already given for {claim.id} stage {stage}; "
                        f"a rebut needs new evidence")


def _validate_cut(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    if slate.mode == "refute-only":
        problems.append("refute-only slate has no cut stage")
    claim = _known_claim(slate, event, problems)
    rnd = _round(event, problems)
    values = {f: _enum(event, f, model.FIELD_ENUMS[f], problems) for f in model.CUT_FIELDS}
    if "choice" in event:
        _nonempty(event, "choice", problems)
    evidence = event.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        problems.append("`evidence` must map evaluate angle ids to evidence text")
    else:
        covered: set[str] = set()
        for key, text in evidence.items():
            row = _angle(slate, "evaluate", key, problems)
            if not isinstance(text, str) or not text.strip():
                problems.append(f"evidence for {key!r} must be non-empty text")
            if row is not None and row.get("field"):
                covered.add(row["field"])
        for name in model.CUT_FIELDS:
            if name not in covered:
                problems.append(f"cut: no evidence for `{name}` (give an evaluate angle whose field is {name})")
    if agent == model.SLATE_AGENT:
        problems.append("agent 'slate' may not write cut")
    if claim is None:
        return
    if claim.dead:
        problems.append(f"{claim.id} is {claim.dead}; it accepts nothing")
        return
    rstate = slate.refute_state(claim)
    if rstate not in model.REFUTE_DONE:
        problems.append(f"cut: {claim.id} refute state is {rstate}; cut needs refute converged, "
                        f"inconclusive or unconverged")
    _roles(slate, claim, agent, "cut", problems)
    if rnd is not None:
        expected = claim.cut_round + 1
        cap = slate.cap("cut_rounds")
        if rnd > cap:
            problems.append(f"cut: round {rnd} exceeds caps.cut_rounds {cap}")
        elif rnd != expected:
            problems.append(f"cut: {claim.id} next cut round is {expected}, got {rnd}")
    if (rstate == "converged" and values["difficulty"] in model.CHOICE_DIFFICULTY
            and not (isinstance(event.get("choice"), str) and event["choice"].strip())):
        problems.append(f"cut: {claim.id} survived with difficulty {values['difficulty']}; "
                        f"a non-empty `choice` is required")


def _validate_accept(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    if slate.mode == "refute-only":
        problems.append("refute-only slate has no cut stage")
    claim = _known_claim(slate, event, problems)
    rnd = _round(event, problems)
    if claim is None or rnd is None:
        return
    if claim.dead:
        problems.append(f"{claim.id} is {claim.dead}; it accepts nothing")
        return
    if agent != claim.finder:
        problems.append(f"accept: only {claim.id}'s finder {claim.finder} may accept")
    last = claim.cut_round
    if last == 0:
        problems.append(f"accept: {claim.id} has no cut round to accept")
        return
    if rnd != last:
        problems.append(f"accept: {claim.id} latest cut round is {last}, got {rnd}")
    elif claim.accepted_round == last:
        problems.append(f"accept: {claim.id} cut round {last} is already accepted")
    elif claim.cut_pending == last:
        problems.append(f"accept: {claim.id} cut round {last} was rebutted; answer the next cut round")


def _validate_cutoff(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    if event.get("as") != model.CONVERGE_AGENT:
        problems.append("cutoff is computed by `converge cutoff` only; it is rejected from --as input")
    if slate.mode == "refute-only":
        problems.append("refute-only slate has no cut stage")
        return
    open_claims = slate.open_claims()
    if open_claims:
        problems.append("cutoff: open claims remain: "
                        + ", ".join(f"{c.id} ({phase})" for c, phase in open_claims))
        return
    expected = model.cutoff_results(model.compute_cutoff(slate))
    if event.get("results") != expected:
        problems.append("cutoff: results differ from the computed cutoff")


# ---------------------------------------------------------------------------
# apply


def apply_event(slate: Slate, event: dict[str, Any]) -> None:
    kind = event["event"]
    slate.events.append(event)
    if kind == "init":
        slate.mode = event["mode"]
        slate.lenses = list(event["lenses"])
        slate.angles = event["angles"]
        slate.config = event["config"]
        slate.snapshot = event.get("snapshot")
        slate.review_pass = event.get("pass")
        slate.since = event.get("since")
    elif kind == "file":
        slate.claims[event["id"]] = Claim(
            id=event["id"], finder=event["as"], lens=event.get("lens"), angle=event.get("angle"),
            loc=event["loc"], original=event["claim"], text=event["claim"],
            trigger=event["trigger"], origin=event["origin"], depends=list(event.get("depends", [])),
            rule=event.get("rule"), filed_seq=event["seq"],
        )
    elif kind == "find-run":
        slate.find_runs.append(event)
    elif kind == "angle-na":
        slate.angle_na.append(event)
    elif kind == "refute":
        _apply_refute(slate, event)
    elif kind == "rebut":
        claim = slate.claims[event["claim"]]
        claim.rebut_hashes[event["stage"]].add(event["evidence_sha256"])
        if event["stage"] == "refute":
            claim.refute_pending = claim.refute_round
            _back_to_refute(claim)
        else:
            claim.cut_pending = claim.cut_round
        slate.cutoff_valid = False
    elif kind == "cut":
        claim = slate.claims[event["claim"]]
        claim.stage = "cut"
        claim.cut_rounds[event["round"]] = event
        claim.cutters.add(event["as"])
    elif kind == "accept":
        slate.claims[event["claim"]].accepted_round = event["round"]
    elif kind == "cutoff":
        slate.cutoff = event
        slate.cutoff_valid = True


def _back_to_refute(claim: Claim) -> None:
    claim.stage = "refute"
    claim.cut_rounds.clear()
    claim.cut_pending = 0
    claim.accepted_round = 0


def _apply_refute(slate: Slate, event: dict[str, Any]) -> None:
    claim = slate.claims[event["claim"]]
    slate.refute_started = True
    slate.cutoff_valid = False
    claim.refute_rounds.setdefault(event["round"], []).append(event)
    claim.refuters.add(event["as"])
    claim.used_angles.add(event["angle"])
    outcome = event["outcome"]
    if outcome in model.DEAD_OUTCOMES:
        claim.dead = outcome
        claim.dead_event = event
    elif outcome == "downgraded":
        claim.downgrades.append(event)
        claim.text = event["narrowed"]
    if (len(claim.refute_rounds[event["round"]]) >= 2 and event["round"] > claim.refute_pending):
        claim.reopened = False
    if outcome in ("killed", "downgraded"):
        for dependent in slate.claims.values():
            if dependent.live and claim.id in dependent.depends:
                dependent.refute_pending = dependent.refute_round
                dependent.reopened = True
                _back_to_refute(dependent)


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
