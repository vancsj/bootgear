#!/usr/bin/env python3
"""Command line for engine's session ledger.

One Markdown file per run, five fixed sections (settlement, decisions,
todos, pitches, state). This script is the only thing that ever writes it —
no skill's own Edit/Write calls should touch the file directly, so the
format can't drift the way free-form editing invites over a long,
many-compaction run.

    init              create a new ledger, write its settlement once
    read              print a section, or the whole file
    recall            print the settlement and recovery state together
    record-decision   append a decisions line
    next-question-id  print the next unused debate question id
    update-todo       toggle a todo's done state in place
    record-pitch      append a pitches line
    close             mark the ledger closed (succeeded or failed)
    write-ticket      write the run's ticket body; the only writer of ticket_path

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
import sys
from datetime import datetime
from pathlib import Path

from bootgear_cli.clikit import caller_cwd, caller_path, emit, refuse

from engine import session_paths
from engine.session_decisions import (
    _open_question_ids,
    cmd_next_question_id,
    cmd_record_decision,
)
from engine.session_ledger import (
    DEFAULT_DIR,
    MACHINES_SECTION,
    RUN_ID_HELP,
    SECTIONS,
    _append_to_section,
    _check_no_embedded_heading,
    _check_open,
    _check_run_id,
    _ledger_command,
    _ledger_path,
    _now,
    _outcome_operand,
    _read_text,
    _read_text_ledger,
    _run_id_command,
    _section_body,
    _section_span,
    _single_line,
    _text_operand,
    _write_atomic,
)
from engine.session_settlement import (  # noqa: F401
    TASK_TYPES,
    _artefact_review_problems,
    _bind_task_folder,
    _stored_owned_artifacts,
    _validate_settlement,
    _verb_owned_problems,
)
from engine.session_ticket import cmd_write_ticket
from engine.session_views import _state_fields, cmd_read, cmd_recall

START_NODE = "clarify"


def cmd_init(args: argparse.Namespace) -> None:
    """`_init`, with an unreadable settlement or unusable `--dir` refused."""
    try:
        _init(args)
    except (OSError, UnicodeError) as e:
        sys.exit(f"cannot init {_ledger_path(args.run_id, args.dir)}: {e}")


def _check_dir_line(resolved_dir: str) -> None:
    """Refuse a ledger directory that would break the `session_dir:` line."""
    if "\n" in resolved_dir or "\r" in resolved_dir:
        sys.exit(f"resolved ledger directory contains a line break: {resolved_dir!r} — "
                 f"refusing to write it into the settlement as `session_dir:`, since an "
                 f"embedded newline there would corrupt the ledger's line-based structure "
                 f"(e.g. read as a spurious extra field or heading-like line); pass a "
                 f"--dir with no newline in it")


def _bind_session_dir(settlement: str, resolved_dir: str) -> str:
    """Set the settlement's `session_dir:` to `resolved_dir`, replacing any column-0 value."""
    lines = [line for line in settlement.split("\n")
             if not line.startswith("session_dir:")]  # column 0 only, not indented
    lines.append(f"session_dir: {resolved_dir}")
    return "\n".join(lines)


def _init(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir)
    resolved_dir = str(path.parent)
    _check_dir_line(resolved_dir)
    if path.exists() and not args.force:
        sys.exit(f"{path} already exists — settlement is written once; "
                  f"pass --force only to intentionally start over")
    if path.exists() and (owned := _stored_owned_artifacts(path)):
        sys.exit(f"{path} lists owned artifacts ({', '.join(owned)}) — --force is refused, "
                 f"since it would drop the record that this run owns them; the ledger is "
                 f"unchanged, ask the user how to proceed")
    settlement = Path(args.settlement_file).read_text().rstrip("\n") \
        if args.settlement_file else sys.stdin.read().rstrip("\n")
    _check_no_embedded_heading(settlement, "the settlement")
    settlement = _bind_session_dir(settlement, resolved_dir)
    problems, summary = _validate_settlement(settlement, args.run_id, path.parent, caller_cwd())
    problems += _verb_owned_problems(summary)
    if problems:
        refuse(f"session init refused for {path}: {len(problems)} problem(s)", problems)
    settlement, task_folder = _bind_task_folder(settlement)
    try:
        if task_folder is not None:
            task_folder.mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.exit(f"cannot init {path}: directory setup failed: {exc}; no ledger was written")
    text = (
        f"# session: {args.run_id} — {datetime.now().astimezone().strftime('%Y-%m-%d')}\n\n"
        f"## settlement\n{settlement}\n\n"
        f"## decisions\n\n"
        f"## todos\n\n"
        f"## pitches\n\n"
        f"## state\ncurrent: {START_NODE}\nstarted: {_now()}\n"
    )
    registered_path = False
    try:
        registered_path = session_paths.register_session_path(
            args.run_id, path.parent, DEFAULT_DIR
        )
        try:
            _write_atomic(path, text)
        except BaseException:
            if registered_path:
                session_paths.unregister_session_path(args.run_id, path.parent, DEFAULT_DIR)
            raise
    except (OSError, session_paths.SessionPathError) as exc:
        sys.exit(f"cannot init {path}: {exc}; no ledger was written")
    emit(args.output_mode, {"path": str(path)}, f"INIT     {path}")


def cmd_validate(args: argparse.Namespace) -> None:
    _check_run_id(args.run_id)
    source = Path("<ledger>")
    try:
        if args.settlement_file:
            source = args.settlement_file
            body = source.read_text().rstrip("\n")
            expected_dir = (args.dir or DEFAULT_DIR).resolve()
            _check_dir_line(str(expected_dir))
            body = _bind_session_dir(body, str(expected_dir))
        else:
            path = _ledger_path(args.run_id, args.dir)
            source = path
            body = _section_body(_read_text(path), "settlement")
            expected_dir = path.parent
    except (OSError, UnicodeError) as exc:
        sys.exit(f"cannot validate {source}: {exc}")
    problems, summary = _validate_settlement(body, args.run_id, expected_dir, caller_cwd())
    if args.settlement_file:
        problems += _verb_owned_problems(summary)
    if problems:
        refuse(f"session validate refused for {source}: {len(problems)} problem(s)", problems)
    emit(args.output_mode, {"run_id": args.run_id, "valid": True, "fields": summary},
         f"VALID    {args.run_id} fields={', '.join(summary['fields'])}")


def cmd_update_todo(args: argparse.Namespace) -> None:
    path = _ledger_path(args.run_id, args.dir, text_operand=True)
    text = _read_text_ledger(path, args.run_id)
    _check_open(text, path)
    todo_text = _single_line(_text_operand(args), "todo text")
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
    path = _ledger_path(args.run_id, args.dir, text_operand=True)
    text = _read_text_ledger(path, args.run_id)
    _check_open(text, path)
    pitch_text = _single_line(_text_operand(args), "pitch text")
    line = f"- {_now()} — {pitch_text}"
    _write_atomic(path, _append_to_section(text, "pitches", line))
    emit(args.output_mode, {"line": line}, "PITCH    recorded")


def cmd_close(args: argparse.Namespace) -> None:
    args.outcome = _outcome_operand(args)
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
        close = _ledger_command("session close", args.run_id, path, f"--outcome {current}")
        if current == "failed":
            close += ' --reason "<why the goal is undoable>"'
        sys.exit(f"close {outcome} refused: the run already ended at '{current}', "
                 f"a terminal node with no outgoing transition — run: "
                 f"{close}")
    if current != outcome:
        fix = _ledger_command("state transition", args.run_id, path,
                              f"--to {outcome} --reason \"<why>\"")
        sys.exit(f"close {outcome} requires current state '{outcome}', but it is "
                 f"'{current}'; transition first — if '{current}' has no legal "
                 f"edge to '{outcome}', or needs --confirm-leave or --leave-arg, "
                 f"its refusal says what to add — run: {fix}")
    closing = f"\n## closed\n{_now()} — {outcome}"
    if args.reason:
        closing += f" — {_single_line(args.reason, '--reason')}"
    _write_atomic(path, text.rstrip("\n") + "\n" + closing + "\n")
    try:
        session_paths.unregister_session_path(args.run_id, path.parent, DEFAULT_DIR)
    except OSError as exc:
        print(f"WARNING could not remove the runtime session path registration: {exc}",
              file=sys.stderr)
    emit(args.output_mode, {"outcome": outcome}, f"CLOSED   {outcome}")
TEXT_POSITIONAL_HELP = "only after an explicit run_id; otherwise use --text"


def add_subparsers(sub: argparse._SubParsersAction, dir_parent: argparse.ArgumentParser) -> None:
    s = sub.add_parser("init", parents=[dir_parent],
                        help="create a new ledger and write its settlement")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("--settlement-file", type=caller_path,
                   help="read settlement body from this file instead of stdin")
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing ledger for this run-id")
    s.set_defaults(func=_run_id_command(cmd_init))

    s = sub.add_parser("validate", parents=[dir_parent],
                        help="validate an execution settlement without writing")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("--settlement-file", type=caller_path,
                   help="validate this settlement body instead of an existing ledger")
    s.set_defaults(func=_run_id_command(cmd_validate))

    s = sub.add_parser("read", parents=[dir_parent],
                        help="print a section, or the whole ledger")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
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
    s.set_defaults(func=_run_id_command(cmd_read))

    s = sub.add_parser("recall", parents=[dir_parent],
                        help="print settlement, full decisions, open todos, state, "
                             "and recent pitches")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.set_defaults(func=_run_id_command(cmd_recall))

    s = sub.add_parser(
        "record-decision", parents=[dir_parent], help="append a decisions entry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Debate --summary forms by mode (include text after the colon):\n"
            "  debate           round N, party '<role>': <position>\n"
            "  scope-settled    scope_settled: <topic, scope, principles, cutoff, dissent>\n"
            "  debate           unanimous_convergence: <question, agreed answer, round count>\n"
            "  debate-capped    consented_stop: or round_cap: <question, decision, dissent>\n"
            "  debate-degraded  degraded_convergence: <question, answer, unavailable party, round count>\n"
            "\n"
            "Start each question at round 0. Record scope-settled after a round-0 entry\n"
            "and before any round 1+ entry. Repeat the current round number or advance\n"
            "to a higher one. A final entry requires a prior round entry and closes the\n"
            "question. After that, record no further entries for the same question."
        ),
    )
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("--mode", required=True,
                   choices=["solo", "resolve", "debate", "debate-capped",
                            "debate-degraded", "scope-settled"],
                   help="how the decision was reached: solo (below threshold), "
                        "resolve (source-of-truth order), debate (round position "
                        "or unanimous close), debate-capped (consented stop or "
                        "round cap), debate-degraded (convergence with an unavailable "
                        "party), scope-settled (closes round 0)")
    s.add_argument("--summary", required=True, help="one-line decision, reason, and cited evidence")
    s.add_argument("--question", metavar="QID",
                   help="stable id (e.g. 'q1') tying every round and the "
                        "closing entry of one debate together; required for "
                        "--mode debate/debate-capped/debate-degraded/"
                        "scope-settled, refused for any other mode — get one "
                        "from `next-question-id`")
    s.set_defaults(func=_run_id_command(cmd_record_decision))

    s = sub.add_parser("update-todo", parents=[dir_parent],
                        help="add a todo, or toggle one done")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("text", nargs="?", help=TEXT_POSITIONAL_HELP)
    s.add_argument("--text", dest="text_option", metavar="TEXT",
                    help="the todo text (or a substring to match an existing one)")
    done_group = s.add_mutually_exclusive_group()
    done_group.add_argument("--done", action="store_true",
                   help="mark the matching todo done, instead of adding a new one")
    done_group.add_argument("--reopen", action="store_true",
                   help="confirm reopening a todo that's already marked done "
                        "(refused without this, to guard against an accidental "
                        "re-add silently undoing completed work); mutually "
                        "exclusive with --done, since marking done and "
                        "confirming a reopen are contradictory requests")
    s.set_defaults(func=_run_id_command(cmd_update_todo))

    s = sub.add_parser("next-question-id", parents=[dir_parent],
                        help="print the next unused debate question id (q1, q2, ...)")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.set_defaults(func=_run_id_command(cmd_next_question_id))

    s = sub.add_parser("record-pitch", parents=[dir_parent],
                        help="append a pitches entry")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("text", nargs="?", help=TEXT_POSITIONAL_HELP)
    s.add_argument("--text", dest="text_option", metavar="TEXT",
                    help="the pitch text")
    s.set_defaults(func=_run_id_command(cmd_record_pitch))

    s = sub.add_parser("close", parents=[dir_parent], help="mark the ledger closed")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("outcome", nargs="?", choices=["succeeded", "failed"], help="goal result; use this or --outcome")
    s.add_argument("--outcome", dest="outcome_option", choices=["succeeded", "failed"],
                    help="the run outcome")
    s.add_argument("--reason", help="required in practice for a failed outcome, "
                                     "naming what made the goal undoable")
    s.set_defaults(func=_run_id_command(cmd_close))

    s = sub.add_parser("write-ticket", parents=[dir_parent],
                        help="write the run's ticket body and record that the run owns it")
    s.add_argument("run_id", nargs="?", help=RUN_ID_HELP)
    s.add_argument("--body-file", type=caller_path, required=True,
                   help="the ticket body: Markdown with the five part headings")
    s.set_defaults(func=_run_id_command(cmd_write_ticket))


def main() -> None:
    """`python -m engine.session` is `task session`, refusals included."""
    from engine import cli
    cli.main(["session", *sys.argv[1:]])


if __name__ == "__main__":
    main()
