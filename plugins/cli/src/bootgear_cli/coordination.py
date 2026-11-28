"""Persistent seats, assignments and deliveries for a shared host."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from bootgear_cli import clikit

DEFAULT_TIMEOUT = 5.0
HEARTBEAT_TTL = 10
RESTART_GRACE = 720
ADVISOR_WORK_TIMEOUT = 5 * 300
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*")
PARTICIPANT_ENV = "BOOTGEAR_COORDINATION_PARTICIPANT"
HOST_CALLER = ":host"

Record = dict[str, Any]


def _name(value: str, label: str) -> str:
    if not NAME.fullmatch(value):
        clikit.refuse(f"invalid {label}: {value!r}", code=2)
    return value


def _key(*values: str) -> str:
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def _read(path: Path) -> Record:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _write(path: Path, value: Record) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as target:
        temporary = Path(target.name)
        try:
            json.dump(value, target, ensure_ascii=False)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
            target.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class _StoreBusy(clikit.Refusal):
    pass


@contextmanager
def _lock(path: Path, timeout: float) -> Iterator[None]:
    deadline = time.monotonic() + timeout
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _StoreBusy("coordination store is busy; retry the command")
                time.sleep(min(remaining, 0.02))
        yield
    finally:
        os.close(fd)


def _seat(role: str, *, invitation: str | None = None,
          occupant: Record | None = None) -> Record:
    joined_at = time.time() if occupant else 0
    return {"role": role, "invitation": invitation, "occupant": occupant,
            "seen_at": joined_at, "heartbeat_at": joined_at, "restart_until": 0}


@dataclass(frozen=True)
class Caller:
    root: Path
    shared_host_id: str
    host: str
    participant: str | None

    @classmethod
    def from_environment(cls) -> Caller:
        participant = os.environ.get(PARTICIPANT_ENV)
        if not participant:
            clikit.refuse("no coordination caller binding; run Gear as one command in a host Bash tool call")
        return cls.from_host_event(None if participant == HOST_CALLER else participant)

    @classmethod
    def from_host_event(cls, participant: str | None = None) -> Caller:
        shared_host_id = clikit.session_id()
        host = clikit.host()
        if not shared_host_id or not host:
            clikit.refuse("run inside a Claude Code or Codex host with a shared host ID")
        path = os.environ.get("BOOTGEAR_COORDINATION_DIR")
        root = clikit.caller_path(path) if path else Path.home() / ".bootgear" / "coordination"
        return cls(root.resolve(), _name(shared_host_id, "shared host ID"), host, participant)

    def identity(self) -> Record:
        return {"host": self.host, "shared_host_id": self.shared_host_id,
                "participant": self.participant}

    @property
    def path(self) -> Path:
        return self.root / self.shared_host_id


def _directory(caller: Caller) -> None:
    caller.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    caller.root.chmod(0o700)


def initialize(caller: Caller, timeout: float) -> Record:
    if caller.participant:
        clikit.refuse("main must initialize the coordination store")
    _directory(caller)
    with _lock(caller.root / ".lock", timeout):
        _detach_stopped(caller)
        if caller.path.is_symlink():
            clikit.refuse("this host already joined a coordination store")
        caller.path.mkdir(mode=0o700, exist_ok=True)
        path = caller.path / "store.json"
        if not path.exists():
            _write(path, {"seats": {"main": _seat("main", occupant=caller.identity())},
                          "assignments": {}, "requests": {}, "deliveries": [],
                          "active_slate": None, "slates": {}, "stopped": {}})
    return {"seat": "main", "status": "ready"}


@dataclass(frozen=True)
class Store:
    path: Path
    state: Record
    seat: str

    def require_main(self) -> None:
        if self.seat != "main":
            clikit.refuse("this operation requires the main seat")

    def delivery(self, recipient: str, kind: str, body: Record) -> Record:
        item = {"delivery_id": uuid4().hex, "kind": kind, **body}
        self.state["deliveries"].append({"recipient": recipient, "body": item, "ack": False})
        return item

    def open_assignment(self) -> Record | None:
        return next((item for item in self.state["assignments"].values()
                     if item["executor_seat"] == self.seat and item["status"] == "open"), None)


class Stopped(RuntimeError):
    def __init__(self, seat: str):
        super().__init__(seat)
        self.seat = seat


def _state_path(caller: Caller) -> Path:
    path = caller.path.resolve()
    record = path / "store.json"
    if path.parent != caller.root or not record.is_file():
        clikit.refuse("no coordination store for this host; initialize or join one")
    return record


def _occupant_seat(state: Record, caller: Caller) -> str | None:
    identity = caller.identity()
    return next((seat for seat, entry in state["seats"].items() if entry["occupant"] == identity), None)


def observe(caller: Caller) -> Store | None:
    record = _state_path(caller)
    state = _read(record)
    seat = _occupant_seat(state, caller)
    return Store(record.parent, state, seat) if seat is not None else None


def _raise_if_stopped(state: Record, caller: Caller) -> None:
    if seat := state.get("stopped", {}).get(_identity_key(caller.identity())):
        raise Stopped(seat)


@contextmanager
def transaction(caller: Caller, timeout: float = DEFAULT_TIMEOUT, *,
                accept_stopped: bool = False) -> Iterator[Store]:
    record = _state_path(caller)
    try:
        with _lock(record.parent / ".lock", timeout):
            state = _read(record)
            if accept_stopped:
                _raise_if_stopped(state, caller)
            seat = _occupant_seat(state, caller)
            if seat is None:
                clikit.refuse("participant has no seat in this coordination store")
            previous = json.dumps(state)
            store = Store(record.parent, state, seat)
            yield store
            entry = state["seats"][seat]
            if entry["occupant"] == caller.identity():
                _touch(entry)
            if json.dumps(state) != previous:
                _write(record, state)
    except _StoreBusy:
        if accept_stopped:
            _raise_if_stopped(_read(record), caller)
        raise


def reserve(store: Store, seat: str, role: str) -> Record:
    store.require_main()
    _name(seat, "seat")
    _name(role, "role")
    existing = store.state["seats"].get(seat)
    if existing and (existing["role"] != role or existing["occupant"]):
        clikit.refuse(f"seat is already reserved or occupied: {seat}")
    if not existing:
        existing = store.state["seats"][seat] = _seat(role, invitation=uuid4().hex)
    elif existing["invitation"] is None:
        existing["invitation"] = uuid4().hex
    return _reservation(store, seat, existing, "reserved")


def _reservation(store: Store, seat: str, record: Record, status: str) -> Record:
    return {"seat": seat, "role": record["role"], "status": status,
            "invitation": f"{store.path.name}/{record['invitation']}"}


def replace(store: Store, seat: str) -> Record:
    store.require_main()
    previous = store.state["seats"].get(seat)
    if not previous or seat == "main":
        clikit.refuse(f"cannot replace seat: {seat}")
    now = time.time()
    if now - previous["seen_at"] <= HEARTBEAT_TTL or now < previous["restart_until"]:
        clikit.refuse(f"seat is live: {seat}")
    record = store.state["seats"][seat] = _seat(previous["role"], invitation=uuid4().hex)
    if "mechanism" in previous:
        record["mechanism"] = previous["mechanism"]
    return _reservation(store, seat, record, "replaced")


def _link(caller: Caller, store_path: Path) -> bool:
    if caller.path == store_path:
        return False
    if caller.path.is_symlink() and caller.path.resolve() == store_path:
        return False
    _detach_stopped(caller)
    if caller.path.exists() or caller.path.is_symlink():
        clikit.refuse("this host already has a coordination store")
    caller.path.symlink_to(store_path.name, target_is_directory=True)
    return True


def _identity_key(identity: Record) -> str:
    return _key(identity["host"], identity["shared_host_id"], identity["participant"] or "")


def _detach_stopped(caller: Caller) -> None:
    if not caller.path.is_symlink():
        return
    record = _state_path(caller)
    state = _read(record)
    if _identity_key(caller.identity()) in state.get("stopped", {}) and _occupant_seat(state, caller) is None:
        caller.path.unlink()


def _bind(state: Record, seat: str, identity: Record) -> None:
    active = state["slates"].get(state["active_slate"])
    if active is None:
        return
    previous = active["participants"].setdefault(_identity_key(identity), seat)
    if previous != seat:
        clikit.refuse("this participant already held a different seat on the active slate")


def join(caller: Caller, invitation: str, timeout: float) -> Record:
    owner, delimiter, key = invitation.partition("/")
    if not delimiter or not NAME.fullmatch(owner) or not NAME.fullmatch(key):
        clikit.refuse("invalid coordination invitation", code=2)
    path = caller.root / owner
    if path.is_symlink() or not (path / "store.json").is_file():
        clikit.refuse("no coordination store for this invitation")
    if caller.path == path and not caller.participant:
        clikit.refuse("native participants need a bound participant ID to join")
    with _lock(caller.root / ".lock", timeout), _lock(path / ".lock", timeout):
        state_path = path / "store.json"
        state = _read(state_path)
        identity = caller.identity()
        for seat, record in state["seats"].items():
            if record["occupant"] == identity:
                clikit.refuse(f"participant already holds a seat: {seat}")
        for seat, record in state["seats"].items():
            if record["invitation"] == key and record["occupant"] is None:
                mechanism = record.get("mechanism")
                if mechanism == "advisor" and caller.path == path:
                    clikit.refuse("this seat requires an external advisor")
                if mechanism == "native_subagent" and caller.path != path:
                    clikit.refuse("this invitation is for a native participant")
                _bind(state, seat, identity)
                now = time.time()
                record.update(occupant=identity, invitation=None, seen_at=now, heartbeat_at=now)
                state.setdefault("stopped", {}).pop(_identity_key(identity), None)
                for assignment in state["assignments"].values():
                    if assignment["executor_seat"] == seat and assignment["status"] == "open":
                        assignment["progress_at"] = now
                linked = _link(caller, path)
                try:
                    _write(state_path, state)
                except OSError:
                    if linked:
                        caller.path.unlink()
                    raise
                return {"status": "joined", "seat": seat, "role": record["role"]}
        clikit.refuse("coordination invitation is no longer valid")


def _stop(store: Store, seat: str) -> None:
    record = store.state["seats"][seat]
    occupant = record["occupant"]
    store.state.setdefault("stopped", {})[_identity_key(occupant)] = seat
    record.update(occupant=None, seen_at=0, heartbeat_at=0, restart_until=0)


def release(caller: Caller, seat: str, timeout: float) -> Record:
    with transaction(caller, timeout) as store:
        store.require_main()
        record = store.state["seats"].get(seat)
        if seat == "main" or not record or not record["occupant"]:
            clikit.refuse(f"cannot release seat: {seat}")
        _stop(store, seat)
    return {"status": "released", "seat": seat}


def linked(store: Store, seat: str) -> bool:
    occupant = store.state["seats"][seat]["occupant"]
    return occupant is not None and occupant["shared_host_id"] != store.path.name


def _touch(record: Record) -> None:
    now = time.time()
    if now - record["seen_at"] >= 3:
        record["seen_at"] = now


def heartbeat(store: Store, *, restarting: bool = False, background: bool = False) -> None:
    record = store.state["seats"][store.seat]
    now = time.time()
    if restarting:
        record["restart_until"] = now + RESTART_GRACE
    elif background:
        record.update(heartbeat_at=now, restart_until=0)


def _idle_exit(store: Store) -> Record | None:
    if not linked(store, store.seat):
        return None
    main = store.state["seats"]["main"]
    if time.time() <= max(main["seen_at"] + RESTART_GRACE, main["restart_until"]):
        return None
    if any(item["status"] == "open" and store.seat in (item["executor_seat"], item["receiver_seat"])
           for item in store.state["assignments"].values()):
        return None
    _stop(store, store.seat)
    return {"status": "stopped", "seat": store.seat}


def _stalled_advisor(store: Store) -> Record | None:
    if store.seat != "main":
        return None
    now = time.time()
    minutes = ADVISOR_WORK_TIMEOUT // 60
    for item in store.state["assignments"].values():
        if item["status"] != "open" or now - item["progress_at"] < ADVISOR_WORK_TIMEOUT:
            continue
        seat = item["executor_seat"]
        record = store.state["seats"][seat]
        reserved_advisor = record["invitation"] and record.get("mechanism", record["role"]) == "advisor"
        if linked(store, seat) or reserved_advisor:
            return {"status": "blocked", "seat": seat, "assignment_id": item["assignment_id"],
                    "message": f"Advisor seat {seat} has made no assignment progress for {minutes} minutes."}
    return None


def activate(store: Store, slate_id: str, plugin: str, command: str) -> Record:
    store.require_main()
    _name(slate_id, "slate ID")
    _name(plugin, "planner plugin")
    _name(command, "planner command")
    if store.state["active_slate"] is not None:
        clikit.refuse("finish the active slate before opening another")
    if slate_id in store.state["slates"]:
        clikit.refuse(f"slate ID is already in use: {slate_id}")
    participants = {_identity_key(value["occupant"]): seat for seat, value in store.state["seats"].items()
                    if value["occupant"]}
    record = {"id": slate_id, "planner": [plugin, command], "workflow": [], "participants": participants}
    store.state["slates"][slate_id] = record
    store.state["active_slate"] = slate_id
    return record


def active_slate(store: Store) -> Record | None:
    return store.state["slates"].get(store.state["active_slate"])


def workflow_for(slate_path: Path, slate_id: str) -> list[Record]:
    if slate_path.parent.name != "slates":
        return []
    record = slate_path.parent.parent / "store.json"
    if not record.is_file():
        return []
    return _read(record)["slates"].get(slate_id, {}).get("workflow", [])


@contextmanager
def saved_store(slate_path: Path) -> Iterator[Store | None]:
    path = slate_path.parent.parent
    record = path / "store.json"
    if slate_path.parent.name == "slates" and record.is_file():
        with _lock(path / ".lock", DEFAULT_TIMEOUT):
            yield Store(path, _read(record), "")
    else:
        yield None


@contextmanager
def saved_workflow(slate_path: Path, slate_id: str) -> Iterator[list[Record]]:
    with saved_store(slate_path) as store:
        yield store.state["slates"].get(slate_id, {}).get("workflow", []) if store else []


def finish(store: Store) -> None:
    store.require_main()
    slate = active_slate(store)
    if slate is None:
        clikit.refuse("no active coordination slate")
    if any(item.get("slate") == slate["id"] and item["status"] == "open"
           for item in store.state["assignments"].values()):
        clikit.refuse("complete the active slate's assignments before finishing it")
    store.state["active_slate"] = None


def _planner(store: Store, timeout: float, *, completion: Record | None = None) -> Record | None:
    slate = active_slate(store)
    assert slate is not None
    request = {"slate": slate, "store": str(store.path), "seat": store.seat,
               "role": store.state["seats"][store.seat]["role"]}
    if completion is not None:
        request["complete"] = completion
    argv = clikit.gear_argv(*slate["planner"])
    try:
        result = subprocess.run(argv, input=json.dumps(request), text=True, capture_output=True,
                                check=False, timeout=timeout)
        if result.returncode:
            clikit.refuse(f"coordination planner failed: {result.stderr.strip() or result.returncode}")
        plan = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        clikit.refuse(f"coordination planner failed: {error}")
    return plan


def _plan(store: Store, timeout: float) -> Record | None:
    slate = active_slate(store)
    if slate is None or (store.seat != "main" and store.seat not in slate.get("roster", {})):
        return None
    plan = _planner(store, timeout)
    if plan is None:
        return None
    if (not isinstance(plan, dict) or set(plan) != {"batch", "receiver", "work"}
            or not isinstance(plan["batch"], str) or not plan["batch"]
            or not isinstance(plan["receiver"], str) or plan["receiver"] not in store.state["seats"]
            or not _valid_work(plan["work"])):
        clikit.refuse("coordination planner failed: invalid work")
    batch = _key(slate["id"], store.seat, plan["batch"])
    if batch in store.state["requests"]:
        return None
    summary = assign(store, store.seat, plan["receiver"], None,
                     request_key=batch, slate=slate["id"], work=plan["work"], batch=plan["batch"])
    return store.state["assignments"][summary["assignment_id"]]


def _valid_work(work: object) -> bool:
    if not isinstance(work, dict) or not isinstance(work.get("phase"), str):
        return False
    actions = work.get("actions")
    return isinstance(actions, list) and bool(actions) and all(
        isinstance(action, dict) and isinstance(action.get("input"), dict)
        and isinstance(action["input"].get("action"), str) for action in actions
    )


def send(store: Store, seat: str, message: str, request_key: str | None) -> Record:
    if seat not in store.state["seats"] or seat == store.seat:
        clikit.refuse(f"unknown or invalid recipient seat: {seat}")
    if not message.strip():
        clikit.refuse("send requires a message")
    request_key = _key(store.seat, request_key or _key(seat, message))
    existing = store.state["requests"].get(request_key)
    if existing:
        item = store.state["assignments"][existing]
        if item["executor_seat"] != seat or item["message"] != message:
            clikit.refuse("request key already identifies a different assignment")
        return {"assignment_id": existing, "status": item["status"]}
    return assign(store, seat, store.seat, message, request_key=request_key)


def assign(store: Store, executor: str, receiver: str, message: str | None, *,
           request_key: str | None = None, **attributes: Any) -> Record:
    assignment_id = uuid4().hex
    summary = {"assignment_id": assignment_id, "status": "open"}
    if work := attributes.get("work"):
        for action in work["actions"]:
            action["input"]["assignment_id"] = assignment_id
    item = store.delivery(executor, "assignment",
                          {**summary, "executor_seat": executor, "receiver_seat": receiver,
                           "message": message, **attributes})
    store.state["assignments"][assignment_id] = {**item, "progress_at": time.time()}
    if request_key:
        store.state["requests"][request_key] = assignment_id
    return summary


def poll(store: Store, acknowledge: str | None, timeout: float = DEFAULT_TIMEOUT) -> Record:
    deliveries = [row for row in store.state["deliveries"] if row["recipient"] == store.seat]
    if acknowledge:
        item = next((row for row in deliveries if row["body"]["delivery_id"] == acknowledge), None)
        if item is None:
            clikit.refuse("delivery does not belong to the polling seat")
        item["ack"] = True
    unread = next((row["body"] for row in deliveries if not row["ack"]), None)
    return (unread or store.open_assignment() or _plan(store, timeout) or _stalled_advisor(store)
            or _idle_exit(store) or {"status": "idle"})


def complete(store: Store, assignment_id: str, message: str | None,
             timeout: float = DEFAULT_TIMEOUT) -> Record:
    assignment = store.state["assignments"].get(assignment_id)
    if assignment is None or assignment["executor_seat"] != store.seat:
        clikit.refuse("assignment can only be completed by its executor seat")
    summary = {"assignment_id": assignment_id, "status": "complete"}
    if assignment["status"] == "complete":
        if assignment["reply"] != message:
            clikit.refuse("assignment already completed with a different reply")
        return summary
    if "slate" in assignment:
        active = active_slate(store)
        if active is None or active["id"] != assignment["slate"]:
            clikit.refuse("assignment does not belong to the active slate")
        completed = _planner(store, timeout, completion=assignment)
        if (not isinstance(completed, dict) or set(completed) != {"workflow"}
                or not isinstance(completed["workflow"], list)):
            clikit.refuse("coordination planner failed: invalid completion")
        active["workflow"].extend(completed["workflow"])
        assignment["advisor_work"] = linked(store, store.seat)
    assignment.update(status="complete", reply=message)
    for delivery in store.state["deliveries"]:
        if delivery["body"]["delivery_id"] == assignment["delivery_id"]:
            delivery["ack"] = True
            break
    store.delivery(assignment["receiver_seat"], "result", {**summary, "message": message})
    return summary


def blocked(store: Store, message: str) -> Record:
    if store.seat == "main":
        clikit.refuse("main already owns the workflow")
    if not message.strip():
        clikit.refuse("blocked requires a description")
    assignment = store.open_assignment()
    return store.delivery("main", "blocked", {"seat": store.seat, "message": message,
                                               "assignment_id": assignment["assignment_id"]
                                               if assignment else None})
