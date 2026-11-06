"""Read-only intake and independent observation coverage through public commands."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, TypeGuard

COMMANDS = "settings, intake, gate"
EXAMPLES = {
    "settings": "spec-feedback settings --task-folder <folder> --json",
    "intake": "spec-feedback intake --task-folder <folder> --observations <file> --destination spec-review",
    "gate": "spec-feedback gate --task-folder <folder> --slate <slate> --converge-dir <dir> --observations <file> --checks <file>",
}
OBSERVATION_FIELDS = {"id", "evidence_paths"}
CHECK_FIELDS = {"id", "state", "evidence_refs", "disposition", "claim_ids"}


class Unavailable(Exception):
    pass


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _text(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _identifier(value: Any, where: str, problems: list[str]) -> TypeGuard[str]:
    if not _text(value) or value.startswith("-") or "\n" in value or "\r" in value:
        problems.append(f"{where} must be nonempty text without an option prefix or line break")
        return False
    return True


def _path(value: Any, where: str, problems: list[str], *, absolute: bool = False) -> Path | None:
    if not _identifier(value, where, problems):
        return None
    path = Path(value).expanduser()
    if absolute and not path.is_absolute():
        problems.append(f"{where} must be an absolute path")
        return None
    if not path.is_absolute():
        path = Path(os.environ.get("GEAR_CALLER_CWD", os.getcwd())) / path
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        problems.append(f"{where}: {exc}")
        return None


def _read(path: Path | None, where: str, problems: list[str]) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError) as exc:
        problems.append(f"{where} {path}: {exc}")
        return None


def _fields(value: dict[str, Any], expected: set[str], where: str, problems: list[str]) -> None:
    problems.extend(f"{where}: missing {key}" for key in sorted(expected - value.keys()))
    problems.extend(f"{where}: unknown field {key}" for key in sorted(value.keys() - expected))


def _entries(value: Any, key: str, fields: set[str], problems: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        problems.append(f"{key}: expected an object")
        return []
    _fields(value, {key, "slate"} if key == "checks" else {key}, key, problems)
    rows = value.get(key)
    if not isinstance(rows, list):
        problems.append(f"{key}: expected an array")
        return []
    result = []
    seen: set[str] = set()
    singular = "observation" if key == "observations" else "check"
    for index, row in enumerate(rows):
        where = f"{singular}[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{where}: expected an object")
            continue
        cid = row.get("id")
        if _identifier(cid, f"{where}.id", problems):
            where = f"{singular} {cid}"
            if cid in seen:
                problems.append(f"duplicate {singular} {cid}")
            seen.add(cid)
        _fields(row, fields, where, problems)
        result.append(row)
    return result


def _observations(path: Path | None, problems: list[str]) -> list[dict[str, Any]]:
    rows = _entries(_read(path, "observations", problems), "observations", OBSERVATION_FIELDS, problems)
    for index, row in enumerate(rows):
        where = f"observation {row.get('id', index)}.evidence_paths"
        paths = row.get("evidence_paths")
        if not isinstance(paths, list) or not paths:
            problems.append(f"{where} must be a nonempty array")
            continue
        for item in paths:
            evidence = _path(item, where, problems)
            if evidence is not None:
                try:
                    with evidence.open("rb") as stream:
                        stream.read(1)
                except OSError as exc:
                    problems.append(f"{where} {evidence}: {exc}")
    return rows


def _strings(value: Any, where: str, problems: list[str], *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        problems.append(f"{where} must be {'a nonempty' if nonempty else 'an'} array")
        return []
    for index, item in enumerate(value):
        if not _text(item):
            problems.append(f"{where}[{index}] must be nonempty text")
    return [item for item in value if _text(item)]


def _checks(path: Path | None, slate: str, observations: list[dict[str, Any]],
            problems: list[str]) -> list[dict[str, Any]]:
    value = _read(path, "checks", problems)
    rows = _entries(value, "checks", CHECK_FIELDS, problems)
    if isinstance(value, dict) and value.get("slate") != slate:
        problems.append(f"checks slate {value.get('slate')!r} does not match current slate {slate!r}")
    known = {row["id"] for row in observations if isinstance(row.get("id"), str)}
    assessed: set[str] = set()
    for index, row in enumerate(rows):
        cid = row.get("id")
        where = f"check {cid if isinstance(cid, str) else index}"
        if isinstance(cid, str):
            assessed.add(cid)
            if cid not in known:
                problems.append(f"{where}: unknown observation {cid}")
        state = row.get("state")
        if state not in ("checked", "unassessed"):
            problems.append(f"{where}.state must be checked or unassessed")
        elif state == "unassessed":
            problems.append(f"{where}: unassessed observation")
        _strings(row.get("evidence_refs"), f"{where}.evidence_refs", problems, nonempty=state == "checked")
        if not isinstance(row.get("disposition"), str) or (state == "checked" and not _text(row.get("disposition"))):
            problems.append(f"{where}.disposition must be {'nonempty ' if state == 'checked' else ''}text")
        claims = _strings(row.get("claim_ids"), f"{where}.claim_ids", problems)
        for claim in claims:
            _identifier(claim, f"{where}.claim_ids", problems)
    problems.extend(f"{cid}: missing check" for cid in sorted(known - assessed))
    return rows


def _command(name: str) -> str:
    root = Path(__file__).resolve().parents[2]
    host = os.environ.get("BOOTGEAR_HOST", "codex" if (root / "scripts").is_dir() else "claude")
    bundled = root / "scripts" / name
    if host == "codex" and bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    return shutil.which(name) or name


def _public(name: str, argv: list[str], *, gate: bool = False) -> dict[str, Any]:
    try:
        result = subprocess.run([_command(name), *argv], capture_output=True, text=True, check=False)
    except OSError as exc:
        raise Unavailable(f"{name} public command: {exc}") from exc
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        diagnostic = result.stderr.strip() or result.stdout.strip() or str(exc)
        raise Unavailable(f"{name} public command returned no JSON handback (exit {result.returncode}): {diagnostic}") from exc
    if not isinstance(value, dict):
        raise Unavailable(f"{name} public command returned a non-object handback: {result.stdout.strip()}")
    if value.get("outcome") == "unavailable":
        raise Unavailable(f"{name} public command: {value.get('diagnostic') or result.stderr.strip() or value}")
    if result.returncode != 0 and not (gate and value.get("ok") is False):
        diagnostic = value.get("diagnostic") or value.get("problems") or result.stderr.strip() or value
        raise Unavailable(f"{name} public command failed (exit {result.returncode}): {diagnostic}")
    return value


def _base(task: Path | None) -> dict[str, Any]:
    return {"task_folder": str(task) if task else None,
            "requirements_path": str(task / "requirements.md") if task else None,
            "design_path": str(task / "design.md") if task and (task / "design.md").is_file() else None}


def cmd_settings(args: argparse.Namespace) -> dict[str, Any]:
    problems: list[str] = []
    task = _path(args.task_folder, "task_folder", problems) if args.task_folder else None
    return {**_base(task), "outcome": "refused" if problems else "ready", "problems": problems,
            "layout": {"requirements": "requirements.md", "design": "design.md (optional)"},
            "schemas": {"observations": {"observations": [{"id": "<id>", "evidence_paths": ["<raw file>"]}]},
                        "checks": {"slate": "<current-slate>", "checks": [{"id": "<id>", "state": "checked|unassessed",
                            "evidence_refs": ["<independent evidence>"], "disposition": "<required behaviour>", "claim_ids": []}]}},
            "commands": EXAMPLES, "outcomes": ["ready", "passed", "refused", "unavailable"],
            "capabilities": {name: {"command": _command(name), "available": shutil.which(_command(name)) is not None,
                                    "diagnostic": None if shutil.which(_command(name)) else
                                    f"Executable lookup found no {name} public command"}
                             for name in ("self-review", "converge")},
            "next": "Caller: supply the raw observations to spec-feedback intake, or supply independent checks to gate."}


def cmd_intake(args: argparse.Namespace) -> dict[str, Any]:
    problems: list[str] = []
    task = _path(args.task_folder, "task_folder", problems)
    observations_path = _path(args.observations, "observations", problems)
    _observations(observations_path, problems)
    data = {**_base(task), "observations_path": str(observations_path) if observations_path else None,
            "destination": args.destination, "checkpoints": []}
    if task and task.exists() and not task.is_dir():
        problems.append(f"task_folder is not a directory: {task}")
    if not problems and task:
        history = _public("self-review", ["status", "--task-folder", str(task), "--stage", "spec", "--json"])
        checkpoints = history.get("checkpoints")
        if not isinstance(checkpoints, list) or not isinstance(history.get("record_exists"), bool):
            raise Unavailable(f"self-review status returned incomplete checkpoint history: {history}")
        data["checkpoints"] = checkpoints
        requirements = task / "requirements.md"
        design = task / "design.md"
        for path in (requirements, design):
            if path.exists():
                try:
                    path.read_text()
                except (OSError, UnicodeError) as exc:
                    problems.append(f"primary artifact {path}: {exc}")
        expected = "spec-review" if requirements.is_file() else "spec"
        if not requirements.is_file() and design.exists():
            problems.append("design exists without requirements; recover the incomplete package")
        if not requirements.is_file() and checkpoints:
            problems.append("requirements missing after a spec checkpoint; recover the same package")
        if args.destination != expected:
            problems.append(f"destination must be {expected}; got {args.destination}")
    return {**data, "outcome": "refused" if problems else "ready", "problems": problems,
            "next": "Caller: correct the reported inputs and retry intake." if problems else
                    f"Caller: hand the same task folder and raw observations to {args.destination}."}


def cmd_gate(args: argparse.Namespace) -> dict[str, Any]:
    problems: list[str] = []
    task = _path(args.task_folder, "task_folder", problems)
    directory = _path(args.converge_dir, "converge_dir", problems, absolute=True)
    observations_path = _path(args.observations, "observations", problems)
    checks_path = _path(args.checks, "checks", problems)
    valid_slate = _identifier(args.slate, "slate", problems)
    observations = _observations(observations_path, problems)
    checks = _checks(checks_path, args.slate, observations, problems)
    data = {**_base(task), "slate": args.slate, "converge_dir": str(directory) if directory else None,
            "observations_path": str(observations_path) if observations_path else None,
            "checks_path": str(checks_path) if checks_path else None, "checks": checks, "converge": None}
    if directory and valid_slate:
        status = _public("converge", ["status", args.slate, "--dir", str(directory), "--json"])
        claims = status.get("claims")
        if status.get("slate") != args.slate or not isinstance(claims, list):
            raise Unavailable(f"converge status returned incomplete current-slate claims: {status}")
        if any(not isinstance(row, dict) or not _text(row.get("id")) for row in claims):
            raise Unavailable(f"converge status returned invalid current-slate claim entries: {status}")
        known = {row["id"] for row in claims}
        for row in checks:
            for claim in row.get("claim_ids", []) if isinstance(row.get("claim_ids"), list) else []:
                if isinstance(claim, str) and claim not in known:
                    problems.append(f"check {row.get('id')}: unknown current-slate claim {claim}")
        gate = _public("converge", ["gate", args.slate, "--dir", str(directory), "--json"], gate=True)
        data["converge"] = gate
        if gate.get("slate") != args.slate or not isinstance(gate.get("ok"), bool):
            raise Unavailable(f"converge gate returned no gate result: {gate}")
        if not gate["ok"]:
            failures = gate.get("problems")
            problems.extend(failures if isinstance(failures, list) and failures else ["converge gate has incomplete work"])
    return {**data, "outcome": "refused" if problems else "passed", "problems": problems,
            "next": "Caller: retain the gaps, obtain independent checks, and complete normal converge work before retrying." if problems else
                    "Caller: link the independent dispositions to private todos, then resume the bound workflow within its scope."}


def _parser() -> Parser:
    parser = Parser(prog="spec-feedback", allow_abbrev=False)
    subs = parser.add_subparsers(dest="command", required=True)
    for name, function in (("settings", cmd_settings), ("intake", cmd_intake), ("gate", cmd_gate)):
        sub = subs.add_parser(name, allow_abbrev=False)
        sub.set_defaults(function=function)
        sub.add_argument("--task-folder", required=name != "settings")
        output = sub.add_mutually_exclusive_group()
        output.add_argument("--json", action="store_true")
        output.add_argument("--prose", action="store_true")
        if name != "settings":
            sub.add_argument("--observations", required=True)
        if name == "intake":
            sub.add_argument("--destination", required=True, choices=("spec", "spec-review"))
        if name == "gate":
            for flag in ("--slate", "--converge-dir", "--checks"):
                sub.add_argument(flag, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv and argv[0] in EXAMPLES else "settings"
    json_mode = "--json" in argv or ("--prose" not in argv and os.environ.get("BOOTGEAR_OUTPUT") == "json")
    try:
        args = _parser().parse_args(argv)
        data = args.function(args)
    except UsageError as exc:
        data = {"outcome": "refused", "problems": [str(exc)],
                "next": "Caller: correct the arguments and retry the same command."}
    except Unavailable as exc:
        data = {"outcome": "unavailable", "problems": [], "diagnostic": str(exc),
                "next": "Caller: return blocked with this diagnostic and retain pending observations and private todos."}
    if data["outcome"] in ("refused", "unavailable"):
        print(f"example: {EXAMPLES[command]}\ncommands: {COMMANDS}", file=sys.stderr)
    if json_mode:
        print(json.dumps(data, indent=2))
    else:
        if "schemas" in data:
            print("commands: " + COMMANDS)
            print("layout: requirements.md; design.md is optional")
            print("observations: object with observations array; each entry has id and nonempty evidence_paths")
            print("checks: current slate and checks array; each entry has id, state, evidence_refs, disposition, claim_ids")
            print("states: checked or unassessed; checked requires evidence_refs and disposition")
            for name, capability in data["capabilities"].items():
                print(f"{name}: {capability['command']} ({'available' if capability['available'] else capability['diagnostic']})")
        for key in ("task_folder", "requirements_path", "design_path", "destination", "slate"):
            if key == "design_path" and key in data and data[key] is None:
                print("design_path: none (optional)")
            if data.get(key) is not None:
                print(f"{key}: {data[key]}")
        for problem in data.get("problems", []):
            print(f"- {problem}")
        if data.get("diagnostic"):
            print(f"diagnostic: {data['diagnostic']}")
        print(f"outcome: {data['outcome']}\nnext: {data['next']}")
    return 0 if data["outcome"] in ("ready", "passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
