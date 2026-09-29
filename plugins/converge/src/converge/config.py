"""Layered `converge.yaml`: built-in defaults < user < project < task.

`resolve`/`_merge` are copied from engine's `config.py` (not imported: converge
ships standalone). The user layer is `~/.claude/converge.yaml`, or
`~/.codex/converge.yaml` when `CONVERGE_HOST=codex`.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from . import model

NAME = "converge"
LAYER_NAMES = ("user", "project", "task")

DEFAULTS: dict[str, Any] = {
    "cutoff": {
        "report_if": [
            {"severity": ["security", "data-loss"], "frequency": ["every-call", "common", "rare"]},
            {"severity": ["wrong-behavior"], "frequency": ["every-call", "common"]},
            {"confidence": ["reproduced"],
             "severity": ["security", "data-loss", "wrong-behavior", "degraded"],
             "frequency": ["every-call", "common", "rare"]},
        ],
        "report_if_gap_hunt": [
            {"frequency": ["every-call", "common"]},
            {"frequency": ["rare"], "severity": ["security", "data-loss"]},
        ],
        "report_rules": [],
    },
    "caps": {"refute_rounds": 5, "cut_rounds": 3, "per_lens": 3, "agents": model.MAX_AGENTS},
    "angles": {"files": [], "disable": []},
}
# Replaces `report_if` and `report_if_gap_hunt` for a slate started with `--pass` >= 2;
# `report_rules` and the other sections keep their resolved values.
REREVIEW_CUTOFF: dict[str, Any] = {
    "report_if": [
        {"severity": ["security", "data-loss"], "frequency": ["every-call", "common", "rare"]},
        {"severity": ["wrong-behavior"], "frequency": ["every-call", "common"]},
        {"confidence": ["reproduced"], "severity": ["security", "data-loss", "wrong-behavior"],
         "frequency": ["every-call", "common", "rare"]},
    ],
    "report_if_gap_hunt": [
        {"frequency": ["every-call", "common"],
         "severity": ["security", "data-loss", "wrong-behavior"]},
        {"frequency": ["rare"], "severity": ["security", "data-loss"]},
    ],
}
SCHEMA = {
    "cutoff": ("report_if", "report_if_gap_hunt", "report_rules"),
    "caps": ("refute_rounds", "cut_rounds", "per_lens", "agents"),
    "angles": ("files", "disable"),
}


OPTIONAL_KEYS = ("report_rules",)


class ConfigError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def user_path() -> Path:
    host_dir = ".codex" if os.environ.get("CONVERGE_HOST") == "codex" else ".claude"
    return Path.home() / host_dir / f"{NAME}.yaml"


def _load(path: Path, label: str) -> tuple[Any, bool]:
    if not path.exists():
        return {}, False
    if not path.is_file():
        raise ConfigError([f"{label} config is not a file: {path}"])
    try:
        value = yaml.safe_load(path.read_text())
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigError([f"cannot read {label} config {path}: {exc}"]) from exc
    return {} if value is None else value, True


def _merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        result = copy.deepcopy(base)
        for key, value in override.items():
            result[key] = _merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    return copy.deepcopy(override)


def _rules(value: Any, where: str, problems: list[str]) -> None:
    if not isinstance(value, list):
        problems.append(f"{where} must be a list of rules")
        return
    for i, rule in enumerate(value):
        at = f"{where}[{i}]"
        if not isinstance(rule, dict) or not rule:
            problems.append(f"{at} must be a non-empty mapping field -> allowed values")
            continue
        for name, allowed in rule.items():
            if name not in model.RULE_FIELDS:
                problems.append(f"{at}: unknown field {name!r} (allowed: {', '.join(model.RULE_FIELDS)})")
                continue
            if not isinstance(allowed, list) or not allowed:
                problems.append(f"{at}.{name} must be a non-empty list")
                continue
            enum = model.RULE_FIELDS[name]
            for item in allowed:
                if not isinstance(item, str) or (enum is not None and item not in enum):
                    choices = ", ".join(enum) if enum else "a lens id"
                    problems.append(f"{at}.{name}: bad value {item!r} (allowed: {choices})")


def validate_config(value: Any, label: str, complete: bool = False) -> list[str]:
    """Problems in one layer (or, with `complete`, the effective config)."""
    problems: list[str] = []
    if not isinstance(value, dict):
        return [f"{label}: top level must be a mapping"]
    for key in value:
        if key not in SCHEMA:
            problems.append(f"{label}: unknown key {key!r} (allowed: {', '.join(SCHEMA)})")
    for section, keys in SCHEMA.items():
        if section not in value:
            if complete:
                problems.append(f"{label}: missing section {section!r}")
            continue
        body = value[section]
        if not isinstance(body, dict):
            problems.append(f"{label}: {section} must be a mapping")
            continue
        for key in body:
            if key not in keys:
                problems.append(f"{label}: unknown key {section}.{key} (allowed: {', '.join(keys)})")
        for key in keys:
            where = f"{label}: {section}.{key}"
            if key not in body:
                # Snapshots from before report_rules existed stay valid.
                if complete and key not in OPTIONAL_KEYS:
                    problems.append(f"{where} is missing")
                continue
            item = body[key]
            if section == "cutoff" and key != "report_rules":
                _rules(item, where, problems)
            elif section == "caps":
                if not isinstance(item, int) or isinstance(item, bool) or item < 1:
                    problems.append(f"{where} must be a positive integer; got {item!r}")
                elif key == "agents" and item > model.MAX_AGENTS:
                    problems.append(f"{where} must be at most {model.MAX_AGENTS} "
                                    f"(agents per task, main included); got {item!r}")
            elif not isinstance(item, list) or not all(isinstance(x, str) and x for x in item):
                problems.append(f"{where} must be a list of non-empty strings")
    return problems


def resolve(project_root: Path, task_path: Path | None) -> dict[str, Any]:
    """Merge the layers; raise ConfigError listing every problem."""
    project_root = project_root.expanduser().resolve()
    paths: dict[str, Path | None] = {
        "user": user_path(),
        "project": project_root / ".bootgear" / "config" / f"{NAME}.yaml",
        "task": task_path.expanduser() if task_path else None,
    }
    problems: list[str] = []
    effective: Any = copy.deepcopy(DEFAULTS)
    sources = []
    for layer in LAYER_NAMES:
        path = paths[layer]
        if path is None:
            sources.append({"layer": layer, "path": "<none>", "present": False})
            continue
        if layer == "task" and not path.is_file():
            problems.append(f"task config does not exist: {path}")
            sources.append({"layer": layer, "path": str(path), "present": False})
            continue
        try:
            value, present = _load(path, layer)
        except ConfigError as exc:
            problems.extend(exc.problems)
            continue
        layer_problems = validate_config(value, f"{layer} {path}")
        problems.extend(layer_problems)
        if not layer_problems:
            effective = _merge(effective, value)
        sources.append({"layer": layer, "path": str(path), "present": present})
    if not problems:
        problems.extend(validate_config(effective, "effective", complete=True))
    if problems:
        raise ConfigError(problems)
    return {"project_root": str(project_root), "sources": sources, "effective": effective}
