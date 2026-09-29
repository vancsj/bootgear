"""Resolve layered YAML configuration and optional model reports."""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from engine.clikit import caller_cwd, caller_path, emit

NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
LAYER_NAMES = ("user", "project", "task")


def _fail(message: str) -> NoReturn:
    sys.exit(f"invalid configuration: {message}")


def _load(path: Path, label: str) -> tuple[Any, bool]:
    if not path.exists():
        return {}, False
    if not path.is_file():
        _fail(f"{label} config is not a file: {path}")
    try:
        value = yaml.safe_load(path.read_text())
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        _fail(f"cannot read {label} config {path}: {exc}")
    return {} if value is None else value, True


def _merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        result = copy.deepcopy(base)
        for key, value in override.items():
            result[key] = _merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    return copy.deepcopy(override)


def _model_report(value: Any, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    report = []
    if "model" in value or "profile" in value:
        report.append({
            "path": ".".join(path) or "<root>",
            "model": value.get("model"),
            "profile": value.get("profile"),
        })
    for key, child in value.items():
        if isinstance(key, str):
            report.extend(_model_report(child, (*path, key)))
    return report


# Resolved per-party fields shown to the user but never written to settlement.
REPORT_ONLY_FIELDS = frozenset({"model", "profile"})
SETTLE_NEXT = "write `debate_party_config` into settlement verbatim; model/profile are report-only"


def _debate_party_config(effective: Any) -> dict[str, Any]:
    """Drop the report-only model/profile fields from resolved debate-parties
    config. Every other field is kept, so settlement validation still refuses
    a misspelt or unsupported one."""
    parties = effective.get("parties") if isinstance(effective, dict) else None
    if parties is None:
        return {}
    if not isinstance(parties, dict):
        return {"parties": parties}
    return {"parties": {
        party_id: {k: v for k, v in config.items() if k not in REPORT_ONLY_FIELDS}
        if isinstance(config, dict) else config
        for party_id, config in parties.items()
    }}


def resolve(name: str, project_root: Path, user_path: Path | None,
            project_path: Path | None, task_path: Path | None,
            report_models: bool) -> dict[str, Any]:
    if not NAME_RE.match(name):
        _fail(f"config name must match {NAME_RE.pattern}: {name!r}")
    project_root = project_root.resolve()
    if not project_root.is_dir():
        _fail(f"project root is not a directory: {project_root}")

    paths = {
        "user": (user_path or (Path.home() / ".claude" / f"{name}.yaml")).expanduser(),
        "project": project_path or (project_root / ".bootgear" / "config" / f"{name}.yaml"),
        "task": task_path,
    }
    effective: Any = {}
    sources = []
    for layer in LAYER_NAMES:
        path = paths[layer]
        if path is None:
            value, present = {}, False
            display_path = "<none>"
        else:
            value, present = _load(path, layer)
            display_path = str(path)
        effective = _merge(effective, value)
        sources.append({"layer": layer, "path": display_path, "present": present})

    result: dict[str, Any] = {
        "name": name,
        "project_root": str(project_root),
        "sources": sources,
        "effective": effective,
    }
    if name == "debate-parties":
        result["debate_party_config"] = _debate_party_config(effective)
        result["next"] = SETTLE_NEXT
    if report_models:
        result["model_report"] = _model_report(effective)
    return result


def cmd_resolve(args: argparse.Namespace) -> None:
    result = resolve(
        args.name,
        args.project_root,
        args.user_config,
        args.project_config,
        args.task_config_file,
        args.report == "models",
    )
    prose = [f"CONFIG    {result['name']} project={result['project_root']}"]
    for source in result["sources"]:
        state = "present" if source["present"] else "missing"
        prose.append(f"SOURCE    {source['layer']} {state} {source['path']}")
    for model in result.get("model_report", []):
        prose.append(f"MODEL     {model['path']} model={model['model'] or '<native default>'} "
                     f"profile={model['profile'] or '<none>'}")
    if "debate_party_config" in result:
        prose.append(f"next: {SETTLE_NEXT}")
    # `--json` predates the output modes and keeps its indented shape.
    emit("json" if args.json else "prose", result, prose,
         json_text=json.dumps(result, indent=2, sort_keys=True))


def add_subparsers(sub: argparse._SubParsersAction) -> None:
    resolve_parser = sub.add_parser("resolve", help="resolve user/project/task configuration")
    resolve_parser.add_argument("--name", required=True, help="configuration name")
    resolve_parser.add_argument("--project-root", type=caller_path, default=caller_cwd())
    resolve_parser.add_argument("--user-config", type=caller_path)
    resolve_parser.add_argument("--project-config", type=caller_path)
    resolve_parser.add_argument("--task-config-file", type=caller_path)
    resolve_parser.add_argument("--report", choices=("none", "models"), default="none")
    resolve_parser.add_argument("--json", action="store_true")
    resolve_parser.set_defaults(func=cmd_resolve)
