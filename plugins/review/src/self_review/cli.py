"""Validate and record bounded author checkpoints."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn, TextIO, TypeGuard

STAGES = ("spec", "code")
MODES = ("invoke", "absorb", "neither")
ORIGINS = ("project-config", "user-request", "host-registration", "caller-judgement")
CONFIRMATIONS = ("user-message", "user-confirmed-ledger-entry")
COMMANDS = ("settings", "status", "open", "configure", "pass")


class Refusal(Exception):
    def __init__(self, problems: list[str], outcome: str = "refused", pending: list[str] | None = None):
        self.problems = problems
        self.outcome = outcome
        self.pending = pending or []
        self.current: dict[str, Any] | None = None
        super().__init__("; ".join(problems))


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        command = next((item for item in sys.argv[1:] if item in COMMANDS), "status")
        self.exit(2, f"Error: {message}\nExample: self-review {command} --task-folder TASK --stage spec --json\n"
                     f"Commands: {', '.join(COMMANDS)}\nNext: Caller corrects the arguments and retries.\n")


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def identifier(value: Any) -> TypeGuard[str]:
    return nonempty(value) and not value.startswith("-") and "\n" not in value and "\r" not in value


def confirmation(value: Any, label: str, problems: list[str]) -> None:
    if not isinstance(value, dict):
        problems.append(f"{label} requires kind and ref")
        return
    if value.get("kind") not in CONFIRMATIONS:
        problems.append(f"{label}.kind must be one of {', '.join(CONFIRMATIONS)}")
    if not identifier(value.get("ref")):
        problems.append(f"{label}.ref must be a nonempty reference that does not start with '-'")


def candidate_list(value: Any, label: str, problems: list[str], project: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        problems.append(f"{label} must be a list")
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(value):
        prefix = f"{label}[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{prefix} must be an object")
            continue
        name = entry.get("name")
        if not identifier(name):
            problems.append(f"{prefix}.name must not be empty or start with '-'")
        elif name in seen:
            problems.append(f"{prefix}.name duplicates {name}")
        else:
            seen.add(name)
        origins = ["project-config"] if project else entry.get("origins", [entry.get("origin")])
        if not isinstance(origins, list) or not origins or any(origin not in ORIGINS for origin in origins):
            problems.append(f"{prefix}.origin must use {', '.join(ORIGINS)}")
            origins = []
        if identifier(name):
            result.append({"name": name, "origins": sorted(set(origins))})
    return result


def configured(request: dict[str, Any], project_candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    problems: list[str] = []
    missing_inventory = "candidates" not in request
    inventory = candidate_list(request.get("candidates", []), "candidates", problems)
    by_name: dict[str, dict[str, Any]] = {}
    for item in project_candidates + inventory:
        name = item["name"]
        existing = by_name.setdefault(name, {"name": name, "origins": []})
        existing["origins"] = sorted(set(existing["origins"] + item["origins"]))
    selections = request.get("selections", [])
    if not isinstance(selections, list):
        problems.append("selections must be a list")
        selections = []
    selected: set[str] = set()
    for index, item in enumerate(selections):
        label = f"selections[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{label} must be an object")
            continue
        name = item.get("name")
        if not identifier(name):
            problems.append(f"{label}.name must not be empty or start with '-'")
        elif name not in by_name:
            problems.append(f"{label}.name is unknown: {name}")
        elif name in selected:
            problems.append(f"{label}.name duplicates {name}")
        else:
            selected.add(name)
        if item.get("mode") not in MODES:
            problems.append(f"{label}.mode must be one of {', '.join(MODES)}")
        confirmation(item.get("confirmation"), f"{label}.confirmation", problems)
        for field in ("scope", "coverage"):
            if not nonempty(item.get(field)):
                problems.append(f"{label}.{field} must be nonempty")
    limit = request.get("limit", 2)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        problems.append("limit must be a positive integer")
    elif limit != 2:
        confirmation(request.get("limit_confirmation"), "limit_confirmation", problems)
    if problems:
        raise Refusal(problems)
    if missing_inventory:
        raise Refusal(["Caller must supply an explicit candidates inventory, including an empty list."],
                      "needs-candidates", ["candidates"])
    missing = sorted(set(by_name) - selected)
    if missing:
        raise Refusal([f"Missing selections: {', '.join(missing)}"], "needs-selection", missing)
    return list(by_name.values()), copy.deepcopy(selections)


def state_problems(state: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("checkpoints"), list):
        return ["Record requires version 1 and checkpoints list"]
    visits = {stage: 0 for stage in STAGES}
    last: dict[str, dict[str, Any]] = {}
    for index, checkpoint in enumerate(state["checkpoints"]):
        label = f"checkpoints[{index}]"
        if not isinstance(checkpoint, dict):
            problems.append(f"{label} must be an object")
            continue
        stage = checkpoint.get("stage")
        if stage not in STAGES:
            problems.append(f"{label}.stage is invalid")
            continue
        visits[stage] += 1
        if checkpoint.get("visit") != visits[stage]:
            problems.append(f"{label}.visit must increase by one")
        if stage in last and last[stage].get("outcome") == "ready":
            problems.append(f"{label} follows an open checkpoint")
        last[stage] = checkpoint
        count, limit, history = checkpoint.get("passes"), checkpoint.get("limit"), checkpoint.get("pass_history")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            problems.append(f"{label}.limit must be a positive integer")
            continue
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= limit:
            problems.append(f"{label}.passes must be between zero and limit")
            continue
        if not isinstance(history, list) or len(history) != count:
            problems.append(f"{label}.pass_history must match passes")
            continue
        try:
            configured({"candidates": checkpoint.get("candidates"), "selections": checkpoint.get("selections"),
                        "limit": limit, "limit_confirmation": checkpoint.get("limit_confirmation")}, [])
        except Refusal as exc:
            problems.extend(f"{label}: {problem}" for problem in exc.problems)
        for number, entry in enumerate(history, 1):
            if not isinstance(entry, dict):
                problems.append(f"{label}.pass_history[{number}] must be an object")
                continue
            if entry.get("number") != number or entry.get("result") not in ("clean", "found"):
                problems.append(f"{label}.pass_history[{number}] has invalid number or result")
            if number < count and entry.get("result") == "clean":
                problems.append(f"{label}.pass_history contains passes after clean")
            try:
                configured({"candidates": entry.get("candidates"), "selections": entry.get("selections")}, [])
            except Refusal as exc:
                problems.extend(f"{label}.pass_history[{number}]: {problem}" for problem in exc.problems)
            refs_problems(entry.get("unresolved_refs"), f"{label}.pass_history[{number}].unresolved_refs", problems)
        expected = "clean" if history and history[-1].get("result") == "clean" else "limit-reached" if count == limit else "ready"
        if checkpoint.get("outcome") != expected:
            problems.append(f"{label}.outcome must be {expected}")
        refs_problems(checkpoint.get("unresolved_refs"), f"{label}.unresolved_refs", problems)
        if history and checkpoint.get("unresolved_refs") != history[-1].get("unresolved_refs"):
            problems.append(f"{label}.unresolved_refs must match its last pass")
        if visits[stage] > 1:
            renewal_problems(checkpoint.get("renewal"), label + ".renewal", problems)
    return problems


def refs_problems(value: Any, label: str, problems: list[str]) -> None:
    if not isinstance(value, list):
        problems.append(f"{label} must be a list of references")
    else:
        for index, reference in enumerate(value):
            if not identifier(reference):
                problems.append(f"{label}[{index}] must be a nonempty reference that does not start with '-'")


def renewal_problems(value: Any, label: str, problems: list[str]) -> None:
    if not isinstance(value, dict):
        problems.append(f"{label} requires kind and supporting ref")
        return
    if value.get("kind") not in ("independent-revision", "confirmed-intent-change"):
        problems.append(f"{label}.kind must be independent-revision or confirmed-intent-change")
    if not identifier(value.get("ref")):
        problems.append(f"{label}.ref requires supporting independent review or confirmed intent")
    if value.get("kind") == "confirmed-intent-change":
        confirmation(value.get("confirmation"), f"{label}.confirmation", problems)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise Refusal([f"{path}: expected a JSON object"])
    return value


def load(path: Path) -> dict[str, Any]:
    state = read_object(path) if path.exists() else {"version": 1, "checkpoints": []}
    problems = state_problems(state)
    if problems:
        raise Refusal(problems)
    return state


def atomic_write(path: Path, state: dict[str, Any]) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(state, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def summary(task: Path, stage: str | None, state: dict[str, Any]) -> dict[str, Any]:
    checkpoints = copy.deepcopy([item for item in state["checkpoints"] if stage is None or item["stage"] == stage])
    result = {"outcome": "ready", "task_folder": str(task), "record_path": str(task / "self-review.json"),
              "record_exists": (task / "self-review.json").exists(), "stage": stage, "checkpoints": checkpoints,
              "pending": [], "diagnostic": "", "unresolved_refs": []}
    if checkpoints:
        result.update(copy.deepcopy(checkpoints[-1]))
    return result


def next_action(outcome: str) -> str:
    if outcome in ("clean", "limit-reached"):
        return "Caller retains open author work and hands artifacts to independent review without author hypotheses."
    if outcome in ("needs-selection", "needs-candidates"):
        return "Caller obtains the missing inventory or explicit user selections, then retries without recording a pass."
    if outcome == "unavailable":
        return "Caller returns blocked with this diagnostic and preserves pending author work."
    if outcome == "refused":
        return "Caller corrects the reported problems and retries without resetting the checkpoint."
    return "Author applies confirmed source modes, checks the artifact, then records the expected next pass."


def path_value(raw: str, label: str) -> Path:
    if not identifier(raw):
        raise Refusal([f"{label} must be a path that does not start with '-' or contain line breaks"])
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(os.environ.get("GEAR_CALLER_CWD", os.getcwd())) / path
    return path.resolve()


def run(args: argparse.Namespace, task: Path) -> dict[str, Any]:
    project = path_value(args.project_root, "project-root")
    if task.exists() and not task.is_dir():
        raise Refusal(["task-folder must be a directory"])
    request: dict[str, Any] = {}
    if args.input:
        text = sys.stdin.read() if args.input == "-" else path_value(args.input, "input").read_text()
        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            raise Refusal([f"input JSON: {exc}"]) from exc
        if not isinstance(request, dict):
            raise Refusal(["input must be a JSON object"])
    project_file = project / ".bootgear/config/self-review.json"
    problems: list[str] = []
    project_candidates = candidate_list(read_object(project_file).get("candidates"), "project candidates", problems, True) if project_file.exists() else []
    if problems:
        raise Refusal(problems)
    record = task / "self-review.json"
    if args.command == "settings":
        result = summary(task, args.stage, {"checkpoints": []})
        result.update(defaults={"limit": 2}, candidate_configuration=project_candidates,
                      effective_supplied_values=request,
                      supported_inputs={"stages": STAGES, "modes": MODES, "origins": ORIGINS,
                                        "confirmation_kinds": CONFIRMATIONS, "commands": COMMANDS})
        return result
    if args.command == "status" and not record.exists():
        return summary(task, args.stage, {"checkpoints": []})
    prepared = configured(request, project_candidates) if args.command in ("open", "configure") else None
    if args.command == "pass":
        if not isinstance(request.get("expected_pass"), int) or isinstance(request.get("expected_pass"), bool) or request["expected_pass"] < 1:
            problems.append("expected_pass must be a positive integer")
        if request.get("result") not in ("clean", "found"):
            problems.append("result must be clean or found")
        refs_problems(request.get("unresolved_refs"), "unresolved_refs", problems)
        if problems:
            raise Refusal(problems)
    try:
        import fcntl
    except ImportError as exc:
        raise Refusal([f"advisory-lock unavailable: {exc}"], "unavailable") from exc
    lock: TextIO | None = None
    try:
        task.mkdir(parents=True, exist_ok=True)
        lock = (task / ".self-review.lock").open("a+")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        if lock is not None:
            lock.close()
        raise Refusal([f"advisory-lock unavailable: {exc}"], "unavailable") from exc
    assert lock is not None
    try:
        state = load(record)
        if args.command == "status":
            return summary(task, args.stage, state)
        checkpoints = state["checkpoints"]
        matching = [item for item in checkpoints if item["stage"] == args.stage]
        current = matching[-1] if matching else None
        if args.command == "open":
            if current and current["outcome"] == "ready":
                raise Refusal(["An open checkpoint already exists; configure it without resetting its budget."])
            if current:
                renewal_problems(request.get("renewal"), "renewal", problems)
            elif "renewal" in request:
                problems.append("A first checkpoint cannot renew a predecessor")
            if problems:
                raise Refusal(problems)
            assert prepared is not None
            current = {"stage": args.stage, "visit": len(matching) + 1, "passes": 0,
                       "limit": request.get("limit", 2), "limit_confirmation": request.get("limit_confirmation"),
                       "outcome": "ready", "candidates": prepared[0], "selections": prepared[1],
                       "renewal": request.get("renewal"), "pass_history": [], "unresolved_refs": []}
            checkpoints.append(current)
        else:
            if current is None:
                raise Refusal(["No checkpoint exists; open one first."])
            if current["outcome"] != "ready":
                raise Refusal(["The checkpoint is closed and immutable."])
            if args.command == "configure":
                preserved = [item for item in current["candidates"] if "project-config" in item["origins"]]
                prepared = configured(request, project_candidates + preserved)
                if "limit" in request and request["limit"] != current["limit"]:
                    problems.append("An active checkpoint's limit cannot change")
                assert prepared is not None
                required = {item["name"] for item in current["candidates"] if "project-config" in item["origins"]}
                provided = {item["name"] for item in prepared[0]}
                if required - provided:
                    problems.append(f"Cannot remove project-config candidates: {', '.join(sorted(required - provided))}")
                if problems:
                    raise Refusal(problems)
                current.update(candidates=prepared[0], selections=prepared[1])
            else:
                if request["expected_pass"] != current["passes"] + 1:
                    raise Refusal([f"expected_pass must be {current['passes'] + 1}; current passes: {current['passes']}"])
                current["passes"] += 1
                current["unresolved_refs"] = copy.deepcopy(request["unresolved_refs"])
                current["pass_history"].append({"number": current["passes"], "result": request["result"],
                                                "candidates": copy.deepcopy(current["candidates"]),
                                                "selections": copy.deepcopy(current["selections"]),
                                                "unresolved_refs": copy.deepcopy(request["unresolved_refs"])})
                current["outcome"] = "clean" if request["result"] == "clean" else "limit-reached" if current["passes"] == current["limit"] else "ready"
        problems = state_problems(state)
        if problems:
            raise Refusal(problems)
        atomic_write(record, state)
        return summary(task, args.stage, state)
    except Refusal as exc:
        exc.current = summary(task, args.stage, load(record))
        raise
    finally:
        lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description="Record bounded author self-review checkpoints.")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        sub = commands.add_parser(command)
        sub.add_argument("--task-folder", required=command != "settings", default=".")
        sub.add_argument("--project-root", default=os.environ.get("GEAR_CALLER_CWD", os.getcwd()))
        sub.add_argument("--stage", choices=STAGES, required=command in ("open", "configure", "pass"))
        sub.add_argument("--input", help="One JSON file, or '-' for stdin")
        output = sub.add_mutually_exclusive_group()
        output.add_argument("--json", action="store_true")
        output.add_argument("--prose", action="store_true")
    args = parser.parse_args(argv)
    task = Path(os.getcwd())
    try:
        task = path_value(args.task_folder, "task-folder")
        result = run(args, task)
    except Refusal as exc:
        result = exc.current or summary(task, args.stage, {"checkpoints": []})
        result.update(outcome=exc.outcome, diagnostic=str(exc), pending=exc.pending)
    except (OSError, ValueError) as exc:
        result = summary(task, args.stage, {"checkpoints": []})
        result.update(outcome="unavailable", diagnostic=f"self-review local JSON/storage mechanism unavailable: {exc}")
    result["next"] = next_action(result["outcome"])
    if result["outcome"] == "ready" and args.command == "settings":
        result["next"] = "Caller supplies the explicit candidate inventory and confirmed selections, then checks public status."
    elif result["outcome"] == "ready" and not result["checkpoints"]:
        result["next"] = "Caller opens a checkpoint with an explicit candidate inventory and confirmed selections."

    if args.json or (not args.prose and os.environ.get("BOOTGEAR_OUTPUT") == "json"):
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Self-review: {result['record_path']}")
        if "visit" in result:
            print(f"{result['stage']} visit {result['visit']}: {result['passes']}/{result['limit']} passes")
        if result["diagnostic"]:
            print(f"Diagnostic: {result['diagnostic']}")
        print(f"Outcome: {result['outcome']}")
        print(f"Next: {result['next']}")
    return 3 if result["outcome"] == "unavailable" else 2 if result["outcome"] in ("refused", "needs-candidates", "needs-selection") else 0


if __name__ == "__main__":
    raise SystemExit(main())
