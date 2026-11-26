"""`converge` command line: write events, query state, compute cutoff, gate, render."""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path
from typing import Any

from bootgear_cli.clikit import (
    Catalog,
    add_mode_flags,
    caller_cwd,
    caller_path,
    leaf_commands,
    parser_class,
    run,
)

from . import angles as angles_mod
from . import ledger, model, protocol, seats
from .advisor_wait import cmd_advisor_wait
from .cli_actions import (
    _batch_arg,
    cmd_accept,
    cmd_action,
    cmd_angle_na,
    cmd_attack,
    cmd_cut,
    cmd_cutoff,
    cmd_escalate,
    cmd_file,
    cmd_find_run,
    cmd_fix_check,
    cmd_gap_hunt_done,
    cmd_launch,
    cmd_rebut,
    cmd_reply,
    cmd_verdict,
    cmd_work,
)
from .cli_common import (
    CATALOG,
    EXAMPLES,  # noqa: F401
    FIND_CATALOG,
    TRIAGE_CATALOG,
)
from .cli_reports import (
    cmd_angles,
    cmd_config,
    cmd_converged,
    cmd_coverage,
    cmd_gate,
    cmd_prune,
    cmd_render,
    cmd_status,
)
from .cli_setup import cmd_init

# ---------------------------------------------------------------------------
# parser


def _parser(catalog: Catalog = CATALOG) -> argparse.ArgumentParser:
    parser = parser_class(catalog)(prog=catalog.display_prog(), description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, func: Any, *, write: bool = False, slate: bool = True,
                dir_required: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        if slate:
            p.add_argument("slate")
            if dir_required:
                # gate refuses a relative --dir rather than resolving it;
                # leave_check passes the settlement's value.
                p.add_argument("--dir", type=Path, required=True)
            else:
                p.add_argument("--dir", type=caller_path, default=ledger.DEFAULT_DIR.expanduser())
        if write:
            p.add_argument("--as", dest="agent", required=True, help="declared agent id")
        p.set_defaults(func=func)
        return p

    def config_args(p: argparse.ArgumentParser, *, root_help: str =
                    "project directory for .bootgear/config layers; default is the caller directory") -> None:
        p.add_argument("--config", type=caller_path, help="task-layer converge.yaml")
        p.add_argument("--project-root", type=caller_path, default=caller_cwd(), help=root_help)

    p = command("init", cmd_init, write=True)
    p.add_argument("--lenses", default="")
    p.add_argument("--angles", nargs="*", type=caller_path, default=[])
    p.add_argument("--snapshot", action="store_true",
                   help="pin a work-tree snapshot commit at refs/converge/<slate>; requires --pass")
    p.add_argument("--pass", dest="review_pass", type=int, metavar="N",
                   help="review pass number; N >= 1; passes from 2 use cutoff.rereview.lenses over cutoff.lenses")
    p.add_argument("--since", metavar="PREV_SLATE",
                   help="previous slate with a snapshot; requires --snapshot and --pass equal to the previous pass + 1; prints their git diff")
    p.add_argument("--settlement", type=caller_path, metavar="FILE",
                   help="engine settlement YAML; its converge_seats and advisor_roles seat the slate")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--review-group", metavar="ID",
                       help="Engine run ID for the shared advisor reservations")
    group.add_argument("--continue-from", metavar="SLATE",
                       help="preceding standalone slate in the same directory and project")
    p.add_argument("--refuters", type=int, choices=(1, 2), default=2,
                   help="refuter seats on the slate; 1 drops r2")
    p.add_argument("--defaults", type=caller_path, metavar="FILE",
                   help="caller-layer converge.yaml, below the user layer: a skill's cutoff tables")
    p.add_argument("--report-rule", action="append", default=[], metavar="ID",
                   help="append a missing cutoff report rule; repeat in the required order")
    p.add_argument("--r2-only-retry", nargs=2, type=int, metavar=("FINDER", "R1"),
                   help="approved positive finder and r1 counts. Resolved counts must match and r2 must be 1.")
    config_args(p, root_help="project directory for .bootgear/config layers and git refs/converge/<slate> snapshots")

    p = command("file", cmd_file, write=True)
    p.description = "File a supported claim. Every claim requires lens and angle. origin=lens uses an init lens; gap-hunt belongs to R2."
    p.add_argument("--lens")
    p.add_argument("--angle")
    p.add_argument("--loc", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--trigger", required=True)
    p.add_argument("--evidence", required=True,
                   help="the command output or file:line hops the claim rests on")
    p.add_argument("--tier", required=True, metavar="{reproduced,traced,inferred}",
                   help="reproduced: you ran a command or test and quote output showing the "
                        "trigger; traced: no run, and you cite file:line for every hop from the "
                        "entry point to the effect; inferred: any other basis")
    p.add_argument("--origin", required=True)
    p.add_argument("--depends")
    p.add_argument("--rule")

    p = command("escalate", cmd_escalate, write=True)
    p.description = "Record the escalation check. For no widening, omit both wider and evidence; still record the check."
    p.add_argument("--claim", required=True)
    p.add_argument("--wider")
    p.add_argument("--evidence")

    p = command("find-run", cmd_find_run, write=True)
    for flag in ("--lens", "--angle", "--tell", "--searches", "--positive-control"):
        p.add_argument(flag, required=True)
    p.add_argument("--result", required=True,
                   help="`none` if the find filed no claim, else the claim ids it filed, comma-separated")

    p = command("gap-hunt-done", cmd_gap_hunt_done, write=True)
    p.description = "Record completion from r2 after a parallel gap hunt, including with zero claims."

    p = command("angle-na", cmd_angle_na, write=True)
    p.description = "Record an absent tell. find requires lens; attack requires claim and a current table angle."
    p.add_argument("--phase", required=True)
    p.add_argument("--angle", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--lens")
    p.add_argument("--claim")

    p = command("cut", cmd_cut, write=True)
    p.description = ("Rate the current cut. after requires difficulty. A matching choice policy requires choice. "
                     "Artifact trivial/local also requires patch, callers=none, and migration=none. "
                     "Implementation difficulty requires callers and migration. Read current work for the lens policy.")
    p.add_argument("--claim", required=True)
    p.add_argument("--when", required=True)
    p.add_argument("--round", required=True, type=int)
    for name in ("impact", "size", "reach"):
        p.add_argument(f"--{name}", required=True, metavar=f"{{{','.join(model.FIELD_ENUMS[name])}}}")
    p.add_argument("--rate", type=int,
                   help=f"the count an evaluate angle with field rate asks for "
                        f"({CATALOG.display_prog()} angles "
                        "--tag evaluate --angles <file>); required when the claim's lens policy "
                        "has a rate_at_least rule, else 0")
    p.add_argument("--difficulty", metavar=f"{{{','.join(model.DIFFICULTY)}}}",
                   help="after cuts only")
    p.add_argument("--patch", help="the fix as a unified diff; after cuts only")
    p.add_argument("--callers", metavar="{none,changed}",
                   help="whether the fix changes a signature, output format or config key")
    p.add_argument("--migration", metavar="{none,needed}",
                   help="whether the fix needs a data or interface migration")
    p.add_argument("--evidence", action="append", default=[], metavar="ANGLE=TEXT",
                   help="repeat ANGLE=TEXT for each applicable evaluate angle")
    p.add_argument("--choice", help="decision options; required when choice_if matches or cheap policy requires a noncheap decision")

    p = command("attack", cmd_attack, write=True)
    p.description = "Record one refuted angle. Use clean for checked angles that do not refute the claim."
    p.add_argument("--claim", required=True)
    p.add_argument("--batch", required=True, type=_batch_arg)
    for flag in ("--angle", "--tell", "--evidence", "--searches",
                 "--positive-control"):
        p.add_argument(flag, required=True)
    p.add_argument("--last", action="store_true",
                   help="close the fresh-eye batch with this attack")

    for name in ("clean", "act"):
        p = command(name, cmd_action, write=True)
        p.formatter_class = argparse.RawDescriptionHelpFormatter
        p.description = ("Submit a generated JSON action from work. Its envelope has slate, source_seq, role, and action. "
                         "Clean also has claim, batch, and checks. "
                         "Each check has angle, tell, evidence, searches, and positive_control. "
                         "Use last=true only to finish a fresh-eye batch below its cap. "
                         "Replace example context with current work and supply your own checked evidence.\n"
                         'JSON example: {"slate":"s1","source_seq":1,"role":"r1","action":"clean",'
                         '"claim":"F001","batch":1,"checks":[{"angle":"cited-but-unread",'
                         '"tell":"claim cites a source","evidence":"a.py:1 defines the cited entry",'
                         '"searches":"rg entry a.py","positive_control":"entry found at a.py:1"}]}')
        p.add_argument("--input", required=True, metavar="FILE|-",
                       help="one generated action object; - reads stdin; all checks validate before append")

    p = command("work", cmd_work, write=True)
    p.add_argument("--role-host", required=True, choices=("claude", "codex"),
                   help="host that executes this role's commands; always explicit")
    p.add_argument("--role", choices=seats.SEATS,
                   help="seat for a custom agent id not yet present in the slate")
    p.add_argument("--wait", type=int, metavar="SECONDS",
                   help="positive duration for parallel work or main dispatch; main requires --after-seq")
    p.add_argument("--after-seq", type=int, metavar="SEQ",
                   help="main wait only: source_seq from the last work package main handled on this slate")
    p.add_argument("--active-worker", action="append", default=[], metavar="ID",
                   help="main wait only: repeat for each worker with an active turn or unanswered receipt on this slate")
    p.add_argument("--out", type=caller_path,
                   help="optional: save work.json and separate editable actions in an assigned workflow directory outside the target artifact")

    p = command("advisor-wait", cmd_advisor_wait, write=True)
    p.description = "Wait for one parallel advisor response with a quiet receive limit."
    p.add_argument("--channel", required=True, help="reserved channel number")
    p.add_argument("--request", required=True, metavar="MESSAGE_ID",
                   help="message_id from the outstanding request's send receipt")
    p.add_argument("--timeout", type=float, default=300, metavar="SECONDS",
                   help="seconds per receive (default: 300)")

    p = command("reply", cmd_reply, write=True)
    p.description = "Reply to the batch's refutation. rebut requires new evidence; decline carries no evidence or text."
    p.add_argument("--claim", required=True)
    p.add_argument("--batch", required=True, type=_batch_arg)
    p.add_argument("--stance", required=True)
    p.add_argument("--evidence")
    p.add_argument("--text", help="the clarified claim text, with stance rebut")

    p = command("verdict", cmd_verdict, write=True)
    p.description = "Answer the finder's rebuttal. disagree requires evidence; agree does not require evidence."
    p.add_argument("--claim", required=True)
    p.add_argument("--batch", required=True, type=_batch_arg)
    p.add_argument("--verdict", required=True)
    p.add_argument("--evidence")

    p = command("rebut", cmd_rebut, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--when", required=True)
    p.add_argument("--evidence", required=True)

    p = command("accept", cmd_accept, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--when", required=True)
    p.add_argument("--round", required=True, type=int)

    p = command("fix-check", cmd_fix_check, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--outcome", required=True, metavar="{pass,fail}",
                   help="pass: the patch passed the tests and checks and the review slate "
                        "holds no finding; fail: it did not, and the patch is reverted")
    p.add_argument("--evidence", required=True, help="the checks run and their result")
    p.add_argument("--review-slate", metavar="SLATE",
                   help="the slate that re-reviewed only the patch; required with pass")

    p = command("status", cmd_status)
    p.add_argument("--json", action="store_true", help="print JSON")
    command("converged", cmd_converged)
    command("cutoff", cmd_cutoff)
    command("coverage", cmd_coverage)
    p = command("gate", cmd_gate, dir_required=True)
    p.add_argument("--kind", choices=("triage",),
                   help="triage: each surviving claim is reproduced, and --report backs it with "
                        "a row, a command, an output and a reproduction-rerun attack")
    p.add_argument("--report", type=Path, metavar="FILE",
                   help="the triage report, an absolute path; only with --kind triage")
    p.add_argument("--base-slate", metavar="SLATE",
                   help="triage: the first visit's slate; each report row must name one of its "
                        "claims, so a later visit adds no cause claim")
    command("render", cmd_render)

    p = command("prune", cmd_prune, slate=False)
    p.add_argument("slates", nargs="+", metavar="slate",
                   help="slate ids whose refs/converge/<slate> snapshot refs will be deleted")
    p.add_argument("--project-root", type=caller_path, default=caller_cwd(),
                   help="git repository that holds refs/converge/<slate> snapshot refs")

    p = command("angles", cmd_angles, slate=False)
    p.add_argument("--tag", choices=angles_mod.TAGS)
    p.add_argument("--angles", nargs="*", type=caller_path, default=[])
    config_args(p)

    p = command("config", cmd_config, slate=False)
    p.add_argument("action", choices=("validate", "resolve"))
    config_args(p)

    p = command("launch", cmd_launch, write=True)
    p.description = "Reserve configured native identities, including serial cutter and native refuters. Only the saved main actor can reserve them."
    p.add_argument("--input", required=True, metavar="FILE",
                   help="JSON object with launches: [{id, host: claude|codex, model, effort}]; use '-' for stdin. "
                        "Use saved work profiles. Returns model with effort on Claude or reasoning_effort on Codex.")
    p = command("launch-result", cmd_launch, write=True)
    p.description = "Record native role results. A known effective mismatch blocks the slate."
    p.add_argument("--input", required=True, metavar="FILE",
                   help="JSON object with outcomes: [{id, state: finished|blocked, handle, receipt_worker, "
                        "effective: {model, effort}, reason}]; use '-' for stdin. A native handle and receipt_worker "
                        "are required for finished outcomes or native evidence. A blocked outcome needs a reason.")
    add_mode_flags(parser)
    guidance = {
        "slate": "saved slate id; lowercase letters, digits, dots, underscores, and hyphens",
        "dir": "slate directory; default ~/.bootgear/converge; gate requires an absolute path",
        "lenses": "comma-separated lens ids; at least one is required",
        "angles": "YAML angle files; saved with effective built-in definitions during init",
        "lens": "lens id; required for every claim and phase=find",
        "angle": "saved angle id; fresh-eye attacks instead use a new printable one-line name",
        "loc": "source location as path:line",
        "claim": "claim text for file; saved claim id for other commands",
        "trigger": "concrete input or action that reaches the claimed effect",
        "origin": "lens for the finder; gap-hunt for R2 after find coverage",
        "depends": "comma-separated earlier claim ids",
        "rule": "report rule id from the effective cutoff policy",
        "wider": "wider claim text; requires evidence; omit both for no widening",
        "evidence": "observed output or source:line evidence",
        "tell": "why this angle applies",
        "searches": "searches actually performed",
        "positive_control": "a known matching result from the search",
        "phase": "find checks one lens; attack checks one claim's current table batch",
        "reason": "one printable line explaining why the tell does not apply",
        "when": "before the attack or after it",
        "round": "positive cut round; work fills the current next round",
        "impact": "effect supported by evaluate evidence",
        "size": "affected user or record count class",
        "reach": "which caller can reach the trigger",
        "batch": "positive integer for a table batch, or fresh-eye",
        "stance": "rebut needs new evidence; decline kills the claim",
        "verdict": "agree ends the dispute; disagree requires evidence",
        "last": "finish this fresh-eye batch below its cap; invalid for numeric batches",
        "tag": "return definitions for this angle purpose",
        "action": "validate checks configuration; resolve prints the effective layers",
    }
    enums = {"origin": model.ORIGIN, "tier": model.TIER, "phase": model.PHASE,
             "when": protocol.WHEN, "stance": protocol.STANCE, "verdict": protocol.VERDICT}
    for leaf in leaf_commands(parser).values():
        for argument in leaf._actions:
            if argument.help is None:
                argument.help = guidance.get(argument.dest)
            if argument.dest in enums:
                argument.metavar = "{" + ",".join(enums[argument.dest]) + "}"
    return parser


def main(argv: list[str] | None = None) -> None:
    raw = sys.argv[1:] if argv is None else argv
    find = "--phase=find" in raw or any(
        flag == "--phase" and value == "find" for flag, value in itertools.pairwise(raw))
    triage = any(arg.partition("=")[0] in ("--kind", "--report") for arg in raw)
    catalog = FIND_CATALOG if find else TRIAGE_CATALOG if triage else CATALOG
    run(_parser(catalog), catalog, lambda a: a.command, argv)


if __name__ == "__main__":
    main()
