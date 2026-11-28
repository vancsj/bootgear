"""Write validated actions to Converge slates."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import Any

from bootgear_cli.clikit import (
    caller_path,
    emit,
    gear_command,
)

from . import ledger, model, protocol, render, work
from .cli_common import (
    CATALOG,
    _coverage_problems,
    _ids,
    _next_step,
    _opt,
    _read,
    _refuse,
    _refuse_next,
    _step,
    _workflow,
    _write,
    _written,
)
from .model import Slate

DEFAULT_WORK_WAIT = 300


def cmd_file(args: argparse.Namespace) -> None:
    event = _opt({"event": "file", "loc": args.loc, "claim": args.claim,
                  "trigger": args.trigger, "evidence": args.evidence, "tier": args.tier,
                  "origin": args.origin},
                 lens=args.lens, angle=args.angle, rule=args.rule,
                 depends=_ids(args.depends) if args.depends else None)
    written = _write(args, event, build=lambda s: {"id": model.claim_id(len(s.claims) + 1)})
    _written(args, {"id": written["id"]}, f"FILED {written['id']}")


def cmd_escalate(args: argparse.Namespace) -> None:
    event = _opt({"event": "escalate", "claim": args.claim},
                 wider=args.wider, evidence=args.evidence)
    written = _write(args, event)
    wider = "yes" if "wider" in written else "no"
    _written(args, {"seq": written["seq"], "claim": args.claim, "wider": wider == "yes"},
             f"ESCALATE seq={written['seq']} {args.claim} wider={wider}")


def cmd_gap_hunt_done(args: argparse.Namespace) -> None:
    written = _write(args, {"event": "gap-hunt-done"})
    _written(args, {"seq": written["seq"]}, f"GAP HUNT DONE seq={written['seq']}")


def cmd_find_run(args: argparse.Namespace) -> None:
    result: Any = "none" if args.result.strip() == "none" else _ids(args.result)
    written = _write(args, {"event": "find-run", "lens": args.lens, "angle": args.angle,
                            "tell": args.tell, "searches": args.searches,
                            "positive_control": args.positive_control, "result": result})
    _written(args, {"seq": written["seq"], "lens": args.lens, "angle": args.angle},
             f"FIND-RUN seq={written['seq']} lens={args.lens} angle={args.angle}")


def cmd_angle_na(args: argparse.Namespace) -> None:
    event = _opt({"event": "angle-na", "phase": args.phase, "angle": args.angle,
                  "reason": args.reason}, lens=args.lens, claim=args.claim)
    written = _write(args, event)
    _written(args, {"seq": written["seq"], "phase": args.phase, "angle": args.angle},
             f"ANGLE-NA seq={written['seq']} phase={args.phase} angle={args.angle}")


def cmd_rebut(args: argparse.Namespace) -> None:
    written = _write(args, {"event": "rebut", "claim": args.claim, "when": args.when,
                            "evidence": args.evidence,
                            "evidence_sha256": ledger.evidence_hash(args.evidence)})
    _written(args, {"seq": written["seq"], "claim": args.claim, "when": args.when},
             f"REBUT seq={written['seq']} {args.claim} when={args.when}")


def cmd_cut(args: argparse.Namespace) -> None:
    evidence: dict[str, str] = {}
    problems = []
    for item in args.evidence:
        key, sep, text = item.partition("=")
        if not sep:
            problems.append(f"--evidence must be ANGLE=TEXT; got {item!r}")
        elif key in evidence:
            problems.append(f"--evidence given twice for {key!r}")
        else:
            evidence[key] = text
    if problems:
        _refuse(problems)
    event = _opt({"event": "cut", "claim": args.claim, "when": args.when, "round": args.round,
                  "impact": args.impact, "size": args.size, "reach": args.reach,
                  "evidence": evidence},
                 rate=args.rate, difficulty=args.difficulty, patch=args.patch,
                 callers=args.callers, migration=args.migration, choice=args.choice)
    written = _write(args, event)
    _written(args,
             {"seq": written["seq"], "claim": args.claim, "when": args.when, "round": args.round},
             f"CUT seq={written['seq']} {args.claim} when={args.when} round={args.round}")


def cmd_accept(args: argparse.Namespace) -> None:
    written = _write(args, {"event": "accept", "claim": args.claim, "when": args.when,
                            "round": args.round})
    _written(args,
             {"seq": written["seq"], "claim": args.claim, "when": args.when, "round": args.round},
             f"ACCEPT seq={written['seq']} {args.claim} when={args.when} round={args.round}")


def _batch_arg(value: str) -> int | str:
    """`--batch`: a table batch number, or `fresh-eye`."""
    return int(value) if value.isdigit() else value


def cmd_attack(args: argparse.Namespace) -> None:
    event = {"event": "attack", "claim": args.claim, "batch": args.batch, "angle": args.angle,
             "tell": args.tell, "evidence": args.evidence,
             "searches": args.searches, "positive_control": args.positive_control}
    if args.last:
        event["last"] = True
    written = _write(args, event)
    _written(args, {"seq": written["seq"], "claim": args.claim, "batch": args.batch,
                    "angle": args.angle, "outcome": "refuted"},
             f"ATTACK seq={written['seq']} {args.claim} batch={args.batch} angle={args.angle} "
             "outcome=refuted")


def cmd_action(args: argparse.Namespace) -> None:
    if args.slate is None:
        from .coordination_commands import cmd_act

        if args.dir is not None or args.agent is not None:
            _refuse(["the active assignment derives its directory and seat from the coordination store"])
        cmd_act(args)
        return
    if args.command == "act":
        args.dir = args.dir or ledger.DEFAULT_DIR.expanduser()
        if args.agent is None:
            _refuse(["explicit slate action requires --as"])
    args.action_next = f"refresh your work: {gear_command('cli', 'coordination')} poll"
    try:
        text = sys.stdin.read() if args.input == "-" else caller_path(args.input).read_text()
        value = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        _refuse_next(args, "invalid action", [str(exc)], args.action_next)
    if not isinstance(value, dict):
        _refuse_next(args, "invalid action", ["input must be one JSON object"], args.action_next)
    if args.command == "clean" and value.get("action") != "clean":
        _refuse_next(args, "invalid action", ["clean requires action=clean"], args.action_next)

    def build(slate: Slate) -> dict[str, Any]:
        event = work.event(slate, value, args.agent)
        if event["event"] == "fix-check" and event.get("outcome") == "pass":
            review_args = argparse.Namespace(**vars(args), review_slate=event["review_slate"])
            problems, _ = _review_problems(review_args, slate)
            if problems:
                raise ledger.LedgerError(problems)
        return event

    written = _write(args, {"event": value.get("action")}, build=build)
    data = {key: field for key, field in written.items() if key not in ("ts", "as")}
    _written(args, data, f"{written['event'].upper()} seq={written['seq']} "
             + str(written.get("claim", "")))


def cmd_reply(args: argparse.Namespace) -> None:
    event: dict[str, Any] = {"event": "reply", "claim": args.claim, "batch": args.batch,
                             "stance": args.stance}
    if args.evidence is not None:
        event.update(evidence=args.evidence, evidence_sha256=ledger.evidence_hash(args.evidence))
    written = _write(args, _opt(event, text=args.text))
    _written(args, {"seq": written["seq"], "claim": args.claim, "batch": args.batch,
                    "stance": args.stance},
             f"REPLY seq={written['seq']} {args.claim} batch={args.batch} stance={args.stance}")


def cmd_verdict(args: argparse.Namespace) -> None:
    event = _opt({"event": "verdict", "claim": args.claim, "batch": args.batch,
                  "verdict": args.verdict}, evidence=args.evidence)
    written = _write(args, event)
    _written(args, {"seq": written["seq"], "claim": args.claim, "batch": args.batch,
                    "verdict": args.verdict},
             f"VERDICT seq={written['seq']} {args.claim} batch={args.batch} "
             f"verdict={args.verdict}")


def cmd_cutoff(args: argparse.Namespace) -> None:
    slate = _read(args)
    problems = _coverage_problems(slate)
    problems.extend(f"{claim.id} is open in {phase}" for claim, phase in slate.open_claims())
    if problems:
        _refuse_next(args, "refused", problems, _next_step(args, slate))
    if not slate.cutoff_valid:
        def build(current: Slate) -> dict[str, Any]:
            return {"results": protocol.cutoff_results(protocol.compute_cutoff(current))}
        _write(args, {"event": "cutoff", "as": model.CONVERGE_AGENT}, build=build)
        slate = _read(args)
    assert slate.cutoff is not None
    rows = protocol.compute_cutoff(slate)
    counts = render.counts(rows)
    emit(args.output_mode,
         {"seq": slate.cutoff["seq"], "rows": protocol.cutoff_results(rows)},
         [f"CUTOFF seq={slate.cutoff['seq']} {counts}",
          *(f"{row.claim.id} {row.result} status={row.status} cut={row.cut} rank={row.rank} "
            f"reason={row.reason}" for row in rows)],
         _step(args, "render"))


def _fix_baseline(slate: Slate) -> dict[str, Any] | None:
    """The last `cutoff` event written before the slate's first `fix-check`, else its latest."""
    baseline = None
    for event in slate.events:
        if event["event"] == "fix-check":
            break
        if event["event"] == "cutoff":
            baseline = event
    return baseline


def _review_problems(args: argparse.Namespace, slate: Slate) -> tuple[list[str], bool]:
    """Every failed check of `--review-slate`, and whether it holds findings: it reads from
    the same --dir, has a current cutoff no older than this slate's last cutoff before its
    first fix-check, and reports no claim with `cut: no` that is not killed."""
    name = args.review_slate
    try:
        path = ledger.slate_path(args.dir, name)
    except ledger.LedgerError as exc:
        return [f"--review-slate: {p}" for p in exc.problems], False
    if not path.is_file():
        return [f"--review-slate: no slate {name!r} in {args.dir}"], False
    try:
        review = ledger.read(path, name, workflow=_workflow(args, name))
    except ledger.LedgerError as exc:
        return [f"--review-slate: slate {name!r} is unreadable: " + "; ".join(exc.problems)], False
    if not review.cutoff_valid or review.cutoff is None:
        cutoff = CATALOG.command(f"cutoff {shlex.quote(name)} --dir {shlex.quote(str(args.dir))}")
        return [f"--review-slate: slate {name!r} has no current cutoff; run {cutoff}"], False
    problems = []
    baseline = _fix_baseline(slate)
    if baseline is not None and review.cutoff["ts"] < baseline["ts"]:
        problems.append(f"--review-slate: slate {name!r}'s cutoff ({review.cutoff['ts']}) is older "
                        f"than {args.slate}'s cutoff seq={baseline['seq']} ({baseline['ts']}), "
                        f"its last before the first fix-check; re-review the patch")
    found = [row["claim"] for row in review.cutoff["results"]
             if row["cut"] == "no" and row["result"] != "killed"]
    if found:
        problems.append(f"--review-slate: slate {name!r} holds findings ({', '.join(found)}); "
                        f"the patch fails check 7")
    return problems, bool(found)


def cmd_fix_check(args: argparse.Namespace) -> None:
    if args.outcome == "pass" and args.review_slate is not None and args.review_slate != args.slate:
        slate = _read(args)
        problems, found = _review_problems(args, slate)
        if problems:
            fail = _step(args, "fix-check", f"--as {args.agent} --claim {args.claim} "
                         '--outcome fail --evidence "<the findings>"')
            cutoff = f"{gear_command('converge', 'converge')} cutoff"
            step = (f"record --outcome fail and revert the patch: {fail}" if found
                    else "re-review only the patch in a new slate, then run "
                         f"{cutoff}, then rerun fix-check")
            _refuse_next(args, "refused", problems, step)
    written = _write(args, _opt({"event": "fix-check", "claim": args.claim,
                                 "outcome": args.outcome, "evidence": args.evidence},
                                review_slate=args.review_slate))
    _written(args, {"seq": written["seq"], "claim": args.claim, "outcome": args.outcome},
             f"FIX-CHECK seq={written['seq']} {args.claim} outcome={args.outcome}")
