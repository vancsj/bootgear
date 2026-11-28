"""Create slates and manage their Git snapshots."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from bootgear_cli import coordination
from bootgear_cli.clikit import argv_template, emit, gear_command

from . import angles as angles_mod
from . import assignments, ledger, native_profiles, seats
from . import config as config_mod
from .cli_common import (
    CATALOG,
    _ids,
    _next_step,
    _path,
    _read,
    _refuse,
    _refuse_next,
    _workflow,
    _write,
)
from .model import Slate

# ---------------------------------------------------------------------------
# git snapshots


def _ref(slate_id: str) -> str:
    return f"refs/converge/{slate_id}"


def _git(root: Path, *argv: str, env: dict[str, str] | None = None
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True,
                          env=env, check=False)


def _git_error(what: str, out: subprocess.CompletedProcess[str]) -> str:
    return f"{what} failed (exit {out.returncode}): {out.stderr.strip() or out.stdout.strip()}"


def _git_root(project_root: Path) -> tuple[Path | None, str | None]:
    """The work-tree top level of `project_root`, or the reason it is not a git repo."""
    try:
        out = _git(project_root, "rev-parse", "--show-toplevel")
    except OSError as exc:
        return None, f"git is not runnable: {exc}"
    if out.returncode != 0:
        return None, (f"--project-root {project_root} is not a git work tree: "
                      f"{out.stderr.strip()}")
    return Path(out.stdout.strip()), None


def _snapshot_commit(root: Path, slate_id: str) -> str:
    """Commit the work tree, untracked files included, through a temp index."""
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    has_head = head.returncode == 0
    with tempfile.TemporaryDirectory(prefix="converge-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        steps = [("read-tree", "HEAD")] if has_head else []
        for step in [*steps, ("add", "-A")]:
            out = _git(root, *step, env=env)
            if out.returncode != 0:
                _refuse([_git_error(f"snapshot: git {' '.join(step)}", out)])
        tree = _git(root, "write-tree", env=env)
        if tree.returncode != 0:
            _refuse([_git_error("snapshot: git write-tree", tree)])
        parent = ["-p", "HEAD"] if has_head else []
        commit = _git(root, "-c", "user.name=converge", "-c", "user.email=converge@localhost",
                      "commit-tree", tree.stdout.strip(), *parent,
                      "-m", f"converge snapshot {slate_id}", env=env)
        if commit.returncode != 0:
            _refuse([_git_error("snapshot: git commit-tree", commit)])
    return commit.stdout.strip()


def _since_problems(args: argparse.Namespace, root: Path | None
                    ) -> tuple[dict[str, str] | None, list[str]]:
    """The previous slate's {slate, snapshot}, or every failed --since check."""
    try:
        prev_path = ledger.slate_path(args.dir, args.since)
    except ledger.LedgerError as exc:
        return None, [f"--since: {p}" for p in exc.problems]
    if not prev_path.is_file():
        return None, [f"--since: prev exists: no slate {args.since!r} in {args.dir}"]
    try:
        prev = ledger.read(prev_path, args.since, workflow=_workflow(args, args.since))
    except ledger.LedgerError as exc:
        return None, [f"--since: prev exists: slate {args.since!r} is unreadable: "
                      + "; ".join(exc.problems)]
    problems = []
    if prev.snapshot is None:
        problems.append(f"--since: prev has a snapshot sha: {args.since!r} was not started "
                        f"with --snapshot")
    elif root is not None:
        out = _git(root, "cat-file", "-e", f"{prev.snapshot}^{{commit}}")
        if out.returncode != 0:
            problems.append(f"--since: git cat-file -e {prev.snapshot}^{{commit}} failed in "
                            f"{root}: {out.stderr.strip() or 'no such commit'}")
    if prev.review_pass is None or args.review_pass != prev.review_pass + 1:
        expected = "prev pass + 1" if prev.review_pass is None else str(prev.review_pass + 1)
        problems.append(f"--since: --pass must equal {args.since!r}'s pass + 1 ({expected}); "
                        f"got {args.review_pass}")
    if problems or prev.snapshot is None:
        return None, problems
    return {"slate": args.since, "snapshot": prev.snapshot}, []


def _snapshot_problems(args: argparse.Namespace) -> list[str]:
    """Flag checks that need no git or ledger read."""
    problems = []
    if args.review_pass is not None and args.review_pass < 1:
        problems.append(f"--pass must be >= 1; got {args.review_pass}")
    if args.snapshot and args.review_pass is None:
        problems.append("--snapshot requires --pass <n>")
    if args.since is not None and not args.snapshot:
        problems.append("--since requires --snapshot")
    return problems


# ---------------------------------------------------------------------------
# seats


def _slate_seats(refuters: int) -> tuple[str, ...]:
    """The seats a slate with this refuter count holds."""
    return tuple(seat for seat in seats.SEATS if refuters == 2 or seat != "r2")


def _init_seats(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    """The init event's `seats`/`advisor` fields and the NOTE texts, from
    --settlement; refuses a malformed or mismatched settlement before any write."""
    if args.settlement is None:
        return {}, []
    fix = (f"correct converge_seats or advisor_roles in {args.settlement} so they agree, then "
           f"rerun init; in an engine run the settlement is fixed: stop blocked and report "
           f"this refusal")
    try:
        settlement = yaml.safe_load(args.settlement.read_text())
    except (OSError, yaml.YAMLError) as exc:
        _refuse_next(args, "invalid settlement seats",
                     [f"--settlement {args.settlement} is unreadable: {exc}"], fix)
    if not isinstance(settlement, dict):
        _refuse_next(args, "invalid settlement seats",
                     ["--settlement must be a YAML mapping (the engine settlement)"], fix)
    roles, chosen = settlement.get("advisor_roles"), settlement.get("converge_seats")
    shape = [*seats.roles_problems(roles), *seats.seat_problems(chosen)]
    if shape:
        _refuse_next(args, "invalid settlement seats", [f"{f}: {m}" for f, m in shape], fix)
    mismatch = seats.seat_mismatch(roles, chosen)
    if mismatch:
        _refuse_next(args, "settlement seats do not match its advisor roles",
                     [f"{f}: {m}" for f, m in mismatch], fix)
    every = seats.resolved(chosen or {})
    held = _slate_seats(args.refuters)
    fields: dict[str, Any] = {"seats": {seat: every[seat] for seat in held}}
    notes = []
    if every[seats.ADVISOR_SEAT] == "advisor":
        if seats.ADVISOR_SEAT not in held:
            notes.append("r2 is advisor in the settlement, but this slate has no r2; "
                         "the advisor holds no seat on this slate")
        else:
            named, brief, defaulted = seats.seat_roles(roles, seats.ADVISOR_SEAT)
            fields["advisor"] = {"roles": named, "brief": brief,
                                 "startup": roles.get("startup", "direct") if roles is not None else "direct"}
            if roles and "launcher" in roles:
                fields["advisor"]["launcher"] = roles["launcher"]
            if defaulted:
                notes.append("r2 is advisor with no advisor role in the settlement; it takes "
                             f"{', '.join(named)} and the stock brief")
    return fields, notes


# ---------------------------------------------------------------------------
# write commands


def cmd_init(args: argparse.Namespace) -> None:
    if args.slate is not None:
        if args.require_advisor:
            _refuse(["--require-advisor needs an active coordination store"])
        args.dir = args.dir or ledger.DEFAULT_DIR.expanduser()
        if args.agent is None:
            _refuse(["explicit slate initialization requires --as"])
        _init(args)
        return
    if args.dir is not None or args.agent is not None:
        _refuse(["the active slate derives its directory and seat from the coordination store"])
    with coordination.transaction(coordination.Caller.from_environment()) as store:
        args.dir = store.path / "slates"
        while True:
            args.slate = f"review-{uuid4().hex[:8]}"
            if args.slate not in store.state["slates"] and not ledger.slate_path(args.dir, args.slate).exists():
                break
        args.agent = "main"
        args.coordination_store = store
        coordination.activate(store, args.slate, "converge", "plan")
        _init(args, store)


def _init(args: argparse.Namespace, store: coordination.Store | None = None) -> None:
    seat_fields, notes = _init_seats(args)
    if args.artifact is not None or args.advisor_brief is not None:
        if store is None or args.artifact is None or args.advisor_brief is None:
            _refuse(["use --artifact and --advisor-brief together when opening the active coordination slate"])
        if not args.artifact.is_file() or not args.advisor_brief.is_file():
            _refuse(["--artifact and --advisor-brief must name files"])
        active = coordination.active_slate(store)
        assert active is not None
        active["advisor_scope"] = {"artifact": str(args.artifact), "brief": str(args.advisor_brief)}
    launcher = seat_fields.get("advisor", {}).get("launcher")
    launch_argv = None
    if store is not None and launcher:
        try:
            markers = ("{invitation}", "{seat}") if "{seat}" in launcher else ("{invitation}",)
            launch_argv = argv_template(launcher, markers)
        except ValueError as error:
            _refuse([f"advisor launcher: {error}"])
    project_root = args.project_root.expanduser().resolve()
    task_config = args.config
    try:
        resolved = config_mod.resolve(project_root, task_config, args.defaults)
    except config_mod.ConfigError as exc:
        _refuse(exc.problems, "invalid configuration")
    effective = resolved["effective"]
    report_rules = effective["cutoff"]["report_rules"]
    for rule in args.report_rule:
        if rule not in report_rules:
            report_rules.append(rule)
    if any(not rule.strip() for rule in args.report_rule):
        _refuse(["--report-rule requires a nonempty rule ID"])
    counts = effective["parallelism"]
    try:
        rows = angles_mod.resolve(args.angles, effective, Path(resolved["project_root"]))
    except angles_mod.AngleError as exc:
        _refuse(exc.problems, "invalid angles")
    if args.review_pass is not None and args.review_pass >= 2:
        effective = config_mod.rereview(effective)
    event: dict[str, Any] = {"event": "init", "lenses": _ids(args.lenses), "angles": rows,
                             "config": effective, "refuters": args.refuters,
                             "project_root": resolved["project_root"]}
    if store is not None:
        event["coordinated"] = True
    if task_config is not None:
        event["task_config"] = str(task_config.resolve())
    if effective.get("finder_routing") is not None:
        host = os.environ.get("BOOTGEAR_HOST", "claude")
        initial = Slate(args.slate, lenses=event["lenses"], angles=rows, config=effective)
        plan = assignments.finder_plan(initial, host)
        if plan.problems:
            _refuse(plan.problems, "finder capacity")
        event["native_host"] = host
    if effective.get("finder_routing") is not None or effective.get("native_profiles"):
        event["native_host"] = os.environ.get("BOOTGEAR_HOST", "claude")
    if args.review_pass is not None:
        event["pass"] = args.review_pass
    event.update(seat_fields)
    participants = None
    if store is not None:
        slate = Slate(args.slate)
        initial = {**event, "as": args.agent}
        if problems := ledger.validate_event(slate, initial):
            _refuse(problems)
        ledger.apply_event(slate, initial)
        participants = _prepare_seats(store, slate, launch_argv, args.require_advisor)
    problems = _snapshot_problems(args)
    if not args.snapshot:
        if problems:
            _refuse(problems)
        event = _write(args, event, create=True)
    else:
        event = _init_snapshot(args, event, problems)
    path = _path(args)
    data: dict[str, Any] = {"slate": args.slate, "lenses": event["lenses"], "angles": len(rows),
                            "path": str(path),
                            "parallelism": effective["parallelism"]}
    workers = " ".join(f"{seat}={counts[seat]}" for seat in ("finder", "r1", "r2"))
    head = (f"INIT {args.slate} lenses={','.join(event['lenses']) or '-'} "
            f"angles={len(rows)} {workers} path={path}")
    for key in ("pass", "snapshot"):
        if key in event:
            data[key] = event[key]
            head += f" {key}={event[key]}"
    lines = [head]
    if "task_config" in event:
        data["task_config"] = event["task_config"]
    if "since" in event:
        delta = f"git diff {event['since']['snapshot']} {event['snapshot']}"
        data["since"], data["diff"] = event["since"]["slate"], delta
        lines.append(f"DIFF since {event['since']['slate']}: {delta}")
    if participants is not None:
        data["participants"] = participants
        lines.extend("SEAT " + " ".join(f"{key}={value}" for key, value in member.items()
                                        if value is not None) for member in participants)
        emit(args.output_mode, data, lines, "start the invited native participants, then run "
             + gear_command("cli", "coordination") + " poll")
        return
    slate_seats = event.get("seats", {})
    if event.get("advisor") or notes:
        data.update(seats=slate_seats, notes=notes)
        lines.append("SEATS " + " ".join(f"{seat}={m}" for seat, m in slate_seats.items()))
        lines.extend(f"NOTE {note}" for note in notes)
    next_step = _next_step(args, _read(args)) if "native_host" in event else None
    emit(args.output_mode, data, lines, next_step)


def _prepare_seats(store: coordination.Store, slate: Slate,
                   launch_argv: list[str] | None, require_advisor: bool) -> list[dict[str, Any]]:
    roster = {**assignments.workers(slate), "cutter": "cutter"}
    active = coordination.active_slate(store)
    assert active is not None
    active["roster"] = roster
    advisors = [seat for seat, role in roster.items() if slate.mechanism(role) == "advisor"]
    if require_advisor and not advisors:
        _refuse(["this task requires an external advisor seat in its settlement"])
    if require_advisor and all(
            (entry := store.state["seats"].get(seat)) and entry["occupant"] and not coordination.linked(store, seat)
            for seat in advisors):
        _refuse(["release a seated native refuter before opening a review that requires an external advisor"])
    active.update(advisors=advisors, advisor_launch=launch_argv, advisor_required=require_advisor, advisor_gaps={})
    profiles = native_profiles.profiles(slate)
    participants = []
    for seat, role in roster.items():
        reservation = _seat_invitation(store, seat, role)
        record = store.state["seats"][seat]
        if seat in advisors:
            if record["occupant"] and not coordination.linked(store, seat):
                active["advisor_gaps"][seat] = "Using the seated native participant."
                record["mechanism"] = "native_subagent"
            else:
                record["mechanism"] = "advisor"
                reservation.pop("invitation", None)
        else:
            record.pop("mechanism", None)
        member = {**reservation, "mechanism": record.get("mechanism", slate.mechanism(role)),
                  "profile": profiles.get(seat)}
        participants.append(member)
    return participants


def _seat_invitation(store: coordination.Store, seat: str, role: str) -> dict[str, Any]:
    previous = store.state["seats"].get(seat)
    if previous and previous["occupant"] and previous["role"] == role:
        return {"seat": seat, "role": role, "status": "joined"}
    return coordination.reserve(store, seat, role)


def _init_snapshot(args: argparse.Namespace, event: dict[str, Any],
                   problems: list[str]) -> dict[str, Any]:
    """Check every --snapshot/--since precondition, pin the snapshot ref, then append init;
    a failed append deletes the ref."""
    root, reason = _git_root(args.project_root)
    if reason:
        problems.append(f"--snapshot requires a git --project-root: {reason}")
    since = None
    if args.since is not None and args.review_pass is not None:
        since, since_problems = _since_problems(args, root)
        problems.extend(since_problems)
    path = _path(args)
    if path.is_file():
        try:
            ledger.read(path, args.slate, workflow=_workflow(args, args.slate))
            problems.append(f"slate {args.slate!r} is already initialised in {args.dir}")
        except ledger.LedgerError as exc:
            if path.stat().st_size:
                problems.extend(exc.problems)
    if problems:
        _refuse(problems)
    assert root is not None
    sha = _snapshot_commit(root, args.slate)
    ref = _ref(args.slate)
    # Generated IDs must not take an existing snapshot from a different store.
    expected = ("",) if getattr(args, "coordination_store", None) is not None else ()
    pinned = _git(root, "update-ref", ref, sha, *expected)
    if pinned.returncode != 0:
        _refuse([_git_error(f"pin: git update-ref {_ref(args.slate)} {sha}", pinned)])
    event = {"as": args.agent, **event, "snapshot": sha}
    if since is not None:
        event["since"] = since
    try:
        return ledger.append(path, args.slate, event, create=True)
    except BaseException as exc:
        removed = _git(root, "update-ref", "-d", ref, sha)
        if removed.returncode == 0:
            cleanup = f"removed {_ref(args.slate)}"
        else:
            cleanup = (_git_error(f"remove {_ref(args.slate)}", removed)
                       + f"; run: {CATALOG.display_prog()} prune {args.slate} --project-root {root}")
        if isinstance(exc, ledger.LedgerError):
            _refuse([*exc.problems, cleanup])
        raise
