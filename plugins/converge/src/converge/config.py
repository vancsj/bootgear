"""Layered `converge.yaml`: built-in defaults < caller < user < project < task.

`resolve`/`_merge` are copied from engine's `config.py` (not imported: converge
ships standalone). The caller layer is the file a skill passes to `init --defaults`.
The user layer is `~/.claude/converge.yaml`, or `~/.codex/converge.yaml` when
`CONVERGE_HOST=codex`.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from . import model

NAME = "converge"
LAYER_NAMES = ("caller", "user", "project", "task")

DEFAULTS: dict[str, Any] = {
    "cutoff": {
        "report_rules": [],
        "lenses": {"default": {
            "attack_if": [
                {"reach": ["normal", "crafted"], "impact": ["security", "data-loss", "wrong-output"]},
                {"reach": ["normal", "crafted"], "tier": ["reproduced"]},
            ],
            "report_if": [
                {"status": ["survived", "disputed"], "reach": ["normal", "crafted"],
                 "impact": ["security", "data-loss", "wrong-output"]},
            ],
            "choice_if": [],
        }},
        "rereview": {"lenses": {}},
        "cheap": {"enabled": True, "files": 1, "lines": 10, "trivial_lines": 3, "tests": 1,
                  "test_globs": ["**/test_*", "**/*_test.*", "**/tests/**", "**/*.test.*",
                                 "**/*.spec.*"]},
    },
    "caps": {"cut_rounds": 5, "per_lens": {"default": 50}, "agents": model.MAX_AGENTS,
             "angles_per_claim": 5, "batch_items": 30},
    "angles": {"files": [], "disable": []},
    "steps": {"escalate": True, "gap_hunt": True, "cut": "both"},
}
SCHEMA = {
    "cutoff": ("report_rules", "lenses", "rereview", "cheap"),
    "caps": ("cut_rounds", "per_lens", "agents", "angles_per_claim", "batch_items"),
    "angles": ("files", "disable"),
    "steps": ("escalate", "gap_hunt", "cut"),
}
# When the cutter rates: before the attack, after it, both, or never.
CUT_MODES = ("before", "after", "both", "none")
# The rule lists one `cutoff.lenses.<lens>` table may hold.
LENS_KEYS = ("attack_if", "report_if", "choice_if")
CHEAP_KEYS = ("enabled", "files", "lines", "trivial_lines", "tests", "test_globs")


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
            if name in model.RULE_MINIMUMS:
                if not isinstance(allowed, int) or isinstance(allowed, bool) or allowed < 0:
                    problems.append(f"{at}.{name} must be a non-negative integer; got {allowed!r}")
                continue
            if not isinstance(allowed, list) or not allowed:
                problems.append(f"{at}.{name} must be a non-empty list")
                continue
            enum = model.RULE_FIELDS[name]
            for item in allowed:
                if not isinstance(item, str) or (enum is not None and item not in enum):
                    choices = ", ".join(enum) if enum else "a lens id"
                    problems.append(f"{at}.{name}: bad value {item!r} (allowed: {choices})")


def _per_lens(item: Any, where: str, complete: bool, problems: list[str]) -> None:
    if not isinstance(item, dict):
        problems.append(f"{where} must be a map; use per_lens: {{default: <n>}}")
        return
    for lens, cap in item.items():
        if not isinstance(lens, str) or not lens:
            problems.append(f"{where} keys must be non-empty strings; got {lens!r}")
        elif not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
            problems.append(f"{where}.{lens} must be a positive integer; got {cap!r}")
    if complete and "default" not in item:
        problems.append(f"{where} needs a `default` key")


def _lens_tables(item: Any, where: str, complete: bool, problems: list[str]) -> None:
    """A map of lens -> {attack_if, report_if, choice_if}; `complete` needs `default`."""
    if not isinstance(item, dict):
        problems.append(f"{where} must be a map of lens -> {', '.join(LENS_KEYS)}")
        return
    for lens, table in item.items():
        if not isinstance(lens, str) or not lens:
            problems.append(f"{where} keys must be non-empty strings; got {lens!r}")
            continue
        if not isinstance(table, dict):
            problems.append(f"{where}.{lens} must be a map of {', '.join(LENS_KEYS)}")
            continue
        for key, rules in table.items():
            if key not in LENS_KEYS:
                problems.append(f"{where}.{lens}: unknown key {key!r} "
                                f"(allowed: {', '.join(LENS_KEYS)})")
            else:
                _rules(rules, f"{where}.{lens}.{key}", problems)
    if complete and "default" not in item:
        problems.append(f"{where} needs a `default` key")


def _rereview(item: Any, where: str, complete: bool, problems: list[str]) -> None:
    if not isinstance(item, dict):
        problems.append(f"{where} must be a map with key `lenses`")
        return
    for key in item:
        if key != "lenses":
            problems.append(f"{where}: unknown key {key!r} (allowed: lenses)")
    if "lenses" in item:
        _lens_tables(item["lenses"], f"{where}.lenses", False, problems)
    elif complete:
        problems.append(f"{where}.lenses is missing")


def _cheap(item: Any, where: str, complete: bool, problems: list[str]) -> None:
    if not isinstance(item, dict):
        problems.append(f"{where} must be a map of {', '.join(CHEAP_KEYS)}")
        return
    for key in item:
        if key not in CHEAP_KEYS:
            problems.append(f"{where}: unknown key {key!r} (allowed: {', '.join(CHEAP_KEYS)})")
    for key in CHEAP_KEYS:
        if key not in item:
            if complete:
                problems.append(f"{where}.{key} is missing")
            continue
        value = item[key]
        if key == "enabled":
            if not isinstance(value, bool):
                problems.append(f"{where}.{key} must be true or false; got {value!r}")
        elif key == "test_globs":
            if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
                problems.append(f"{where}.{key} must be a list of non-empty strings")
        elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
            problems.append(f"{where}.{key} must be a non-negative integer; got {value!r}")


def validate_config(value: Any, label: str, complete: bool = False) -> list[str]:
    """Problems in one layer, or with `complete` in the effective config or a snapshot."""
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
                if complete:
                    problems.append(f"{where} is missing")
                continue
            item = body[key]
            if section == "cutoff" and key == "lenses":
                _lens_tables(item, where, complete, problems)
            elif section == "cutoff" and key == "rereview":
                _rereview(item, where, complete, problems)
            elif section == "cutoff" and key == "cheap":
                _cheap(item, where, complete, problems)
            elif section == "caps" and key == "per_lens":
                _per_lens(item, where, complete, problems)
            elif section == "caps":
                if not isinstance(item, int) or isinstance(item, bool) or item < 1:
                    problems.append(f"{where} must be a positive integer; got {item!r}")
                elif key == "agents" and item > model.MAX_AGENTS:
                    problems.append(f"{where} must be at most {model.MAX_AGENTS} "
                                    f"(agents per task, main included); got {item!r}")
            elif section == "steps" and key == "cut":
                if item not in CUT_MODES:
                    problems.append(f"{where} must be one of {', '.join(CUT_MODES)}; got {item!r}")
            elif section == "steps":
                if not isinstance(item, bool):
                    problems.append(f"{where} must be true or false; got {item!r}")
            elif not isinstance(item, list) or not all(isinstance(x, str) and x for x in item):
                problems.append(f"{where} must be a list of non-empty strings")
    return problems


def resolve(project_root: Path, task_path: Path | None,
            caller_path: Path | None = None) -> dict[str, Any]:
    """Merge the layers onto the defaults; raise ConfigError listing every problem."""
    project_root = project_root.expanduser().resolve()
    paths: dict[str, Path | None] = {
        "caller": caller_path.expanduser() if caller_path else None,
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
        if layer in ("caller", "task") and not path.is_file():
            problems.append(f"{layer} config does not exist: {path}")
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


def rereview(effective: dict[str, Any]) -> dict[str, Any]:
    """`effective` with `cutoff.rereview.lenses` laid over `cutoff.lenses`: for each lens it
    names, the rule lists it gives replace that lens's, and the lens keeps its other lists. A
    lens with no table of its own starts from `default`."""
    cutoff = effective["cutoff"]
    lenses = copy.deepcopy(cutoff["lenses"])
    for lens, overlay in cutoff["rereview"]["lenses"].items():
        base = cutoff["lenses"].get(lens, cutoff["lenses"]["default"])
        lenses[lens] = {**copy.deepcopy(base), **copy.deepcopy(overlay)}
    return {**effective, "cutoff": {**cutoff, "lenses": lenses}}
