"""Describe and launch advisor work through its public interface."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from bootgear_cli.clikit import (
    gear_command,
)

from . import seats


def _converge_command() -> str:
    """Return the public Gear command for Converge."""
    return gear_command("converge", "converge")


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
