"""Create slates and manage their Git snapshots."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from bootgear_cli.clikit import emit

from . import angles as angles_mod
from . import assignments, ledger, seats
from . import config as config_mod
from .cli_advisor import _driver_lines, _drivers, launcher_problems
from .cli_common import (
    CATALOG,
    _ids,
    _next_step,
    _path,
    _read,
    _refuse,
    _refuse_next,
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
        prev = ledger.read(prev_path, args.since)
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
                                 "startup": roles.get("startup", "early") if roles is not None else "early"}
            if roles and "launcher" in roles:
                fields["advisor"]["launcher"] = roles["launcher"]
            if defaulted:
                notes.append("r2 is advisor with no advisor role in the settlement; it takes "
                             f"{', '.join(named)} and the stock brief")
    return fields, notes


# ---------------------------------------------------------------------------
# write commands


def _review_inputs(args: argparse.Namespace, project_root: Path) -> tuple[str, Path | None]:
    if args.review_group is not None:
        return args.review_group, args.config
    prior = args.continue_from
    if prior is None:
        return str(_path(args).resolve()), args.config
    try:
        path = ledger.slate_path(args.dir, prior)
        previous = ledger.read(path, prior)
    except ledger.LedgerError as error:
        _refuse(error.problems, "cannot continue standalone review")
    if previous.project_root != str(project_root):
        _refuse([f"preceding slate {prior!r} belongs to a different project"])
    saved = Path(previous.task_config) if previous.task_config is not None else None
    return previous.review_group or str(path.resolve()), args.config or saved


def _r2_retry_problems(counts: dict[str, int], approved: list[int]) -> list[str]:
    expected = {"finder": approved[0], "r1": approved[1], "r2": 1}
    problems = []
    for seat, value in expected.items():
        if value < 1:
            problems.append(f"approved {seat} count must be positive; got {value}")
        elif counts[seat] != value:
            problems.append(f"parallelism.{seat} is {counts[seat]}, expected {value} for this r2-only retry")
    return problems


def cmd_init(args: argparse.Namespace) -> None:
    seat_fields, notes = _init_seats(args)
    project_root = args.project_root.expanduser().resolve()
    review_group, task_config = _review_inputs(args, project_root)
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
    if args.r2_only_retry is not None:
        problems = _r2_retry_problems(counts, args.r2_only_retry)
        if problems:
            _refuse_next(args, "invalid r2-only retry", problems,
                         "Restore the approved finder and r1 counts and set r2 to 1 before retrying init.")
    r2_workers = counts["r2"]
    if r2_workers > 1 and seat_fields.get("seats", {}).get("r2") == "advisor":
        problems = launcher_problems(seat_fields["advisor"])
        if problems:
            _refuse_next(args, "invalid parallel advisor launcher", problems,
                         "For a parallel launch, use an approved invitation-aware launcher. "
                         "For an approved task override of parallelism.r2 only, set r2 to 1. "
                         f"Retry with --r2-only-retry {counts['finder']} {counts['r1']}. "
                         "Preserve finder and r1 counts and other task settings.")
    try:
        rows = angles_mod.resolve(args.angles, effective, Path(resolved["project_root"]))
    except angles_mod.AngleError as exc:
        _refuse(exc.problems, "invalid angles")
    if args.review_pass is not None and args.review_pass >= 2:
        effective = config_mod.rereview(effective)
    event: dict[str, Any] = {"event": "init", "lenses": _ids(args.lenses), "angles": rows,
                             "config": effective, "refuters": args.refuters,
                             "project_root": resolved["project_root"],
                             "review_group": review_group}
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
    problems = _snapshot_problems(args)
    if not args.snapshot:
        if problems:
            _refuse(problems)
        event = _write(args, event, create=True)
    else:
        event = _init_snapshot(args, event, problems)
    path = _path(args)
    data: dict[str, Any] = {"slate": args.slate, "lenses": event["lenses"], "angles": len(rows),
                            "path": str(path), "review_group": event["review_group"],
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
    slate_seats = event.get("seats", {})
    drivers = _drivers(args.slate, args.dir, slate_seats, event.get("advisor"),
                       review_group=event["review_group"], r2_workers=r2_workers)
    if drivers or notes:
        data.update(seats=slate_seats, drivers=drivers, notes=notes)
        lines.append("SEATS " + " ".join(f"{seat}={m}" for seat, m in slate_seats.items()))
        for driver in drivers:
            lines.extend(_driver_lines(driver))
        lines.extend(f"NOTE {note}" for note in notes)
    early = event.get("advisor", {}).get("startup") != "deferred"
    step = (("; ".join(driver["prepare"] for driver in drivers) or None) if early
            else _next_step(args, _read(args)))
    if step is None and "native_host" in event:
        step = _next_step(args, _read(args))
    emit(args.output_mode, data, lines, step)


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
            ledger.read(path, args.slate)
            problems.append(f"slate {args.slate!r} is already initialised in {args.dir}")
        except ledger.LedgerError as exc:
            if path.stat().st_size:
                problems.extend(exc.problems)
    if problems:
        _refuse(problems)
    assert root is not None
    sha = _snapshot_commit(root, args.slate)
    pinned = _git(root, "update-ref", _ref(args.slate), sha)
    if pinned.returncode != 0:
        _refuse([_git_error(f"pin: git update-ref {_ref(args.slate)} {sha}", pinned)])
    event = {"as": args.agent, **event, "snapshot": sha}
    if since is not None:
        event["since"] = since
    try:
        return ledger.append(path, args.slate, event, create=True)
    except BaseException as exc:
        removed = _git(root, "update-ref", "-d", _ref(args.slate))
        if removed.returncode == 0:
            cleanup = f"removed {_ref(args.slate)}"
        else:
            cleanup = (_git_error(f"remove {_ref(args.slate)}", removed)
                       + f"; run: {CATALOG.display_prog()} prune {args.slate} --project-root {root}")
        if isinstance(exc, ledger.LedgerError):
            _refuse([*exc.problems, cleanup])
        raise
