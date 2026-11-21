#!/usr/bin/env python3
"""State machine management for engine: transition the run's `## state`
ledger section, amend or show the run's machine in force, and
validate/diagram a state machine YAML file.

Handles state commands and writes changes to the state and machines sections.

    transition   move the run to a new state machine node (hard gate)
    current      print the run's current node and its full reminder
    amend        replace the run's machine mid-run (appends to `## machines`)
    show         print the run's machine in force and its version
    validate     check a state machine YAML file's structure
    diagram      print Mermaid stateDiagram-v2 source for a valid machine
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from bootgear_cli.clikit import caller_path, emit, refuse

from engine import state_machine
from engine.session_ledger import (
    MACHINES_SECTION,
    RUN_ID_HELP,
    _append_to_section,
    _check_open,
    _ledger_command,
    _ledger_path,
    _machines_heading,
    _now,
    _read_text,
    _run_id_command,
    _section_body,
    _section_span,
    _single_line,
    _write_atomic,
)
from engine.session_settlement import _task_folder_problems
from engine.state_leave_checks import LeaveRefused, _parse_leave_args, _run_leave_check
from engine.state_machine import (
    _file_problems,
    render_diagram,
)
from engine.state_views import (
    CURRENT_STATE_RE,
    _close_command,
    _current_node,
    _current_node_lookup,
    _node_reminder_data,
    _node_reminder_text,
    _run_machine,
    _visit_count,
    current_node_report,
    current_node_view,
    try_current_node_view,  # noqa: F401
)

validate = state_machine.validate


def cmd_current(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    view = current_node_view(_read_text(path), path)
    lines, data, next_step = current_node_report(view, args.run_id, path)
    data["destinations"] = view["destinations"]
    if not view["terminal"]:
        lines.append("destinations: " + ", ".join(view["destinations"]))
    prose = [f"STATE    current: {view['current']}", *lines]
    json_next = data.pop("next", None)
    emit(args.output_mode, data, prose,
         json_next if args.output_mode == "json" else next_step)


def cmd_transition(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    reason = _single_line(args.reason, "--reason")
    force = args.force
    if force:
        _, problems = _parse_leave_args(args.leave_arg or [])
        if problems:
            sys.exit("invalid --leave-arg: " + "; ".join(problems))
    if any(item.split("=", 1)[0] == "task_folder" for item in (args.leave_arg or [])):
        sys.exit("task_folder is reserved; omit --leave-arg task_folder and use the run binding")
    settlement = yaml.safe_load(_section_body(text, "settlement"))
    if not isinstance(settlement, dict):
        sys.exit("settlement must be a mapping")
    folder_problems = _task_folder_problems(settlement, settlement.get("task_type"))
    if folder_problems:
        sys.exit("task_folder refused: " + "; ".join(message for _, message in folder_problems))
    task_folder = settlement.get("task_folder")
    if task_folder is not None:
        task_folder = str(Path(task_folder).expanduser().resolve())

    nodes, current, current_node = _current_node_lookup(text, path)
    bypassed = []
    if current_node.get("terminal") and not force:
        sys.exit(f"'{current}' is a terminal node and accepts no outgoing "
                 f"transition, `failed` included — the run already ended")

    dest = args.to
    if dest not in nodes:
        sys.exit(f"'{dest}' is not a node in this run's state_machine")
    if current_node.get("terminal"):
        bypassed.append("terminal-node")

    next_list = current_node.get("next") or []
    if dest != "failed" and dest not in next_list:
        if not force:
            sys.exit(f"'{current}' has no transition to '{dest}' — legal "
                     f"destinations from here are {next_list + ['failed']}; "
                     f"'failed' is always legal regardless of `next:`")
        bypassed.append("edge")

    max_visits = nodes[dest].get("max_visits") if isinstance(nodes[dest], dict) else None
    if isinstance(max_visits, int) and not isinstance(max_visits, bool):
        visits = _visit_count(text, dest)
        if visits >= max_visits:
            if not force:
                sys.exit(f"'{dest}' has max_visits: {max_visits} and the run has "
                         f"already entered it {visits} time(s) — refusing to enter "
                         f"it again; 'failed' stays legal")
            bypassed.append("visit-cap")

    reminder = current_node.get("reminder")
    leave = reminder.get("leave") if isinstance(reminder, dict) else None
    if leave and dest != "failed" and not args.confirm_leave:
        if not force:
            sys.exit(f"'{current}' has a leave condition and cannot be left "
                     f"without confirming it: {leave}\n"
                     f"Pass --confirm-leave once this is actually true; "
                     f"'--to failed' needs no confirmation")
        bypassed.append("leave-confirmation")

    log_line = f"- {_now()} {current} -> {dest} ({reason})"
    leave_check = reminder.get("leave_check") if isinstance(reminder, dict) else None
    exit_checks = reminder.get("exit_checks") if isinstance(reminder, dict) else None
    exit_check = (exit_checks.get(dest)
                  if isinstance(exit_checks, dict) and dest != "failed" else None)
    refusal = None
    if not force and not leave_check and exit_check is None and args.leave_arg:
        sys.exit(f"'{current}' has no leave_check for exit '{dest}', so --leave-arg "
                 f"{', '.join(args.leave_arg)} matches no placeholder")
    if force:
        if leave_check and dest != "failed":
            bypassed.append("leave-check")
        elif exit_check is not None:
            bypassed.append("exit-check")
        log_line += f" [force requested={dest}; bypassed={','.join(bypassed) or 'none'}]"
    elif leave_check and dest != "failed":
        try:
            argv = _run_leave_check(current, leave_check, args.leave_arg or [], task_folder)
        except LeaveRefused as refused:
            sys.exit(refused.message)
        log_line += f" [leave_check exit 0: {' '.join(argv)}]"
    elif exit_check is not None:
        try:
            argv = _run_leave_check(current, exit_check["argv"], args.leave_arg or [], task_folder)
        except LeaveRefused as refused:
            fallback = exit_check.get("on_refuse")
            if fallback is None:
                sys.exit(refused.message)
            fallback_visits = (_visit_count(text, fallback)
                               if isinstance(nodes[fallback].get("max_visits"), int) else 0)
            limit = nodes[fallback].get("max_visits")
            if isinstance(limit, int) and fallback_visits >= limit:
                sys.exit(f"exit check for '{dest}' refused and its fallback '{fallback}' "
                         f"has max_visits: {limit}, already entered {fallback_visits} "
                         f"time(s); refusing to enter it again\n{refused.message}")
            first = refused.message.split("\n")[0]
            log_line = f"- {_now()} {current} -> {fallback} ({reason}; {first})"
            refusal = refused.message
            dest = fallback
        else:
            log_line += f" [leave_check exit 0: {' '.join(argv)}]"
    body = _section_body(text, "state")
    new_body = CURRENT_STATE_RE.sub(f"current: {dest}", body, count=1)
    start, end = _section_span(text, "state")
    lines = [line for line in new_body.strip("\n").split("\n") if line.strip()]
    current_line = lines[0]
    # Only a "- " line is a transition-log entry. Anything else after
    # `current:` (e.g. `started:`) is a header field, not a logged
    # transition — preserved verbatim, in place, rather than being folded
    # into the log the way a purely positional rebuild would fold it.
    header_lines = [line for line in lines[1:] if not line.startswith("- ")]
    log_entries = [line for line in lines[1:] if line.startswith("- ")]
    log_entries.append(log_line)
    new_section_lines = [current_line] + header_lines + log_entries
    # A `## machines` section after `## state` keeps its blank line.
    gap = "\n" if end < len(text) else ""
    new_text = text[:start] + "\n".join(new_section_lines) + "\n" + gap + text[end:]
    _write_atomic(path, new_text)

    dest_node = nodes[dest]
    prose = [f"STATE    {current} -> {dest}"]
    if force:
        prose.append(f"force requested={args.to}; reason={reason}; "
                     f"bypassed={','.join(bypassed) or 'none'}")
    reminder_text = _node_reminder_text(dest_node)
    if reminder_text:
        prose.append(reminder_text)
    if refusal is not None:
        prose.append(f"REFUSED  {refusal}")
    reminder_data = _node_reminder_data(dest_node)
    confirm = None
    next_step = None
    if dest_node.get("terminal"):
        confirm = (f"before entering '{dest}': confirm goal's {dest} "
                   f"condition genuinely holds now — not merely that no other "
                   f"path remains.")
        prose.append(f"CONFIRM  {confirm}")
        next_step = _close_command(args.run_id, path, dest)
    data = {"from": current, "to": dest, "reminder": reminder_data, "confirm": confirm}
    if force:
        data.update(force=True, requested=args.to, reason=reason, bypassed=bypassed)
    if refusal is not None:
        data["refused"] = refusal
    if args.output_mode == "json" and next_step is None and reminder_data:
        # JSON has no `do:` line, so the reminder's step is its `next`.
        next_step = reminder_data["do"]
    if force and next_step is None:
        next_step = _ledger_command("state current", args.run_id, path)
    emit(args.output_mode, data, prose, next_step)


def _load_valid(path: Path, output_mode: str, refusing: str = "") -> dict:
    """The sound machine at `path`. Any load or validation problem is
    printed (prose, or `{"path","ok":false,"problems"}`), then exit 1; with
    `refusing`, it is raised as a refusal naming that instead."""
    if not path.exists():
        sys.exit(f"no file at {path}")
    data, problems = _file_problems(path)
    if problems or data is None:
        head = f"{path}: {len(problems)} problem(s) found"
        if refusing:
            refuse(f"{head} — {refusing}", [("", p) for p in problems])
        emit(output_mode,
             {"path": str(path), "ok": False, "problems": problems},
             [f"{head}:", *(f"  - {p}" for p in problems)])
        sys.exit(1)
    return data


def cmd_validate(args: argparse.Namespace) -> None:
    _load_valid(args.path, args.output_mode)
    emit(args.output_mode, {"path": str(args.path), "ok": True, "problems": []},
         f"{args.path}: ok")


def _machine_entry(version: int, current: str, reason: str, machine: dict) -> str:
    """A `## machines` entry: the header, then the validated machine dumped
    as YAML with every line indented two spaces, so it parses back to
    exactly `machine`."""
    dumped = yaml.safe_dump(machine, sort_keys=False).rstrip("\n")
    body = [f"  {line}" for line in dumped.split("\n")]
    return "\n".join([f"- v{version} {_now()} at {current} ({reason})", *body])


def _with_machine_entry(text: str, entry: str) -> str:
    """`text` with `entry` appended to `## machines`, reusing an existing
    heading and creating the section at the end of the ledger only when
    absent."""
    if not text.endswith("\n"):
        text += "\n"
    if _machines_heading(text) is None:
        return text.rstrip("\n") + f"\n\n## {MACHINES_SECTION}\n{entry}\n"
    start, end = _section_span(text, MACHINES_SECTION)
    kept = text[start:end].strip("\n")
    body = (kept + "\n" if kept else "") + entry + "\n"
    if end < len(text):
        body += "\n"
    return text[:start] + body + text[end:]


def _amend_current_problems(current: str, old_node: object,
                            new_nodes: dict) -> list[tuple[str, str]]:
    """The current node keeps its leave gate, and a `next:` path from it
    still reaches `succeeded`."""
    problems: list[tuple[str, str]] = []
    old_reminder = old_node.get("reminder") if isinstance(old_node, dict) else None
    new_node = new_nodes[current]
    new_reminder = new_node.get("reminder") if isinstance(new_node, dict) else None
    for key in ("leave", "leave_check", "exit_checks"):
        old = old_reminder.get(key) if isinstance(old_reminder, dict) else None
        new = new_reminder.get(key) if isinstance(new_reminder, dict) else None
        if old != new:
            problems.append(("--machine-file", (
                f"changes '{current}''s `reminder.{key}` ({old!r} -> {new!r}) — keep "
                f"the current node's gate as in force; it can change once the run "
                f"has left '{current}'")))
    if not state_machine.reaches_succeeded(new_nodes, current):
        problems.append(("--machine-file", (
            f"has no `next:` path from '{current}' to 'succeeded' — the run could "
            f"only end 'failed'")))
    return problems


def cmd_amend(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    from_version, old_machine = _run_machine(text, path)
    old_nodes = old_machine["nodes"]
    current = _current_node(text, path)

    problems: list[tuple[str, str]] = []
    reason = args.reason.strip()
    if "\n" in args.reason or "\r" in args.reason:
        problems.append(("--reason", "contains a line break — give one line"))
    elif not reason:
        problems.append(("--reason", "is blank — say why the machine changes"))
    elif " -> " in reason:
        problems.append(("--reason", ("contains ' -> ', which the decisions line "
                                      "reserves for 'v<N> -> v<N+1>' — paraphrase it")))
    current_node = old_nodes.get(current)
    if isinstance(current_node, dict) and current_node.get("terminal"):
        problems.append(("current node", (f"'{current}' is terminal — the run already "
                                          f"ended, there is nothing left to amend")))
    new_machine, file_problems = _file_problems(args.machine_file)
    problems += [("--machine-file", p) for p in file_problems]
    if new_machine is not None and not file_problems:
        if current not in new_machine["nodes"]:
            problems.append(("--machine-file", (f"has no '{current}' node — the run's "
                                                f"current node must stay in the machine")))
        elif new_machine == old_machine:
            problems.append(("--machine-file", (f"is identical to the machine in force "
                                                f"(v{from_version}) — nothing to amend")))
        else:
            problems += _amend_current_problems(current, current_node,
                                                new_machine["nodes"])
    if problems:
        refuse(f"amend refused for {path}: {len(problems)} problem(s) — fix each and "
               f"rerun; the machine in force to edit is printed by "
               + _ledger_command("state show", args.run_id, path), problems)
    assert new_machine is not None

    new_nodes = new_machine["nodes"]
    added = [n for n in new_nodes if n not in old_nodes]
    removed = [n for n in old_nodes if n not in new_nodes]
    edges_changed = [n for n in new_nodes
                     if n in old_nodes and state_machine.edges(new_nodes[n]) != state_machine.edges(old_nodes[n])]
    to_version = from_version + 1
    entry = _machine_entry(to_version, current, reason, new_machine)
    decision = (f"- {_now()} [solo] AMENDMENT state_machine: v{from_version} -> "
                f"v{to_version} (added: {', '.join(added) or 'none'}; removed: "
                f"{', '.join(removed) or 'none'}; full machine in ## "
                f"{MACHINES_SECTION}), {reason}")
    new_text = _append_to_section(_with_machine_entry(text, entry), "decisions", decision)
    _write_atomic(path, new_text)

    node = new_nodes[current]
    prose = [(f"AMENDED  state_machine v{from_version} -> v{to_version} at {current} "
              f"(added: {', '.join(added) or 'none'}; removed: "
              f"{', '.join(removed) or 'none'}; edges changed: "
              f"{', '.join(edges_changed) or 'none'})")]
    reminder_text = _node_reminder_text(node)
    if reminder_text:
        prose.append(reminder_text)
    reminder_data = _node_reminder_data(node)
    data = {"from_version": from_version, "to_version": to_version, "current": current,
            "added": added, "removed": removed, "edges_changed": edges_changed,
            "reminder": reminder_data}
    next_step = None
    if args.output_mode == "json" and reminder_data:
        next_step = reminder_data["do"]
    emit(args.output_mode, data, prose, next_step)


def cmd_show(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    version, machine = _run_machine(text, path)
    source = "settlement" if version == 1 else f"## {MACHINES_SECTION} v{version}"
    current = _current_node(text, path)
    emit(args.output_mode,
         {"version": version, "source": source, "current": current, "machine": machine},
         [f"MACHINE  v{version} ({source})",
          yaml.safe_dump(machine, sort_keys=False).rstrip("\n")])


def cmd_diagram(args: argparse.Namespace) -> None:
    data = _load_valid(args.path, args.output_mode, "refusing to diagram an invalid machine")
    mermaid = render_diagram(data)
    emit(args.output_mode, {"path": str(args.path), "mermaid": mermaid}, mermaid)


def add_subparsers(sub: argparse._SubParsersAction, dir_parent: argparse.ArgumentParser) -> None:
    s = sub.add_parser("transition", parents=[dir_parent],
                        help="move the run to a new state machine node")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("--to", required=True, metavar="NODE",
                   help="destination node; state current lists normal choices, state show lists all nodes for --force")
    s.add_argument("--reason", required=True,
                   help="one line stating why this move happens now")
    s.add_argument("--force", action="store_true",
                   help="bypass workflow gates with --reason; keep run, destination, and ledger validation")
    s.add_argument("--confirm-leave", action="store_true",
                   help="required to leave a node whose reminder has a "
                        "`leave` condition, except for 'failed'; bare flag, "
                        "no accompanying text needed")
    s.add_argument("--leave-arg", action="append", metavar="NAME=VALUE",
                   help="value for a {NAME} placeholder in the leave check "
                        "of the exit taken (`reminder.leave_check`, or "
                        "`reminder.exit_checks.<exit>`); repeatable")
    s.set_defaults(func=_run_id_command(cmd_transition))

    s = sub.add_parser("current", parents=[dir_parent],
                        help="print the run's current node and its full reminder")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.set_defaults(func=_run_id_command(cmd_current))

    s = sub.add_parser("amend", parents=[dir_parent],
                        help="replace the run's machine mid-run with a valid one "
                             "that keeps the current node")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("--machine-file", required=True, type=caller_path,
                   help="the full new machine YAML — start from `state show`")
    s.add_argument("--reason", required=True,
                   help="one line stating why the machine changes now")
    s.set_defaults(func=_run_id_command(cmd_amend))

    s = sub.add_parser("show", parents=[dir_parent],
                        help="print the run's machine in force and its version")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.set_defaults(func=_run_id_command(cmd_show))

    s = sub.add_parser("validate", help="check a state machine YAML file's structure")
    s.add_argument("path", type=caller_path, help="path to a state machine YAML file")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("diagram", help="print Mermaid stateDiagram-v2 source "
                                        "for a valid machine")
    s.add_argument("path", type=caller_path, help="path to a state machine YAML file")
    s.set_defaults(func=cmd_diagram)


def main() -> None:
    """`python -m engine.state` is `task state`, refusals included."""
    from engine import cli
    cli.main(["state", *sys.argv[1:]])


if __name__ == "__main__":
    main()
