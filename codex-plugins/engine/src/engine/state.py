#!/usr/bin/env python3
"""State machine management for engine: transition the run's `## state`
ledger section, amend or show the run's machine in force, and
validate/diagram a state machine YAML file.

Owns everything that reasons about the machine graph itself, as opposed to
session.py's settlement/decisions/todos/pitches ledger sections.

    transition   move the run to a new state machine node (hard gate)
    current      print the run's current node and its full reminder
    amend        replace the run's machine mid-run (appends to `## machines`)
    show         print the run's machine in force and its version
    validate     check a state machine YAML file's structure
    diagram      print Mermaid stateDiagram-v2 source for a valid machine
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import yaml

from engine.clikit import ENV_MODE, caller_path, emit, refuse
from engine.session import (
    MACHINES_SECTION,
    _append_to_section,
    _check_open,
    _command,
    _heading_re,
    _ledger_args,
    _ledger_path,
    _machines_heading,
    _now,
    _read_text,
    _section_body,
    _section_span,
    _single_line,
    _write_atomic,
)

START_NODE = "clarify"
TERMINAL_NODES = {"succeeded", "failed"}
RESERVED_NODE_NAMES = TERMINAL_NODES
# Matches "state_machine: |" at column 0 in the settlement body — the block
# scalar convention settlement already uses for goal: >, applied here to a
# nested YAML document instead of a paragraph.
STATE_MACHINE_FIELD_RE = re.compile(r"(?m)^state_machine: \|\n((?:(?:[ \t].*)?\n)*)")
CURRENT_STATE_RE = re.compile(r"(?m)^current: (?P<node>\S+)\s*$")
# A Mermaid stateDiagram-v2 state ID may not contain a hyphen; node names in
# this schema are hyphenated (spec-debate, debate-findings, ...), so every diagram ID is
# derived from the node name by replacing "-" with "_". Two distinct node
# names that only differ by choosing "-" vs "_" in the same position (e.g.
# "spec-debate" and "spec_debate" both present) would collide under this
# substitution — checked for explicitly below rather than silently letting
# one shadow the other in the emitted diagram.
_MERMAID_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# A `## state` log entry as cmd_transition writes it:
# "- <YYYY-MM-DD HH:MM> <from> -> <to> (<reason>)[ [leave_check ...]]".
_LOG_ENTRY_DEST_RE = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+ -> (?P<dest>\S+) \(")
LEAVE_CHECK_PLACEHOLDER_RE = re.compile(r"\{(?P<name>[a-z_]+)\}")
LEAVE_ARG_RE = re.compile(r"\A(?P<name>[a-z_]+)=(?P<value>.*)\Z", re.DOTALL)
LEAVE_CHECK_TIMEOUT_ENV = "ENGINE_LEAVE_CHECK_TIMEOUT"
LEAVE_CHECK_DEFAULT_TIMEOUT = 120.0
LEAVE_CHECK_OUTPUT_TAIL_LINES = 40
# A `## machines` entry header as cmd_amend writes it; the entry's machine
# text follows on lines indented two spaces.
MACHINE_ENTRY_RE = re.compile(
    r"^- v(?P<v>\d+) (?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) at (?P<node>\S+) "
    r"\((?P<reason>.*)\)$")


def _mermaid_id(node_name: str) -> str:
    return node_name.replace("-", "_")


def _extract_state_machine(text: str, path: Path) -> dict:
    """Parse settlement's `state_machine: |` block scalar into the machine's
    node mapping. This is the one place engine parses the machine's
    structure rather than treating it as opaque text."""
    settlement = _section_body(text, "settlement")
    m = STATE_MACHINE_FIELD_RE.search(settlement)
    if not m:
        sys.exit(f"malformed ledger at {path}: settlement has no "
                  f"'state_machine: |' block — clarify must write the "
                  f"resolved machine into settlement before any `transition` "
                  f"call")
    block = m.group(1)
    lines = [line.removeprefix("  ")
             for line in block.split("\n")]
    dedented = "\n".join(lines)
    try:
        data = yaml.safe_load(dedented)
    except yaml.YAMLError as e:
        sys.exit(f"malformed ledger at {path}: settlement's 'state_machine: |' "
                  f"block is not valid YAML: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        sys.exit(f"malformed ledger at {path}: settlement's 'state_machine: |' "
                  f"block has no top-level `nodes` mapping")
    return data


def _machine_entries(text: str, path: Path) -> list[dict]:
    """The `## machines` entries, oldest first, as `{version, at, node,
    reason, machine}`. Settlement's machine is v1, so the Nth entry must be
    v(N+1); any other shape exits as a malformed ledger."""
    body = _section_body(text, MACHINES_SECTION)
    entries: list[dict] = []
    raw: list[str] = []

    def finish() -> None:
        if not entries:
            return
        entry = entries[-1]
        label = f"malformed ledger at {path}: ## {MACHINES_SECTION} v{entry['version']}"
        try:
            data = yaml.safe_load("\n".join(line.removeprefix("  ") for line in raw))
        except yaml.YAMLError as e:
            sys.exit(f"{label} is not valid YAML: {e}")
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
            sys.exit(f"{label} has no top-level `nodes` mapping")
        entry["machine"] = data

    for line in body.split("\n"):
        m = MACHINE_ENTRY_RE.match(line)
        if m:
            finish()
            raw = []
            version = int(m.group("v"))
            expected = len(entries) + 2
            if version != expected:
                sys.exit(f"malformed ledger at {path}: ## {MACHINES_SECTION} "
                         f"v{version} is out of sequence — expected v{expected} "
                         f"(settlement's machine is v1)")
            entries.append({"version": version, "at": m.group("at"),
                            "node": m.group("node"), "reason": m.group("reason")})
        elif not line.strip() or line.startswith("  "):
            if not entries and line.strip():
                sys.exit(f"malformed ledger at {path}: ## {MACHINES_SECTION} "
                         f"has machine text before any '- v<N> <ts> at <node> "
                         f"(<reason>)' entry header")
            raw.append(line)
        else:
            sys.exit(f"malformed ledger at {path}: ## {MACHINES_SECTION} line "
                     f"{line!r} is neither a '- v<N> <ts> at <node> (<reason>)' "
                     f"entry header nor machine text indented two spaces")
    finish()
    return entries


def _run_machine(text: str, path: Path) -> tuple[int, dict]:
    """The run's machine in force and its version: the newest `## machines`
    entry, else settlement's `state_machine` as v1."""
    entries = _machine_entries(text, path)
    if entries:
        return entries[-1]["version"], entries[-1]["machine"]
    return 1, _extract_state_machine(text, path)


def _current_node(text: str, path: Path) -> str:
    body = _section_body(text, "state")
    m = CURRENT_STATE_RE.search(body)
    if not m:
        sys.exit(f"malformed ledger at {path}: '## state' has no 'current: "
                  f"<node>' line — not written by `init`, or hand-edited "
                  f"into a bad state")
    return m.group("node")


def _rendered_do(reminder: dict) -> str | None:
    """`reminder.do`, with a legacy `reminder.skill` folded in. `validate`
    rejects `skill`, but a machine settled before it was dropped can still
    carry it, and settlement cannot be rewritten."""
    do = reminder.get("do") or None
    skill = reminder.get("skill")
    if not isinstance(skill, str) or not skill.strip():
        return do
    call = f"Call the {skill.strip()} skill."
    return f"{do} {call}" if do else call


def _node_reminder_text(node: dict) -> str | None:
    """The full reminder contents to print on entering a node, or None if it
    has no `reminder`. `transition` prints the
    new node's `do`/`branches`/`leave` so the caller doesn't have to
    separately re-read the machine YAML to find them."""
    reminder = node.get("reminder")
    if not isinstance(reminder, dict):
        return None
    lines = []
    do = _rendered_do(reminder)
    if do:
        lines.append(f"do: {do}")
    branches = reminder.get("branches")
    if isinstance(branches, dict) and branches:
        lines.append("branches:")
        for dest, meaning in branches.items():
            lines.append(f"  {dest}: {meaning}")
    if reminder.get("leave"):
        lines.append(f"leave: {reminder['leave']}")
    leave_check = reminder.get("leave_check")
    if isinstance(leave_check, list) and leave_check:
        lines.append(f"leave_check: {' '.join(str(a) for a in leave_check)}")
    return "\n".join(lines) if lines else None


def _node_reminder_data(node: dict) -> dict | None:
    """The same reminder fields as `_node_reminder_text`, as JSON data."""
    reminder = node.get("reminder")
    if not isinstance(reminder, dict):
        return None
    branches = reminder.get("branches")
    leave_check = reminder.get("leave_check")
    return {
        "do": _rendered_do(reminder),
        "branches": dict(branches) if isinstance(branches, dict) and branches else None,
        "leave": reminder.get("leave") or None,
        "leave_check": ([str(a) for a in leave_check]
                        if isinstance(leave_check, list) and leave_check else None),
    }


def _visit_count(text: str, dest: str) -> int:
    """How many times the run has entered `dest`: its `-> <dest> (` log
    entries, plus the implicit entry `init` makes into the start node."""
    body = _section_body(text, "state")
    count = sum(1 for line in body.split("\n")
                if (m := _LOG_ENTRY_DEST_RE.match(line)) and m.group("dest") == dest)
    if dest == START_NODE:
        count += 1
    return count


def _reaches_succeeded(nodes: dict, start: str) -> bool:
    """True if some `next:` path from `start` reaches `succeeded`, ignoring
    `max_visits`."""
    seen, frontier = {start}, [start]
    while frontier:
        for dest in _edges(nodes.get(frontier.pop())):
            if dest == "succeeded":
                return True
            if dest in nodes and dest not in seen:
                seen.add(dest)
                frontier.append(dest)
    return False


def _parse_leave_args(raw: list[str]) -> tuple[dict[str, str], list[str]]:
    args: dict[str, str] = {}
    problems: list[str] = []
    for item in raw:
        m = LEAVE_ARG_RE.match(item)
        if not m:
            problems.append(f"--leave-arg '{item}' is not name=value with a "
                            f"name matching [a-z_]+")
            continue
        name, value = m.group("name"), m.group("value")
        if name in args:
            problems.append(f"--leave-arg '{name}' is given more than once")
        elif not value.strip():
            problems.append(f"--leave-arg '{name}' has an empty value")
        elif "\n" in value or "\r" in value:
            problems.append(f"--leave-arg '{name}' contains a line break")
        elif value.startswith("-"):
            problems.append(f"--leave-arg '{name}' starts with '-', which the "
                            f"leave_check program would read as an option")
        args[name] = value
    return args, problems


# <plugin-root>/src/engine/state.py -> <plugin-root>
PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def _resolve_program(program: str) -> str | None:
    """Codex host: a leave_check program bundled in this plugin's
    `scripts/` wins; otherwise fall back to PATH lookup."""
    bundled = PLUGIN_ROOT / "scripts" / program
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    return shutil.which(program)


def _leave_check_timeout() -> float:
    raw = os.environ.get(LEAVE_CHECK_TIMEOUT_ENV)
    if raw is None or raw == "":
        return LEAVE_CHECK_DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if value <= 0:
        sys.exit(f"{LEAVE_CHECK_TIMEOUT_ENV}={raw!r} must be a positive "
                 f"number of seconds")
    return value


def _tail(output: str) -> str:
    lines = output.rstrip("\n").split("\n") if output.strip() else []
    tail = lines[-LEAVE_CHECK_OUTPUT_TAIL_LINES:]
    return "\n".join(f"  | {line}" for line in tail) if tail else "  | (no output)"


def _run_leave_check(current: str, template: list[str],
                     raw_args: list[str]) -> list[str]:
    """Substitute --leave-arg values into `template`, run it without a
    shell, and return the executed argv. Exits with every problem listed on
    any refusal, before anything is written."""
    leave_args, problems = _parse_leave_args(raw_args)
    placeholders: list[str] = []
    for part in template:
        for m in LEAVE_CHECK_PLACEHOLDER_RE.finditer(part):
            if m.group("name") not in placeholders:
                placeholders.append(m.group("name"))
    for name in placeholders:
        if name not in leave_args:
            problems.append(f"leave_check placeholder '{{{name}}}' has no "
                            f"--leave-arg {name}=<value>")
    for name in leave_args:
        if name not in placeholders:
            problems.append(f"--leave-arg '{name}' matches no placeholder in "
                            f"'{current}''s leave_check")
    if problems:
        sys.exit(f"'{current}' has a leave_check and cannot be left: "
                 f"{len(problems)} problem(s) found:\n"
                 + "\n".join(f"  - {p}" for p in problems))

    argv = [LEAVE_CHECK_PLACEHOLDER_RE.sub(lambda m: leave_args[m.group("name")], part)
            for part in template]
    resolved = _resolve_program(argv[0])
    if resolved is None:
        sys.exit(f"leave_check program '{argv[0]}' not found — install the "
                 f"plugin that provides it")
    argv = [resolved, *argv[1:]]
    timeout = _leave_check_timeout()
    shown = " ".join(argv)
    try:
        # The output tail is quoted in a refusal an LLM reads, so the check
        # prints prose even though its stdout is this pipe.
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True,
                                env={**os.environ, ENV_MODE: "prose"})
    except OSError as e:
        sys.exit(f"'{current}' leave_check could not start: {shown}: {e}")
    try:
        out_bytes, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The check runs in its own session so its whole process group —
        # grandchildren holding the output pipe included — dies with it.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out_bytes, _ = proc.communicate()
        output = out_bytes.decode(errors="replace")
        sys.exit(f"'{current}' leave_check timed out after {timeout:g}s: "
                 f"{shown}\nlast {LEAVE_CHECK_OUTPUT_TAIL_LINES} lines of "
                 f"output:\n{_tail(output)}")
    output = out_bytes.decode(errors="replace")
    if proc.returncode != 0:
        sys.exit(f"'{current}' leave_check exited {proc.returncode}: "
                 f"{shown}\nlast {LEAVE_CHECK_OUTPUT_TAIL_LINES} lines of "
                 f"output:\n{_tail(output)}")
    return argv


def _current_node_lookup(text: str, path: Path) -> tuple[dict, str, dict]:
    """The machine in force's nodes, the current node's name, and that node;
    exits on every malformed ledger."""
    version, machine = _run_machine(text, path)
    nodes = machine["nodes"]
    current = _current_node(text, path)
    current_node = nodes.get(current)
    if not isinstance(current_node, dict):
        sys.exit(f"current state '{current}' is not a node in this run's "
                 f"state_machine v{version} — the ledger's '## state' and the "
                 f"machine in force have gone out of sync")
    return nodes, current, current_node


def current_node_view(text: str, path: Path) -> dict:
    """The run's current node, whether it is terminal, its reminder as data
    and as text, and whether the ledger is closed."""
    _, current, node = _current_node_lookup(text, path)
    return {"current": current, "terminal": bool(node.get("terminal")),
            "reminder": _node_reminder_data(node), "text": _node_reminder_text(node),
            "closed": _heading_re("closed").search(text) is not None}


def try_current_node_view(text: str, path: Path) -> tuple[dict | None, str | None]:
    """`current_node_view`, or its refusal message instead of exiting."""
    try:
        return current_node_view(text, path), None
    except SystemExit as e:
        return None, str(e.code)


def _close_command(run_id: str, path: Path, dest: str) -> str:
    close = f"session close {_ledger_args(run_id, path)} {dest}"
    if dest == "failed":
        close += ' --reason "<why the goal is undoable>"'
    return _command(close)


def current_node_report(view: dict, run_id: str, path: Path) -> tuple[list[str], dict, str | None]:
    """The current node as `state current` reports it: prose lines after the
    `STATE` line, JSON data, and the prose `next` (only the `session close`
    command, for a terminal node of an open ledger). The JSON data carries its
    own `next`: that close command, else the reminder's `do`."""
    lines = [view["text"]] if view["text"] else []
    next_step = None
    if view["terminal"] and view["closed"]:
        lines.append("terminal: the run already ended")
    elif view["terminal"]:
        lines.append("terminal: close the ledger")
        next_step = _close_command(run_id, path, view["current"])
    elif not view["text"]:
        lines.append("no reminder: work toward goal")
    data = {k: view[k] for k in ("current", "terminal", "reminder")}
    json_next = next_step
    if not view["terminal"]:
        json_next = (view["reminder"] or {}).get("do")
    if json_next:
        data["next"] = json_next
    return lines, data, next_step


def cmd_current(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    view = current_node_view(_read_text(path), path)
    lines, data, next_step = current_node_report(view, args.run_id, path)
    prose = [f"STATE    current: {view['current']}", *lines]
    json_next = data.pop("next", None)
    emit(args.output_mode, data, prose,
         json_next if args.output_mode == "json" else next_step)


def cmd_transition(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    reason = _single_line(args.reason, "--reason")

    nodes, current, current_node = _current_node_lookup(text, path)
    if current_node.get("terminal"):
        sys.exit(f"'{current}' is a terminal node and accepts no outgoing "
                 f"transition, `failed` included — the run already ended")

    dest = args.to
    if dest not in nodes:
        sys.exit(f"'{dest}' is not a node in this run's state_machine")

    next_list = current_node.get("next") or []
    if dest != "failed" and dest not in next_list:
        sys.exit(f"'{current}' has no transition to '{dest}' — legal "
                 f"destinations from here are {next_list + ['failed']}; "
                 f"'failed' is always legal regardless of `next:`")

    max_visits = nodes[dest].get("max_visits") if isinstance(nodes[dest], dict) else None
    if isinstance(max_visits, int) and not isinstance(max_visits, bool):
        visits = _visit_count(text, dest)
        if visits >= max_visits:
            sys.exit(f"'{dest}' has max_visits: {max_visits} and the run has "
                     f"already entered it {visits} time(s) — refusing to enter "
                     f"it again; 'failed' stays legal")

    reminder = current_node.get("reminder")
    leave = reminder.get("leave") if isinstance(reminder, dict) else None
    if leave and not args.confirm_leave:
        sys.exit(f"'{current}' has a leave condition and cannot be left "
                 f"without confirming it: {leave}\n"
                 f"Pass --confirm-leave once this is actually true — for "
                 f"'{dest}' included")

    log_line = f"- {_now()} {current} -> {dest} ({reason})"
    leave_check = reminder.get("leave_check") if isinstance(reminder, dict) else None
    if not leave_check and args.leave_arg:
        sys.exit(f"'{current}' has no leave_check, so --leave-arg "
                 f"{', '.join(args.leave_arg)} matches no placeholder")
    if leave_check and dest != "failed":
        argv = _run_leave_check(current, leave_check, args.leave_arg or [])
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
    reminder_text = _node_reminder_text(dest_node)
    if reminder_text:
        prose.append(reminder_text)
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
    if args.output_mode == "json" and next_step is None and reminder_data:
        # JSON has no `do:` line, so the reminder's step is its `next`.
        next_step = reminder_data["do"]
    emit(args.output_mode, data, prose, next_step)


def _load(path: Path) -> tuple[dict | None, list[str]]:
    """Parse the YAML file. Returns (data, problems) — data is None if the
    file isn't even valid YAML or isn't a mapping with a `nodes` mapping,
    in which case problems explains why and no further check runs (there's
    nothing structural left to check against)."""
    try:
        raw = path.read_text()
    except (OSError, UnicodeError) as e:
        return None, [f"cannot read {path}: {e}"]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return None, [f"{path} is not valid YAML: {e}"]
    if not isinstance(data, dict):
        return None, [f"{path} must be a YAML mapping at the top level, got {type(data).__name__}"]
    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return None, [f"{path} has no non-empty top-level `nodes` mapping"]
    return data, []


def _validate_leave_check(node_name: str, leave_check: object, leave: object) -> list[str]:
    problems: list[str] = []
    if leave is None:
        problems.append(f"node '{node_name}': `reminder.leave_check` requires `reminder.leave`")
    if not isinstance(leave_check, list) or not leave_check:
        problems.append(f"node '{node_name}': `reminder.leave_check` must be a non-empty list of strings")
        return problems
    for i, part in enumerate(leave_check):
        if not isinstance(part, str) or not part.strip():
            problems.append(f"node '{node_name}': `reminder.leave_check[{i}]` must be a non-empty string")
            continue
        if "\n" in part:
            problems.append(f"node '{node_name}': `reminder.leave_check[{i}]` must be single-line, contains a line break")
        leftover = LEAVE_CHECK_PLACEHOLDER_RE.sub("", part)
        if "{" in leftover or "}" in leftover:
            problems.append(
                f"node '{node_name}': `reminder.leave_check[{i}]` '{part}' has a brace "
                f"that is not a {{name}} placeholder with name matching [a-z_]+"
            )
    return problems


def _validate_reminder(node_name: str, node: dict, next_list: list) -> list[str]:
    problems: list[str] = []
    reminder = node.get("reminder")
    if reminder is None:
        return problems
    if not isinstance(reminder, dict):
        return [f"node '{node_name}': `reminder` must be a mapping, got {type(reminder).__name__}"]

    if "skill" in reminder:
        problems.append(f"node '{node_name}': `reminder.skill` was removed; name the "
                        f"skill and how to call it in `reminder.do`")

    leave = reminder.get("leave")
    if leave is not None:
        if not isinstance(leave, str) or not leave.strip():
            problems.append(f"node '{node_name}': `reminder.leave` must be non-empty single-line text")
        elif "\n" in leave:
            problems.append(f"node '{node_name}': `reminder.leave` must be single-line, contains a line break")

    if "leave_check" in reminder:
        problems.extend(_validate_leave_check(node_name, reminder.get("leave_check"), leave))

    branches = reminder.get("branches")
    if branches is not None:
        if not isinstance(branches, dict):
            problems.append(f"node '{node_name}': `reminder.branches` must be a mapping, got {type(branches).__name__}")
        else:
            next_set = set(next_list) if isinstance(next_list, list) else set()
            branch_keys = set(branches.keys())
            missing_from_branches = next_set - branch_keys
            extra_in_branches = branch_keys - next_set
            if missing_from_branches:
                problems.append(
                    f"node '{node_name}': `reminder.branches` is missing key(s) present in "
                    f"`next`: {', '.join(sorted(missing_from_branches))}"
                )
            if extra_in_branches:
                problems.append(
                    f"node '{node_name}': `reminder.branches` has key(s) not present in "
                    f"`next`: {', '.join(sorted(extra_in_branches))}"
                )
            for dest, text in branches.items():
                if not isinstance(text, str) or not text.strip():
                    problems.append(
                        f"node '{node_name}': `reminder.branches['{dest}']` must be "
                        f"non-empty single-line text"
                    )
                elif "\n" in text:
                    problems.append(
                        f"node '{node_name}': `reminder.branches['{dest}']` must be "
                        f"single-line, contains a line break"
                    )
    return problems


def validate(data: dict) -> list[str]:
    problems: list[str] = []
    nodes: dict = data["nodes"]

    for name in TERMINAL_NODES:
        if name not in nodes:
            problems.append(f"required node '{name}' is missing")

    if START_NODE not in nodes:
        problems.append(f"required start node '{START_NODE}' is missing")

    for name, node in nodes.items():
        if not isinstance(node, dict):
            problems.append(f"node '{name}': must be a mapping, got {type(node).__name__}")
            continue

        terminal = node.get("terminal", False)
        if not isinstance(terminal, bool):
            problems.append(f"node '{name}': `terminal` must be a boolean, got {type(terminal).__name__}")
            terminal = bool(terminal)

        if terminal and name not in TERMINAL_NODES:
            problems.append(
                f"node '{name}': marked `terminal: true` but only "
                f"{', '.join(sorted(TERMINAL_NODES))} may be terminal"
            )
        if not terminal and name in TERMINAL_NODES:
            problems.append(f"node '{name}': is a reserved terminal node name but is not marked `terminal: true`")

        next_list = node.get("next")
        if terminal:
            if next_list:
                problems.append(f"node '{name}': terminal node must not have a `next:` list")
        else:
            if not isinstance(next_list, list) or not next_list:
                problems.append(f"node '{name}': non-terminal node must have a non-empty `next:` list")
                next_list = []
            else:
                for dest in next_list:
                    if dest not in nodes:
                        problems.append(f"node '{name}': `next:` destination '{dest}' is not a defined node")

        if "max_visits" in node:
            max_visits = node["max_visits"]
            if terminal:
                problems.append(f"node '{name}': `max_visits` is not allowed on a terminal node")
            elif (not isinstance(max_visits, int) or isinstance(max_visits, bool)
                  or max_visits < 1):
                problems.append(f"node '{name}': `max_visits` must be a positive integer, got {max_visits!r}")

        problems.extend(_validate_reminder(name, node, next_list if isinstance(next_list, list) else []))

    # Every node name outside the two reserved terminal names must not
    # itself be one of those two reserved names under another guise — this
    # is already covered by "reserved terminal node name" above, so no
    # separate check is needed here for that half; what remains is the
    # opposite direction, checked above as "terminal but not named
    # succeeded/failed".

    # Reachability from clarify, BFS over declared `next:` edges plus the
    # universal implicit edge every non-terminal node has to `failed` (real,
    # but never listed in any node's `next:`). Without that implicit edge, `failed`
    # would fail this check on every machine, since no node ever lists it.
    reachable = {START_NODE} if START_NODE in nodes else set()
    frontier = list(reachable)
    while frontier:
        current = frontier.pop()
        node = nodes.get(current)
        if not isinstance(node, dict):
            continue
        destinations = set(node.get("next") or [])
        if not node.get("terminal") and "failed" in nodes:
            destinations.add("failed")
        for dest in destinations:
            if dest in nodes and dest not in reachable:
                reachable.add(dest)
                frontier.append(dest)

    unreachable = set(nodes) - reachable
    if unreachable:
        problems.append(
            f"node(s) unreachable from '{START_NODE}': {', '.join(sorted(unreachable))}"
        )
    if "succeeded" in nodes and "succeeded" not in reachable:
        problems.append(f"required terminal node 'succeeded' is not reachable from '{START_NODE}'")

    # Mermaid ID collisions: two distinct node names that map to the same
    # underscored ID (see _mermaid_id) would silently merge in any --diagram
    # output, so this is checked regardless of whether --diagram is used —
    # a machine that fails this can never be diagrammed correctly, which is
    # itself a soundness problem, not only a rendering inconvenience.
    id_owners: dict[str, list[str]] = {}
    for name in nodes:
        id_owners.setdefault(_mermaid_id(name), []).append(name)
    for mermaid_id, owners in id_owners.items():
        if len(owners) > 1:
            problems.append(
                f"node names {', '.join(sorted(owners))} all map to the same Mermaid "
                f"state ID '{mermaid_id}' (hyphens and underscores are not "
                f"distinguishable in a diagram ID) — rename one"
            )

    return problems


def render_diagram(data: dict) -> str:
    """Emit Mermaid stateDiagram-v2 source for an already-valid machine.
    Caller must run `validate()` first and refuse to call this on a machine
    with any problems: the diagram is generated from a machine already known
    sound, not a best-effort rendering of a potentially broken one."""
    nodes: dict = data["nodes"]
    lines = ["stateDiagram-v2", f"    [*] --> {_mermaid_id(START_NODE)}"]
    for name in sorted(nodes):
        node = nodes[name]
        if not isinstance(node, dict) or node.get("terminal"):
            continue
        reminder_value = node.get("reminder")
        reminder = reminder_value if isinstance(reminder_value, dict) else {}
        branches_value = reminder.get("branches")
        branches = branches_value if isinstance(branches_value, dict) else {}
        for dest in node.get("next") or []:
            src_id = _mermaid_id(name)
            dest_id = _mermaid_id(dest)
            label = branches.get(dest)
            if label:
                lines.append(f"    {src_id} --> {dest_id}: {label}")
            else:
                lines.append(f"    {src_id} --> {dest_id}")
    lines.append(f"    {_mermaid_id('succeeded')} --> [*]")
    return "\n".join(lines)


def _file_problems(path: Path) -> tuple[dict | None, list[str]]:
    """`_load` then `validate`: (data, problems), data None when unloadable."""
    if not path.exists():
        return None, [f"no file at {path}"]
    data, problems = _load(path)
    if not problems and data is not None:
        problems = validate(data)
    return data, problems


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


def _edges(node: object) -> list:
    return list(node.get("next") or []) if isinstance(node, dict) else []


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
    for key in ("leave", "leave_check"):
        old = old_reminder.get(key) if isinstance(old_reminder, dict) else None
        new = new_reminder.get(key) if isinstance(new_reminder, dict) else None
        if old != new:
            problems.append(("--machine-file", (
                f"changes '{current}''s `reminder.{key}` ({old!r} -> {new!r}) — keep "
                f"the current node's gate as in force; it can change once the run "
                f"has left '{current}'")))
    if not _reaches_succeeded(new_nodes, current):
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
               + _command(f"state show {_ledger_args(args.run_id, path)}"), problems)
    assert new_machine is not None

    new_nodes = new_machine["nodes"]
    added = [n for n in new_nodes if n not in old_nodes]
    removed = [n for n in old_nodes if n not in new_nodes]
    edges_changed = [n for n in new_nodes
                     if n in old_nodes and _edges(new_nodes[n]) != _edges(old_nodes[n])]
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
    s.add_argument("run_id")
    s.add_argument("--to", required=True, metavar="NODE",
                   help="the destination node — must be in the current "
                        "node's `next:` list, or 'failed'")
    s.add_argument("--reason", required=True,
                   help="one line stating why this move happens now")
    s.add_argument("--confirm-leave", action="store_true",
                   help="required to leave a node whose reminder has a "
                        "`leave` condition, 'failed' included; bare flag, "
                        "no accompanying text needed")
    s.add_argument("--leave-arg", action="append", metavar="NAME=VALUE",
                   help="value for a {NAME} placeholder in the current "
                        "node's `reminder.leave_check`; repeatable")
    s.set_defaults(func=cmd_transition)

    s = sub.add_parser("current", parents=[dir_parent],
                        help="print the run's current node and its full reminder")
    s.add_argument("run_id")
    s.set_defaults(func=cmd_current)

    s = sub.add_parser("amend", parents=[dir_parent],
                        help="replace the run's machine mid-run with a valid one "
                             "that keeps the current node")
    s.add_argument("run_id")
    s.add_argument("--machine-file", required=True, type=caller_path,
                   help="the full new machine YAML — start from `state show`")
    s.add_argument("--reason", required=True,
                   help="one line stating why the machine changes now")
    s.set_defaults(func=cmd_amend)

    s = sub.add_parser("show", parents=[dir_parent],
                        help="print the run's machine in force and its version")
    s.add_argument("run_id")
    s.set_defaults(func=cmd_show)

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
