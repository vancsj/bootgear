"""`converge` command line: write events, query state, compute cutoff, gate, render."""
from __future__ import annotations

import argparse
import contextlib
import copy
import dataclasses
import io
import itertools
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

import yaml

from . import angles as angles_mod
from . import config as config_mod
from . import ledger, model, protocol, render, seats
from .clikit import (
    Catalog,
    Refusal,
    add_mode_flags,
    caller_cwd,
    caller_path,
    dumps,
    emit,
    parser_class,
    refuse,
    render_refusal,
    run,
)
from .model import Slate

EXIT_OK, EXIT_NO, EXIT_REFUSED = 0, 1, 2
_MISSING = "continue the finder with the missing angles, then "

# Leaf command -> runnable argv after the program, shown in every refusal.
EXAMPLES = {
    "init": "init <slate> --dir <dir> --as main --lenses <a,b> --angles <file> "
            "--settlement <file>",
    "file": "file <slate> --dir <dir> --as finder --lens <lens> --angle <angle> --origin lens "
            '--loc <path:line> --claim "<claim>" --trigger "<trigger>"',
    "escalate": 'escalate <slate> --dir <dir> --as finder --claim F001 --wider "<text>" '
                '--evidence "<route>"',
    "find-run": "find-run <slate> --dir <dir> --as finder --lens <lens> --angle <angle> "
                '--tell "<tell>" --searches "<searches>" --positive-control "<hit>" --result none',
    "angle-na": "angle-na <slate> --dir <dir> --as r1 --phase attack --claim F001 "
                '--angle <angle> --reason "<why>"',
    "attack": "attack <slate> --dir <dir> --as r1 --claim F001 --batch 1 --angle <angle> "
              '--tell "<tell>" --outcome clean --evidence "<evidence>" --searches "<searches>" '
              '--positive-control "<hit>"',
    "reply": 'reply <slate> --dir <dir> --as finder --claim F001 --batch 1 --stance rebut '
             '--evidence "<new evidence>"',
    "verdict": "verdict <slate> --dir <dir> --as r1 --claim F001 --batch 1 --verdict agree",
    "cut": "cut <slate> --dir <dir> --as cutter --claim F001 --when after --round 1 "
           "--frequency common --severity wrong-behavior --confidence traced --difficulty local "
           "--evidence <angle>=<evidence>",
    "rebut": 'rebut <slate> --dir <dir> --as finder --claim F001 --when after '
             '--evidence "<new evidence>"',
    "accept": "accept <slate> --dir <dir> --as finder --claim F001 --when after --round 1",
    "status": "status <slate> --dir <dir> --json",
    "converged": "converged <slate> --dir <dir>",
    "cutoff": "cutoff <slate> --dir <dir>",
    "coverage": "coverage <slate> --dir <dir>",
    "gate": "gate <slate> --dir <abs-dir>",
    "render": "render <slate> --dir <dir>",
    "angles": "angles --tag find --angles <file>",
    "config": "config validate --project-root <dir>",
    "prune": "prune <slate> <slate> --project-root <dir>",
}
ANGLE_NA_FIND = ("angle-na <slate> --dir <dir> --as finder --phase find --lens <lens> "
                 '--angle <angle> --reason "<why>"')
FREQUENT = ("file", "attack", "reply", "verdict", "cut", "status", "converged")
CATALOG = Catalog(prog="converge", examples=EXAMPLES, frequent=FREQUENT,
                  legacy_json=frozenset({"status"}))
# A `--phase find` call's refusals show the find form of the angle-na example.
FIND_CATALOG = dataclasses.replace(CATALOG, examples={**EXAMPLES, "angle-na": ANGLE_NA_FIND})


def _refuse(problems: list[str], what: str = "refused") -> NoReturn:
    refuse(f"converge: {what}:", [("", p) for p in problems], code=EXIT_REFUSED)


def _refuse_next(args: argparse.Namespace, message: str, problems: list[str],
                 next_step: str) -> NoReturn:
    """A refusal with its example and command list, then the next step: the last prose
    line, or the error object's `next` in JSON."""
    buffer = io.StringIO()
    refusal = Refusal(f"converge: {message}:", [("", p) for p in problems], code=EXIT_REFUSED)
    find = args.command == "angle-na" and args.phase == "find"
    with contextlib.redirect_stderr(buffer):
        render_refusal(FIND_CATALOG if find else CATALOG, args.command, refusal,
                       args.output_mode)
    if args.output_mode == "json":
        error = json.loads(buffer.getvalue())
        error["error"]["next"] = next_step
        print(dumps(error), file=sys.stderr)
    else:
        sys.stderr.write(f"{buffer.getvalue()}next: {next_step}\n")
    sys.exit(EXIT_REFUSED)


def _step(args: argparse.Namespace, name: str, *rest: str) -> str:
    """Runnable `converge <name>` on this slate and dir, for a `next:` line."""
    tail = "".join(f" {part}" for part in rest)
    return CATALOG.command(f"{name} {shlex.quote(args.slate)} "
                           f"--dir {shlex.quote(str(args.dir))}{tail}")


def _path(args: argparse.Namespace) -> Path:
    try:
        return ledger.slate_path(args.dir, args.slate)
    except ledger.LedgerError as exc:
        _refuse(exc.problems)


def _read(args: argparse.Namespace) -> Slate:
    try:
        return ledger.read(_path(args), args.slate)
    except ledger.LedgerError as exc:
        _refuse(exc.problems)


def _write(args: argparse.Namespace, event: dict[str, Any], *, create: bool = False,
           build: Any = None) -> dict[str, Any]:
    """Append one event; a refusal ends with the slate's next step when the slate reads."""
    event = {"as": args.agent, **event} if "as" not in event else event
    try:
        return ledger.append(_path(args), args.slate, event, create=create, build=build)
    except ledger.LedgerError as exc:
        if create:
            _refuse(exc.problems)
        try:
            slate = ledger.read(_path(args), args.slate)
        except ledger.LedgerError:
            _refuse(exc.problems)
        _refuse_next(args, "refused", exc.problems, _next_step(args, slate))


def _written(args: argparse.Namespace, data: dict[str, Any], line: str) -> None:
    """Print a written event's result line and the slate's next step."""
    emit(args.output_mode, data, line, _next_step(args, _read(args)))


# ---------------------------------------------------------------------------
# the next step, from the slate's phase


def _gap_hunt_open(slate: Slate) -> bool:
    """The gap hunt may still file: it is on, the slate has r2, and no escalate, cut or attack
    is written."""
    return (bool(slate.config["steps"]["gap_hunt"]) and slate.init_refuters == 2
            and not any(e["event"] in ("escalate", "cut", "attack") for e in slate.events))


def _plan_text(slate: Slate) -> str:
    """The plan rows grouped by agent role and action, in plan order."""
    groups: dict[tuple[str, str], list[str]] = {}
    for row in itertools.chain.from_iterable(protocol.batch_plan(slate)):
        item = row["claim"] + (f" batch {row['batch']}" if row["batch"] is not None else "")
        groups.setdefault((row["agent_role"], row["action"]), []).append(item)
    return "; ".join(f"{role} {action} {', '.join(items)}"
                     for (role, action), items in groups.items())


def _next_step(args: argparse.Namespace, slate: Slate) -> str:
    """The next legal action on the slate, from `protocol.slate_phase`."""
    phase = protocol.slate_phase(slate)
    if phase == "find":
        return _MISSING + _step(args, "coverage")
    if phase == "done":
        return _step(args, "render")
    step = (_step(args, "cutoff") if phase == "cutoff"
            else f"{phase}: {_plan_text(slate)}; plan: {_step(args, 'status', '--json')}")
    if _gap_hunt_open(slate):
        gap = _step(args, "file", "--as r2 --origin gap-hunt")
        return (f"gap hunt: r2 files the claims the lenses missed ({gap} ...) before the first "
                f"escalate, cut or attack; then {step}")
    return step


def _ids(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _opt(event: dict[str, Any], **values: Any) -> dict[str, Any]:
    event.update({k: v for k, v in values.items() if v is not None})
    return event


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
            fields["advisor"] = {"roles": named, "brief": brief}
            if defaulted:
                notes.append("r2 is advisor with no advisor role in the settlement; it takes "
                             f"{', '.join(named)} and the stock brief")
    return fields, notes


def _converge_path() -> Path:
    """This host's converge wrapper, for a listener that does not share PATH."""
    wrapper = "scripts" if os.environ.get("CONVERGE_HOST") == "codex" else "bin"
    return Path(__file__).resolve().parents[2] / wrapper / "converge"


def _drivers(slate_id: str, ledger_dir: Path, slate_seats: dict[str, str],
             advisor: dict[str, Any] | None) -> list[dict[str, str]]:
    """How the orchestrator drives each advisor seat through the advisor channel."""
    drivers = []
    abs_dir = ledger_dir.resolve()
    for seat, mechanism in slate_seats.items():
        if mechanism != "advisor":
            continue
        if advisor is None:
            named, brief, _ = seats.seat_roles(None, seat)
        else:
            named, brief = advisor["roles"], advisor["brief"]
        body = shlex.quote(str(abs_dir / f"{slate_id}.{seat}.request.txt"))
        channel = 'python3 "$CHANNEL_SCRIPT"'
        converge = shlex.quote(str(_converge_path()))
        quoted_dir = shlex.quote(str(abs_dir))
        drivers.append({
            "seat": seat,
            "step": (f'{channel} send --channel "$CHANNEL" --from asker --to listener '
                     f"--kind request --body-file {body} && "
                     f'{channel} receive --channel "$CHANNEL" --for asker --timeout 300'),
            "placeholders": ("a fresh shell keeps no variables, so write the step with the "
                             "literal channel.py path and channel number the pairing printed in "
                             'place of "$CHANNEL_SCRIPT" and "$CHANNEL"'),
            "then": ("do not run the while-loop next that send prints; a turn has 5 receives in "
                     "total, the one in the step included; on receive exit 1 run that receive "
                     "alone again; take the response whose parent_id is this send's message_id "
                     "and fetch it; a stale peer, or no matching response after the 5th receive, "
                     f"stops the slate blocked naming {seat}"),
            "other_messages": ("a response whose parent_id is not this send's message_id is a "
                               "late reply: fetch it so it stops reappearing, discard it, and run "
                               "the same receive again without counting it toward the 5; a "
                               "message of any other kind is a protocol error: stop the slate "
                               f"blocked naming {seat}"),
            "check": (f"after each reply, run converge status {shlex.quote(slate_id)} "
                      f"--dir {quoted_dir} --json; a reply starting "
                      f"WRITE-DENIED, or a turn whose {seat} events are absent from status, "
                      f"stops the slate blocked naming {seat}; never redo the turn with a "
                      f"native subagent"),
            "request": "\n".join((
                "TYPE: delegate",
                (f"USER_REQUEST: You are seat {seat} ({', '.join(named)}) on converge slate "
                 f"{slate_id}. {brief.rstrip('.')}. <role brief for this turn>"),
                "CONTEXT: <claims under test: id, text, loc, trigger; this turn's angles>",
                (f'SCOPE: write events only with: UV_CACHE_DIR="${{TMPDIR:-/tmp}}/converge-uv-cache" '
                 f"{converge} <attack|reply|verdict|file|rebut|accept|escalate|angle-na> "
                 f"{shlex.quote(slate_id)} "
                 f"--dir {quoted_dir} --as {seat} ...; these commands append to "
                 f"{shlex.quote(str(abs_dir / f'{slate_id}.jsonl'))}, which may be outside your "
                 f"writable roots: request write permission for each such command as your host "
                 f"requires (Codex: sandbox_permissions require_escalated); if permission is "
                 f'denied or cannot be granted, run nothing else and reply "WRITE-DENIED {seat}: '
                 f'<the error text>"; read any file; change nothing else; reply with every line '
                 f"those commands print"),
            )),
        })
    return drivers


def _driver_lines(driver: dict[str, str]) -> list[str]:
    seat = driver["seat"]
    return [f"DRIVER {seat} step (one background step per turn): {driver['step']}",
            f"DRIVER {seat} placeholders: {driver['placeholders']}",
            f"DRIVER {seat} then: {driver['then']}",
            f"DRIVER {seat} other messages: {driver['other_messages']}",
            f"DRIVER {seat} check: {driver['check']}",
            f"REQUEST {seat} (write to the body file before each send; fill each <...>):",
            *driver["request"].splitlines()]


def _reclaim_step(seat: str) -> str:
    return (f"reclaim the advisor channel for {seat} (the {seat} channel in the run ledger's "
            f"advisor channels decision, when there is one) through the advisor skill's channel "
            f"pairing (--mode asking, communication channel: scan and claim, and start the "
            f"heartbeat if none runs); it prints the channel.py path and the channel number to "
            f"put in the driver step; keep the channel open after this slate; if it hands back "
            f"no listener, stop blocked naming {seat}")


# ---------------------------------------------------------------------------
# write commands


def cmd_init(args: argparse.Namespace) -> None:
    seat_fields, notes = _init_seats(args)
    try:
        resolved = config_mod.resolve(args.project_root, args.config)
    except config_mod.ConfigError as exc:
        _refuse(exc.problems, "invalid configuration")
    effective = resolved["effective"]
    try:
        rows = angles_mod.resolve(args.angles, effective, Path(resolved["project_root"]))
    except angles_mod.AngleError as exc:
        _refuse(exc.problems, "invalid angles")
    if args.review_pass is not None and args.review_pass >= 2:
        effective = {**effective, "cutoff": {**effective["cutoff"],
                                             **copy.deepcopy(config_mod.REREVIEW_CUTOFF)}}
    event: dict[str, Any] = {"event": "init", "lenses": _ids(args.lenses), "angles": rows,
                             "config": effective, "refuters": args.refuters}
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
                            "path": str(path)}
    head = (f"INIT {args.slate} lenses={','.join(event['lenses']) or '-'} "
            f"angles={len(rows)} path={path}")
    for key in ("pass", "snapshot"):
        if key in event:
            data[key] = event[key]
            head += f" {key}={event[key]}"
    lines = [head]
    if "since" in event:
        delta = f"git diff {event['since']['snapshot']} {event['snapshot']}"
        data["since"], data["diff"] = event["since"]["slate"], delta
        lines.append(f"DIFF since {event['since']['slate']}: {delta}")
    slate_seats = event.get("seats", {})
    drivers = _drivers(args.slate, args.dir, slate_seats, event.get("advisor"))
    if drivers or notes:
        data.update(seats=slate_seats, drivers=drivers, notes=notes)
        lines.append("SEATS " + " ".join(f"{seat}={m}" for seat, m in slate_seats.items()))
        for driver in drivers:
            lines.extend(_driver_lines(driver))
        lines.extend(f"NOTE {note}" for note in notes)
    step = "; ".join(_reclaim_step(driver["seat"]) for driver in drivers) or None
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
                       + f"; run: converge prune {args.slate} --project-root {root}")
        if isinstance(exc, ledger.LedgerError):
            _refuse([*exc.problems, cleanup])
        raise


def cmd_file(args: argparse.Namespace) -> None:
    event = _opt({"event": "file", "loc": args.loc, "claim": args.claim,
                  "trigger": args.trigger, "origin": args.origin},
                 lens=args.lens, angle=args.angle, rule=args.rule,
                 depends=_ids(args.depends) if args.depends else None)
    written = _write(args, event, build=lambda s: {"id": model.claim_id(len(s.claims) + 1)})
    _written(args, {"id": written["id"]}, f"FILED {written['id']}")


def cmd_escalate(args: argparse.Namespace) -> None:
    event = _opt({"event": "escalate", "claim": args.claim},
                 wider=args.wider, evidence=args.evidence)
    written = _write(args, event)
    wider = "yes" if "wider" in written else "no"
    _written(args, {"seq": written["seq"], "claim": args.claim, "wider": wider == "yes"},
             f"ESCALATE seq={written['seq']} {args.claim} wider={wider}")


def cmd_find_run(args: argparse.Namespace) -> None:
    result: Any = "none" if args.result.strip() == "none" else _ids(args.result)
    written = _write(args, {"event": "find-run", "lens": args.lens, "angle": args.angle,
                            "tell": args.tell, "searches": args.searches,
                            "positive_control": args.positive_control, "result": result})
    _written(args, {"seq": written["seq"], "lens": args.lens, "angle": args.angle},
             f"FIND-RUN seq={written['seq']} lens={args.lens} angle={args.angle}")


def cmd_angle_na(args: argparse.Namespace) -> None:
    event = _opt({"event": "angle-na", "phase": args.phase, "angle": args.angle,
                  "reason": args.reason}, lens=args.lens, claim=args.claim)
    written = _write(args, event)
    _written(args, {"seq": written["seq"], "phase": args.phase, "angle": args.angle},
             f"ANGLE-NA seq={written['seq']} phase={args.phase} angle={args.angle}")


def cmd_rebut(args: argparse.Namespace) -> None:
    written = _write(args, {"event": "rebut", "claim": args.claim, "when": args.when,
                            "evidence": args.evidence,
                            "evidence_sha256": ledger.evidence_hash(args.evidence)})
    _written(args, {"seq": written["seq"], "claim": args.claim, "when": args.when},
             f"REBUT seq={written['seq']} {args.claim} when={args.when}")


def cmd_cut(args: argparse.Namespace) -> None:
    evidence: dict[str, str] = {}
    problems = []
    for item in args.evidence:
        key, sep, text = item.partition("=")
        if not sep:
            problems.append(f"--evidence must be ANGLE=TEXT; got {item!r}")
        elif key in evidence:
            problems.append(f"--evidence given twice for {key!r}")
        else:
            evidence[key] = text
    if problems:
        _refuse(problems)
    event = _opt({"event": "cut", "claim": args.claim, "when": args.when, "round": args.round,
                  "frequency": args.frequency, "severity": args.severity,
                  "confidence": args.confidence, "difficulty": args.difficulty,
                  "evidence": evidence}, choice=args.choice, fix=args.fix)
    written = _write(args, event)
    _written(args,
             {"seq": written["seq"], "claim": args.claim, "when": args.when, "round": args.round},
             f"CUT seq={written['seq']} {args.claim} when={args.when} round={args.round}")


def cmd_accept(args: argparse.Namespace) -> None:
    written = _write(args, {"event": "accept", "claim": args.claim, "when": args.when,
                            "round": args.round})
    _written(args,
             {"seq": written["seq"], "claim": args.claim, "when": args.when, "round": args.round},
             f"ACCEPT seq={written['seq']} {args.claim} when={args.when} round={args.round}")


def _batch_arg(value: str) -> int | str:
    """`--batch`: a table batch number, or `fresh-eye`."""
    return int(value) if value.isdigit() else value


def cmd_attack(args: argparse.Namespace) -> None:
    event = {"event": "attack", "claim": args.claim, "batch": args.batch, "angle": args.angle,
             "tell": args.tell, "outcome": args.outcome, "evidence": args.evidence,
             "searches": args.searches, "positive_control": args.positive_control}
    if args.last:
        event["last"] = True
    written = _write(args, event)
    _written(args, {"seq": written["seq"], "claim": args.claim, "batch": args.batch,
                    "angle": args.angle, "outcome": args.outcome},
             f"ATTACK seq={written['seq']} {args.claim} batch={args.batch} angle={args.angle} "
             f"outcome={args.outcome}")


def cmd_reply(args: argparse.Namespace) -> None:
    event: dict[str, Any] = {"event": "reply", "claim": args.claim, "batch": args.batch,
                             "stance": args.stance}
    if args.evidence is not None:
        event.update(evidence=args.evidence, evidence_sha256=ledger.evidence_hash(args.evidence))
    written = _write(args, _opt(event, text=args.text))
    _written(args, {"seq": written["seq"], "claim": args.claim, "batch": args.batch,
                    "stance": args.stance},
             f"REPLY seq={written['seq']} {args.claim} batch={args.batch} stance={args.stance}")


def cmd_verdict(args: argparse.Namespace) -> None:
    event = _opt({"event": "verdict", "claim": args.claim, "batch": args.batch,
                  "verdict": args.verdict}, evidence=args.evidence)
    written = _write(args, event)
    _written(args, {"seq": written["seq"], "claim": args.claim, "batch": args.batch,
                    "verdict": args.verdict},
             f"VERDICT seq={written['seq']} {args.claim} batch={args.batch} "
             f"verdict={args.verdict}")


def cmd_cutoff(args: argparse.Namespace) -> None:
    slate = _read(args)
    problems = _coverage_problems(slate)
    problems.extend(f"{claim.id} is open in {phase}" for claim, phase in slate.open_claims())
    if problems:
        _refuse_next(args, "refused", problems, _next_step(args, slate))
    if not slate.cutoff_valid:
        def build(current: Slate) -> dict[str, Any]:
            return {"results": protocol.cutoff_results(protocol.compute_cutoff(current))}
        _write(args, {"event": "cutoff", "as": model.CONVERGE_AGENT}, build=build)
        slate = _read(args)
    assert slate.cutoff is not None
    rows = protocol.compute_cutoff(slate)
    counts = {result: sum(row.result == result for row in rows)
              for result in ("finding", "follow-up", "killed")}
    emit(args.output_mode,
         {"seq": slate.cutoff["seq"], "rows": protocol.cutoff_results(rows)},
         [(f"CUTOFF seq={slate.cutoff['seq']} findings={counts['finding']} "
          f"follow-up={counts['follow-up']} killed={counts['killed']}"),
          *(f"{row.claim.id} {row.result} status={row.status} cut={row.cut} rank={row.rank} "
            f"reason={row.reason}" for row in rows)],
         _step(args, "render"))


# ---------------------------------------------------------------------------
# read commands


def _claim_status(slate: Slate, claim: model.Claim, flags: dict[str, bool],
                  unverified: set[str]) -> dict[str, Any]:
    batch = (protocol.next_batch(slate, claim)
             if claim.live and claim.id not in unverified else None)
    rating = claim.state.rating
    return {
        "id": claim.id,
        "status": protocol.status(slate, claim, unverified),
        "cut": "yes" if flags.get(claim.id) else "no",
        "batch": batch,
        "batch_state": None if batch is None else protocol.batch_state(slate, claim, batch),
        "lens": claim.lens,
        "origin": claim.origin,
        "finder": claim.finder,
        "claim": claim.text,
        "escalated": claim.escalation is not None,
        "rating": {f: rating[f] for f in model.CUT_FIELDS} if rating else None,
        "unused_attack_angles": slate.remaining_angles(claim),
    }


def _claim_line(c: dict[str, Any]) -> str:
    batch = "-" if c["batch"] is None else c["batch"]
    return (f"{c['id']} status={c['status']} cut={c['cut']} batch={batch} "
            f"batch_state={c['batch_state'] or '-'} escalated={'yes' if c['escalated'] else 'no'} "
            f"unused={','.join(c['unused_attack_angles']) or '-'}")


def _plan_lines(plan: list[list[dict[str, Any]]]) -> list[str]:
    lines = []
    for index, chunk in enumerate(plan, start=1):
        for row in chunk:
            line = f"PLAN {index} {row['claim']} {row['action']} {row['agent_role']}"
            if row["batch"] is not None:
                line += f" batch={row['batch']}"
            if row["angles"]:
                line += f" angles={','.join(row['angles'])}"
            lines.append(line)
    return lines


def _coverage_problems(slate: Slate) -> list[str]:
    return [f"lens {lens} has missing find angles: {', '.join(row.missing)}"
            for lens, row in render.coverage(slate).items() if row.missing]


def _unresolved_choices(slate: Slate) -> list[dict[str, str]]:
    if not slate.cutoff_valid:
        return []
    return [{"claim": row.claim.id, "result": row.result, "choice": choice}
            for row in protocol.compute_cutoff(slate)
            if row.result == "finding"
            and (choice := (row.claim.state.rating or {}).get("choice"))]


def cmd_status(args: argparse.Namespace) -> None:
    slate = _read(args)
    flags, unverified = protocol.cut_flags(slate), protocol.unverified_ids(slate)
    claims = [_claim_status(slate, c, flags, unverified) for c in slate.claims.values()]
    cutoff = "current" if slate.cutoff_valid else ("stale" if slate.cutoff else "none")
    agents = slate.agent_ids()
    phase = protocol.slate_phase(slate)
    plan = protocol.batch_plan(slate)
    step = _next_step(args, slate)
    if args.json:
        data: dict[str, Any] = {
            "slate": slate.slate_id, "lenses": slate.lenses, "refuters": slate.init_refuters,
            "cutoff": cutoff, "agents": agents, "agent_cap": slate.cap("agents"),
            "phase": phase, "steps": slate.config["steps"], "caps": slate.config["caps"],
            "plan": plan,
            "seats": slate.seats,
            "drivers": _drivers(slate.slate_id, args.dir, slate.seats, slate.advisor),
            "claims": claims, "next": step}
        emit(args.output_mode, {}, [], json_text=json.dumps(data, indent=2))
        return
    advisor = ",".join(seat for seat in slate.seats if slate.mechanism(seat) == "advisor")
    lines = [(f"SLATE {slate.slate_id} lenses={','.join(slate.lenses) or '-'} "
              f"phase={phase} cutoff={cutoff} claims={len(claims)} "
              f"agents={len(agents)}/{slate.cap('agents')} advisor={advisor or '-'}"),
             *map(_claim_line, claims), *_plan_lines(plan)]
    emit(args.output_mode, {}, lines, step)


def cmd_converged(args: argparse.Namespace) -> None:
    slate = _read(args)
    phase = protocol.slate_phase(slate)
    flags = protocol.cut_flags(slate)
    open_ids = {claim.id: claim_phase for claim, claim_phase in slate.open_claims()}
    pending, disputed = [], []
    for claim in slate.claims.values():
        if claim.id in open_ids:
            pending.append(f"{claim.id} open in {open_ids[claim.id]}")
        elif (claim.live and claim.state.status == "disputed" and not flags[claim.id]):
            disputed.append(claim.id)
            pending.append(f"{claim.id} disputed cut=no")
    done = protocol.converged(slate)
    data = {"converged": done, "phase": phase, "pending": pending}
    if done:
        emit(args.output_mode, data, "CONVERGED", "end the slate with outcome converged")
        return
    if phase == "done":
        step = ("end the slate with outcome unconverged; disputed findings: "
                + ", ".join(disputed))
    else:
        step = _next_step(args, slate)
    emit(args.output_mode, data, [f"OPEN phase={phase} claims={len(pending)}", *pending], step)
    sys.exit(EXIT_NO)


def cmd_coverage(args: argparse.Namespace) -> None:
    slate = _read(args)
    coverage = render.coverage(slate)
    lines = []
    for lens, row in coverage.items():
        lines.append(f"LENS {lens} ran={','.join(row.ran) or '-'} na={','.join(row.na) or '-'} "
                     f"missing={','.join(row.missing) or '-'}")
        lines.extend(f"NA {lens} {angle_id} {reason}" for angle_id, reason in row.na.items())
    if any(row.missing for row in coverage.values()):
        step = _MISSING + _step(args, "coverage")
    else:
        step = _step(args, "status", "--json")
    emit(args.output_mode,
         {"lenses": {lens: {"ran": row.ran, "na": row.na, "missing": row.missing}
                     for lens, row in coverage.items()}},
         lines, step)


def cmd_gate(args: argparse.Namespace) -> None:
    if not args.dir.is_absolute():
        _refuse([f"gate needs an absolute --dir; got {str(args.dir)!r}"])
    path = _path(args)
    if not path.is_file():
        _refuse([f"no slate {args.slate!r} in {args.dir} (expected {path})"])
    slate = _read(args)
    problems = _coverage_problems(slate)
    for claim, phase in slate.open_claims():
        problems.append(f"{claim.id} is open in {phase}")
    if not slate.cutoff_valid:
        problems.append("no current cutoff (run `converge cutoff` after the last state change)")
    cutoff_seq = slate.cutoff["seq"] if slate.cutoff else None
    data = {"slate": args.slate, "ok": not problems, "problems": problems, "cutoff_seq": cutoff_seq}
    if problems:
        emit(args.output_mode, data, [f"GATE fail {args.slate}", *problems],
             _next_step(args, slate))
        sys.exit(EXIT_NO)
    shown = "-" if cutoff_seq is None else cutoff_seq
    emit(args.output_mode, data, f"GATE ok {args.slate} cutoff_seq={shown}",
         _step(args, "converged"))


def cmd_render(args: argparse.Namespace) -> None:
    slate = _read(args)
    markdown = render.render(slate)
    if args.output_mode == "json":
        emit(args.output_mode, {"slate": args.slate, "markdown": markdown,
                                "choices": _unresolved_choices(slate)}, [])
        return
    sys.stdout.write(markdown)


def cmd_prune(args: argparse.Namespace) -> None:
    problems = [f"slate id must match {model.ID_RE.pattern}: {slate!r}"
                for slate in args.slates if not model.ID_RE.match(slate)]
    root, reason = _git_root(args.project_root)
    if reason:
        problems.append(reason)
    if problems:
        _refuse(problems)
    assert root is not None
    pruned, missing, failed, lines = [], [], [], []
    for slate in dict.fromkeys(args.slates):
        ref = _ref(slate)
        if _git(root, "show-ref", "--verify", "--quiet", ref).returncode != 0:
            missing.append(slate)
            lines.append(f"WARN no ref {ref}")
            continue
        out = _git(root, "update-ref", "-d", ref)
        if out.returncode != 0:
            failed.append(_git_error(f"git update-ref -d {ref}", out))
            continue
        pruned.append(slate)
        lines.append(f"PRUNED {ref}")
    if failed:
        _refuse([*failed, *lines])
    emit(args.output_mode, {"pruned": pruned, "missing": missing}, lines)


def cmd_angles(args: argparse.Namespace) -> None:
    try:
        resolved = config_mod.resolve(args.project_root, args.config)
        rows = angles_mod.resolve(args.angles, resolved["effective"], Path(resolved["project_root"]))
    except (config_mod.ConfigError, angles_mod.AngleError) as exc:
        _refuse(exc.problems)
    rows = [row for row in rows if not args.tag or row["tag"] == args.tag]
    lines = []
    for row in rows:
        extra = "".join(f" {k}={row[k]}" for k in ("field", "lens") if k in row)
        lines.append(f"{row['tag']} {row['id']}{extra} — tell: {row['tell']} — asks: {row['asks']}")
    emit(args.output_mode, {"angles": rows}, lines)


def cmd_config(args: argparse.Namespace) -> None:
    try:
        resolved = config_mod.resolve(args.project_root, args.config)
    except config_mod.ConfigError as exc:
        _refuse(exc.problems, "invalid configuration")
    if args.action == "validate":
        emit(args.output_mode, {"valid": True, "sources": resolved["sources"]},
             [*(f"SOURCE {source['layer']} {'present' if source['present'] else 'missing'} "
                f"{source['path']}" for source in resolved["sources"]), "CONFIG valid"])
        return
    emit(args.output_mode, resolved, json.dumps(resolved, indent=2))


# ---------------------------------------------------------------------------
# parser


def _parser(catalog: Catalog = CATALOG) -> argparse.ArgumentParser:
    parser = parser_class(catalog)(prog="converge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, func: Any, *, write: bool = False, slate: bool = True,
                dir_required: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        if slate:
            p.add_argument("slate")
            if dir_required:
                # gate refuses a relative --dir rather than resolving it;
                # leave_check passes the settlement's value.
                p.add_argument("--dir", type=Path, required=True)
            else:
                p.add_argument("--dir", type=caller_path, default=ledger.DEFAULT_DIR.expanduser())
        if write:
            p.add_argument("--as", dest="agent", required=True, help="declared agent id")
        p.set_defaults(func=func)
        return p

    def config_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", type=caller_path, help="task-layer converge.yaml")
        p.add_argument("--project-root", type=caller_path, default=caller_cwd())

    p = command("init", cmd_init, write=True)
    p.add_argument("--lenses", default="")
    p.add_argument("--angles", nargs="*", type=caller_path, default=[])
    p.add_argument("--snapshot", action="store_true",
                   help="pin a work-tree snapshot commit at refs/converge/<slate>")
    p.add_argument("--pass", dest="review_pass", type=int, metavar="N",
                   help="review pass number; N >= 2 uses the re-review cutoff")
    p.add_argument("--since", metavar="PREV_SLATE",
                   help="previous pass's slate; prints the git diff between the snapshots")
    p.add_argument("--settlement", type=caller_path, metavar="FILE",
                   help="engine settlement YAML; its converge_seats and advisor_roles seat the slate")
    p.add_argument("--refuters", type=int, choices=(1, 2), default=2,
                   help="refuter seats on the slate; 1 drops r2")
    config_args(p)

    p = command("file", cmd_file, write=True)
    p.add_argument("--lens")
    p.add_argument("--angle")
    p.add_argument("--loc", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--trigger", required=True)
    p.add_argument("--origin", required=True)
    p.add_argument("--depends")
    p.add_argument("--rule")

    p = command("escalate", cmd_escalate, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--wider")
    p.add_argument("--evidence")

    p = command("find-run", cmd_find_run, write=True)
    for flag in ("--lens", "--angle", "--tell", "--searches", "--positive-control", "--result"):
        p.add_argument(flag, required=True)

    p = command("angle-na", cmd_angle_na, write=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--angle", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--lens")
    p.add_argument("--claim")

    p = command("cut", cmd_cut, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--when", required=True)
    p.add_argument("--round", required=True, type=int)
    for name in model.CUT_FIELDS:
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--evidence", action="append", default=[], metavar="ANGLE=TEXT")
    p.add_argument("--choice")
    p.add_argument("--fix")

    p = command("attack", cmd_attack, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--batch", required=True, type=_batch_arg)
    for flag in ("--angle", "--tell", "--outcome", "--evidence", "--searches",
                 "--positive-control"):
        p.add_argument(flag, required=True)
    p.add_argument("--last", action="store_true",
                   help="close the fresh-eye batch with this attack")

    p = command("reply", cmd_reply, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--batch", required=True, type=_batch_arg)
    p.add_argument("--stance", required=True)
    p.add_argument("--evidence")
    p.add_argument("--text", help="the clarified claim text, with stance rebut")

    p = command("verdict", cmd_verdict, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--batch", required=True, type=_batch_arg)
    p.add_argument("--verdict", required=True)
    p.add_argument("--evidence")

    p = command("rebut", cmd_rebut, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--when", required=True)
    p.add_argument("--evidence", required=True)

    p = command("accept", cmd_accept, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--when", required=True)
    p.add_argument("--round", required=True, type=int)

    p = command("status", cmd_status)
    p.add_argument("--json", action="store_true")
    command("converged", cmd_converged)
    command("cutoff", cmd_cutoff)
    command("coverage", cmd_coverage)
    command("gate", cmd_gate, dir_required=True)
    command("render", cmd_render)

    p = command("prune", cmd_prune, slate=False)
    p.add_argument("slates", nargs="+", metavar="slate")
    p.add_argument("--project-root", type=caller_path, default=caller_cwd())

    p = command("angles", cmd_angles, slate=False)
    p.add_argument("--tag", choices=angles_mod.TAGS)
    p.add_argument("--angles", nargs="*", type=caller_path, default=[])
    config_args(p)

    p = command("config", cmd_config, slate=False)
    p.add_argument("action", choices=("validate", "resolve"))
    config_args(p)
    add_mode_flags(parser)
    return parser


def main(argv: list[str] | None = None) -> None:
    raw = sys.argv[1:] if argv is None else argv
    find = "--phase=find" in raw or any(
        flag == "--phase" and value == "find" for flag, value in itertools.pairwise(raw))
    catalog = FIND_CATALOG if find else CATALOG
    run(_parser(catalog), catalog, lambda a: a.command, argv)


if __name__ == "__main__":
    main()
