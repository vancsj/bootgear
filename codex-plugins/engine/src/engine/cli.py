#!/usr/bin/env python3
"""Unified engine command line.

    task session init|validate|read|recall|record-decision|update-todo|next-question-id|
                 record-pitch|close ...
    task state   transition|current|amend|show|validate|diagram ...

`session` is the ledger (settlement, decisions, todos, pitches, close) —
see engine.session. `state` is the state machine (transition the run's
current node, print it with its reminder, amend or show the run's machine, validate or diagram a machine
file) — see engine.state.
"""
from __future__ import annotations

import argparse

from engine import config, session, state
from engine.clikit import Catalog, add_mode_flags, caller_path, parser_class, run

# Leaf command -> runnable argv after the program, shown in every refusal.
EXAMPLES = {
    "session init": "session init <run-id> --settlement-file <file>",
    "session validate": "session validate <run-id> --dir <session-dir>",
    "session read": "session read <run-id> --dir <session-dir> --section state",
    "session recall": "session recall <run-id> --dir <session-dir>",
    "session record-decision": ('session record-decision <run-id> --dir <session-dir> '
                                '--mode solo --summary "<decision>"'),
    "session update-todo": ('session update-todo <run-id> --dir <session-dir> '
                            '"<todo text>" --done'),
    "session next-question-id": "session next-question-id <run-id> --dir <session-dir>",
    "session record-pitch": ('session record-pitch <run-id> --dir <session-dir> '
                             '"<what changed>"'),
    "session close": "session close <run-id> --dir <session-dir> succeeded",
    "state transition": ('state transition <run-id> --dir <session-dir> --to <node> '
                         '--reason "<why>"'),
    "state amend": ('state amend <run-id> --dir <session-dir> --machine-file '
                    '<machine.yaml> --reason "<why>"'),
    "state current": "state current <run-id> --dir <session-dir>",
    "state show": "state show <run-id> --dir <session-dir>",
    "state validate": "state validate <machine.yaml>",
    "state diagram": "state diagram <machine.yaml>",
    "config resolve": "config resolve --name <name> --project-root <dir>",
}
CATALOG = Catalog(prog=session.PROG, examples=EXAMPLES,
                  frequent=("session recall", "session record-decision", "state transition"),
                  legacy_json=frozenset({"config resolve"}))


def build_parser() -> argparse.ArgumentParser:
    p = parser_class(CATALOG)(prog=CATALOG.prog, description=__doc__,
                              formatter_class=argparse.RawDescriptionHelpFormatter)
    top = p.add_subparsers(dest="group", required=True)

    dir_parent = argparse.ArgumentParser(add_help=False)
    dir_parent.add_argument("--dir", type=caller_path, default=None,
                             help=f"ledger directory (default: {session.DEFAULT_DIR})")

    session_parser = top.add_parser("session", help="ledger: settlement, decisions, "
                                                      "todos, pitches, close")
    session_sub = session_parser.add_subparsers(dest="cmd", required=True)
    session.add_subparsers(session_sub, dir_parent)

    state_parser = top.add_parser("state", help="state machine: transition, "
                                                  "current, amend, show, validate, diagram")
    state_sub = state_parser.add_subparsers(dest="cmd", required=True)
    state.add_subparsers(state_sub, dir_parent)

    config_parser = top.add_parser("config", help="resolve layered configuration")
    config_sub = config_parser.add_subparsers(dest="cmd", required=True)
    config.add_subparsers(config_sub)

    add_mode_flags(p)
    return p


def main(argv: list[str] | None = None) -> None:
    run(build_parser(), CATALOG, lambda a: f"{a.group} {a.cmd}", argv)


if __name__ == "__main__":
    main()
