"""Describe and launch advisor work through its public interface."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from bootgear_cli.clikit import (
    argv_template,
    gear_command,
)

from . import assignments, seats

INVITE_MARKERS = ("{group}", "{worker}", "{invitation}")


def launcher_problems(advisor: dict[str, Any]) -> list[str]:
    template = advisor.get("launcher")
    if template is None:
        return (["deferred parallel startup requires an approved launcher template"]
                if advisor.get("startup") == "deferred" else [])
    try:
        argv_template(template, INVITE_MARKERS)
    except ValueError as error:
        return [f"launcher template: {error}"]
    return []


def _converge_command() -> str:
    """Return the public Gear command for Converge."""
    return gear_command("converge", "converge")


def _parallel_driver(slate_id: str, ledger_dir: Path, group: str,
                     worker: str, advisor: dict[str, Any] | None) -> dict[str, str]:
    directory = shlex.quote(str(ledger_dir.resolve()))
    slate = shlex.quote(slate_id)
    identity = shlex.join(["--group", group, "--worker", worker])
    channel = gear_command("advisor", "channel")
    work = {host: (f"{gear_command('converge', 'converge', host=host)} work {slate} "
                   f"--dir {directory} --as {worker} --role-host {host}")
            for host in ("claude", "codex")}
    launch = (advisor or {}).get("launcher")
    start = (f"{channel} launch {identity} --template {shlex.quote(launch)}" if launch else
             "give the operator the reserved group, worker ID, and invitation for Advisor listening mode")
    path = shlex.quote(str(ledger_dir.resolve() / f"{slate_id}.{worker}.request.txt"))
    wait = (f"{_converge_command()} advisor-wait {slate} --dir {directory} --as {worker} "
            '--channel "$CHANNEL" --request "$MESSAGE_ID"')
    brief = seats.seat_roles(None, "r2")[1] if advisor is None else advisor["brief"]
    return {
        "seat": "r2",
        "worker": worker,
        "group": group,
        "prepare": ("reserve only when this worker has an assignment" if (advisor or {}).get("startup") == "deferred"
                    else "prepare the invited listener before its first assignment"),
        "reserve": f"{channel} reserve {identity}",
        "launch": start,
        "wait_listener": f"{channel} wait-listener {identity}",
        "work_claude": work["claude"],
        "work_codex": work["codex"],
        "step": (f'{channel} send --channel "$CHANNEL" --from asker --to listener '
                 f"--kind request --cap 1 --body-file {path} --json"),
        "receive": wait,
        "then": ("Start the reserve output's asker heartbeat if needed before launch. "
                 "Use the reserved channel returned by wait-listener. Save the send receipt. "
                 "Run receive in the background with its message ID. Continue main's slate work while it runs. "
                 "Use main's printed wait when ready work has been dispatched. Include this worker while its receipt "
                 "is unanswered. Resume receiving the same ID. Keep one active request."),
        "request": "\n".join((
            "TYPE: delegate",
            f"USER_REQUEST: Act as worker {worker} in seat r2. {brief} <full worker assignment and role brief>",
            "CONTEXT: <artifact, assigned claims, evidence and applicable standards>",
            f"SCOPE: Use the work command for your actual host: {work['claude']} or {work['codex']}.",
            ("Keep the same worker ID for direct Gear actions. When Gear offers gap-hunt-done, record it before replying. "
             "Continue ready work and use work --wait for ordinary prerequisites. "
             "Report completion, a finder reply handoff, or blocked work."),
            "Respect the assigned write scope. Report WRITE-DENIED and the exact refusal if a write fails.",
            "Tests already ran:",
            "- latest test: <recorded command>; result: <one recorded result line>",
        )),
    }


def _drivers(slate_id: str, ledger_dir: Path, slate_seats: dict[str, str],
             advisor: dict[str, Any] | None, *, review_group: str | None = None,
             r2_workers: int = 1) -> list[dict[str, str]]:
    """How the orchestrator drives each advisor seat through the advisor channel."""
    if r2_workers > 1 and review_group is not None and slate_seats.get("r2") == "advisor":
        return [_parallel_driver(slate_id, ledger_dir, review_group, assignments.worker_id("r2", index), advisor)
                for index in range(r2_workers)]
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
        channel = gear_command("advisor", "channel")
        converge = _converge_command()
        quoted_dir = shlex.quote(str(abs_dir))
        drivers.append({
            "seat": seat,
            "prepare": _reclaim_step(seat, advisor),
            "step": (f'{channel} send --channel "$CHANNEL" --from asker --to listener '
                     f"--kind request --body-file {body} && "
                     f'{channel} receive --channel "$CHANNEL" --for asker --timeout 300'),
            "placeholders": ("a fresh shell keeps no variables, so write the step with the "
                             "Gear channel command and channel number the pairing printed in "
                             'place of the command and "$CHANNEL"'),
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
            "check": (f"after each reply, run {converge} status {shlex.quote(slate_id)} "
                      f"--dir {quoted_dir} --json; a reply starting "
                      f"WRITE-DENIED, or a turn whose {seat} events are absent from status, "
                      f"stops the slate blocked naming {seat}; never redo the turn with a "
                      f"native subagent"),
            "request": "\n".join((
                "TYPE: delegate",
                (f"USER_REQUEST: You are seat {seat} ({', '.join(named)}) on converge slate "
                 f"{slate_id}. {brief.rstrip('.')}. <role brief for this turn>"),
                "CONTEXT: <claims under test: id, text, loc, trigger; this turn's angles>",
                ("SCOPE: Call cli:gear through your own host. "
                 f"Run work {shlex.quote(slate_id)} --dir {quoted_dir} --as {seat} "
                 "--role-host <your executing host>. "
                 "Use that host in Gear's --host option. "
                 "Fill a generated action and submit it through act. "
                 f"Write only your events in {shlex.quote(str(abs_dir / f'{slate_id}.jsonl'))}, "
                 "task action files, and memory-ledger entries. Read any source file. "
                 f'If a write is denied, stop and reply "WRITE-DENIED {seat}: <the error text>". '
                 "Reply with the command results. Preserve all other write limits."),
                "Tests already ran:",
                "- latest test: <recorded command>; result: <one recorded result line>",
                "Required: main agent fills this part by hand before each send.",
                ("Use the latest test command recorded in the run ledger, even if it covers "
                 "only part of the tests."),
                "Use one result line from that record; include no exit code or record path.",
                "Do not combine commands that did not run together.",
                "If no test result is recorded, write none recorded.",
                "Skip redundant runs covered by recorded test commands.",
                "You can probe behaviour those commands did not cover.",
            )),
        })
    return drivers


def _driver_lines(driver: dict[str, str]) -> list[str]:
    seat = driver["seat"]
    if "worker" in driver:
        worker = driver["worker"]
        return [f"DRIVER {worker} {key}: {driver[key]}"
                for key in ("prepare", "reserve", "launch", "wait_listener", "step", "receive", "then")
                ] + [f"REQUEST {worker}:", *driver["request"].splitlines()]
    return [f"DRIVER {seat} prepare (before this seat's first task): {driver['prepare']}",
            f"DRIVER {seat} step (one background step per turn): {driver['step']}",
            f"DRIVER {seat} placeholders: {driver['placeholders']}",
            f"DRIVER {seat} then: {driver['then']}",
            f"DRIVER {seat} other messages: {driver['other_messages']}",
            f"DRIVER {seat} check: {driver['check']}",
            f"REQUEST {seat} (write to the body file before each send; fill each <...>):",
            *driver["request"].splitlines()]


def _reclaim_step(seat: str, advisor: dict[str, Any] | None = None) -> str:
    reclaim = (f"reclaim the advisor channel for {seat} (the {seat} channel in the run ledger's "
            f"advisor channels decision, when there is one) through the advisor skill's channel "
            f"pairing (--mode asking, communication channel: scan and claim, and start the "
            f"heartbeat if none runs); it prints the Gear command and channel number to "
            f"put in the driver step; keep the channel open after this slate; if it hands back "
            f"no listener, stop blocked naming {seat}")

    if advisor is None or advisor.get("startup") != "deferred":
        return reclaim
    return (f"reuse the recorded {seat} channel if one exists; only when no {seat} channel is recorded, "
            f"start its listener with the approved launcher: {advisor['launcher']}; "
            f"then {reclaim}; record the newly paired {seat} channel in the run ledger's "
            f"advisor channels decision when this is an engine run; never replace a recorded "
            f"channel or switch mechanisms on failure")
