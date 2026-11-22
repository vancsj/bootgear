"""Read, render, and gate Converge slates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bootgear_cli.clikit import (
    emit,
)

from . import angles as angles_mod
from . import config as config_mod
from . import ledger, model, protocol, render
from .cli_advisor import _drivers
from .cli_common import (
    _MISSING,
    CATALOG,
    EXIT_NO,
    _coverage_problems,
    _next_step,
    _path,
    _read,
    _refuse,
    _refuse_next,
    _step,
)
from .cli_setup import _git, _git_error, _git_root, _ref
from .model import Slate
from .triage_report import report_problems

# ---------------------------------------------------------------------------
# read commands


def _claim_status(slate: Slate, claim: model.Claim, flags: dict[str, bool],
                  unverified: set[str]) -> dict[str, Any]:
    batch = (protocol.next_batch(slate, claim)
             if claim.live and claim.id not in unverified else None)
    rating = claim.state.rating
    stored = {row["claim"]: row["result"] for row in (slate.cutoff or {}).get("results", [])}
    result = {"result": stored[claim.id]} if claim.id in stored else {}
    return {
        "id": claim.id,
        "status": protocol.status(slate, claim, unverified),
        "cut": "yes" if flags.get(claim.id) else "no",
        "batch": batch,
        "batch_state": None if batch is None else protocol.batch_state(slate, claim, batch),
        "lens": claim.lens,
        "origin": claim.origin,
        "finder": claim.finder,
        "claim": claim.text,
        "loc": claim.loc,
        "trigger": claim.trigger,
        "evidence": claim.evidence,
        "tier": claim.tier,
        "escalated": claim.escalation is not None,
        "rating": ({f: rating.get(f) for f in (*model.CUT_FIELDS, *model.AFTER_FIELDS)}
                   if rating else None),
        "artifact_patch_eligible": protocol.artifact_patch_eligible(slate, claim),
        "fixed_remaining": slate.remaining_angles(claim),
        "fresh_eye": [e["angle"] for e in claim.state.attacks.get(protocol.FRESH_EYE, [])],
        "na_reasons": claim.na_reasons,
        **result,
        "fix_check": claim.fix_check["outcome"] if claim.fix_check else "none",
    }


def _claim_line(c: dict[str, Any]) -> str:
    batch = "-" if c["batch"] is None else c["batch"]
    na = " ".join(f"na[{angle}]={reason}" for angle, reason in c["na_reasons"].items())
    fresh = f" fresh-eye={','.join(c['fresh_eye'])}" if c["fresh_eye"] else ""
    return (f"{c['id']} status={c['status']} cut={c['cut']} tier={c['tier']} batch={batch} "
            f"batch_state={c['batch_state'] or '-'} escalated={'yes' if c['escalated'] else 'no'} "
            f"fixed_remaining={','.join(c['fixed_remaining']) or '-'}{fresh}"
            f" artifact_patch_eligible={str(c['artifact_patch_eligible']).lower()}"
            + (f" {na}" if na else ""))


def _adhoc_line(rows: list[dict[str, Any]]) -> str:
    return "ADHOC " + (", ".join(f"{row['angle']} claim={row['claim']} seq={row['seq']}"
                                 for row in rows) or "-")


def _plan_lines(plan: list[list[dict[str, Any]]]) -> list[str]:
    lines = []
    for index, chunk in enumerate(plan, start=1):
        for row in chunk:
            line = f"PLAN {index} {row['claim']} {row['action']} {row['agent_role']}"
            if row["batch"] is not None:
                line += f" batch={row['batch']}"
            if row["angles"]:
                line += f" angles={','.join(row['angles'])}"
            lines.append(line)
    return lines


def _unresolved_choices(slate: Slate) -> list[dict[str, str]]:
    if not slate.cutoff_valid:
        return []
    return [{"claim": row.claim.id, "result": row.result, "choice": choice}
            for row in protocol.compute_cutoff(slate)
            if row.result == "finding"
            and (choice := (row.claim.state.rating or {}).get("choice"))]


def cmd_status(args: argparse.Namespace) -> None:
    slate = _read(args)
    flags, unverified = protocol.cut_flags(slate), protocol.unverified_ids(slate)
    claims = [_claim_status(slate, c, flags, unverified) for c in slate.claims.values()]
    cutoff = "current" if slate.cutoff_valid else ("stale" if slate.cutoff else "none")
    agents = slate.agent_ids()
    phase = protocol.slate_phase(slate)
    plan = protocol.batch_plan(slate)
    adhoc = protocol.adhoc_angles(slate)
    step = _next_step(args, slate)
    if args.json:
        data: dict[str, Any] = {
            "slate": slate.slate_id, "lenses": slate.lenses, "refuters": slate.init_refuters,
            "difficulty_basis": slate.config["cutoff"]["difficulty_basis"],
            "cutoff": cutoff, "agents": agents, "agent_cap": slate.agent_cap,
            "parallelism": slate.parallelism,
            "review_group": slate.review_group,
            "gap_hunt_done": slate.gap_hunt_done,
            "phase": phase, "steps": slate.config["steps"], "caps": slate.config["caps"],
            "plan": plan,
            "seats": slate.seats,
            "drivers": _drivers(slate.slate_id, args.dir, slate.seats, slate.advisor,
                                review_group=slate.review_group, r2_workers=slate.parallelism["r2"]),
            "claims": claims, "adhoc_angles": adhoc, "next": step}
        emit(args.output_mode, {}, [], json_text=json.dumps(data, indent=2))
        return
    advisor = ",".join(seat for seat in slate.seats if slate.mechanism(seat) == "advisor")
    lines = [(f"SLATE {slate.slate_id} lenses={','.join(slate.lenses) or '-'} "
              f"phase={phase} cutoff={cutoff} claims={len(claims)} "
              f"difficulty_basis={slate.config['cutoff']['difficulty_basis']} "
              f"agents={len(agents)}/{slate.agent_cap} advisor={advisor or '-'}"),
             *map(_claim_line, claims), _adhoc_line(adhoc), *_plan_lines(plan)]
    emit(args.output_mode, {}, lines, step)


def cmd_converged(args: argparse.Namespace) -> None:
    slate = _read(args)
    phase = protocol.slate_phase(slate)
    flags = protocol.cut_flags(slate)
    open_ids = {claim.id: claim_phase for claim, claim_phase in slate.open_claims()}
    pending, disputed = [], []
    for claim in slate.claims.values():
        if claim.id in open_ids:
            pending.append(f"{claim.id} open in {open_ids[claim.id]}")
        elif (claim.live and claim.state.status == "disputed" and not flags[claim.id]):
            disputed.append(claim.id)
            pending.append(f"{claim.id} disputed cut=no")
    done = protocol.converged(slate)
    data = {"converged": done, "phase": phase, "pending": pending}
    if done:
        emit(args.output_mode, data, "CONVERGED", "end the slate with outcome converged")
        return
    if phase == "done":
        step = ("end the slate with outcome unconverged; disputed findings: "
                + ", ".join(disputed))
    else:
        step = _next_step(args, slate)
    emit(args.output_mode, data, [f"OPEN phase={phase} claims={len(pending)}", *pending], step)
    sys.exit(EXIT_NO)


def cmd_coverage(args: argparse.Namespace) -> None:
    slate = _read(args)
    coverage = render.coverage(slate)
    lines = []
    for lens, row in coverage.items():
        lines.append(f"LENS {lens} ran={','.join(row.ran) or '-'} na={','.join(row.na) or '-'} "
                     f"missing={','.join(row.missing) or '-'}")
        lines.extend(f"NA {lens} {angle_id} {reason}" for angle_id, reason in row.na.items())
    if any(row.missing for row in coverage.values()):
        step = _MISSING + _step(args, "coverage")
    else:
        step = _step(args, "status", "--json")
    emit(args.output_mode,
         {"lenses": {lens: {"ran": row.ran, "na": row.na, "missing": row.missing}
                     for lens, row in coverage.items()}},
         lines, step)


def _base_slate(args: argparse.Namespace) -> Slate | None:
    """The `--base-slate` slate, or None when the option is not given."""
    if args.base_slate is None:
        return None
    try:
        return ledger.read(ledger.slate_path(args.dir, args.base_slate), args.base_slate)
    except ledger.LedgerError as exc:
        _refuse(exc.problems)


def _triage_report(args: argparse.Namespace) -> tuple[str | None, list[str]]:
    """The --report text for `--kind triage`, or every --kind/--report problem."""
    problems = []
    if args.base_slate is not None and args.kind is None:
        problems.append("--base-slate needs --kind triage")
    if args.kind is not None and args.report is None:
        problems.append("--kind triage needs --report <absolute file>")
    if args.report is None:
        return None, problems
    if args.kind is None:
        problems.append("--report needs --kind triage")
    if not args.report.is_absolute():
        problems.append(f"--report needs an absolute path; got {str(args.report)!r}")
    elif not args.report.is_file():
        problems.append(f"--report {args.report} is not a file")
    if problems:
        return None, problems
    try:
        return args.report.read_text(), []
    except (OSError, UnicodeError) as exc:
        return None, [f"--report {args.report} is unreadable: {exc}"]


def cmd_gate(args: argparse.Namespace) -> None:
    if not args.dir.is_absolute():
        _refuse([f"gate needs an absolute --dir; got {str(args.dir)!r}"])
    report, usage = _triage_report(args)
    if usage:
        _refuse(usage, code=EXIT_NO)
    base = _base_slate(args)
    path = _path(args)
    if not path.is_file():
        _refuse([f"no slate {args.slate!r} in {args.dir} (expected {path})"])
    slate = _read(args)
    problems = _coverage_problems(slate)
    for claim, phase in slate.open_claims():
        problems.append(f"{claim.id} is open in {phase}")
    if not slate.cutoff_valid:
        problems.append(f"no current cutoff (run `{CATALOG.display_prog()} cutoff` after the last state change)")
    step = _next_step(args, slate) if problems else None
    if report is not None:
        problems.extend(report_problems(slate, report, base))
    cutoff_seq = slate.cutoff["seq"] if slate.cutoff else None
    data = {"slate": args.slate, "ok": not problems, "problems": problems, "cutoff_seq": cutoff_seq}
    if problems:
        if step is None:
            step = ("revise the report and return to triage" if report is not None
                    else "no revision is possible after this gate; end the run as failed")
        emit(args.output_mode, data, [f"GATE fail {args.slate}", *problems], step)
        sys.exit(EXIT_NO)
    shown = "-" if cutoff_seq is None else cutoff_seq
    emit(args.output_mode, data, f"GATE ok {args.slate} cutoff_seq={shown}",
         _step(args, "converged"))


def cmd_render(args: argparse.Namespace) -> None:
    slate = _read(args)
    markdown = render.render(slate)
    if args.output_mode == "json":
        fix_now = [{"claim": row.claim.id, "patch": (row.claim.state.rating or {})["patch"]}
                   for row in protocol.compute_cutoff(slate) if row.result == "fix-now"]
        emit(args.output_mode, {"slate": args.slate, "markdown": markdown,
                                "choices": _unresolved_choices(slate),
                                "claims": render.claim_inputs(slate),
                                "difficulty_basis": slate.config["cutoff"]["difficulty_basis"],
                                "fix_now": fix_now}, [])
        return
    sys.stdout.write(markdown)


def cmd_prune(args: argparse.Namespace) -> None:
    problems = [f"slate id must match {model.ID_RE.pattern}: {slate!r}"
                for slate in args.slates if not model.ID_RE.match(slate)]
    root, reason = _git_root(args.project_root)
    if reason:
        problems.append(reason)
    if problems:
        _refuse(problems)
    assert root is not None
    pruned, missing, failed, lines = [], [], [], []
    for slate in dict.fromkeys(args.slates):
        ref = _ref(slate)
        if _git(root, "show-ref", "--verify", "--quiet", ref).returncode != 0:
            missing.append(slate)
            lines.append(f"WARN no ref {ref}")
            continue
        out = _git(root, "update-ref", "-d", ref)
        if out.returncode != 0:
            failed.append(_git_error(f"git update-ref -d {ref}", out))
            continue
        pruned.append(slate)
        lines.append(f"PRUNED {ref}")
    if failed:
        _refuse([*failed, *lines])
    emit(args.output_mode, {"pruned": pruned, "missing": missing}, lines)


def cmd_angles(args: argparse.Namespace) -> None:
    try:
        resolved = config_mod.resolve(args.project_root, args.config)
        rows = angles_mod.resolve(args.angles, resolved["effective"], Path(resolved["project_root"]))
    except (config_mod.ConfigError, angles_mod.AngleError) as exc:
        _refuse(exc.problems)
    basis = resolved["effective"]["cutoff"]["difficulty_basis"]
    if basis == "implementation":
        rows = [{**row, "asks": "Cite concrete production remedy paths, scope, affected callers, "
                 "migration needs, and testing work. Rate that remedy independently of document patch size.",
                 "values": {
                     "redesign": "the production remedy needs a choice between reasonable designs",
                     "cross-cutting": "otherwise, production paths, callers, migration or testing cross the local limits",
                     "trivial": "otherwise, the production remedy fits one non-test file and at most three changed lines",
                     "local": "otherwise, the production remedy fits one non-test file, ten changed lines and one test file"}}
                if row["id"] == "files-touched" else row for row in rows]
    rows = [row for row in rows if not args.tag or row["tag"] == args.tag]
    if args.tag == "find" and not rows:
        _refuse_next(
            args,
            "no find angles found",
            ["no find angles were resolved from --angles or angles.files"],
            "add a find angle with --angles <file> or configure angles.files, then "
            f"rerun `{CATALOG.display_prog()} angles --tag find`",
        )
    lines = []
    for row in rows:
        extra = "".join(f" {k}={row[k]}" for k in ("field", "lens") if k in row)
        lines.append(f"{row['tag']} {row['id']}{extra} — tell: {row['tell']} — asks: {row['asks']}")
        lines.extend(f"  {value}: {test}" for value, test in row.get("values", {}).items())
    emit(args.output_mode, {"angles": rows, "difficulty_basis": basis}, lines)


def cmd_config(args: argparse.Namespace) -> None:
    try:
        resolved = config_mod.resolve(args.project_root, args.config)
    except config_mod.ConfigError as exc:
        _refuse(exc.problems, "invalid configuration")
    if args.action == "validate":
        emit(args.output_mode, {"valid": True, "sources": resolved["sources"]},
             [*(f"SOURCE {source['layer']} {'present' if source['present'] else 'missing'} "
                f"{source['path']}" for source in resolved["sources"]), "CONFIG valid"])
        return
    emit(args.output_mode, resolved, json.dumps(resolved, indent=2))
