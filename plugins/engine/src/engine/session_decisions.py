"""Record decisions and manage debate question IDs."""

from __future__ import annotations

import argparse
import re
import sys

from bootgear_cli.clikit import emit, refuse

from .session_decision_rules import (
    DEBATE_MODES,
    QUESTION_ID_RE,
    ROUND_ENTRY_RE,
    _is_closing_entry,
    _parse_decision_entry,
    _validate_decision_shape,
)
from .session_ledger import (
    _append_to_section,
    _check_open,
    _ledger_command,
    _ledger_path,
    _now,
    _read_text,
    _section_body,
    _single_line,
    _write_atomic,
)

AMENDMENT_RE = re.compile(r"\AAMENDMENT (\S+):")
UNAMENDABLE_FIELDS = {"session_dir", "task_folder"}
# Amendments an engine command writes itself, with the command that does.
ENGINE_OWNED_AMENDMENTS = {"state_machine": "task state amend"}


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
         _ledger_command("session record-decision", args.run_id, path,
                         f"--mode debate --question {question} --summary \"round 0, party '<role>': "
                         f"<topic, scope, principles, cutoff>\""))


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
                            + _ledger_command("state amend", args.run_id, path,
                                              "--machine-file <file> --reason \"<why>\""))
        if field == "task_folder":
            problems.append("task_folder cannot be recorded as an AMENDMENT; "
                            "the authoring folder is immutable for this run")
        elif field in UNAMENDABLE_FIELDS:
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
        next_step = _ledger_command(
            "session record-decision", args.run_id, path,
            f"--mode debate --question {args.question} --summary \"round 1, party '<role>': <position>\"")
    emit(args.output_mode, {"line": line}, "DECISION recorded", next_step)
