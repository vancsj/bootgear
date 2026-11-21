"""Validate run settlement fields and artifact ownership."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml

from engine import seats

from .session_ledger import _section_body

TASK_TYPES = {"ticket-writing", "ticket-to-pr", "triage", "change-review", "design-doc", "artefact-review"}
TRIAGE_CUTOFFS = ("product", "one-user")
# The one-user profile is a project override, read under the caller's project root.
ONE_USER_CUTOFF = Path(".bootgear") / "config" / "cutoff-one-user.yaml"
TICKET_FILE = "issue.md"
# Run-ledger fields that only `session write-ticket` writes.
VERB_OWNED_FIELDS = ("ticket_path", "owned_artifacts")
# The five parts of a ticket body; each needs a Markdown heading with this text.
TICKET_HEADINGS = ("Problem", "Outcome", "Acceptance criteria", "Scope", "Verification notes")
HEADING_LINE_RE = re.compile(r"^#{1,6}[ \t]+(?P<text>.*?)[ \t]*$")
ENGINE_SKILLS = {"clarify", "execute", "resolve", "debate", "recall"}
SKILL_FIELDS = ("spec_skill", "test_skill", "review_skill")
# The state-machine nodes that call each skill field.
SKILL_FIELD_NODES = {
    "spec_skill": ("spec",),
    "test_skill": ("test-code", "e2e-test", "triage"),
    "review_skill": ("review",),
}
OPTIONAL_SKILL_FIELDS = ("spec_review_skill", "spec_review_override")
# Both hosts dispatch a debate party as a sub-agent or through the advisor
# skill.
PARTY_MECHANISMS = seats.MECHANISMS
# Fields a `debate_party_config.parties.<id>` entry may carry in settlement.
PARTY_CONFIG_FIELDS = frozenset({"label", "prompt", "mechanism", "enabled"})


def _required_skill_fields(machine_text) -> set[str]:
    # Without a readable machine, no node can show which skills are unused, so all are required.
    nodes = set()
    if isinstance(machine_text, str):
        try:
            machine = yaml.safe_load(machine_text)
        except yaml.YAMLError:
            machine = None
        if isinstance(machine, dict) and isinstance(machine.get("nodes"), dict):
            nodes = set(machine["nodes"])
    if not nodes:
        return set(SKILL_FIELDS)
    return {field for field, field_nodes in SKILL_FIELD_NODES.items() if nodes & set(field_nodes)}


def _triage_cutoff_problems(data: dict, task_type: object,
                            project_root: Path) -> list[tuple[str, str]]:
    """A triage run needs `triage_cutoff`; any other type refuses it. `one-user`
    needs the project's own cutoff file."""
    if "triage_cutoff" not in data:
        if task_type == "triage":
            return [("triage_cutoff",
                     f"is required for a triage run: {' or '.join(TRIAGE_CUTOFFS)}")]
        return []
    value = data["triage_cutoff"]
    problems: list[tuple[str, str]] = []
    if task_type != "triage":
        problems.append(("triage_cutoff", f"only a triage run has one, not {task_type!r}"))
    if value not in TRIAGE_CUTOFFS:
        problems.append(("triage_cutoff",
                         f"must be one of: {', '.join(TRIAGE_CUTOFFS)}, got {value!r}"))
    elif value == "one-user" and task_type == "triage":
        cutoff_file = project_root / ONE_USER_CUTOFF
        if not cutoff_file.is_file():
            problems.append(("triage_cutoff", f"'one-user' needs {cutoff_file}, which is absent"))
    return problems


def _has_line_break(value: str) -> bool:
    return "\n" in value or "\r" in value


def _work_dir_problems(data: dict, task_type: object) -> list[tuple[str, str]]:
    """A design-doc run needs `work_dir`; any `work_dir` is an absolute or `~` path."""
    if "work_dir" not in data:
        if task_type == "design-doc":
            return [("work_dir", ("is required for a design-doc run: an absolute path "
                                  "or a path that starts with '~'"))]
        return []
    value = data["work_dir"]
    if (isinstance(value, str) and value.strip() and not _has_line_break(value)
            and os.path.isabs(os.path.expanduser(value))):
        return []
    return [("work_dir", "must be an absolute path or start with '~'")]


def _task_folder_problems(data: dict, task_type: object) -> list[tuple[str, str]]:
    """Validate the authoring folder before creating any task storage."""
    if "task_folder" not in data:
        if task_type in {"ticket-to-pr", "change-review", "artefact-review"}:
            return [("task_folder", f"is required for a {task_type} run")]
        return []
    value = data["task_folder"]
    if (not isinstance(value, str) or not value.strip() or _has_line_break(value)
            or not os.path.isabs(os.path.expanduser(value))):
        return [("task_folder", "must be an absolute or home path without line breaks")]
    try:
        folder = Path(value).expanduser().resolve()
        parent = folder
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.is_dir():
            return [("task_folder", f"is not a usable directory: {parent}")]
        if not os.access(parent, os.W_OK | os.X_OK):
            return [("task_folder", f"directory is unavailable: {parent}")]
    except (OSError, ValueError, RuntimeError) as exc:
        return [("task_folder", f"cannot resolve directory: {exc}")]
    return []


def _artefact_review_problems(data: dict, task_type: object) -> list[tuple[str, str]]:
    """Validate review inputs before the run creates any storage."""
    value = data.get("artefact_review")
    if task_type != "artefact-review":
        return [("artefact_review", "is only valid for artefact-review")] if "artefact_review" in data else []
    if not isinstance(value, dict):
        return [("artefact_review", "requires request and inputs mapping")]
    problems = []
    for key in value:
        if key not in {"request", "inputs", "config"}:
            problems.append(("artefact_review", f"unknown field {key}"))
    if not isinstance(value.get("request"), str) or not value["request"].strip():
        problems.append(("artefact_review.request", "requires a nonempty string"))
    inputs = value.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        problems.append(("artefact_review.inputs", "requires nonempty local input paths"))
        inputs = []
    paths = [(f"inputs[{i}]", item) for i, item in enumerate(inputs)]
    if "config" in value:
        paths.append(("config", value["config"]))
    canonical = []
    for key, item in paths:
        if (not isinstance(item, str) or not item.strip() or _has_line_break(item)
                or not os.path.isabs(os.path.expanduser(item))):
            problems.append((f"artefact_review.{key}", "requires an absolute or home file path"))
            continue
        path = Path(item).expanduser()
        if not path.is_file():
            problems.append((f"artefact_review.{key}", f"is not a readable local file: {path}"))
        elif not os.access(path, os.R_OK):
            problems.append((f"artefact_review.{key}", f"cannot read local file: {path}"))
        if key.startswith("inputs"):
            canonical.append(str(path.resolve()))
    if len(canonical) != len(set(canonical)):
        problems.append(("artefact_review.inputs", "must name distinct input files"))
    return problems


def _bind_task_folder(settlement: str) -> tuple[str, Path | None]:
    """Canonicalise the validated scalar without changing other YAML fields."""
    node = yaml.compose(settlement)
    if not isinstance(node, yaml.MappingNode):
        return settlement, None
    for key, value in node.value:
        if key.value == "task_folder":
            folder = Path(value.value).expanduser().resolve()
            start, end = value.start_mark.index, value.end_mark.index
            suffix = "\n" if settlement[start:end].endswith("\n") else ""
            return settlement[:start] + json.dumps(str(folder)) + suffix + settlement[end:], folder
    return settlement, None


def _ticket_path(run_id: str, session_dir: Path) -> Path:
    """The one path a run's ticket body can have."""
    return session_dir / f"{run_id}.artifacts" / TICKET_FILE


def _ticket_path_problems(value: object, task_type: object, run_id: str,
                          session_dir: Path) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    if task_type != "ticket-writing":
        problems.append(("ticket_path", f"only a ticket-writing run has one, not {task_type!r}"))
    if not isinstance(value, str):
        return [*problems, ("ticket_path", "must be a path string")]
    if not value.strip():
        problems.append(("ticket_path", "must not be empty"))
    if _has_line_break(value):
        problems.append(("ticket_path", "must not contain a line break"))
    if value.startswith("-"):
        problems.append(("ticket_path", "must not start with '-'"))
    if not os.path.isabs(value):
        problems.append(("ticket_path", "must be an absolute path"))
    expected = str(_ticket_path(run_id, session_dir))
    if value != expected:
        problems.append(("ticket_path", f"must equal {expected}"))
    return problems


def _owned_artifacts_problems(data: dict) -> list[tuple[str, str]]:
    if "owned_artifacts" not in data:
        return []
    owned = data["owned_artifacts"]
    if isinstance(owned, list) and all(isinstance(item, str) and os.path.isabs(item)
                                       for item in owned):
        return []
    return [("owned_artifacts", "must be a list of absolute paths")]


def _stored_owned_artifacts(path: Path) -> list[str]:
    """The `owned_artifacts` of the ledger at `path`; exits when they cannot be read."""
    try:
        data = yaml.safe_load(_section_body(path.read_text(), "settlement"))
    except yaml.YAMLError as exc:
        sys.exit(f"cannot read owned_artifacts of {path}, refusing to overwrite it: {exc}")
    if not isinstance(data, dict) or _owned_artifacts_problems(data):
        sys.exit(f"cannot read owned_artifacts of {path}, refusing to overwrite it")
    return data.get("owned_artifacts", [])


def _verb_owned_problems(summary: dict) -> list[tuple[str, str]]:
    """The fields of a settlement for `init` that only the write verb may write."""
    fields = summary.get("fields", [])
    return [(field, "is written only by `session write-ticket`; remove it from the settlement")
            for field in VERB_OWNED_FIELDS if field in fields]


def _validate_settlement(body: str, run_id: str, session_dir: Path,
                         project_root: Path) -> tuple[list[tuple[str, str]], dict]:
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        return [("settlement", f"invalid YAML: {exc}")], {}
    if not isinstance(data, dict):
        return [("settlement", "must be a YAML mapping")], {}

    problems: list[tuple[str, str]] = []
    required = {
        "task_type", "request_assessment", "approach", "principles", "source_of_truth",
        "debate_threshold", "debate_round_cap", "convergence_policy",
        "consented_stop_allowed", "debate_party_config",
        "debate_roster", "review_fix_mode", "autonomy", "goal", "state_machine",
        "session_dir",
    }
    required |= _required_skill_fields(data.get("state_machine"))
    for field in sorted(required - data.keys()):
        problems.append((field, "is required"))

    def text_field(field: str) -> None:
        value = data.get(field)
        if value is None:
            return
        if not isinstance(value, str) or not value.strip():
            problems.append((field, "must be a non-empty string"))

    task_type = data.get("task_type")
    if task_type is not None and task_type not in TASK_TYPES:
        problems.append(("task_type", f"must be one of: {', '.join(sorted(TASK_TYPES))}"))
    problems.extend(_triage_cutoff_problems(data, task_type, project_root))
    problems.extend(_work_dir_problems(data, task_type))
    problems.extend(_task_folder_problems(data, task_type))
    problems.extend(_artefact_review_problems(data, task_type))
    if "ticket_path" in data:
        problems.extend(_ticket_path_problems(data["ticket_path"], task_type, run_id, session_dir))
    problems.extend(_owned_artifacts_problems(data))
    for field in ("request_assessment", "approach", "principles", "debate_threshold"):
        text_field(field)

    source_of_truth = data.get("source_of_truth")
    if source_of_truth is not None:
        if not isinstance(source_of_truth, dict) or not source_of_truth:
            problems.append(("source_of_truth", "must be a non-empty mapping"))
        else:
            for domain, source in source_of_truth.items():
                if not isinstance(domain, str) or not isinstance(source, str) or not source.strip():
                    problems.append(("source_of_truth", "every domain must map to a non-empty string"))

    cap = data.get("debate_round_cap")
    if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or cap < 1):
        problems.append(("debate_round_cap", "must be a positive integer"))
    convergence = data.get("convergence_policy")
    if convergence is not None and convergence != "unanimous":
        problems.append(("convergence_policy", "must be 'unanimous'"))
    consented = data.get("consented_stop_allowed")
    if consented is not None and not isinstance(consented, bool):
        problems.append(("consented_stop_allowed", "must be boolean"))

    def skill_value(field: str, *, override: bool = False) -> None:
        value = data.get(field)
        if value is None:
            return
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, dict):
            values = list(value.values())
            if not values or any(not isinstance(item, str) or not item.strip() for item in values):
                problems.append((field, "must be a skill name or a non-empty label-to-skill mapping"))
                return
        else:
            problems.append((field, "must be a skill name or label-to-skill mapping"))
            return
        if any(item in ENGINE_SKILLS for item in values):
            problems.append((field, "must name a domain skill, not an engine skill"))
        if override and isinstance(value, dict) and any(not isinstance(key, str) or not key.strip() for key in value):
            problems.append((field, "mapping labels must be non-empty strings"))

    for field in SKILL_FIELDS:
        skill_value(field)
    for field in ("spec_override", "test_override", "review_override", *OPTIONAL_SKILL_FIELDS):
        if field in data:
            skill_value(field, override=True)

    debate_mode = data.get("debate_mode")
    if debate_mode is not None and debate_mode not in {"mandatory", "threshold"}:
        problems.append(("debate_mode", "must be mandatory or threshold"))

    roster = data.get("debate_roster")
    if roster is not None:
        if not isinstance(roster, list) or not 2 <= len(roster) <= 5:
            problems.append(("debate_roster", "must contain 2 to 5 stable party IDs"))
        elif any(not isinstance(item, str) or not item.strip() for item in roster):
            problems.append(("debate_roster", "every party ID must be a non-empty string"))
        elif len(set(roster)) != len(roster) or "main-agent" not in roster:
            problems.append(("debate_roster", "must be unique and include main-agent"))

    parties = data.get("debate_parties")
    if parties is not None:
        if not isinstance(parties, list):
            problems.append(("debate_parties", "must be a list"))
        else:
            ids = []
            for party in parties:
                if not isinstance(party, dict):
                    problems.append(("debate_parties", "each party must be a mapping"))
                    continue
                party_id = party.get("id")
                ids.append(party_id)
                for field in ("id", "label", "prompt"):
                    if not isinstance(party.get(field), str) or not party[field].strip():
                        problems.append((f"debate_parties.{field}", "must be a non-empty string"))
                if isinstance(party_id, str) and (":" in party_id or "\n" in party_id or "\r" in party_id):
                    problems.append(("debate_parties.id", "must be single-line and cannot contain ':'"))
                if party.get("mechanism") not in PARTY_MECHANISMS:
                    problems.append(("debate_parties.mechanism",
                                     f"party {party_id!r} has mechanism {party.get('mechanism')!r}; "
                                     "must be one of: " + ", ".join(PARTY_MECHANISMS)))
            if len(ids) != len(set(ids)):
                problems.append(("debate_parties", "party IDs must be unique"))
            if isinstance(roster, list):
                missing = [party_id for party_id in ids if party_id not in roster]
                if missing:
                    problems.append(("debate_parties", f"party IDs missing from debate_roster: {missing}"))

    party_config = data.get("debate_party_config")
    if party_config is not None:
        if not isinstance(party_config, dict):
            problems.append(("debate_party_config", "must be a mapping; empty mapping means native defaults"))
        elif party_config:
            configured = party_config.get("parties")
            if not isinstance(configured, dict):
                problems.append(("debate_party_config.parties", "must be a mapping when configuration is non-empty"))
            else:
                for party_id, config in configured.items():
                    if isinstance(roster, list) and party_id not in roster:
                        problems.append((f"debate_party_config.parties.{party_id}", "is not in debate_roster"))
                    if not isinstance(config, dict):
                        problems.append((f"debate_party_config.parties.{party_id}", "must be a mapping"))
                        continue
                    if set(config) - PARTY_CONFIG_FIELDS:
                        problems.append((f"debate_party_config.parties.{party_id}", "contains unsupported fields"))
                    if any(not isinstance(value, (str, bool)) for value in config.values()):
                        problems.append((f"debate_party_config.parties.{party_id}", "values must be strings or booleans"))
                    if "mechanism" in config and config["mechanism"] not in PARTY_MECHANISMS:
                        problems.append((f"debate_party_config.parties.{party_id}.mechanism",
                                         f"got {config['mechanism']!r}; must be one of: "
                                         + ", ".join(PARTY_MECHANISMS)))
                    if "enabled" in config and not isinstance(config["enabled"], bool):
                        problems.append((f"debate_party_config.parties.{party_id}.enabled",
                                         "must be true or false"))

    # `codex_role`, the field's legacy form, is left unchecked so old ledgers resume.
    advisor_roles = data.get("advisor_roles")
    converge_seats = data.get("converge_seats")
    shape = seats.roles_problems(advisor_roles) + seats.seat_problems(converge_seats)
    problems.extend(shape)
    if not shape and (party_config is None or isinstance(party_config, dict)):
        problems.extend(seats.seat_mismatch(advisor_roles, converge_seats))
        problems.extend(seats.party_mismatch(advisor_roles, party_config, roster))

    admission = data.get("debate_admission")
    if admission is not None:
        if not isinstance(admission, list) or any(not isinstance(item, str) for item in admission):
            problems.append(("debate_admission", "must be a list of skill names"))
        elif any(item in ENGINE_SKILLS for item in admission):
            problems.append(("debate_admission", "cannot admit engine skills"))

    review_fix_mode = data.get("review_fix_mode")
    if review_fix_mode is not None and review_fix_mode not in {"accepted_only", "auto_within_permitted_mutations"}:
        problems.append(("review_fix_mode", "must be accepted_only or auto_within_permitted_mutations"))

    autonomy = data.get("autonomy")
    if autonomy is not None:
        if not isinstance(autonomy, dict):
            problems.append(("autonomy", "must be a mapping"))
        else:
            if autonomy.get("no_further_questions") is not True:
                problems.append(("autonomy.no_further_questions", "must be true"))
            mutations = autonomy.get("permitted_mutations")
            if (not isinstance(mutations, list) or not mutations or
                    any(not isinstance(item, str) or not item.strip() for item in mutations)):
                problems.append(("autonomy.permitted_mutations", "must be a non-empty list of specific actions"))
            if isinstance(mutations, list) and any(item.strip().lower() == "go ahead autonomously" for item in mutations if isinstance(item, str)):
                problems.append(("autonomy.permitted_mutations", "must name specific actions"))

    goal = data.get("goal")
    if goal is not None:
        if not isinstance(goal, dict):
            problems.append(("goal", "must contain succeeded and failed conditions"))
        else:
            for field in ("succeeded", "failed"):
                if not isinstance(goal.get(field), str) or not goal[field].strip():
                    problems.append((f"goal.{field}", "must be a non-empty string"))

    session_value = data.get("session_dir")
    expected_dir = str(session_dir)
    if session_value is not None and (not isinstance(session_value, str) or session_value != expected_dir):
        problems.append(("session_dir", f"must exactly equal {expected_dir}"))

    machine_value = data.get("state_machine")
    machine = None
    if machine_value is not None:
        if not isinstance(machine_value, str) or not machine_value.strip():
            problems.append(("state_machine", "must be a non-empty YAML block"))
        else:
            from engine.state_machine import validate
            from engine.state_views import STATE_MACHINE_FIELD_RE

            if not STATE_MACHINE_FIELD_RE.search(body):
                problems.append(("state_machine", "must use a literal YAML block: state_machine: |"))
            try:
                machine = yaml.safe_load(machine_value)
            except yaml.YAMLError as exc:
                problems.append(("state_machine", f"invalid YAML: {exc}"))
            else:
                if not isinstance(machine, dict):
                    problems.append(("state_machine", "must contain a YAML mapping"))
                else:
                    problems.extend(("state_machine", problem) for problem in validate(machine))

    machine_name = machine.get("name") if isinstance(machine, dict) else None
    return problems, {
        "task_type": data.get("task_type"),
        "session_dir": data.get("session_dir"),
        "state_machine": machine_name,
        "fields": sorted(data),
    }
