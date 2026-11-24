"""Shared Converge command input, output, and next steps."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import itertools
import json
import shlex
import sys
from pathlib import Path
from typing import Any, NoReturn

from bootgear_cli.clikit import (
    Catalog,
    Refusal,
    current_program,
    dumps,
    emit,
    gear_command,
    host,
    refuse,
    render_refusal,
)

from . import assignments, ledger, native_launch, protocol, render, seats
from .cli_advisor import _reclaim_step
from .model import Slate

EXIT_NO = 1
EXIT_REFUSED = 2
_MISSING = "continue the finder with the missing angles, then "

# Leaf command -> runnable argv after the program, shown in every refusal.
EXAMPLES = {
    "init": "init <slate> --dir <dir> --as main --lenses <a,b> --angles <file> "
            "--settlement <file>",
    "file": "file <slate> --dir <dir> --as finder --lens <lens> --angle <angle> --origin lens "
            '--loc <path:line> --claim "<claim>" --trigger "<trigger>" --evidence "<evidence>" '
            "--tier <tier>",
    "escalate": 'escalate <slate> --dir <dir> --as finder --claim F001 --wider "<text>" '
                '--evidence "<route>"',
    "find-run": "find-run <slate> --dir <dir> --as finder --lens <lens> --angle <angle> "
                '--tell "<tell>" --searches "<searches>" --positive-control "<hit>" --result none',
    "angle-na": "angle-na <slate> --dir <dir> --as r1 --phase attack --claim F001 "
                '--angle <angle> --reason "<why>"',
    "gap-hunt-done": "gap-hunt-done <slate> --dir <dir> --as r2",
    "attack": "attack <slate> --dir <dir> --as r1 --claim F001 --batch 1 --angle <angle> "
              '--tell "<tell>" --evidence "<evidence>" --searches "<searches>" '
              '--positive-control "<hit>"',
    "clean": "clean <slate> --dir <dir> --as r1 --input <action.json>",
    "work": "work <slate> --dir <dir> --as r1 --role-host claude --out <work-dir>",
    "act": "act <slate> --dir <dir> --as r1 --input <action.json>",
    "advisor-wait": "advisor-wait <slate> --dir <dir> --as r2-2 --channel 0001 --request <message-id>",
    "reply": 'reply <slate> --dir <dir> --as finder --claim F001 --batch 1 --stance rebut '
             '--evidence "<new evidence>"',
    "verdict": "verdict <slate> --dir <dir> --as r1 --claim F001 --batch 1 --verdict agree",
    "cut": "cut <slate> --dir <dir> --as cutter --claim F001 --when after --round 1 "
           "--impact wrong-output --size one --reach normal --difficulty local "
           "--evidence <angle>=<evidence>",
    "rebut": 'rebut <slate> --dir <dir> --as finder --claim F001 --when after '
             '--evidence "<new evidence>"',
    "accept": "accept <slate> --dir <dir> --as finder --claim F001 --when after --round 1",
    "fix-check": 'fix-check <slate> --dir <dir> --as main --claim F001 --outcome pass '
                 '--evidence "<checks run and their result>" --review-slate <slate>',
    "status": "status <slate> --dir <dir> --json",
    "converged": "converged <slate> --dir <dir>",
    "cutoff": "cutoff <slate> --dir <dir>",
    "coverage": "coverage <slate> --dir <dir>",
    "gate": "gate <slate> --dir <abs-dir>",
    "render": "render <slate> --dir <dir>",
    "angles": "angles --tag find --angles <file>",
    "config": "config validate --project-root <dir>",
    "prune": "prune <slate> <slate> --project-root <dir>",
    "launch": "launch <slate> --dir <dir> --as main --input <launches.json>",
    "launch-result": "launch-result <slate> --dir <dir> --as main --input <outcomes.json>",
}
ANGLE_NA_FIND = ("angle-na <slate> --dir <dir> --as finder --phase find --lens <lens> "
                 '--angle <angle> --reason "<why>"')
GATE_TRIAGE = "gate <slate> --dir <abs-dir> --kind triage --report <abs-file>"
FREQUENT = ("file", "attack", "reply", "verdict", "cut", "status", "converged")
CATALOG = Catalog(prog=current_program("converge", "converge"), examples=EXAMPLES, frequent=FREQUENT,
                  legacy_json=frozenset({"status"}))
# A `--phase find` call's refusals show the find form of the angle-na example.
FIND_CATALOG = dataclasses.replace(CATALOG, examples={**EXAMPLES, "angle-na": ANGLE_NA_FIND})
# A call that names --kind or --report shows the triage form of the gate example.
TRIAGE_CATALOG = dataclasses.replace(CATALOG, examples={**EXAMPLES, "gate": GATE_TRIAGE})


def _refuse(problems: list[str], what: str = "refused", code: int = EXIT_REFUSED) -> NoReturn:
    refuse(f"converge: {what}:", [("", p) for p in problems], code=code)


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
        _refuse_next(args, "refused", exc.problems,
                     getattr(args, "action_next", None) or _writer_next(args, slate))


def _written(args: argparse.Namespace, data: dict[str, Any], line: str) -> None:
    """Print a written event's result line and the slate's next step."""
    emit(args.output_mode, data, line,
         getattr(args, "action_next", None) or _writer_next(args, _read(args)))


def _writer_next(args: argparse.Namespace, slate: Slate) -> str:
    actor = getattr(args, "agent", None)
    if actor is None or actor == slate.events[0]["as"]:
        return _next_step(args, slate)
    prefix = ("refresh your work: " if assignments.parallel(slate) and actor in assignments.workers(slate)
              else "report the result to main; refresh your work: ")
    return (prefix
            + _role_command(args, host() or "claude", "work")
            + " --role-host " + (host() or "claude"))


# ---------------------------------------------------------------------------
# the next step, from the slate's phase


def _plan_text(slate: Slate) -> str:
    """The plan rows grouped by agent role and action, in plan order."""
    groups: dict[tuple[str, str], list[str]] = {}
    for row in itertools.chain.from_iterable(protocol.batch_plan(slate)):
        item = row["claim"] + (f" batch {row['batch']}" if row["batch"] is not None else "")
        groups.setdefault((row.get("agent", row["agent_role"]), row["action"]), []).append(item)
    return "; ".join(f"{role} {action} {', '.join(items)}"
                     for (role, action), items in groups.items())


def _next_step(args: argparse.Namespace, slate: Slate) -> str:
    """The next legal action on the slate, from `protocol.slate_phase`."""
    phase = protocol.slate_phase(slate)
    if native_launch.blocked(slate):
        return "return the blocked native assignment and its reason to the review caller"
    if phase in ("cutoff", "done") and native_launch.pending(slate):
        return "recover the original native receipts and record launch-result outcomes as main"
    if phase == "find":
        if (saved_host := native_launch.saved_host(slate)) and native_launch.profiles(slate):
            return _work_step(args, saved_host, slate.events[0]["as"])
        if assignments.parallel(slate):
            return _step(args, "work", "--as", slate.events[0]["as"], "--role-host", host() or "claude")
        return _MISSING + _step(args, "coverage")
    if phase == "done":
        return _step(args, "render")
    step = (_step(args, "cutoff") if phase == "cutoff"
            else f"{phase}: {_plan_text(slate)}; plan: {_step(args, 'status', '--json')}")
    gap_open = protocol.gap_hunt_open(slate, phase)
    if phase == "gap-hunt":
        step = "give r2 its gap-hunt assignment on its executing host, including the completion action"
    elif gap_open:
        step = ("gap hunt: continue r2 with work and its explicit executing host; "
                "r2 submits generated act actions, then reports completion to main; "
                f"before the first escalate, cut or attack; then {step}")
    plan = protocol.batch_plan(slate)
    advisor_due = gap_open or any(row["agent_role"] == seats.ADVISOR_SEAT
                                 for row in (plan[0] if plan else []))
    if advisor_due and slate.mechanism(seats.ADVISOR_SEAT) == "advisor" and slate.advisor is not None:
        if slate.parallelism["r2"] > 1:
            step = f"use the ready advisor worker's reserved-channel driver from {_step(args, 'status', '--json')}"
        elif slate.advisor.get("startup") == "deferred":
            step = f"{_reclaim_step(seats.ADVISOR_SEAT, slate.advisor)}; then {step}"
    return step


def _ids(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _opt(event: dict[str, Any], **values: Any) -> dict[str, Any]:
    event.update({k: v for k, v in values.items() if v is not None})
    return event


def _role_command(args: argparse.Namespace, role_host: str, command: str, *, actor: str | None = None) -> str:
    return (f"{gear_command('converge', 'converge', host=role_host)} {command} "
            f"{shlex.quote(args.slate)} --dir {shlex.quote(str(args.dir.resolve()))} "
            f"--as {shlex.quote(actor or args.agent)}")


def _work_step(args: argparse.Namespace, role_host: str, actor: str) -> str:
    return _role_command(args, role_host, "work", actor=actor) + f" --role-host {role_host}"


def _coverage_problems(slate: Slate) -> list[str]:
    problems = [f"lens {lens} has missing find angles: {', '.join(row.missing)}"
                for lens, row in render.coverage(slate).items() if row.missing]
    problems.extend(native_launch.pending(slate))
    return problems
