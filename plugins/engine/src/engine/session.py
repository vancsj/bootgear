#!/usr/bin/env python3
"""Command line for engine's session ledger.

One Markdown file per run, five fixed sections (settlement, decisions,
todos, pitches, state). This script is the only thing that ever writes it —
no skill's own Edit/Write calls should touch the file directly, so the
format can't drift the way free-form editing invites over a long,
many-compaction run.

    init              create a new ledger, write its settlement once
    read              print a section, or the whole file
    record-decision   append a decisions line
    next-question-id  print the next unused debate question id
    update-todo       toggle a todo's done state in place
    record-pitch      append a pitches line
    close             mark the ledger closed (succeeded or failed)

A sixth, optional section, `## machines`, follows `## state`: the run's
mid-run state machine amendments, written only by `state amend`.

See engine.state for `transition`/`validate`/`diagram`, the state
machine commands.

Known limitation: question-id sequencing, one-close-per-question detection,
round-0/scope-settled ordering, and `_check_decisions_shape`'s own re-check
all read the whole decisions section as one unit. One incompatible or
malformed tagged entry anywhere in it — for example a ledger written before
a shape rule existed — can fail every read and write of the entire ledger,
not just that one question. There is no per-question isolation today.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from engine.clikit import ENV_PROG, caller_path, emit, refuse

PROG = "task"
SECTIONS = ["settlement", "decisions", "todos", "pitches", "state"]
# Optional, after `## state` only: a column-0 `## machines` line inside an
# older ledger's settlement is settlement text, not this section.
MACHINES_SECTION = "machines"
START_NODE = "clarify"
DEFAULT_DIR = Path.home() / ".bootgear" / "session"
RUN_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
DEBATE_MODES = {"debate", "debate-capped", "debate-degraded", "scope-settled"}
ALL_MODES = DEBATE_MODES | {"solo", "resolve"}
QUESTION_ID_RE = re.compile(r"\Aq[0-9]+\Z")
QUESTION_TAG_RE = re.compile(r"^\[(q[0-9]+)\]\s")
CURRENT_LINE_RE = re.compile(r"(?m)^current: (?P<node>\S+)\s*$")
STARTED_LINE_RE = re.compile(r"(?m)^started: (?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")
# A `## state` transition-log entry as `state transition` writes it.
TRANSITION_LINE_RE = re.compile(
    r"^- (?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (?P<from>\S+) -> (?P<to>\S+) ")
# Matches a full decision line as record-decision writes it: "- <ts> [<mode>]
# [<qid>] <summary>" (tag omitted for non-debate modes). Anchored on the mode
# bracket so a solo/resolve summary that happens to start with "[qN] " text
# is never mistaken for a real tag — only entries whose actual --mode was a
# debate mode ever carry one.
DECISION_ENTRY_RE = re.compile(r"^- \S+ \S+ \[(?P<mode>[^\]]+)\] (?P<rest>.*)$")
# A single bracket group: "[...]" with no nested brackets inside.
_BRACKET_GROUP_RE = re.compile(r"\[[^\[\]]*\]")
# The line's leading run: "- " (record-decision's fixed entry start), any
# non-bracket characters (the timestamp position, however malformed or
# padded), an optional run of stray "[" characters before the first real
# group (this is what lets a doubled opening bracket like "[[debate]" still
# find "[debate]" as a group instead of failing to match at all — a bare
# "[[..." has no substring matching "\[[^\[\]]*\]" until the SECOND "["),
# then a maximal run of bracket groups tolerating stray/unmatched closing
# bracket characters between them too (not just whitespace) — this is what
# lets a doubled closing bracket like "[debate]]" still be read as one
# bracket group followed by a stray "]", rather than breaking the run
# entirely the way a plain "one bracket group, then whitespace, then the
# next" pattern would. Only closing brackets are tolerated *between* groups,
# never opening ones — an opening bracket there would let the trailing
# tolerance eat into the next group's own opener, splitting one group into
# two matches that no longer read back as a single "[qN]"-shaped group (a
# normal "[mode] [q1]" shape's own "[" before "q1]" would be consumed as
# "trailing" tolerance after the mode group, leaving "q1]" with no opening
# bracket for `_BRACKET_GROUP_RE` to match). The run stops at the
# first character that is neither whitespace nor a bracket character, i.e.
# the first real prose content.
_LEADING_BRACKET_RUN_RE = re.compile(r"^- [^\[\]\n]*\[*((?:\[[^\[\]]*\][\]\s]*)+)")
_TAG_CONTENT_RE = re.compile(r"[qQ][0-9]+")


def _has_hidden_tag(entry: str) -> bool:
    """True if a `[qN]`-shaped bracket appears within the entry's leading
    run of bracket groups — the mode bracket and (if present) the tag
    bracket that follows it, however malformed either one is — rather than
    later in the entry's own free-text summary. Catches every way a tag can
    be hidden from `_parse_decision_entry` while still being unambiguously
    tag-shaped: a malformed or empty mode bracket ("- t t [] [q1] ..." — an
    empty bracket isn't `[^\\]]+`, so the whole line fails DECISION_ENTRY_RE
    and `_check_decisions_shape` would otherwise skip it via `if not parsed:
    continue`), an unknown mode, any run of whitespace between the mode
    bracket and the tag bracket, no space after the tag's closing "]", case
    variation ("[Q1]"), internal whitespace inside the tag's own brackets
    ("[ q1 ]"), an extra or missing whitespace-separated token before the
    mode bracket ("- 2000-01-01 00:00 extra [debate] [q1] ..." — a third
    token where DECISION_ENTRY_RE's fixed "\\S+ \\S+ " expects exactly two),
    a stray extra closing bracket inside or after the mode bracket
    ("[debate]] [q1] ..." — DECISION_ENTRY_RE's `[^\\]]+` mode-bracket
    content stops at the first "]", so the entry fails to parse at all, and
    a naive "one bracket group, then whitespace, then the next" adjacency
    check would also fail here since the stray "]" isn't whitespace), and a
    missing mode bracket entirely ("- 2000-01-01 00:00 [q1] round 1, ..." —
    DECISION_ENTRY_RE reads "[q1]" itself as the mode bracket, an unknown
    mode with no adjacent tag bracket that any narrower "tag right after the
    mode bracket" check would miss), and a stray extra OPENING bracket
    before the mode bracket ("- 2000-01-01 00:00 [[debate] [q1] ..." —
    DECISION_ENTRY_RE's mode-bracket content (`[^\\]]+`, no `[` excluded)
    reads the mode as the literal string "[debate" including the stray "[",
    an unknown mode with no bracket group at all for `_BRACKET_GROUP_RE` to
    find until the run's leading stray-"[" tolerance skips past it). Scans
    by bracket-group *sequence* within the leading run, not a fixed
    character-offset cutoff: an offset bound would also match real prose
    containing a `[qN]`-shaped bracket within roughly the first 40
    characters of a line (e.g. a `solo` entry's own summary discussing
    question tags), which is not a hidden tag at all. Bounding to the
    leading *bracket run* (stopping at the first non-bracket, non-whitespace
    content) keeps detection anchored to "adjacent to the mode bracket
    position," the same principle used everywhere else in this check,
    without being fooled by real prose elsewhere in the entry — for example
    a free-text mode entry and a `solo` entry that mentions `[q1]` later in
    its own prose (both correctly not flagged) and against a citation-style "[abc][q1]" deeper
    in real prose (also correctly not flagged, since it's not part of the
    line's leading run at all)."""
    m = _LEADING_BRACKET_RUN_RE.match(entry)
    if not m:
        return False
    return any(_TAG_CONTENT_RE.fullmatch(g[1:-1].strip())
               for g in _BRACKET_GROUP_RE.findall(m.group(1)))
AMENDMENT_RE = re.compile(r"\AAMENDMENT (\S+):")
UNAMENDABLE_FIELDS = {"session_dir"}
# Amendments an engine command writes itself, with the command that does.
ENGINE_OWNED_AMENDMENTS = {"state_machine": "task state amend"}
# The only two valid shapes for a --mode debate summary, per debate/SKILL.md's
# "Recording" — a round entry ("round N, party '<role>': <content>") or the
# closing unanimous_convergence: outcome. Enforced so an ordinary round's free
# text can never accidentally start with "unanimous_convergence:" and get
# treated as the closing entry it isn't. Requires the quoted role and colon
# the documented shape actually specifies (not just "round N, party ", which
# would also match a role written without quotes or with no separator at
# all), and requires at least one non-space character after the colon so an
# empty position/response can't pass as a real round entry. The role uses
# `.+?` (non-greedy, matching the shortest span up to the first "':" that
# lets the rest of the pattern also match), not `[^']+` — a role containing
# its own apostrophe (e.g. a custom role literally named "reviewer's role",
# which execute's shape check for debate_parties permits, since it only
# requires role to be non-empty) would otherwise never match at all, since
# `[^']+` stops at that role's own internal apostrophe rather than the
# closing quote. `N` (the round number) is restricted to ASCII digits and
# includes 0 — round 0 is the scoping phase (topic/scope/principles/cutoff,
# independent-then-discuss), closed by a `scope-settled` entry before any
# round 1+ substance entry is legal; see debate/SKILL.md's "Round 0:
# scoping". Captured (not just shape-checked) so cmd_record_decision can
# enforce the round-sequencing rule below.
ROUND_ENTRY_RE = re.compile(r"\Around (?P<round>[0-9][0-9]*), party '.+?':\s*\S")


def _command(rest: str) -> str:
    """A runnable `task` command line for a `next:` step."""
    return f"{os.environ.get(ENV_PROG) or PROG} {rest}"


def _ledger_args(run_id: str, path: Path) -> str:
    return f"{run_id} --dir {shlex.quote(str(path.parent))}"


def _malformed(path: Path, problems: list[tuple[str, str]]) -> None:
    if problems:
        refuse(f"malformed ledger at {path}: {len(problems)} problem(s)", problems)


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def _check_run_id(run_id: str) -> None:
    if not RUN_ID_RE.match(run_id) or ".." in run_id:
        sys.exit(f"invalid run-id '{run_id}' — letters, digits, '.', '_', '-' only, "
                  f"no path separators, no trailing newline")


def _ledger_path(run_id: str, base: Path | None = None) -> Path:
    _check_run_id(run_id)
    return (base or DEFAULT_DIR).resolve() / f"{run_id}.md"


def _read_text(path: Path) -> str:
    if not path.exists():
        sys.exit(f"no ledger at {path} — run `init` first")
    text = path.read_text()
    # Structure first: with a missing or duplicated heading the section
    # spans the other checks read are unreliable.
    _malformed(path, _check_structure(text))
    _malformed(path, _check_decisions_shape(text) + _check_todos_shape(text))
    return text


def _check_open(text: str, path: Path) -> None:
    # The heading's mere presence means closed, not just a non-empty body —
    # `close` always writes a body, so an empty `## closed` heading only
    # exists via hand-editing; treating it as still-open would let `close`
    # run again and append a second `## closed` heading, which
    # `_check_structure` then refuses to read at all, permanently.
    if _heading_re("closed").search(text) is not None:
        sys.exit(f"{path} is closed — no further writes accepted")


def _check_structure(text: str) -> list[tuple[str, str]]:
    """Every required section heading must appear exactly once, in the
    fixed order `init` writes them, before any command reads or writes the
    ledger. Presence alone isn't enough — a duplicated or reordered heading
    (e.g. hand-edited, or two '## todos') would let `_section_span` bind to
    the wrong occurrence and silently drop or misplace content on either
    side of it. Returns every (kind, item) problem found; none means sound."""
    problems: list[tuple[str, str]] = []
    positions = []
    for name in SECTIONS:
        matches = list(_heading_re(name).finditer(text))
        if not matches:
            problems.append(("missing section", f"'## {name}'"))
            continue
        if len(matches) > 1:
            problems.append(("duplicated section", f"'## {name}' ×{len(matches)}"))
        positions.append(matches[0].start())
    if positions != sorted(positions):
        problems.append(("sections out of order", f"expected {', '.join(SECTIONS)}"))
    closed = list(_heading_re("closed").finditer(text))
    if len(closed) > 1:
        problems.append(("bad closed heading", f"'## closed' ×{len(closed)}"))
    state = _heading_re(SECTIONS[-1]).search(text)
    if closed and state is not None and closed[0].start() < state.start():
        problems.append(("bad closed heading",
                         f"'## closed' must come after '## {SECTIONS[-1]}'"))
    if state is not None:
        machines = list(_heading_re(MACHINES_SECTION).finditer(text, state.end()))
        if len(machines) > 1:
            problems.append(("duplicated section",
                             f"'## {MACHINES_SECTION}' ×{len(machines)}"))
        if machines and closed and closed[0].start() < machines[0].start():
            problems.append(("bad closed heading",
                             f"'## closed' must come after '## {MACHINES_SECTION}'"))
    return problems


# A heading line is "## <name>" alone on its line, at column 0 — a section
# body line that merely starts with "## " (e.g. a markdown sub-heading inside
# a decision's own text) does not match, since it requires the exact known
# section name and a line boundary on both sides.
def _heading_re(name: str) -> re.Pattern:
    return re.compile(rf"(?m)^## {re.escape(name)}\s*$")


def _any_heading_re(extra: tuple[str, ...] = ()) -> re.Pattern:
    names = "|".join(re.escape(n) for n in SECTIONS + ["closed", *extra])
    return re.compile(rf"(?m)^## (?:{names})\s*$")


def _machines_heading(text: str) -> re.Match | None:
    """The `## machines` heading, searched only after `## state`."""
    state = _heading_re(SECTIONS[-1]).search(text)
    if state is None:
        return None
    return _heading_re(MACHINES_SECTION).search(text, state.end())


def _section_span(text: str, name: str) -> tuple[int, int]:
    """Start/end character offsets of a section's body (after its heading
    line). An absent `## closed` or `## machines` spans the empty end of the
    text."""
    if name == MACHINES_SECTION:
        match = _machines_heading(text)
    else:
        match = _heading_re(name).search(text)
    if match is None:
        if name in ("closed", MACHINES_SECTION):
            return len(text), len(text)
        sys.exit(f"malformed ledger: missing '## {name}' section")
    body_start = match.end() + 1
    rest = text[body_start:]
    after_state = name in (SECTIONS[-1], MACHINES_SECTION)
    next_heading = _any_heading_re((MACHINES_SECTION,) if after_state else ()).search(rest)
    body_end = body_start + (next_heading.start() if next_heading else len(rest))
    return body_start, body_end


def _section_body(text: str, name: str) -> str:
    start, end = _section_span(text, name)
    return text[start:end]


def _append_to_section(text: str, name: str, line: str) -> str:
    """Append a line to a section, normalizing to: one blank line after the
    heading (if any content follows it), entries with no blank lines between
    them, then exactly one blank line before the next heading.

    `text[:head_end]` always ends with the heading's own line plus exactly
    one blank line (that's how `init` writes every empty section, and how
    this function leaves it too) — so that blank line must not be
    re-added here, only the entries and the single blank line that follows
    them before whatever comes next."""
    head_end, end = _section_span(text, name)
    entries = [e for e in text[head_end:end].strip("\n").split("\n") if e.strip()]
    entries.append(line)
    body = "\n".join(entries) + "\n"
    if end < len(text):
        body += "\n"
    return text[:head_end] + body + text[end:]


def _write_atomic(path: Path, text: str) -> None:
    """Write via a fresh, unpredictable temp file in the same directory, then
    rename over the target. A fixed <name>.tmp path lets anything that can
    place a symlink there first redirect the write outside the ledger
    directory; mkstemp's random name and O_EXCL close that off."""
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                     dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _check_no_embedded_heading(body: str, label: str) -> None:
    if _any_heading_re((MACHINES_SECTION,)).search(body):
        sys.exit(f"{label} contains a line that reads as a ledger section "
                  f"heading (e.g. '## todos' or '## closed') on its own —"
                  f" rename or rephrase that line so it isn't mistaken for "
                  f"real ledger structure")


TASK_TYPES = {"ticket-writing", "bug-triage", "ticket-to-pr", "pr-review"}
ENGINE_SKILLS = {"clarify", "execute", "resolve", "debate", "recall"}
SKILL_FIELDS = ("spec_skill", "test_skill", "review_skill")
# Claude Code dispatches a debate party as a sub-agent or through the advisor
# skill; the Codex port accepts native_subagent only.
PARTY_MECHANISMS = ("advisor", "native_subagent")
# Fields a `debate_party_config.parties.<id>` entry may carry in settlement.
PARTY_CONFIG_FIELDS = frozenset({"label", "prompt", "mechanism", "enabled"})


def _validate_settlement(body: str, run_id: str, session_dir: Path, *, strict: bool) -> tuple[list[tuple[str, str]], dict]:
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
        "consented_stop_allowed", "debate_party_config", *SKILL_FIELDS,
        "debate_roster", "review_fix_mode", "autonomy", "goal", "state_machine",
        "session_dir",
    }
    if strict:
        for field in sorted(required - data.keys()):
            problems.append((field, "is required for strict execution validation"))

    def text_field(field: str, *, required_field: bool = False) -> None:
        value = data.get(field)
        if value is None:
            return
        if not isinstance(value, str) or not value.strip():
            problems.append((field, "must be a non-empty string"))

    task_type = data.get("task_type")
    if task_type is not None and task_type not in TASK_TYPES:
        problems.append(("task_type", f"must be one of: {', '.join(sorted(TASK_TYPES))}"))
    for field in ("request_assessment", "approach", "principles", "debate_threshold"):
        text_field(field, required_field=strict)

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
    for field in ("spec_override", "test_override", "review_override"):
        if field in data:
            skill_value(field, override=True)

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
                    if not isinstance(config, dict):
                        problems.append((f"debate_party_config.parties.{party_id}", "must be a mapping"))
                        continue
                    if set(config) - PARTY_CONFIG_FIELDS:
                        problems.append((f"debate_party_config.parties.{party_id}", "contains unsupported fields"))
                    if any(not isinstance(value, (str, bool)) for value in config.values()):
                        problems.append((f"debate_party_config.parties.{party_id}", "values must be strings or booleans"))
                    if "mechanism" in config and config["mechanism"] not in PARTY_MECHANISMS:
                        problems.append((f"debate_party_config.parties.{party_id}.mechanism",
                                         "must be one of: " + ", ".join(PARTY_MECHANISMS)))

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
            if strict and autonomy.get("no_further_questions") is not True:
                problems.append(("autonomy.no_further_questions", "must be true"))
            mutations = autonomy.get("permitted_mutations")
            if strict and (not isinstance(mutations, list) or not mutations or
                           any(not isinstance(item, str) or not item.strip() for item in mutations)):
                problems.append(("autonomy.permitted_mutations", "must be a non-empty list of specific actions"))
            if isinstance(mutations, list) and any(item.strip().lower() == "go ahead autonomously" for item in mutations if isinstance(item, str)):
                problems.append(("autonomy.permitted_mutations", "must name specific actions"))

    goal = data.get("goal")
    if strict and goal is not None:
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
            try:
                machine = yaml.safe_load(machine_value)
            except yaml.YAMLError as exc:
                problems.append(("state_machine", f"invalid YAML: {exc}"))
            else:
                if strict and not isinstance(machine, dict):
                    problems.append(("state_machine", "must contain a YAML mapping"))
                elif strict:
                    from engine import state
                    problems.extend(("state_machine", problem) for problem in state.validate(machine))

    machine_name = machine.get("name") if isinstance(machine, dict) else None
    return problems, {
        "task_type": data.get("task_type"),
        "session_dir": data.get("session_dir"),
        "state_machine": machine_name,
        "fields": sorted(data),
    }


def cmd_init(args: argparse.Namespace) -> None:
    """`_init`, with an unreadable settlement or unusable `--dir` refused."""
    try:
        _init(args)
    except (OSError, UnicodeError) as e:
        sys.exit(f"cannot init {_ledger_path(args.run_id, args.dir)}: {e}")


def _init(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    resolved_dir = str(path.parent)
    if "\n" in resolved_dir or "\r" in resolved_dir:
        sys.exit(f"resolved ledger directory contains a line break: {resolved_dir!r} — "
                 f"refusing to write it into the settlement as `session_dir:`, since an "
                 f"embedded newline there would corrupt the ledger's line-based structure "
                 f"(e.g. read as a spurious extra field or heading-like line); pass a "
                 f"--dir with no newline in it")
    if path.exists() and not args.force:
        sys.exit(f"{path} already exists — settlement is written once; "
                  f"pass --force only to intentionally start over")
    path.parent.mkdir(parents=True, exist_ok=True)
    settlement = Path(args.settlement_file).read_text().rstrip("\n") \
        if args.settlement_file else sys.stdin.read().rstrip("\n")
    _check_no_embedded_heading(settlement, "the settlement")
    # session_dir must be the absolute directory this exact process resolved
    # `--dir` to (path.parent), not a value the caller guessed or computed in
    # a separate command that might have run from a different working
    # directory. Inserting it here, in the same process that just resolved
    # the path, removes that dependency entirely instead of relying on two
    # separate steps agreeing by convention. A caller-supplied `session_dir:`
    # line at column 0 is replaced, not merely trusted, since a stale or
    # wrong value would otherwise silently survive. Matching only at column
    # 0 (not an indented line that merely contains this text inside some
    # other field's own free-text value) is a deliberate, narrow choice: the
    # settlement has no other structural anchor to tell a real top-level
    # field apart from incidental text, and the correct line is always the
    # last one appended below regardless, so a stray indented match is
    # harmless even if left unremoved.
    settlement_lines = [
        line for line in settlement.split("\n")
        if not line.startswith("session_dir:")  # column 0 only, not indented
    ]
    settlement_lines.append(f"session_dir: {resolved_dir}")
    settlement = "\n".join(settlement_lines)
    problems, _ = _validate_settlement(settlement, args.run_id, path.parent, strict=False)
    if problems:
        refuse(f"session init refused for {path}: {len(problems)} problem(s)", problems)
    text = (
        f"# session: {args.run_id} — {datetime.now().astimezone().strftime('%Y-%m-%d')}\n\n"
        f"## settlement\n{settlement}\n\n"
        f"## decisions\n\n"
        f"## todos\n\n"
        f"## pitches\n\n"
        f"## state\ncurrent: {START_NODE}\nstarted: {_now()}\n"
    )
    _write_atomic(path, text)
    emit(args.output_mode, {"path": str(path)}, f"INIT     {path}")


def cmd_validate(args: argparse.Namespace) -> None:
    _check_run_id(args.run_id)
    source = Path("<ledger>")
    try:
        if args.settlement_file:
            source = args.settlement_file
            body = source.read_text().rstrip("\n")
            expected_dir = (args.dir or DEFAULT_DIR).resolve()
        else:
            path = _ledger_path(args.run_id, args.dir)
            source = path
            body = _section_body(_read_text(path), "settlement")
            expected_dir = path.parent
    except (OSError, UnicodeError) as exc:
        sys.exit(f"cannot validate {source}: {exc}")
    problems, summary = _validate_settlement(body, args.run_id, expected_dir, strict=True)
    if problems:
        refuse(f"session validate refused for {source}: {len(problems)} problem(s)", problems)
    emit(args.output_mode, {"run_id": args.run_id, "valid": True, "fields": summary},
         f"VALID    {args.run_id} fields={', '.join(summary['fields'])}")


def _lines(body: str) -> list[str]:
    return [line for line in body.split("\n") if line.strip()]


def _state_fields(body: str) -> dict:
    current = CURRENT_LINE_RE.search(body)
    started = STARTED_LINE_RE.search(body)
    transitions = [
        {"at": m.group("at"), "from": m.group("from"), "to": m.group("to"), "line": line}
        for line in body.split("\n") if (m := TRANSITION_LINE_RE.match(line))
    ]
    return {"current": current.group("node") if current else None,
            "started": started.group("at") if started else None,
            "transitions": transitions}


def cmd_read(args: argparse.Namespace) -> None:
    modes = [name for name, on in
             (("--section", args.section), ("--open-only", args.open_only),
              ("--last", args.last is not None),
              ("--question", args.question is not None)) if on]
    if len(modes) > 1:
        sys.exit(f"{' and '.join(modes)} are mutually exclusive — pick one")
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    if args.question is not None:
        if not QUESTION_ID_RE.match(args.question):
            sys.exit(f"--question '{args.question}' must look like 'q1', 'q2', ...")
        entries = []
        for e in _section_body(text, "decisions").strip("\n").split("\n"):
            if not e.strip():
                continue
            parsed = _parse_decision_entry(e)
            if parsed and parsed[1] == args.question:
                entries.append(e)
        emit(args.output_mode,
             {"run_id": args.run_id, "question": args.question, "decisions": entries},
             "\n".join(entries) if entries else f"(no decisions tagged {args.question})")
        return
    if args.open_only:
        todos = [e for e in _section_body(text, "todos").strip("\n").split("\n")
                 if e.strip().startswith("- [ ]")]
        emit(args.output_mode, {"run_id": args.run_id, "open_todos": todos},
             "\n".join(todos) if todos else "(no open todos)")
        return
    if args.last is not None:
        if args.last < 1:
            sys.exit("--last must be a positive integer")
        data: dict = {"run_id": args.run_id}
        prose = []
        for name in ("decisions", "pitches"):
            entries = [e for e in _section_body(text, name).strip("\n").split("\n")
                       if e.strip()]
            tail = entries[-args.last:]
            data[name], data[f"{name}_total"] = tail, len(entries)
            prose.append(f"-- {name} (last {len(tail)}/{len(entries)}) --")
            prose.append("\n".join(tail) if tail else "(none)")
        emit(args.output_mode, data, prose)
        return
    if args.section:
        body = _section_body(text, args.section)
        data = {"run_id": args.run_id, "section": args.section, "lines": _lines(body)}
        if args.section == "state":
            data |= _state_fields(body)
        prose = body.strip("\n")
        if args.section == MACHINES_SECTION and not prose:
            prose = "(none)"
        emit(args.output_mode, data, prose)
    else:
        closed = _heading_re("closed").search(text)
        emit(args.output_mode, {
            "run_id": args.run_id,
            "title": text.split("\n", 1)[0].removeprefix("# "),
            "sections": {name: _lines(_section_body(text, name))
                         for name in [*SECTIONS, MACHINES_SECTION]},
            "closed": _section_body(text, "closed").strip() if closed else None,
        }, text.strip("\n"))


def _has_content_after_prefix(summary: str, prefix: str) -> bool:
    """True only if `summary` starts with `prefix` and something more than
    whitespace follows it — a closing summary that is just the bare prefix
    (e.g. "round_cap:" with nothing after it) carries none of the required
    content (question, tie-break, dissent, ...) and must not pass as a real
    closing entry."""
    return summary.startswith(prefix) and bool(summary[len(prefix):].strip())


def _single_line(value: str, label: str) -> str:
    if "\n" in value or "\r" in value:
        sys.exit(f"{label} cannot contain a line break — the ledger is one "
                  f"entry per line; split multi-point content across "
                  f"separate calls instead")
    value = value.strip()
    if not value:
        sys.exit(f"{label} cannot be blank")
    return value


def _parse_decision_entry(entry: str) -> tuple[str, str, str] | None:
    """Returns (mode, question_or_empty, summary) for one decision line, or
    None if it doesn't match the format record-decision writes. A [qN] tag
    is only ever recognized when the entry's actual mode is a debate mode —
    free text in a solo/resolve summary that happens to start with "[qN] "
    is never treated as a real tag."""
    m = DECISION_ENTRY_RE.match(entry)
    if not m:
        return None
    mode, rest = m.group("mode"), m.group("rest")
    if mode in DEBATE_MODES:
        tag = QUESTION_TAG_RE.match(rest)
        if tag:
            return mode, tag.group(1), rest[tag.end():]
    return mode, "", rest


def _existing_question_ids(text: str) -> set[str]:
    body = _section_body(text, "decisions")
    ids = set()
    for entry in body.strip("\n").split("\n"):
        if not entry.strip():
            continue
        parsed = _parse_decision_entry(entry)
        if parsed and parsed[1]:
            ids.add(parsed[1])
    return ids


def _is_closing_entry(mode: str, summary: str) -> bool:
    """debate-capped/debate-degraded are closing-only modes; debate is used
    for both in-progress rounds and the unanimous_convergence closing
    outcome, distinguished by the recording convention in debate/SKILL.md's
    "Recording" (a closing summary starts with its outcome name, a round
    entry starts with "round N"). `scope-settled` is deliberately excluded
    here: it closes only the round-0 scoping phase, not the question itself
    — round 1+ substance entries and the question's real close still follow
    it. See `_has_scope_settled`, the parallel check for that narrower
    meaning."""
    if mode in ("debate-capped", "debate-degraded"):
        return True
    if mode == "debate":
        return summary.startswith("unanimous_convergence:")
    return False


def _has_closing_entry(text: str, question: str) -> bool:
    for e in _section_body(text, "decisions").strip("\n").split("\n"):
        if not e.strip():
            continue
        parsed = _parse_decision_entry(e)
        if not parsed:
            continue
        mode, qid, summary = parsed
        if qid == question and _is_closing_entry(mode, summary):
            return True
    return False


def _has_scope_settled(text: str, question: str) -> bool:
    """True once `question`'s round-0 scoping phase has a `scope-settled`
    close — the gate that makes a round 1+ substance entry legal. See
    debate/SKILL.md's "Round 0: scoping"."""
    for e in _section_body(text, "decisions").strip("\n").split("\n"):
        if not e.strip():
            continue
        parsed = _parse_decision_entry(e)
        if not parsed:
            continue
        mode, qid, _summary = parsed
        if qid == question and mode == "scope-settled":
            return True
    return False


def _open_question_ids(text: str) -> set[str]:
    return {q for q in _existing_question_ids(text) if not _has_closing_entry(text, q)}


def _max_recorded_round(text: str, question: str) -> int | None:
    """Highest round number any entry already tagged `question` has
    recorded, or None if none yet (i.e. this would be the question's first
    entry). Returns an Optional, not a bare int defaulting to 0, because 0
    is now a real, legal round number (the scoping phase) — collapsing
    "no rounds recorded" and "round 0 recorded" onto the same sentinel
    value would make a genuine round-0 entry indistinguishable from an
    empty question, silently breaking the first-entry and monotonicity
    checks below."""
    highest = None
    for e in _section_body(text, "decisions").strip("\n").split("\n"):
        if not e.strip():
            continue
        parsed = _parse_decision_entry(e)
        if not parsed or parsed[1] != question:
            continue
        m = ROUND_ENTRY_RE.match(parsed[2])
        if m:
            round_n = int(m.group("round"))
            highest = round_n if highest is None else max(highest, round_n)
    return highest


def _next_question_id(text: str) -> str:
    """The next id `next-question-id` would mint: q1, or the first gap-free
    successor after every id already used. Ids are minted strictly in this
    sequence — `cmd_record_decision` rejects any --question naming a
    genuinely new id (one with no existing entry yet) that isn't this exact
    value, so a ledger can never contain q1 and q3 with no q2, nor start at
    q0 or any other non-sequential value."""
    existing = _existing_question_ids(text)
    n = 1
    while f"q{n}" in existing:
        n += 1
    return f"q{n}"


def cmd_next_question_id(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    open_ids = _open_question_ids(text)
    if open_ids:
        sys.exit(f"question(s) {', '.join(sorted(open_ids))} have no closing entry yet — "
                 f"resume the open debate (see recall/SKILL.md) instead of starting a new "
                 f"one; a second open question makes recall's 'last [qN] tag' resumption "
                 f"rule ambiguous and strands the first")
    question = _next_question_id(text)
    emit(args.output_mode, {"question": question}, question,
         _command(f"session record-decision {_ledger_args(args.run_id, path)} --mode debate "
                  f"--question {question} --summary \"round 0, party '<role>': "
                  f"<topic, scope, principles, cutoff>\""))


def _validate_decision_shape(mode: str, question: str | None, summary: str) -> list[str]:
    """Returns every error message for the ways `mode`/`question`/`summary`
    don't form one of the shapes `cmd_record_decision` allows writing; empty
    if they do.
    Called only from `cmd_record_decision`, never from `cmd_record_pitch` —
    a pitch is a progress report, not a shaped ledger entry, so none of
    these rules apply to it.

    Not shared with `_check_decisions_shape` (the read-time re-check) —
    that function re-implements its own narrower subset of these rules
    inline instead of calling this one, so a rule added here only applies
    at write time until `_check_decisions_shape` is updated to match. A
    hand-edited or otherwise corrupted historical entry that violates a
    rule only enforced here passes every later read unnoticed, the same
    corruption `_check_decisions_shape`'s own docstring warns against for
    the rules it does re-check."""
    problems: list[str] = []
    if question is not None and not QUESTION_ID_RE.match(question):
        problems.append(f"--question '{question}' must look like 'q1', 'q2', ... — "
                        f"get one with `next-question-id`, don't invent your own")
    if mode in DEBATE_MODES and question is None:
        problems.append(f"--mode {mode} requires --question <id> — every debate "
                        f"round and its closing entry must share one stable id so "
                        f"recall (and a later debate on a different question) can "
                        f"tell them apart without scanning free text; get the id "
                        f"with `next-question-id` when starting a new debate, or "
                        f"reuse the id already used for this one")
    if mode not in DEBATE_MODES and question is not None:
        problems.append(f"--question is only for debate modes ({', '.join(sorted(DEBATE_MODES))}), "
                        f"not '{mode}'")
    if mode not in DEBATE_MODES and _has_hidden_tag(f"- ts ts [{mode}] {summary}"):
        problems.append(f"--mode {mode}'s summary starts with what looks like a '[qN]' "
                        f"question tag ('{summary}') — this is indistinguishable on disk "
                        f"from a debate entry hiding its tag (see `_has_hidden_tag`), and "
                        f"every later read/write would refuse the ledger over it; reword "
                        f"the summary so it doesn't open with a bracketed '[qN]'-shaped "
                        f"token, or use a real debate mode with --question if this is "
                        f"actually a tagged debate entry")
    if mode == "debate-capped" and not (
            _has_content_after_prefix(summary, "consented_stop:")
            or _has_content_after_prefix(summary, "round_cap:")):
        problems.append(f"--mode debate-capped closes a question and must have a summary "
                        f"starting with 'consented_stop:' or 'round_cap:', followed by the "
                        f"question, tie-break/CUT-voter detail, and dissent (see debate/SKILL.md's "
                        f"\"Recording\") — got '{summary}'; a bare prefix with nothing after it is "
                        f"the same broken-entry case as no prefix at all, and an ordinary round "
                        f"entry must use --mode debate instead of debate-capped, or it would close "
                        f"the question on a non-closing message")
    if mode == "debate-degraded" and not _has_content_after_prefix(
            summary, "degraded_convergence:"):
        problems.append(f"--mode debate-degraded closes a question and must have a summary "
                        f"starting with 'degraded_convergence:', followed by the question, "
                        f"converged answer, unavailable party, and round count (see "
                        f"debate/SKILL.md's \"Recording\") — got '{summary}'; a bare prefix with "
                        f"nothing after it is the same broken-entry case as no prefix at all, and "
                        f"an ordinary round entry must use --mode debate instead of "
                        f"debate-degraded, or it would close the question on a non-closing message")
    if mode == "scope-settled" and not _has_content_after_prefix(
            summary, "scope_settled:"):
        problems.append(f"--mode scope-settled closes a question's round-0 scoping phase "
                        f"and must have a summary starting with 'scope_settled:', followed "
                        f"by the topic, scope, principles, cutoff, and any preserved "
                        f"dissent (see debate/SKILL.md's \"Round 0: scoping\") — got "
                        f"'{summary}'; a bare prefix with nothing after it is the same "
                        f"broken-entry case as no prefix at all")
    if (mode == "debate" and question is not None
            and not ROUND_ENTRY_RE.match(summary)
            and not _has_content_after_prefix(summary, "unanimous_convergence:")):
        problems.append(f"--mode debate with --question must have a summary starting with "
                        f"\"round N, party '<role>': <content>\" or 'unanimous_convergence:' "
                        f"followed by the question, agreed answer, and round count (see "
                        f"debate/SKILL.md's \"Recording\") — got '{summary}'; free text that "
                        f"happens to start with 'unanimous_convergence:' would otherwise close "
                        f"the question on an ordinary round entry, and a bare prefix with "
                        f"nothing after it is the same broken-entry case as no prefix at all")
    return problems


def _check_decisions_shape(text: str) -> list[tuple[str, str]]:
    """Re-check that every question-tagged, closing-capable decisions entry
    genuinely has the required prefix content for its mode, and that
    question-id/round-number sequencing is intact, on every read — not only
    at the moment `cmd_record_decision` writes it. `_is_closing_entry`
    trusts a `debate-capped`/`debate-degraded` mode, or a `debate` mode
    summary starting with `unanimous_convergence:`, as meaning the tagged
    question is closed, without itself re-checking the prefix has real
    content after it. A hand-edited entry with the right mode bracket but a
    missing or bare prefix (e.g. `[debate-capped] [q1] bad`, no
    `round_cap:`/`consented_stop:`) would otherwise still parse as
    structurally valid and be silently trusted as a genuine close, stranding
    that question as permanently (and wrongly) closed with no record of
    what actually happened. Likewise, a hand-edited `[q3]` tag appearing with
    no prior `q1`/`q2` entry, or a round number that skips or goes backward,
    would otherwise be silently trusted by `_next_question_id`/
    `_max_recorded_round`, since both simply scan whatever tags and round
    numbers already exist on disk without checking they form a real
    sequence.

    Deliberately narrower than `_validate_decision_shape`'s full write-time
    check: only re-checks entries that carry a `[qN]` tag, since that's the
    only case `_is_closing_entry`/sequencing ever inspect a summary's prefix
    or round number for. Untagged entries (including `debate`-mode entries
    recorded before `--question` was a required argument, still present in
    older ledgers) are left alone — they predate today's shape rules and are
    not corruption, just history from before a rule was tightened;
    retroactively enforcing every current shape rule against them would
    break real, already-valid ledgers instead of only catching genuine
    corruption.

    Returns every (kind, item) problem in one scan; an entry with a problem
    is skipped for the sequencing state later entries are checked against."""
    problems: list[tuple[str, str]] = []

    def bad(kind: str, entry: str, detail: str) -> None:
        problems.append((kind, f"{entry!r}: {detail}"))

    seen_qids: set[str] = set()
    closed_qids: set[str] = set()
    max_round: dict[str, int] = {}
    scope_settled_qids: set[str] = set()
    for entry in _section_body(text, "decisions").split("\n"):
        if not entry.strip():
            continue
        parsed = _parse_decision_entry(entry)
        if not parsed:
            # The entry doesn't even match DECISION_ENTRY_RE's strict mode
            # bracket (e.g. an empty "[]"), so it fell through the mode
            # check above entirely — but a genuine [qN] tag can still
            # survive right after the malformed bracket (see
            # _has_hidden_tag), hiding it from every open/closed check the
            # same way an unknown-mode-plus-tag entry would.
            if _has_hidden_tag(entry):
                bad("hidden question tag", entry,
                    "this line doesn't match the expected '- <ts> [<mode>] "
                    "[qN] ...' shape at all (a malformed or empty mode "
                    "bracket), but its content starts with what looks like "
                    "a '[qN]' question tag right where a real tag would be "
                    "— an unparseable line hides that tag from every check "
                    "that depends on it")
            continue
        mode, qid, summary = parsed
        if mode not in ALL_MODES and _has_hidden_tag(entry):
            # An unknown --mode is tolerated on its own — legacy ledgers predate
            # --mode's fixed choice set and may carry free-text labels like
            # "[debate via other-tool]" with no
            # question tag at all, which is real history, not corruption.
            # What's never tolerated is an unknown mode WITH what looks like
            # a [qN] tag in its content: `_parse_decision_entry` only ever
            # recognizes a tag when mode is already a real debate mode, so a
            # bogus mode is otherwise a way to hide a question tag from every
            # open/closed check that depends on it, `close`'s guard against
            # ending the run with a debate still open included. Checked with
            # _has_hidden_tag (not the stricter QUESTION_TAG_RE against
            # DECISION_ENTRY_RE's own `rest` group) so extra whitespace
            # between the mode bracket and the tag bracket — which shifts
            # DECISION_ENTRY_RE's `rest` group to no longer start exactly at
            # "[qN]" — doesn't let the tag slip past this check too.
            bad("hidden question tag", entry,
                f"'{mode}' is not a real --mode value "
                f"({', '.join(sorted(ALL_MODES))}), but its content starts with "
                f"what looks like a '[qN]' question tag — an unknown mode hides "
                f"that tag from every check that depends on it")
            continue
        if not qid:
            # A genuinely untagged legacy entry is fine (see the module
            # docstring above) — but a real debate-mode entry whose tag
            # _has_hidden_tag still finds is not: QUESTION_TAG_RE (used by
            # `_parse_decision_entry` to extract `qid`) requires the tag
            # immediately after the mode bracket with no stray whitespace
            # before it, exact-case "q", no internal whitespace inside its
            # own brackets, and a trailing space after the tag's own closing
            # "]" — deviating in any of those ways (e.g. "[debate]   [q1]
            # ...", "[debate] [q1]round 1, ...", "[debate] [ q1 ] ...", or
            # "[debate] [Q1] ...") makes a real, currently-valid --mode entry
            # parse as untagged instead of failing outright, hiding it from
            # every open/closed check the same way an unparseable line or
            # unknown mode would. Checked regardless of mode (not gated to
            # DEBATE_MODES) since _has_hidden_tag's own adjacency requirement
            # already rules out matching unrelated prose.
            if _has_hidden_tag(entry):
                bad("hidden question tag", entry,
                    f"'{mode}' is a real --mode value, but its content starts "
                    f"with what looks like a '[qN]' question tag that isn't "
                    f"exactly the shape record-decision always writes — this "
                    f"entry would otherwise be silently treated as an untagged "
                    f"legacy entry, hiding its question tag from every check "
                    f"that depends on it")
            continue
        # A tagged entry that fails any check below is reported and then
        # contributes no state (seen/closed/round), so the scan continues.
        if qid not in seen_qids:
            n = 1
            while f"q{n}" in seen_qids:
                n += 1
            if qid != f"q{n}":
                bad("question id out of sequence", entry,
                    f"'{qid}' is the first entry tagging this question, but "
                    f"'q{n}' was expected next — question ids must appear in "
                    f"a gapless sequence starting at q1")
                continue
        if qid in closed_qids:
            bad("entry after close", entry,
                f"'{qid}' already has a closing entry earlier in the ledger — "
                f"a debate closes exactly once and records nothing more "
                f"against that question id, a duplicate or contradictory "
                f"closing entry included; `_has_closing_entry`/`recall`'s "
                f"last-[qN]-tag resumption both assume at most one close "
                f"per question")
            continue
        if mode == "scope-settled" and qid not in max_round:
            bad("scope-settled first", entry,
                f"'{qid}'s round-0 scoping phase has no entries yet — "
                f"scope-settled cannot be a question's first decision, "
                f"the round-0 phase (independent topic/scope/principles/"
                f"cutoff, then discuss) must actually happen first (see "
                f"debate/SKILL.md's \"Round 0: scoping\")")
            continue
        round_match = ROUND_ENTRY_RE.match(summary)
        prior_max = max_round.get(qid)
        if round_match is None and prior_max is None and mode != "scope-settled":
            bad("closing entry first", entry,
                f"'{qid}' has no round entry yet — a closing entry can't "
                f"be the first thing recorded against a question id")
            continue
        round_n = int(round_match.group("round")) if round_match is not None else None
        if round_n is not None:
            if prior_max is None and round_n != 0:
                bad("first round not 0", entry,
                    f"'{qid}'s first entry must be round 0 (the scoping "
                    f"phase), got round {round_n} — see debate/SKILL.md's "
                    f"\"Round 0: scoping\"")
                continue
            if prior_max is not None and round_n < prior_max:
                bad("round goes backward", entry,
                    f"round {round_n} is lower than round {prior_max} "
                    f"already recorded for '{qid}' — round numbers for a "
                    f"question never go backward")
                continue
            if round_n >= 1 and qid not in scope_settled_qids:
                bad("round before scope-settled", entry,
                    f"'{qid}' has a round {round_n} entry but no "
                    f"scope-settled close yet — round 1+ substance is not "
                    f"legal until the round-0 scoping phase closes (see "
                    f"debate/SKILL.md's \"Round 0: scoping\")")
                continue
        if mode == "debate-capped" and not (
                _has_content_after_prefix(summary, "consented_stop:")
                or _has_content_after_prefix(summary, "round_cap:")):
            bad("closing prefix missing", entry,
                f"tagged {qid} as --mode debate-capped but the summary "
                f"has no 'consented_stop:'/'round_cap:' prefix with real "
                f"content after it — this would be silently trusted as "
                f"a genuine close of {qid}, stranding it")
            continue
        if mode == "debate-degraded" and not _has_content_after_prefix(
                summary, "degraded_convergence:"):
            bad("closing prefix missing", entry,
                f"tagged {qid} as --mode debate-degraded but the summary "
                f"has no 'degraded_convergence:' prefix with real "
                f"content after it — this would be silently trusted as "
                f"a genuine close of {qid}, stranding it")
            continue
        if (mode == "debate"
                and not ROUND_ENTRY_RE.match(summary)
                and not _has_content_after_prefix(summary, "unanimous_convergence:")):
            bad("closing prefix missing", entry,
                f"tagged {qid} as --mode debate but the summary is "
                f"neither a 'round N, party ...' entry nor a genuine "
                f"'unanimous_convergence:' close — this entry's real "
                f"shape can't be determined, and {qid}'s open/closed "
                f"state depends on it")
            continue
        seen_qids.add(qid)
        if _is_closing_entry(mode, summary):
            closed_qids.add(qid)
        if mode == "scope-settled":
            scope_settled_qids.add(qid)
        if round_n is not None:
            max_round[qid] = round_n if prior_max is None else max(prior_max, round_n)
    still_open = seen_qids - closed_qids
    if len(still_open) > 1:
        # `record-decision` itself refuses to open a second question while
        # one is already open (see cmd_record_decision's own
        # _open_question_ids check), so this state is only reachable by
        # hand-editing a [qN] tag directly into the ledger — but a hand-edit
        # is exactly what the rest of this function already defends against.
        # Left unchecked, `recall`'s "last [qN] tag" resumption rule would
        # silently resume the wrong one of the two, and every other question
        # left open would go unnoticed until something else about it broke.
        problems.append(("several open questions", (
            f"{', '.join(sorted(still_open))} are all open with no closing "
            f"entry — at most one debate question may be open at a time "
            f"(`record-decision`/`next-question-id` both refuse to open a "
            f"second one; this can only have been hand-edited in), and "
            f"`recall`'s 'last [qN] tag' resumption rule has no defined "
            f"behavior for more than one")))
    return problems


def _check_todos_shape(text: str) -> list[tuple[str, str]]:
    """Re-check on every read that every todos-section entry has exactly the
    two checkbox states `update-todo` ever writes: `- [ ]` (open) or
    `- [x]` (done). Every
    todos entry is a checkbox — there's no freeform-note allowance in this
    section the way untagged legacy decisions entries get one in
    `_check_decisions_shape` — so a line that doesn't even start with `- [`
    is caught here too, not skipped as presumed-legitimate history; nothing
    ever legitimately writes one. A malformed checkbox (`- [y]`, `- []`,
    `- [xx]`, or no checkbox at all) is unusable either way — `read
    --open-only`'s filter only matches `- [ ]` exactly, so such an entry
    silently disappears from the open-todo view without being done either,
    and `update-todo`'s own `already_done` check only matches `- [x]`
    exactly, so it would treat the entry as open and rewrite its checkbox
    without ever surfacing that it was malformed to begin with. Checked
    against the whole line, not just its first 5 characters: `update-todo`
    always writes the checkbox, exactly one space, then the (non-empty,
    `_single_line`-checked) todo text — `- [ ]foo` (no space) and a bare
    `- [ ]`/`- [x]` (no text at all) are just as malformed as a wrong
    checkbox, and just as stuck: `update-todo` matches on `todo_text in e`
    to find a todo, so a bare checkbox with no text can never be matched by
    any `--done`/`--reopen` call, and `_single_line` refuses to record a
    blank text in the first place, leaving it permanently open. Returns
    one (kind, item) problem per malformed entry."""
    problems: list[tuple[str, str]] = []
    for entry in _section_body(text, "todos").split("\n"):
        stripped = entry.strip()
        if not stripped:
            continue
        if stripped[:6] not in ("- [ ] ", "- [x] ") or not stripped[6:].strip():
            problems.append(("bad todo checkbox", (
                f"{entry!r}: the checkbox isn't exactly '- [ ] ' or '- [x] ' "
                f"followed by non-empty text — not written by `update-todo`, or "
                f"hand-edited into a bad state")))
    return problems


def cmd_record_decision(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    summary = _single_line(args.summary, "--summary")
    # Every independent rule is checked and refused once, together. The
    # question-id rules only apply to a well-formed id under a debate mode
    # (anything else is already a shape problem).
    problems = _validate_decision_shape(args.mode, args.question, summary)
    question: str | None = args.question
    tagged = (question if args.mode in DEBATE_MODES and question is not None
              and QUESTION_ID_RE.match(question) else None)
    if tagged is not None:
        round_match = ROUND_ENTRY_RE.match(summary)
        prior_max = _max_recorded_round(text, tagged)
        if round_match is None and prior_max is None and args.mode != "scope-settled":
            problems.append(f"question {args.question} has no round entry yet — a closing "
                            f"entry ('{summary.split(':', 1)[0]}:') cannot be the first thing "
                            f"recorded against a question id; record round 0 first (see "
                            f"debate/SKILL.md's \"Round 0: scoping\")")
        if round_match is not None:
            round_n = int(round_match.group("round"))
            if prior_max is None and round_n != 0:
                problems.append(f"question {args.question}'s first entry must be 'round 0, "
                                f"party ...' — got round {round_n}; a question always opens "
                                f"with the round-0 scoping phase before round 1+ substance "
                                f"(see debate/SKILL.md's \"Round 0: scoping\")")
            if prior_max is not None and round_n < prior_max:
                problems.append(f"round {round_n} is lower than round {prior_max} already "
                                f"recorded for {args.question} — round numbers for a question "
                                f"never go backward; a party's late or retried position "
                                f"either repeats the current round number or moves forward to "
                                f"it, never an earlier one")
            if round_n >= 1 and not _has_scope_settled(text, tagged):
                problems.append(f"question {args.question} has a round {round_n} entry but no "
                                f"scope-settled close yet — round 1+ substance is not legal "
                                f"until the round-0 scoping phase closes (see "
                                f"debate/SKILL.md's \"Round 0: scoping\")")
        if args.mode == "scope-settled" and prior_max is None:
            problems.append(f"question {args.question}'s round-0 scoping phase has no "
                            f"entries yet — scope-settled cannot be a question's first "
                            f"decision, the round-0 phase must actually happen first (see "
                            f"debate/SKILL.md's \"Round 0: scoping\")")
    if tagged is not None and _has_closing_entry(text, tagged):
        problems.append(f"question {args.question} already has a closing entry — a debate "
                        f"closes exactly once and records nothing more against that question "
                        f"id, round entries included; if this is a retry after compaction, do "
                        f"not record anything more for this question")
    if tagged is not None and tagged not in _existing_question_ids(text):
        open_ids = _open_question_ids(text)
        if open_ids:
            problems.append(f"question(s) {', '.join(sorted(open_ids))} have no closing entry "
                            f"yet — get a new id with `next-question-id`, which refuses while "
                            f"one is open, instead of inventing '{args.question}' directly; a "
                            f"second open question strands the first from recall's 'last [qN] "
                            f"tag' resumption rule")
        expected = _next_question_id(text)
        if args.question != expected:
            problems.append(f"'{args.question}' is not the next question id — expected "
                            f"'{expected}'; get it with `next-question-id` instead of "
                            f"inventing one, so ids stay a gapless sequence starting at q1 "
                            f"and every id that exists on disk was actually minted here")
    amendment = AMENDMENT_RE.match(summary)
    if amendment:
        field = amendment.group(1)
        if args.mode != "solo":
            problems.append(f"an 'AMENDMENT {field}:' summary must use --mode solo — got "
                            f"'{args.mode}'; an amendment is a solo decision to change a "
                            f"settled field, not a debate/resolve outcome, even when a "
                            f"debate or resolve call prompted it")
        if field in ENGINE_OWNED_AMENDMENTS:
            problems.append(f"'{field}' cannot be amended with record-decision — "
                            f"`{ENGINE_OWNED_AMENDMENTS[field]}` validates the new "
                            f"value and records the amendment itself; run "
                            + _command(f"state amend {_ledger_args(args.run_id, path)} "
                                       f"--machine-file <file> --reason \"<why>\""))
        if field in UNAMENDABLE_FIELDS:
            problems.append(f"'{field}' cannot be recorded as an AMENDMENT — recall needs "
                            f"--dir to find the ledger before it can read anything out of "
                            f"it, including an amendment to the field that supplies --dir; "
                            f"a mid-run change to '{field}' needs a fresh clarify/init, not "
                            f"an amendment")
        rest = summary[amendment.end():]
        if rest.count(" -> ") != 1:
            problems.append(f"an 'AMENDMENT {field}:' summary must contain exactly one "
                            f"' -> ' separating the old value from the new one — got "
                            f"'{rest.strip()}' ({rest.count(' -> ')} found); neither "
                            f"value may contain that exact substring, paraphrase "
                            f"instead (e.g. 'becomes' or 'changes to')")
        else:
            old_val, new_val = rest.split(" -> ", 1)
            if not old_val.strip() or not new_val.strip():
                problems.append(f"an 'AMENDMENT {field}:' summary must have a non-empty "
                                f"value on both sides of ' -> ' — got "
                                f"old='{old_val.strip()}' new='{new_val.strip()}'")
    if problems:
        refuse(f"record-decision refused for {path}: {len(problems)} problem(s)",
               [("record-decision", p) for p in problems])
    tag = f"[{args.question}] " if args.question else ""
    line = f"- {_now()} [{args.mode}] {tag}{summary}"
    _write_atomic(path, _append_to_section(text, "decisions", line))
    next_step = None
    if args.mode == "scope-settled":
        next_step = _command(
            f"session record-decision {_ledger_args(args.run_id, path)} --mode debate "
            f"--question {args.question} --summary \"round 1, party '<role>': <position>\"")
    emit(args.output_mode, {"line": line}, "DECISION recorded", next_step)


def cmd_update_todo(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    todo_text = _single_line(args.text, "todo text")
    start, end = _section_span(text, "todos")
    entries = [e for e in text[start:end].strip("\n").split("\n") if e.strip()]
    candidates = [i for i, e in enumerate(entries)
                  if e.strip().startswith("- [") and todo_text in e]
    exact = [i for i in candidates
             if entries[i].strip().split("]", 1)[1].strip() == todo_text]
    if exact:
        candidates = exact
    if len(candidates) > 1:
        sys.exit(f"'{todo_text}' matches {len(candidates)} todos ambiguously — "
                  f"use more specific text")
    if candidates:
        i = candidates[0]
        already_done = entries[i].strip().startswith("- [x]")
        if already_done and not args.done and not args.reopen:
            sys.exit(f"'{todo_text}' is already marked done — pass --reopen "
                      f"to explicitly reopen it, or --done to confirm marking "
                      f"it done again")
        if args.reopen and not already_done:
            sys.exit(f"'{todo_text}' is already open — --reopen confirms "
                      f"reopening a todo that's currently marked done, not a "
                      f"no-op on one that already is open")
        mark = "x" if args.done else " "
        content = entries[i].strip().split("]", 1)[1].strip()
        entries[i] = f"- [{mark}] {content}"
    else:
        if args.done:
            sys.exit(f"no todo matching '{todo_text}' — cannot mark done a "
                      f"todo that was never added")
        if args.reopen:
            sys.exit(f"no todo matching '{todo_text}' — --reopen confirms "
                      f"reopening an existing done todo, not adding a new one; "
                      f"drop --reopen to add it as a new open todo")
        entries.append(f"- [ ] {todo_text}")
    body = "\n".join(entries) + "\n" if entries else ""
    if end < len(text):
        body += "\n"
    _write_atomic(path, text[:start] + body + text[end:])
    label = "done" if args.done else ("reopened" if candidates else "added")
    emit(args.output_mode, {"todo": todo_text, "status": label}, f"TODO     {label}")


def cmd_record_pitch(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    pitch_text = _single_line(args.text, "pitch text")
    line = f"- {_now()} — {pitch_text}"
    _write_atomic(path, _append_to_section(text, "pitches", line))
    emit(args.output_mode, {"line": line}, "PITCH    recorded")


def cmd_close(args: argparse.Namespace) -> None:
    if args.outcome == "failed" and not args.reason:
        sys.exit("close failed requires --reason — the goal's undoable "
                  "condition must be named, not left blank")
    path = _ledger_path(args.run_id, args.dir)
    text = _read_text(path)
    _check_open(text, path)
    open_ids = _open_question_ids(text)
    if open_ids:
        sys.exit(f"question(s) {', '.join(sorted(open_ids))} have no closing entry "
                 f"yet — resolve or close every open debate before closing the run; "
                 f"once closed, `session.py` refuses all further writes, so an open "
                 f"question left this way can never be closed at all")
    outcome = "succeeded" if args.outcome == "succeeded" else "failed"
    current = _state_fields(_section_body(text, "state"))["current"]
    if current is None:
        sys.exit(f"malformed ledger at {path}: '## state' has no 'current: "
                 f"<node>' line — not written by `init`, or hand-edited into a "
                 f"bad state")
    if current in ("succeeded", "failed") and current != outcome:
        close = f"session close {_ledger_args(args.run_id, path)} {current}"
        if current == "failed":
            close += ' --reason "<why the goal is undoable>"'
        sys.exit(f"close {outcome} refused: the run already ended at '{current}', "
                 f"a terminal node with no outgoing transition — run: "
                 f"{_command(close)}")
    if current != outcome:
        fix = _command(f"state transition {_ledger_args(args.run_id, path)} "
                       f"--to {outcome} --reason \"<why>\"")
        sys.exit(f"close {outcome} requires current state '{outcome}', but it is "
                 f"'{current}'; transition first — if '{current}' has no legal "
                 f"edge to '{outcome}', or needs --confirm-leave or --leave-arg, "
                 f"its refusal says what to add — run: {fix}")
    closing = f"\n## closed\n{_now()} — {outcome}"
    if args.reason:
        closing += f" — {_single_line(args.reason, '--reason')}"
    _write_atomic(path, text.rstrip("\n") + "\n" + closing + "\n")
    emit(args.output_mode, {"outcome": outcome}, f"CLOSED   {outcome}")


def add_subparsers(sub: argparse._SubParsersAction, dir_parent: argparse.ArgumentParser) -> None:
    s = sub.add_parser("init", parents=[dir_parent],
                        help="create a new ledger and write its settlement")
    s.add_argument("run_id")
    s.add_argument("--settlement-file", type=caller_path,
                   help="read settlement body from this file instead of stdin")
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing ledger for this run-id")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("validate", parents=[dir_parent],
                        help="validate an execution settlement without writing")
    s.add_argument("run_id")
    s.add_argument("--settlement-file", type=caller_path,
                   help="validate this settlement body instead of an existing ledger")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("read", parents=[dir_parent],
                        help="print a section, or the whole ledger")
    s.add_argument("run_id")
    s.add_argument("--section", choices=[*SECTIONS, MACHINES_SECTION],
                   help="print just this section, full history")
    s.add_argument("--open-only", action="store_true",
                   help="print only unchecked todos — the cheap common case "
                        "for 'what's left'")
    s.add_argument("--last", type=int, metavar="N",
                   help="print only the last N decisions and pitches, not "
                        "the full run history")
    s.add_argument("--question", metavar="QID",
                   help="print only decisions tagged with this debate question "
                        "id (e.g. 'q1') — use to resume one debate without "
                        "scanning the whole decisions section")
    s.set_defaults(func=cmd_read)

    s = sub.add_parser("record-decision", parents=[dir_parent],
                        help="append a decisions entry")
    s.add_argument("run_id")
    s.add_argument("--mode", required=True,
                   choices=["solo", "resolve", "debate", "debate-capped",
                            "debate-degraded", "scope-settled"],
                   help="how the decision was reached: solo (below threshold), "
                        "resolve (source-of-truth order), debate (roster "
                        "converged), debate-capped (round limit hit, main "
                        "agent tie-broke), debate-degraded (a party was "
                        "unavailable, fewer than the full roster responded), "
                        "scope-settled (closes a question's round-0 scoping "
                        "phase; round 1+ substance follows separately)")
    s.add_argument("--summary", required=True)
    s.add_argument("--question", metavar="QID",
                   help="stable id (e.g. 'q1') tying every round and the "
                        "closing entry of one debate together; required for "
                        "--mode debate/debate-capped/debate-degraded/"
                        "scope-settled, refused for any other mode — get one "
                        "from `next-question-id`")
    s.set_defaults(func=cmd_record_decision)

    s = sub.add_parser("update-todo", parents=[dir_parent],
                        help="add a todo, or toggle one done")
    s.add_argument("run_id")
    s.add_argument("text", help="the todo text (or a substring to match an "
                                 "existing one)")
    done_group = s.add_mutually_exclusive_group()
    done_group.add_argument("--done", action="store_true",
                   help="mark the matching todo done, instead of adding a new one")
    done_group.add_argument("--reopen", action="store_true",
                   help="confirm reopening a todo that's already marked done "
                        "(refused without this, to guard against an accidental "
                        "re-add silently undoing completed work); mutually "
                        "exclusive with --done, since marking done and "
                        "confirming a reopen are contradictory requests")
    s.set_defaults(func=cmd_update_todo)

    s = sub.add_parser("next-question-id", parents=[dir_parent],
                        help="print the next unused debate question id (q1, q2, ...)")
    s.add_argument("run_id")
    s.set_defaults(func=cmd_next_question_id)

    s = sub.add_parser("record-pitch", parents=[dir_parent],
                        help="append a pitches entry")
    s.add_argument("run_id")
    s.add_argument("text")
    s.set_defaults(func=cmd_record_pitch)

    s = sub.add_parser("close", parents=[dir_parent], help="mark the ledger closed")
    s.add_argument("run_id")
    s.add_argument("outcome", choices=["succeeded", "failed"])
    s.add_argument("--reason", help="required in practice for a failed outcome, "
                                     "naming what made the goal undoable")
    s.set_defaults(func=cmd_close)


def main() -> None:
    """`python -m engine.session` is `task session`, refusals included."""
    from engine import cli
    cli.main(["session", *sys.argv[1:]])


if __name__ == "__main__":
    main()
