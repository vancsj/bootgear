"""Read state machines and render the current run state."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from engine.session_ledger import (
    MACHINES_SECTION,
    _heading_re,
    _ledger_command,
    _section_body,
)
from engine.state_machine import (
    START_NODE,
)

# Matches the `state_machine:` block scalar header at column 0 in the settlement
# body, with any chomping indicator (`|`, `|-`, `|+`) that YAML allows.
STATE_MACHINE_FIELD_RE = re.compile(r"(?m)^state_machine: \|[-+]?\n((?:(?:[ \t].*)?\n)*)")
CURRENT_STATE_RE = re.compile(r"(?m)^current: (?P<node>\S+)\s*$")
# A `## state` log entry as cmd_transition writes it:
# "- <YYYY-MM-DD HH:MM> <from> -> <to> (<reason>)[ [leave_check exit 0: <argv>]]", or on a
# refused exit check "(<reason>; <first refusal line>)" with <to> the on_refuse node.
_LOG_ENTRY_DEST_RE = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+ -> (?P<dest>\S+) \(")
# A `## machines` entry header as cmd_amend writes it; the entry's machine
# text follows on lines indented two spaces.
MACHINE_ENTRY_RE = re.compile(
    r"^- v(?P<v>\d+) (?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) at (?P<node>\S+) "
    r"\((?P<reason>.*)\)$")


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
    exit_checks = reminder.get("exit_checks")
    if isinstance(exit_checks, dict):
        for exit_dest, check in exit_checks.items():
            fallback = check.get("on_refuse") if isinstance(check, dict) else None
            suffix = f" (on refuse: {fallback})" if fallback else ""
            argv = check.get("argv", []) if isinstance(check, dict) else []
            lines.append(f"exit_check {exit_dest}: {' '.join(str(a) for a in argv)}{suffix}")
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
        "exit_checks": reminder.get("exit_checks") or None,
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
    and as text, its valid destinations, and whether the ledger is closed."""
    _, current, node = _current_node_lookup(text, path)
    return {"current": current, "terminal": bool(node.get("terminal")),
            "reminder": _node_reminder_data(node), "text": _node_reminder_text(node),
            "destinations": [] if node.get("terminal") else list(dict.fromkeys([*(node.get("next") or []), "failed"])),
            "closed": _heading_re("closed").search(text) is not None}


def try_current_node_view(text: str, path: Path) -> tuple[dict | None, str | None]:
    """`current_node_view`, or its refusal message instead of exiting."""
    try:
        return current_node_view(text, path), None
    except SystemExit as e:
        return None, str(e.code)


def _close_command(run_id: str, path: Path, dest: str) -> str:
    close = _ledger_command("session close", run_id, path, f"--outcome {dest}")
    if dest == "failed":
        close += ' --reason "<why the goal is undoable>"'
    return close


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
