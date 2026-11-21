"""Write a ticket to the run's owned artifact path."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml
from bootgear_cli.clikit import caller_cwd, emit, refuse

from .session_ledger import (
    _check_open,
    _ledger_command,
    _ledger_path,
    _read_text,
    _section_body,
    _section_span,
    _write_atomic,
)
from .session_settlement import (
    HEADING_LINE_RE,
    TICKET_HEADINGS,
    VERB_OWNED_FIELDS,
    _ticket_path,
    _ticket_path_problems,
    _validate_settlement,
)


def _missing_ticket_headings(body: str) -> list[str]:
    found = {m.group("text").casefold() for line in body.splitlines()
             if (m := HEADING_LINE_RE.match(line))}
    return [part for part in TICKET_HEADINGS if part.casefold() not in found]


def _with_ticket_fields(text: str, owned: list[str], ticket: str) -> str:
    """The ledger text with the settlement's `owned_artifacts` and `ticket_path`
    set to these values."""
    start, end = _section_span(text, "settlement")
    lines = [line for line in text[start:end].rstrip("\n").split("\n")
             if not line.startswith(tuple(f"{field}:" for field in VERB_OWNED_FIELDS))]
    lines += [f"owned_artifacts: {json.dumps(owned)}", f"ticket_path: {json.dumps(ticket)}"]
    return text[:start] + "\n".join(lines) + "\n\n" + text[end:]


def _ticket_next_step(text: str, path: Path, run_id: str) -> str:
    """The transition out of the current node when it has one successor, with
    `--confirm-leave` when the node has a leave condition; else `state current`,
    which prints the node's branches."""
    from engine import state
    _, _, node = state._current_node_lookup(text, path)
    successors = [dest for dest in node.get("next") or [] if dest != "failed"]
    if len(successors) == 1:
        reminder = node.get("reminder")
        confirm = " --confirm-leave" if isinstance(reminder, dict) and reminder.get("leave") else ""
        return _ledger_command("state transition", run_id, path,
                               f"--to {successors[0]} --reason \"<why>\"{confirm}")
    return _ledger_command("state current", run_id, path)


def cmd_write_ticket(args: argparse.Namespace) -> None:
    """Write the run's ticket body at its one path and record that the run owns
    it. Never replaces a file that the run does not own."""
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    session_dir = path.parent
    settlement = _section_body(text, "settlement")
    problems, _ = _validate_settlement(settlement, args.run_id, session_dir, caller_cwd())
    if problems:
        refuse(f"write-ticket refused: the settlement of {path} has {len(problems)} "
               f"problem(s)", problems)
    data = yaml.safe_load(settlement)
    ticket = _ticket_path(args.run_id, session_dir)
    # a. The path, checked at entry.
    problems = _ticket_path_problems(str(ticket), data.get("task_type"), args.run_id, session_dir)
    if problems:
        refuse(f"write-ticket refused for {ticket}: {len(problems)} problem(s)", problems)
    next_step = _ticket_next_step(text, path, args.run_id)
    try:
        ticket.parent.mkdir(exist_ok=True)
    except OSError as exc:
        sys.exit(f"cannot create {ticket.parent}: {exc}")
    # b. The five headings.
    try:
        body = args.body_file.read_text()
    except (OSError, UnicodeError) as exc:
        sys.exit(f"cannot read --body-file {args.body_file}: {exc}")
    missing = _missing_ticket_headings(body)
    if missing:
        refuse(f"write-ticket refused: {args.body_file} lacks {len(missing)} of the "
               f"{len(TICKET_HEADINGS)} part headings; nothing written",
               [("missing heading", f"no '{part}' heading") for part in missing])
    # c. Ownership.
    owned = data.get("owned_artifacts", [])
    exists = os.path.lexists(ticket)
    if exists and str(ticket) not in owned:
        sys.exit(f"{ticket} exists and this run does not own it (it is not in "
                 f"owned_artifacts) — refusing to replace it; the file is unchanged")
    if str(ticket) not in owned:
        owned = [*owned, str(ticket)]
    new_text = _with_ticket_fields(text, owned, str(ticket))
    new_settlement = _section_body(new_text, "settlement")
    problems, _ = _validate_settlement(new_settlement, args.run_id, session_dir, caller_cwd())
    stored = yaml.safe_load(new_settlement) if not problems else {}
    if not problems and (stored.get("ticket_path") != str(ticket)
                         or stored.get("owned_artifacts") != owned):
        problems.append(("settlement",
                         "does not read back the new ticket_path and owned_artifacts"))
    if problems:
        refuse(f"write-ticket refused: the ownership record for {path} is invalid; "
               f"nothing written", problems)
    # d. The path, checked again at write.
    problems = _ticket_path_problems(str(ticket), data.get("task_type"), args.run_id, session_dir)
    if problems:
        refuse(f"write-ticket refused for {ticket}: {len(problems)} problem(s)", problems)
    try:
        if exists:
            _write_atomic(ticket, body)
        else:
            with open(ticket, "x") as handle:
                handle.write(body)
    except OSError as exc:
        sys.exit(f"cannot write {ticket}: {exc}")
    # e. Ownership.
    try:
        _write_atomic(path, new_text)
    except OSError as exc:
        sys.exit(f"wrote {ticket} but cannot record that this run owns it: {exc} — the "
                 f"file stays unowned, so the next write-ticket refuses it")
    action = "rewritten" if exists else "created"
    emit(args.output_mode, {"path": str(ticket), "action": action, "owned_artifacts": owned},
         f"TICKET   {action} {ticket}", next_step)
