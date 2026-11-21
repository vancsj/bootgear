"""Read and render session ledger views."""

from __future__ import annotations

import argparse
import re
import sys

from bootgear_cli.clikit import emit

from .session_decision_rules import QUESTION_ID_RE, _parse_decision_entry
from .session_ledger import (
    MACHINES_SECTION,
    SECTIONS,
    _heading_re,
    _ledger_path,
    _read_text,
    _section_body,
)
from .session_settlement import (  # noqa: F401
    TASK_TYPES,
    _artefact_review_problems,
    _bind_task_folder,
    _stored_owned_artifacts,
    _validate_settlement,
    _verb_owned_problems,
)

CURRENT_LINE_RE = re.compile(r"(?m)^current: (?P<node>\S+)\s*$")
STARTED_LINE_RE = re.compile(r"(?m)^started: (?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")
# A `## state` transition-log entry as `state transition` writes it.
TRANSITION_LINE_RE = re.compile(
    r"^- (?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (?P<from>\S+) -> (?P<to>\S+) ")


def _lines(body: str) -> list[str]:
    return [line for line in body.split("\n") if line.strip()]


def _state_fields(body: str) -> dict:
    current = CURRENT_LINE_RE.search(body)
    started = STARTED_LINE_RE.search(body)
    transitions = [
        {"at": m.group("at"), "from": m.group("from"), "to": m.group("to"), "line": line}
        for line in body.split("\n") if (m := TRANSITION_LINE_RE.match(line))
    ]
    return {"current": current.group("node") if current else None,
            "started": started.group("at") if started else None,
            "transitions": transitions}


def cmd_read(args: argparse.Namespace) -> None:
    modes = [name for name, on in
             (("--section", args.section), ("--open-only", args.open_only),
              ("--last", args.last is not None),
              ("--question", args.question is not None)) if on]
    if len(modes) > 1:
        sys.exit(f"{' and '.join(modes)} are mutually exclusive — pick one")
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    if args.question is not None:
        if not QUESTION_ID_RE.match(args.question):
            sys.exit(f"--question '{args.question}' must look like 'q1', 'q2', ...")
        entries = []
        for e in _section_body(text, "decisions").strip("\n").split("\n"):
            if not e.strip():
                continue
            parsed = _parse_decision_entry(e)
            if parsed and parsed[1] == args.question:
                entries.append(e)
        emit(args.output_mode,
             {"run_id": args.run_id, "question": args.question, "decisions": entries},
             "\n".join(entries) if entries else f"(no decisions tagged {args.question})")
        return
    if args.open_only:
        todos = [e for e in _section_body(text, "todos").strip("\n").split("\n")
                 if e.strip().startswith("- [ ]")]
        emit(args.output_mode, {"run_id": args.run_id, "open_todos": todos},
             "\n".join(todos) if todos else "(no open todos)")
        return
    if args.last is not None:
        if args.last < 1:
            sys.exit("--last must be a positive integer")
        data: dict = {"run_id": args.run_id}
        prose = []
        for name in ("decisions", "pitches"):
            entries = [e for e in _section_body(text, name).strip("\n").split("\n")
                       if e.strip()]
            tail = entries[-args.last:]
            data[name], data[f"{name}_total"] = tail, len(entries)
            prose.append(f"-- {name} (last {len(tail)}/{len(entries)}) --")
            prose.append("\n".join(tail) if tail else "(none)")
        emit(args.output_mode, data, prose)
        return
    if args.section:
        body = _section_body(text, args.section)
        data = {"run_id": args.run_id, "section": args.section, "lines": _lines(body)}
        if args.section == "state":
            data |= _state_fields(body)
        prose = body.strip("\n")
        if args.section == MACHINES_SECTION and not prose:
            prose = "(none)"
        emit(args.output_mode, data, prose)
    else:
        closed = _heading_re("closed").search(text)
        emit(args.output_mode, {
            "run_id": args.run_id,
            "title": text.split("\n", 1)[0].removeprefix("# "),
            "sections": {name: _lines(_section_body(text, name))
                         for name in [*SECTIONS, MACHINES_SECTION]},
            "closed": _section_body(text, "closed").strip() if closed else None,
        }, text.strip("\n"))


def _recall_section(label: str, body: str, empty: str = "(none)") -> list[str]:
    body = body.strip("\n")
    return [f"-- {label} --", body if body else empty]


def cmd_recall(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    open_todos = [line for line in _section_body(text, "todos").strip("\n").split("\n")
                  if line.strip().startswith("- [ ]")]
    pitches = [line for line in _section_body(text, "pitches").strip("\n").split("\n")
               if line.strip()]
    data = {
        "run_id": args.run_id,
        "settlement": _lines(_section_body(text, "settlement")),
        "decisions": _lines(_section_body(text, "decisions")),
        "open_todos": open_todos,
        "state": _lines(_section_body(text, "state")),
        "current_node": None,
        "recent_pitches": pitches[-3:],
    }
    # state.py imports this module at load, so import it here.
    from engine.state import current_node_report, try_current_node_view
    view, error = try_current_node_view(text, path)
    if view is None:
        current_node = f"(unavailable: {error})"
    else:
        lines, data["current_node"], next_step = current_node_report(view, args.run_id, path)
        if next_step:
            lines.append(f"next: {next_step}")
        current_node = "\n".join([view["current"], *lines])
    prose = [
        *_recall_section("settlement", _section_body(text, "settlement")),
        *_recall_section("decisions (full)", _section_body(text, "decisions")),
        *_recall_section("open todos", "\n".join(open_todos)),
        *_recall_section("state", _section_body(text, "state")),
        *_recall_section("current node", current_node),
        *_recall_section("recent pitches (last 3)", "\n".join(pitches[-3:])),
    ]
    emit(args.output_mode, data, prose)
