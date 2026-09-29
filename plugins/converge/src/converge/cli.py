"""`converge` command line: write events, query state, compute cutoff, gate, render."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

from . import angles as angles_mod
from . import config as config_mod
from . import ledger, model, render
from .clikit import (
    Catalog,
    add_mode_flags,
    caller_cwd,
    caller_path,
    emit,
    parser_class,
    refuse,
    run,
)
from .model import Slate

EXIT_OK, EXIT_NO, EXIT_REFUSED = 0, 1, 2

# Leaf command -> runnable argv after the program, shown in every refusal.
EXAMPLES = {
    "init": "init <slate> --dir <dir> --as main --mode full --lenses <a,b> --angles <file>",
    "file": "file <slate> --dir <dir> --as finder --lens <lens> --angle <angle> --origin lens "
            '--loc <path:line> --claim "<claim>" --trigger "<trigger>"',
    "find-run": "find-run <slate> --dir <dir> --as finder --lens <lens> --angle <angle> "
                '--tell "<tell>" --searches "<searches>" --positive-control "<hit>" --result none',
    "angle-na": "angle-na <slate> --dir <dir> --as finder --phase find --lens <lens> "
                '--angle <angle> --reason "<why>"',
    "refute": "refute <slate> --dir <dir> --as r1 --claim F001 --round 1 --angle <angle> "
              '--tell "<tell>" --outcome survived --evidence "<sources>" --searches "<searches>" '
              '--positive-control "<hit>"',
    "rebut": 'rebut <slate> --dir <dir> --as finder --claim F001 --stage refute '
             '--evidence "<new evidence>"',
    "cut": "cut <slate> --dir <dir> --as cutter --claim F001 --round 1 --frequency common "
           "--severity wrong-behavior --confidence traced --difficulty local "
           "--evidence <angle>=<evidence>",
    "accept": "accept <slate> --dir <dir> --as finder --claim F001 --round 1",
    "status": "status <slate> --dir <dir> --json",
    "converged": "converged <slate> --dir <dir> --phase refute",
    "cutoff": "cutoff <slate> --dir <dir>",
    "coverage": "coverage <slate> --dir <dir>",
    "gate": "gate <slate> --dir <abs-dir>",
    "render": "render <slate> --dir <dir>",
    "angles": "angles --tag find --angles <file>",
    "config": "config validate --project-root <dir>",
    "prune": "prune <slate> <slate> --project-root <dir>",
}
FREQUENT = ("file", "refute", "status", "converged")
CATALOG = Catalog(prog="converge", examples=EXAMPLES, frequent=FREQUENT,
                  legacy_json=frozenset({"status"}))


def _refuse(problems: list[str], what: str = "refused") -> NoReturn:
    refuse(f"converge: {what}:", [("", p) for p in problems], code=EXIT_REFUSED)


def _step(args: argparse.Namespace, name: str, *rest: str) -> str:
    """Runnable `converge <name>` on this slate and dir, for a `next:` line."""
    tail = "".join(f" {part}" for part in rest)
    return CATALOG.command(f"{name} {shlex.quote(args.slate)} "
                           f"--dir {shlex.quote(str(args.dir))}{tail}")


def _path(args: argparse.Namespace) -> Path:
    try:
        return ledger.slate_path(args.dir, args.slate)
    except ledger.LedgerError as exc:
        _refuse(exc.problems)


def _read(args: argparse.Namespace) -> Slate:
    try:
        return ledger.read(_path(args), args.slate)
    except ledger.LedgerError as exc:
        _refuse(exc.problems)


def _write(args: argparse.Namespace, event: dict[str, Any], *, create: bool = False,
           build: Any = None) -> dict[str, Any]:
    event = {"as": args.agent, **event} if "as" not in event else event
    try:
        return ledger.append(_path(args), args.slate, event, create=create, build=build)
    except ledger.LedgerError as exc:
        _refuse(exc.problems)


def _ids(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _opt(event: dict[str, Any], **values: Any) -> dict[str, Any]:
    event.update({k: v for k, v in values.items() if v is not None})
    return event


# ---------------------------------------------------------------------------
# git snapshots


def _ref(slate_id: str) -> str:
    return f"refs/converge/{slate_id}"


def _git(root: Path, *argv: str, env: dict[str, str] | None = None
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True,
                          env=env, check=False)


def _git_error(what: str, out: subprocess.CompletedProcess[str]) -> str:
    return f"{what} failed (exit {out.returncode}): {out.stderr.strip() or out.stdout.strip()}"


def _git_root(project_root: Path) -> tuple[Path | None, str | None]:
    """The work-tree top level of `project_root`, or the reason it is not a git repo."""
    try:
        out = _git(project_root, "rev-parse", "--show-toplevel")
    except OSError as exc:
        return None, f"git is not runnable: {exc}"
    if out.returncode != 0:
        return None, (f"--project-root {project_root} is not a git work tree: "
                      f"{out.stderr.strip()}")
    return Path(out.stdout.strip()), None


def _snapshot_commit(root: Path, slate_id: str) -> str:
    """Commit the work tree, untracked files included, through a temp index."""
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    has_head = head.returncode == 0
    with tempfile.TemporaryDirectory(prefix="converge-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        steps = [("read-tree", "HEAD")] if has_head else []
        for step in [*steps, ("add", "-A")]:
            out = _git(root, *step, env=env)
            if out.returncode != 0:
                _refuse([_git_error(f"snapshot: git {' '.join(step)}", out)])
        tree = _git(root, "write-tree", env=env)
        if tree.returncode != 0:
            _refuse([_git_error("snapshot: git write-tree", tree)])
        parent = ["-p", "HEAD"] if has_head else []
        commit = _git(root, "-c", "user.name=converge", "-c", "user.email=converge@localhost",
                      "commit-tree", tree.stdout.strip(), *parent,
                      "-m", f"converge snapshot {slate_id}", env=env)
        if commit.returncode != 0:
            _refuse([_git_error("snapshot: git commit-tree", commit)])
    return commit.stdout.strip()


def _since_problems(args: argparse.Namespace, root: Path | None
                    ) -> tuple[dict[str, str] | None, list[str]]:
    """The previous slate's {slate, snapshot}, or every failed --since check."""
    try:
        prev_path = ledger.slate_path(args.dir, args.since)
    except ledger.LedgerError as exc:
        return None, [f"--since: {p}" for p in exc.problems]
    if not prev_path.is_file():
        return None, [f"--since: prev exists: no slate {args.since!r} in {args.dir}"]
    try:
        prev = ledger.read(prev_path, args.since)
    except ledger.LedgerError as exc:
        return None, [f"--since: prev exists: slate {args.since!r} is unreadable: "
                      + "; ".join(exc.problems)]
    problems = []
    if prev.snapshot is None:
        problems.append(f"--since: prev has a snapshot sha: {args.since!r} was not started "
                        f"with --snapshot")
    elif root is not None:
        out = _git(root, "cat-file", "-e", f"{prev.snapshot}^{{commit}}")
        if out.returncode != 0:
            problems.append(f"--since: git cat-file -e {prev.snapshot}^{{commit}} failed in "
                            f"{root}: {out.stderr.strip() or 'no such commit'}")
    if prev.review_pass is None or args.review_pass != prev.review_pass + 1:
        expected = "prev pass + 1" if prev.review_pass is None else str(prev.review_pass + 1)
        problems.append(f"--since: --pass must equal {args.since!r}'s pass + 1 ({expected}); "
                        f"got {args.review_pass}")
    if problems or prev.snapshot is None:
        return None, problems
    return {"slate": args.since, "snapshot": prev.snapshot}, []


def _snapshot_problems(args: argparse.Namespace) -> list[str]:
    """Flag checks that need no git or ledger read."""
    problems = []
    if args.review_pass is not None and args.review_pass < 1:
        problems.append(f"--pass must be >= 1; got {args.review_pass}")
    if args.snapshot and args.review_pass is None:
        problems.append("--snapshot requires --pass <n>")
    if args.since is not None and not args.snapshot:
        problems.append("--since requires --snapshot")
    return problems


# ---------------------------------------------------------------------------
# write commands


def cmd_init(args: argparse.Namespace) -> None:
    try:
        resolved = config_mod.resolve(args.project_root, args.config)
    except config_mod.ConfigError as exc:
        _refuse(exc.problems, "invalid configuration")
    effective = resolved["effective"]
    try:
        rows = angles_mod.resolve(args.angles, effective, Path(resolved["project_root"]))
    except angles_mod.AngleError as exc:
        _refuse(exc.problems, "invalid angles")
    if args.review_pass is not None and args.review_pass >= 2:
        effective = {**effective, "cutoff": {**effective["cutoff"],
                                             **copy.deepcopy(config_mod.REREVIEW_CUTOFF)}}
    event: dict[str, Any] = {"event": "init", "mode": args.mode, "lenses": _ids(args.lenses),
                             "angles": rows, "config": effective}
    if args.review_pass is not None:
        event["pass"] = args.review_pass
    problems = _snapshot_problems(args)
    if not args.snapshot:
        if problems:
            _refuse(problems)
        event = _write(args, event, create=True)
    else:
        event = _init_snapshot(args, event, problems)
    path = _path(args)
    step = None
    if event["mode"] == "refute-only":
        step = "file every slate claim: " + _step(
            args, "file", "--as slate --origin slate --loc <path:line>",
            '--claim "<text>" --trigger "<what reaches it>"')
    data: dict[str, Any] = {"slate": args.slate, "mode": event["mode"], "lenses": event["lenses"],
                            "angles": len(rows), "path": str(path)}
    head = (f"INIT {args.slate} mode={event['mode']} lenses={','.join(event['lenses']) or '-'} "
            f"angles={len(rows)} path={path}")
    for key in ("pass", "snapshot"):
        if key in event:
            data[key] = event[key]
            head += f" {key}={event[key]}"
    lines = [head]
    if "since" in event:
        delta = f"git diff {event['since']['snapshot']} {event['snapshot']}"
        data["since"], data["diff"] = event["since"]["slate"], delta
        lines.append(f"DIFF since {event['since']['slate']}: {delta}")
    emit(args.output_mode, data, lines, step)


def _init_snapshot(args: argparse.Namespace, event: dict[str, Any],
                   problems: list[str]) -> dict[str, Any]:
    """Check every --snapshot/--since precondition, pin the snapshot ref, then append init;
    a failed append deletes the ref."""
    root, reason = _git_root(args.project_root)
    if reason:
        problems.append(f"--snapshot requires a git --project-root: {reason}")
    since = None
    if args.since is not None and args.review_pass is not None:
        since, since_problems = _since_problems(args, root)
        problems.extend(since_problems)
    path = _path(args)
    if path.is_file():
        try:
            ledger.read(path, args.slate)
            problems.append(f"slate {args.slate!r} is already initialised in {args.dir}")
        except ledger.LedgerError as exc:
            if path.stat().st_size:
                problems.extend(exc.problems)
    if problems:
        _refuse(problems)
    assert root is not None
    sha = _snapshot_commit(root, args.slate)
    pinned = _git(root, "update-ref", _ref(args.slate), sha)
    if pinned.returncode != 0:
        _refuse([_git_error(f"pin: git update-ref {_ref(args.slate)} {sha}", pinned)])
    event = {"as": args.agent, **event, "snapshot": sha}
    if since is not None:
        event["since"] = since
    try:
        return ledger.append(path, args.slate, event, create=True)
    except BaseException as exc:
        removed = _git(root, "update-ref", "-d", _ref(args.slate))
        if removed.returncode == 0:
            cleanup = f"removed {_ref(args.slate)}"
        else:
            cleanup = (_git_error(f"remove {_ref(args.slate)}", removed)
                       + f"; run: converge prune {args.slate} --project-root {root}")
        if isinstance(exc, ledger.LedgerError):
            _refuse([*exc.problems, cleanup])
        raise


def cmd_file(args: argparse.Namespace) -> None:
    event = _opt({"event": "file", "loc": args.loc, "claim": args.claim,
                  "trigger": args.trigger, "origin": args.origin},
                 lens=args.lens, angle=args.angle, rule=args.rule,
                 depends=_ids(args.depends) if args.depends else None)
    written = _write(args, event, build=lambda s: {"id": model.claim_id(len(s.claims) + 1)})
    emit(args.output_mode, {"id": written["id"]}, f"FILED {written['id']}")


def cmd_find_run(args: argparse.Namespace) -> None:
    result: Any = "none" if args.result.strip() == "none" else _ids(args.result)
    written = _write(args, {"event": "find-run", "lens": args.lens, "angle": args.angle,
                            "tell": args.tell, "searches": args.searches,
                            "positive_control": args.positive_control, "result": result})
    emit(args.output_mode, {"seq": written["seq"], "lens": args.lens, "angle": args.angle},
         f"FIND-RUN seq={written['seq']} lens={args.lens} angle={args.angle}")


def cmd_angle_na(args: argparse.Namespace) -> None:
    event = _opt({"event": "angle-na", "phase": args.phase, "angle": args.angle,
                  "reason": args.reason}, lens=args.lens)
    written = _write(args, event)
    emit(args.output_mode, {"seq": written["seq"], "phase": args.phase, "angle": args.angle},
         f"ANGLE-NA seq={written['seq']} phase={args.phase} angle={args.angle}")


def cmd_refute(args: argparse.Namespace) -> None:
    event = _opt({"event": "refute", "claim": args.claim, "round": args.round,
                  "angle": args.angle, "tell": args.tell, "outcome": args.outcome,
                  "evidence": args.evidence, "searches": args.searches,
                  "positive_control": args.positive_control},
                 narrowed=args.narrowed, source=args.source, ledger_evidence=args.ledger_evidence)
    written = _write(args, event)
    emit(args.output_mode, {"seq": written["seq"], "claim": args.claim, "round": args.round,
                            "outcome": args.outcome},
         f"REFUTE seq={written['seq']} {args.claim} round={args.round} outcome={args.outcome}")


def cmd_rebut(args: argparse.Namespace) -> None:
    written = _write(args, {"event": "rebut", "claim": args.claim, "stage": args.stage,
                            "evidence": args.evidence,
                            "evidence_sha256": ledger.evidence_hash(args.evidence)})
    emit(args.output_mode, {"seq": written["seq"], "claim": args.claim, "stage": args.stage},
         f"REBUT seq={written['seq']} {args.claim} stage={args.stage}")


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
    event = _opt({"event": "cut", "claim": args.claim, "round": args.round,
                  "frequency": args.frequency, "severity": args.severity,
                  "confidence": args.confidence, "difficulty": args.difficulty,
                  "evidence": evidence}, choice=args.choice)
    written = _write(args, event)
    emit(args.output_mode, {"seq": written["seq"], "claim": args.claim, "round": args.round},
         f"CUT seq={written['seq']} {args.claim} round={args.round}")


def cmd_accept(args: argparse.Namespace) -> None:
    written = _write(args, {"event": "accept", "claim": args.claim, "round": args.round})
    emit(args.output_mode, {"seq": written["seq"], "claim": args.claim, "round": args.round},
         f"ACCEPT seq={written['seq']} {args.claim} round={args.round}")


def cmd_cutoff(args: argparse.Namespace) -> None:
    slate = _read(args)
    if slate.mode == "refute-only":
        _refuse(["refute-only slate has no cut stage"])
    problems = _coverage_problems(slate)
    problems.extend(f"{claim.id} is open in {phase}" for claim, phase in slate.open_claims())
    if problems:
        _refuse(problems)
    if not slate.cutoff_valid:
        def build(current: Slate) -> dict[str, Any]:
            return {"results": model.cutoff_results(model.compute_cutoff(current))}
        _write(args, {"event": "cutoff", "as": model.CONVERGE_AGENT}, build=build)
        slate = _read(args)
    assert slate.cutoff is not None
    rows = model.compute_cutoff(slate)
    emit(args.output_mode,
         {"seq": slate.cutoff["seq"],
          "rows": [{"claim": row.claim.id, "result": row.result, "rank": row.rank,
                    "reason": row.reason} for row in rows]},
         [f"CUTOFF seq={slate.cutoff['seq']}",
          *(f"{row.claim.id} {row.result} rank={row.rank} reason={row.reason}" for row in rows)],
         _step(args, "render"))


# ---------------------------------------------------------------------------
# read commands


def _claim_status(slate: Slate, claim: model.Claim) -> dict[str, Any]:
    used = claim.used_angles
    status: dict[str, Any] = {
        "id": claim.id,
        "stage": "dead" if claim.dead else claim.stage,
        "refute": slate.refute_state(claim),
        "round": claim.refute_round,
        "reopened": claim.reopened,
        "lens": claim.lens,
        "origin": claim.origin,
        "finder": claim.finder,
        "claim": claim.text,
        "unused_attack_angles": [a for a in slate.angle_ids("attack") if a not in used],
    }
    if slate.mode == "full":
        status["cut"] = slate.cut_state(claim) if slate.refute_state(claim) in model.REFUTE_DONE else "-"
        status["cut_round"] = claim.cut_round
        status["accepted_round"] = claim.accepted_round or None
        status["cut_note"] = model.cut_note(claim, slate.cap("cut_rounds"))
    return status


def _status_phase(slate: Slate) -> tuple[str, int]:
    open_claims = slate.open_claims()
    if not slate.claims:
        phase = "find"
    elif open_claims:
        phase = open_claims[0][1]
    else:
        phase = "complete"
    current_round = max((max(claim.refute_round, claim.cut_round)
                         for claim in slate.claims.values()), default=0)
    return phase, current_round


def _coverage_problems(slate: Slate) -> list[str]:
    return [f"lens {lens} has missing find angles: {', '.join(row.missing)}"
            for lens, row in render.coverage(slate).items() if row.missing]


def _legal_event_types(slate: Slate) -> list[str]:
    legal = {"file"}
    phase, _ = _status_phase(slate)
    if slate.mode == "full" and (phase == "find" or _coverage_problems(slate)):
        legal.update({"find-run", "angle-na"})
    for claim in slate.live_claims():
        refute = slate.refute_state(claim)
        if refute not in model.REFUTE_DONE:
            legal.update({"refute", "rebut"})
        elif slate.mode == "full" and slate.cut_state(claim) not in model.CUT_DONE:
            legal.update({"cut", "accept", "rebut"})
    if (slate.mode == "full" and not _coverage_problems(slate)
            and not slate.open_claims() and not slate.cutoff_valid):
        legal.add("cutoff")
    if slate.cutoff_valid:
        legal.add("render")
    return sorted(legal)


def _unresolved_choices(slate: Slate) -> list[dict[str, str]]:
    if slate.mode != "full" or not slate.cutoff_valid:
        return []
    return [{"claim": row.claim.id, "result": row.result, "choice": choice}
            for row in model.compute_cutoff(slate)
            if (choice := (row.claim.last_cut() or {}).get("choice"))]


def cmd_status(args: argparse.Namespace) -> None:
    slate = _read(args)
    claims = [_claim_status(slate, c) for c in slate.claims.values()]
    cutoff = "current" if slate.cutoff_valid else ("stale" if slate.cutoff else "none")
    agents = slate.agent_ids()
    phase, current_round = _status_phase(slate)
    legal_events = _legal_event_types(slate)
    if args.json:
        emit(args.output_mode, {}, [], json_text=json.dumps(
            {"slate": slate.slate_id, "mode": slate.mode, "lenses": slate.lenses,
             "cutoff": cutoff, "agents": agents, "agent_cap": slate.cap("agents"),
             "phase": phase, "round": current_round, "legal_event_types": legal_events,
             "claims": claims}, indent=2))
        return
    lines = [(f"SLATE {slate.slate_id} mode={slate.mode} lenses={','.join(slate.lenses) or '-'} "
              f"cutoff={cutoff} phase={phase} round={current_round} "
              f"claims={len(claims)} agents={len(agents)}/{slate.cap('agents')} "
              f"legal={','.join(legal_events) or '-'}")]
    for c in claims:
        cut = (f" cut={c['cut']} cut_round={c['cut_round']} accepted={c['accepted_round'] or '-'}"
               if "cut" in c else "")
        reopened = " reopened" if c["reopened"] else ""
        lines.append(f"{c['id']} stage={c['stage']} refute={c['refute']} round={c['round']}"
                     f"{cut}{reopened} unused={','.join(c['unused_attack_angles']) or '-'}")
    emit(args.output_mode, {}, lines)


def cmd_converged(args: argparse.Namespace) -> None:
    slate = _read(args)
    if args.phase == "cut" and slate.mode == "refute-only":
        _refuse(["refute-only slate has no cut stage"])
    pending = []
    for claim in slate.live_claims():
        rstate = slate.refute_state(claim)
        if args.phase == "refute":
            if rstate not in model.REFUTE_DONE:
                pending.append(f"{claim.id} refute={rstate} round={claim.refute_round}")
        elif rstate not in model.REFUTE_DONE:
            pending.append(f"{claim.id} refute={rstate} (cut not started)")
        elif slate.cut_state(claim) not in model.CUT_DONE:
            pending.append(f"{claim.id} cut={slate.cut_state(claim)} cut_round={claim.cut_round}")
    data = {"phase": args.phase, "converged": not pending, "pending": pending}
    if pending:
        step = (_step(args, "status", "--json") if args.phase == "refute"
                else "continue the cutter with the listed claims")
        emit(args.output_mode, data, [f"OPEN phase={args.phase} claims={len(pending)}", *pending],
             step)
        sys.exit(EXIT_NO)
    # A converged refute phase leaves gap hunt vs cut to the caller: no step.
    emit(args.output_mode, data, f"CONVERGED phase={args.phase}",
         _step(args, "cutoff") if args.phase == "cut" else None)


def cmd_coverage(args: argparse.Namespace) -> None:
    slate = _read(args)
    coverage = render.coverage(slate)
    lines = []
    for lens, row in coverage.items():
        lines.append(f"LENS {lens} ran={','.join(row.ran) or '-'} na={','.join(row.na) or '-'} "
                     f"missing={','.join(row.missing) or '-'}")
        lines.extend(f"NA {lens} {angle_id} {reason}" for angle_id, reason in row.na.items())
    if any(row.missing for row in coverage.values()):
        step = "continue the finder with the missing angles, then " + _step(args, "coverage")
    else:
        step = _step(args, "status", "--json")
    emit(args.output_mode,
         {"lenses": {lens: {"ran": row.ran, "na": row.na, "missing": row.missing}
                     for lens, row in coverage.items()}},
         lines, step)


def cmd_gate(args: argparse.Namespace) -> None:
    if not args.dir.is_absolute():
        _refuse([f"gate needs an absolute --dir; got {str(args.dir)!r}"])
    path = _path(args)
    if not path.is_file():
        _refuse([f"no slate {args.slate!r} in {args.dir} (expected {path})"])
    slate = _read(args)
    if slate.mode == "refute-only":
        _refuse(["refute-only slate has no cut stage"])
    problems = []
    problems.extend(_coverage_problems(slate))
    for claim, phase in slate.open_claims():
        problems.append(f"{claim.id} is open in {phase}")
    if not slate.cutoff_valid:
        problems.append("no current cutoff (run `converge cutoff` after the last state change)")
    cutoff_seq = slate.cutoff["seq"] if slate.cutoff else None
    data = {"slate": args.slate, "ok": not problems, "problems": problems, "cutoff_seq": cutoff_seq}
    if problems:
        emit(args.output_mode, data, [f"GATE fail {args.slate}", *problems])
        sys.exit(EXIT_NO)
    shown = "-" if cutoff_seq is None else cutoff_seq
    emit(args.output_mode, data, f"GATE ok {args.slate} cutoff_seq={shown}")


def cmd_render(args: argparse.Namespace) -> None:
    slate = _read(args)
    markdown = render.render(slate)
    if args.output_mode == "json":
        emit(args.output_mode, {"slate": args.slate, "markdown": markdown,
                                "choices": _unresolved_choices(slate)}, [])
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
    rows = [row for row in rows if not args.tag or row["tag"] == args.tag]
    lines = []
    for row in rows:
        extra = "".join(f" {k}={row[k]}" for k in ("field", "lens") if k in row)
        lines.append(f"{row['tag']} {row['id']}{extra} — tell: {row['tell']} — asks: {row['asks']}")
    emit(args.output_mode, {"angles": rows}, lines)


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


# ---------------------------------------------------------------------------
# parser


def _parser() -> argparse.ArgumentParser:
    parser = parser_class(CATALOG)(prog="converge", description=__doc__)
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

    def config_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", type=caller_path, help="task-layer converge.yaml")
        p.add_argument("--project-root", type=caller_path, default=caller_cwd())

    p = command("init", cmd_init, write=True)
    p.add_argument("--mode", required=True, choices=model.MODE)
    p.add_argument("--lenses", default="")
    p.add_argument("--angles", nargs="*", type=caller_path, default=[])
    p.add_argument("--snapshot", action="store_true",
                   help="pin a work-tree snapshot commit at refs/converge/<slate>")
    p.add_argument("--pass", dest="review_pass", type=int, metavar="N",
                   help="review pass number; N >= 2 uses the re-review cutoff")
    p.add_argument("--since", metavar="PREV_SLATE",
                   help="previous pass's slate; prints the git diff between the snapshots")
    config_args(p)

    p = command("file", cmd_file, write=True)
    p.add_argument("--lens")
    p.add_argument("--angle")
    p.add_argument("--loc", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--trigger", required=True)
    p.add_argument("--origin", required=True)
    p.add_argument("--depends")
    p.add_argument("--rule")

    p = command("find-run", cmd_find_run, write=True)
    for flag in ("--lens", "--angle", "--tell", "--searches", "--positive-control", "--result"):
        p.add_argument(flag, required=True)

    p = command("angle-na", cmd_angle_na, write=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--angle", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--lens")

    p = command("refute", cmd_refute, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--round", required=True, type=int)
    for flag in ("--angle", "--tell", "--outcome", "--evidence", "--searches", "--positive-control"):
        p.add_argument(flag, required=True)
    p.add_argument("--narrowed")
    p.add_argument("--source")
    p.add_argument("--ledger-evidence")

    p = command("rebut", cmd_rebut, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--evidence", required=True)

    p = command("cut", cmd_cut, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--round", required=True, type=int)
    for name in model.CUT_FIELDS:
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--evidence", action="append", default=[], metavar="ANGLE=TEXT")
    p.add_argument("--choice")

    p = command("accept", cmd_accept, write=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--round", required=True, type=int)

    p = command("status", cmd_status)
    p.add_argument("--json", action="store_true")
    p = command("converged", cmd_converged)
    p.add_argument("--phase", required=True, choices=("refute", "cut"))
    command("cutoff", cmd_cutoff)
    command("coverage", cmd_coverage)
    command("gate", cmd_gate, dir_required=True)
    command("render", cmd_render)

    p = command("prune", cmd_prune, slate=False)
    p.add_argument("slates", nargs="+", metavar="slate")
    p.add_argument("--project-root", type=caller_path, default=caller_cwd())

    p = command("angles", cmd_angles, slate=False)
    p.add_argument("--tag", choices=angles_mod.TAGS)
    p.add_argument("--angles", nargs="*", type=caller_path, default=[])
    config_args(p)

    p = command("config", cmd_config, slate=False)
    p.add_argument("action", choices=("validate", "resolve"))
    config_args(p)
    add_mode_flags(parser)
    return parser


def main(argv: list[str] | None = None) -> None:
    run(_parser(), CATALOG, lambda a: a.command, argv)


if __name__ == "__main__":
    main()
