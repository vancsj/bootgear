"""Load, validate, and display state machine definitions."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

START_NODE = "clarify"
TERMINAL_NODES = {"succeeded", "failed"}
RESERVED_NODE_NAMES = TERMINAL_NODES

# A Mermaid stateDiagram-v2 state ID may not contain a hyphen; node names in
# this schema are hyphenated (spec-debate, debate-findings, ...), so every diagram ID is
# derived from the node name by replacing "-" with "_". Two distinct node
# names that only differ by choosing "-" vs "_" in the same position (e.g.
# "spec-debate" and "spec_debate" both present) would collide under this
# substitution — checked for explicitly below rather than silently letting
# one shadow the other in the emitted diagram.
_MERMAID_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
LEAVE_CHECK_PLACEHOLDER_RE = re.compile(r"\{(?P<name>[a-z_]+)\}")


def _mermaid_id(node_name: str) -> str:
    return node_name.replace("-", "_")


def edges(node: object) -> list:
    return list(node.get("next") or []) if isinstance(node, dict) else []


def reaches_succeeded(nodes: dict, start: str) -> bool:
    """True if some `next:` path from `start` reaches `succeeded`, ignoring
    `max_visits`."""
    seen, frontier = {start}, [start]
    while frontier:
        for dest in edges(nodes.get(frontier.pop())):
            if dest == "succeeded":
                return True
            if dest in nodes and dest not in seen:
                seen.add(dest)
                frontier.append(dest)
    return False


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


def _validate_exit_checks(node_name: str, exit_checks: object, leave: object,
                          next_list: list) -> list[str]:
    problems: list[str] = []
    if leave is None:
        problems.append(f"node '{node_name}': `reminder.exit_checks` requires `reminder.leave`")
    if not isinstance(exit_checks, dict) or not exit_checks:
        problems.append(f"node '{node_name}': `reminder.exit_checks` must be a non-empty "
                        f"mapping from a `next` node to a check")
        return problems
    for exit_dest, check in exit_checks.items():
        if exit_dest not in next_list:
            problems.append(f"node '{node_name}': `reminder.exit_checks` names '{exit_dest}', "
                            f"which is not in `next`")
        if not isinstance(check, dict):
            problems.append(f"node '{node_name}': `reminder.exit_checks.{exit_dest}.argv` must "
                            f"be a non-empty list of strings")
            continue
        fallback = check.get("on_refuse")
        if fallback is not None and fallback not in next_list:
            problems.append(f"node '{node_name}': `reminder.exit_checks.{exit_dest}.on_refuse` "
                            f"names '{fallback}', which is not in `next`")
        if isinstance(fallback, str) and fallback in exit_checks and fallback != exit_dest:
            problems.append(f"node '{node_name}': `reminder.exit_checks.{exit_dest}.on_refuse` "
                            f"names '{fallback}', which has its own exit check")
        if fallback is not None and fallback == exit_dest:
            problems.append(f"node '{node_name}': `reminder.exit_checks.{exit_dest}.on_refuse` "
                            f"must name a node other than the checked exit")
        extra = set(check) - {"argv", "on_refuse"}
        if extra:
            problems.append(f"node '{node_name}': `reminder.exit_checks.{exit_dest}` has unknown "
                            f"key(s): {', '.join(sorted(extra))}")
        if not isinstance(check.get("argv"), list) or not check["argv"]:
            problems.append(f"node '{node_name}': `reminder.exit_checks.{exit_dest}.argv` must "
                            f"be a non-empty list of strings")
            continue
        problems.extend(_validate_leave_check(f"{node_name}.exit_checks.{exit_dest}",
                                              check["argv"], "" if leave is None else leave))
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
        if isinstance(next_list, list) and len(next_list) != 1:
            problems.append(f"node '{node_name}': `reminder.leave_check` runs on every exit; "
                            f"a node with {len(next_list)} exits names each gated exit in "
                            f"`reminder.exit_checks`")
    if "exit_checks" in reminder:
        problems.extend(_validate_exit_checks(node_name, reminder.get("exit_checks"), leave,
                                              next_list if isinstance(next_list, list) else []))
        if "leave_check" in reminder:
            problems.append(f"node '{node_name}': `reminder.leave_check` and "
                            f"`reminder.exit_checks` cannot both be set")

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
