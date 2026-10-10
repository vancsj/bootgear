"""Output for an LLM reader: prose by default, explicit JSON, runnable refusals, caller paths, and `next:` steps."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from conftest import (
    BATCH_1,
    BIN,
    CUT_EVIDENCE,
    CUTTER,
    DISABLED,
    FINDER,
    MAIN,
    PLUGIN_DIR,
    R1,
    R2,
    Converge,
)

sys.path.insert(0, str(PLUGIN_DIR / "src"))
from converge import cli, clikit

# An invalid mode value is ignored, so the shared default is prose.
PIPE = {"BOOTGEAR_OUTPUT": ""}


def _json(cv: Converge, *args: str, code: int = 0, env: dict[str, str] | None = None) -> Any:
    return json.loads(cv(*args, "--json", code=code, env={**PIPE, **(env or {})}).stdout)


def _error(cv: Converge, *args: str, code: int = 2) -> dict[str, Any]:
    result = cv(*args, "--json", code=code, env=PIPE)
    assert result.stdout == ""
    return json.loads(result.stderr)["error"]


def _init_args(cv: Converge, lenses: str = "correctness,security") -> list[str]:
    steps = cv.root / "steps.yaml"
    steps.write_text(yaml.safe_dump({"steps": {"cut": "before", "gap_hunt": False},
                                     "angles": {"disable": DISABLED}}))
    return ["init", "s1", "--dir", str(cv.dir), "--as", MAIN, "--lenses", lenses,
            "--angles", str(cv.angles), "--project-root", str(cv.project),
            "--config", str(steps)]


def _file_args(cv: Converge, angle: str = "changed-contract", loc: str = "a.py:1") -> list[str]:
    return ["file", "s1", "--dir", str(cv.dir), "--as", FINDER, "--lens", "correctness",
            "--angle", angle, "--origin", "lens", "--loc", loc, "--claim", "c",
            "--trigger", "t"]


def _cut_args(cv: Converge, claim: str, rnd: int, frequency: str = "common") -> list[str]:
    return ["cut", "s1", "--dir", str(cv.dir), "--as", CUTTER, "--claim", claim,
            "--round", str(rnd), "--when", "before", "--frequency", frequency,
            "--severity", "wrong-behavior", "--confidence", "inferred", "--difficulty", "local",
            *CUT_EVIDENCE]


def _attack_args(cv: Converge, angle: str, agent: str, batch: str, outcome: str) -> list[str]:
    return ["attack", "s1", "--dir", str(cv.dir), "--as", agent, "--claim", "F001",
            "--batch", batch, "--angle", angle, "--tell", "t", "--outcome", outcome,
            "--evidence", "e", "--searches", "s", "--positive-control", "p"]


def _next(cv: Converge, rest: str) -> str:
    return f"converge {rest.format(dir=shlex.quote(str(cv.dir)))}"


# ---------------------------------------------------------------------------
# JSON per command


def test_explicit_json_is_json_for_every_command(cv: Converge) -> None:
    # Through the shipped wrapper, so every subcommand runs on the plugin's own declared
    # dependencies at least once.
    cv.use_bin = True
    d = str(cv.dir)
    plan = _next(cv, "status s1 --dir {dir} --json")
    init = _json(cv, *_init_args(cv))
    assert init == {"slate": "s1", "lenses": ["correctness", "security"],
                    "angles": init["angles"], "path": str(cv.path())}
    assert isinstance(init["angles"], int) and init["angles"] > 0
    assert _json(cv, "status", "s1", "--dir", d)["phase"] == "find"
    initial_cutoff_error = _error(cv, "cutoff", "s1", "--dir", d)
    assert any("missing find angles" in item for group in initial_cutoff_error["problems"]
               for item in group["items"])

    find = "continue the finder with the missing angles, then " + _next(cv, "coverage s1 --dir {dir}")
    assert _json(cv, *_file_args(cv)) == {"id": "F001", "next": find}
    run = _json(cv, "find-run", "s1", "--dir", d, "--as", FINDER, "--lens", "correctness",
                "--angle", "changed-contract", "--tell", "t", "--searches", "s",
                "--positive-control", "p", "--result", "F001")
    assert run == {"seq": run["seq"], "lens": "correctness", "angle": "changed-contract",
                   "next": find}
    na = _json(cv, "angle-na", "s1", "--dir", d, "--as", FINDER, "--phase", "find",
               "--angle", "failure-path", "--lens", "security", "--reason", "no I/O")
    assert na == {"seq": run["seq"] + 1, "phase": "find", "angle": "failure-path", "next": find}
    assert _json(cv, "coverage", "s1", "--dir", d) == {
        "lenses": {"correctness": {"ran": ["changed-contract"], "na": {},
                                   "missing": ["failure-path"]},
                   "security": {"ran": [], "na": {"failure-path": "no I/O"},
                                "missing": ["changed-contract"]}},
        "next": find}
    _json(cv, "find-run", "s1", "--dir", d, "--as", FINDER, "--lens", "security",
          "--angle", "changed-contract", "--tell", "t", "--searches", "s",
          "--positive-control", "p", "--result", "none")
    _json(cv, "angle-na", "s1", "--dir", d, "--as", FINDER, "--phase", "find",
          "--angle", "failure-path", "--lens", "correctness", "--reason", "no I/O")

    escalate = _json(cv, "escalate", "s1", "--dir", d, "--as", FINDER, "--claim", "F001")
    assert escalate == {"seq": escalate["seq"], "claim": "F001", "wider": False,
                        "next": f"cut-before: cutter cut-before F001; plan: {plan}"}
    cut = _json(cv, *_cut_args(cv, "F001", 1))
    assert cut == {"seq": cut["seq"], "claim": "F001", "when": "before", "round": 1,
                   "next": f"cut-before: finder accept F001; plan: {plan}"}
    rebut = _json(cv, "rebut", "s1", "--dir", d, "--as", FINDER, "--claim", "F001",
                  "--when", "before", "--evidence", "prod shows every call")
    assert rebut == {"seq": rebut["seq"], "claim": "F001", "when": "before",
                     "next": f"cut-before: cutter cut-before F001; plan: {plan}"}
    _json(cv, *_cut_args(cv, "F001", 2, "every-call"))
    accept = _json(cv, "accept", "s1", "--dir", d, "--as", FINDER, "--claim", "F001",
                   "--when", "before", "--round", "2")
    attack_step = f"attack: r1 attack F001 batch 1; plan: {plan}"
    assert accept == {"seq": accept["seq"], "claim": "F001", "when": "before", "round": 2,
                      "next": attack_step}

    assert _json(cv, "gate", "s1", "--dir", d, code=1) == {
        "slate": "s1", "ok": False, "cutoff_seq": None,
        "problems": ["F001 is open in attack",
                     "no current cutoff (run `converge cutoff` after the last state change)"],
        "next": attack_step}
    assert _json(cv, "converged", "s1", "--dir", d, code=1) == {
        "converged": False, "phase": "attack", "pending": ["F001 open in attack"],
        "next": attack_step}
    attacks = [_json(cv, *_attack_args(cv, angle, R1, "1",
                                       "refuted" if angle == BATCH_1[0] else "clean"))
               for angle in BATCH_1]
    attack = attacks[-1]
    assert attacks[0]["outcome"] == "refuted"
    assert attack == {"seq": attack["seq"], "claim": "F001", "batch": 1, "angle": BATCH_1[-1],
                      "outcome": "clean", "next": f"attack: finder reply F001 batch 1; plan: {plan}"}
    reply = _json(cv, "reply", "s1", "--dir", d, "--as", FINDER, "--claim", "F001", "--batch", "1",
                  "--stance", "rebut", "--evidence", "b.py:4 passes None")
    assert reply == {"seq": reply["seq"], "claim": "F001", "batch": 1, "stance": "rebut",
                     "next": f"attack: r1 verdict F001 batch 1; plan: {plan}"}
    verdict = _json(cv, "verdict", "s1", "--dir", d, "--as", R1, "--claim", "F001",
                    "--batch", "1", "--verdict", "agree")
    assert verdict == {"seq": verdict["seq"], "claim": "F001", "batch": 1, "verdict": "agree",
                       "next": f"attack: r2 attack F001 batch fresh-eye; plan: {plan}"}
    fresh = _json(cv, *_attack_args(cv, "retry timing", R2, "fresh-eye", "clean"), "--last")
    assert fresh["batch"] == "fresh-eye"
    assert fresh["next"] == _next(cv, "cutoff s1 --dir {dir}")

    cutoff = _json(cv, "cutoff", "s1", "--dir", d)
    assert cutoff == {"seq": cutoff["seq"],
                      "rows": [{"claim": "F001", "status": "survived", "cut": "no",
                                "result": "finding", "rank": 1, "reason": "report_if[1]"}],
                      "next": _next(cv, "render s1 --dir {dir}")}
    assert _json(cv, "gate", "s1", "--dir", d) == {
        "slate": "s1", "ok": True, "problems": [], "cutoff_seq": cutoff["seq"],
        "next": _next(cv, "converged s1 --dir {dir}")}
    rendered = _json(cv, "render", "s1", "--dir", d)
    assert rendered == {"slate": "s1", "markdown": cv.ok("render", "s1").stdout,
                        "choices": []}
    assert "findings=1 follow-up=0 killed=0 converged=yes" in rendered["markdown"]
    assert _json(cv, "converged", "s1", "--dir", d) == {
        "converged": True, "phase": "done", "pending": [],
        "next": "end the slate with outcome converged"}
    status = cv("status", "s1", "--dir", d, "--json", env=PIPE).stdout
    status_data = json.loads(status)
    assert status.startswith("{\n  ") and status_data["claims"][0]["id"] == "F001"
    assert {"phase", "steps", "caps", "plan", "refuters", "next"} <= set(status_data)
    assert status_data["phase"] == "done"

    angles = _json(cv, "angles", "--tag", "decide", "--project-root", str(cv.project))["angles"]
    assert {row["tag"] for row in angles} == {"decide"}
    assert "reversibility" in {row["id"] for row in angles}
    validate = _json(cv, "config", "validate", "--project-root", str(cv.project))
    assert validate["valid"] is True and validate["sources"]
    assert {"layer", "present", "path"} <= set(validate["sources"][0])
    resolved = _json(cv, "config", "resolve", "--project-root", str(cv.project))
    assert resolved == json.loads(cv("config", "resolve", "--project-root", str(cv.project), "--json").stdout)
    prune = cv.root / "git"
    prune.mkdir()
    subprocess.run(["git", "init", "-q", str(prune)], check=True)
    assert _json(cv, "prune", "s9", "--project-root", str(prune)) == {"pruned": [],
                                                                      "missing": ["s9"]}


def test_pipe_default_is_prose(cv: Converge) -> None:
    result = cv(*_init_args(cv), env=PIPE)
    assert result.stdout.startswith("INIT s1 lenses=correctness,security ")


def test_prose_on_a_regular_file_and_with_prose_flag(cv: Converge, tmp_path: Path) -> None:
    cv.init()
    out = tmp_path / "out.txt"
    with out.open("w") as handle:
        subprocess.run([str(BIN), "status", "s1", "--dir", str(cv.dir)], stdout=handle,
                       env={**cv.env, **PIPE}, cwd=cv.project, check=True)
    assert out.read_text().startswith("SLATE s1 lenses=")
    piped = cv("status", "s1", "--dir", str(cv.dir), "--prose", env=PIPE).stdout
    assert piped.startswith("SLATE s1 lenses=")
    assert json.loads(cv("status", "s1", "--dir", str(cv.dir), "--json").stdout)["slate"] == "s1"


def test_both_mode_flags_refused(cv: Converge) -> None:
    cv.init()
    err = cv("status", "s1", "--dir", str(cv.dir), "--json", "--prose", code=2).stderr
    assert err.startswith("--json and --prose are mutually exclusive\n")
    assert f"example: converge {cli.EXAMPLES['status']}" in err


# ---------------------------------------------------------------------------
# refusals name the example, the sibling commands and the frequent ones


def test_argparse_refusal_prose(cv: Converge) -> None:
    err = cv("cut", "s1", "--dir", str(cv.dir), "--as", CUTTER, code=2).stderr
    lines = err.splitlines()
    assert lines[0].startswith("converge cut: error: the following arguments are required: ")
    assert "usage:" not in err
    assert lines[1] == f"example: converge {cli.EXAMPLES['cut']}"
    assert lines[2] == "commands: " + ", ".join(k for k in cli.EXAMPLES if k != "cut")
    assert lines[3:] == [f"  converge {cli.EXAMPLES[k]}" for k in cli.FREQUENT if k != "cut"]


def test_domain_refusal_prose_keeps_first_lines(cv: Converge) -> None:
    cv.init()
    err = cv(*_file_args(cv, angle="nope"), code=2).stderr
    lines = err.splitlines()
    assert lines[:2] == ["converge: refused:",
                         "  - unknown find angle 'nope' (not in this slate's init snapshot)"]
    assert lines[2] == f"example: converge {cli.EXAMPLES['file']}"
    assert lines[3].startswith("commands: init, escalate, ")


def test_domain_refusal_json_and_display_prog(cv: Converge) -> None:
    cv.init()
    result = cv(*_file_args(cv, angle="nope"), "--json", code=2,
                env={**PIPE, "BOOTGEAR_PROG": "/p/scripts/converge"})
    error = json.loads(result.stderr)["error"]
    assert error["command"] == "file"
    assert error["message"] == "converge: refused:"
    assert error["example"] == f"/p/scripts/converge {cli.EXAMPLES['file']}"
    assert "file" not in error["commands"] and "init" in error["commands"]
    assert set(error["examples"]) == set(cli.FREQUENT) - {"file"}


def test_argparse_refusal_json(cv: Converge) -> None:
    error = _error(cv, "init", "s1", "--dir", str(cv.dir), "--as", MAIN, "--refuters", "3")
    assert error["command"] == "init"
    assert error["message"].startswith("converge init: error: argument --refuters: invalid choice")
    assert error["example"] == f"converge {cli.EXAMPLES['init']}"


# ---------------------------------------------------------------------------
# every problem in one refusal


def test_every_ledger_problem_in_one_refusal(cv: Converge) -> None:
    cv.init()
    error = _error(cv, *_file_args(cv, angle="nope", loc="no-line"))
    assert error["problems"] == [{"kind": "", "items": [
        "`loc` must match path:line (\\A[^:\\s]+:\\d+\\Z); got 'no-line'",
        "unknown find angle 'nope' (not in this slate's init snapshot)"]}]


# ---------------------------------------------------------------------------
# relative paths resolve against the caller's directory


def test_relative_paths_resolve_against_caller_cwd(cv: Converge) -> None:
    caller = {"GEAR_CALLER_CWD": str(cv.root)}
    out = cv("init", "s1", "--dir", "ledgers", "--as", MAIN,
             "--lenses", "correctness", "--angles", "find-angles.yaml",
             "--project-root", "project", env=caller).stdout
    assert out.startswith("INIT s1 lenses=correctness ")
    assert out.rstrip().endswith(f"path={cv.path()}")
    assert cv.path().is_file()
    assert "changed-contract" in {r["id"] for r in cv.events()[0]["angles"]}
    finds = cv("angles", "--tag", "find", "--angles", "find-angles.yaml", env=caller).stdout
    assert "find changed-contract" in finds


def test_gate_still_refuses_relative_dir(cv: Converge) -> None:
    cv.init()
    rel = os.path.relpath(cv.dir, cv.root)
    err = cv("gate", "s1", "--dir", rel, code=2, env={"GEAR_CALLER_CWD": str(cv.root)}).stderr
    lines = err.splitlines()
    assert lines[:2] == ["converge: refused:", f"  - gate needs an absolute --dir; got {rel!r}"]
    assert lines[2] == "example: converge gate <slate> --dir <abs-dir>"


# ---------------------------------------------------------------------------
# coverage and its `next:` step


def test_coverage_command(cv: Converge) -> None:
    cv.init()
    cid = cv.file()
    cv.ok("find-run", "s1", "--as", FINDER, "--lens", "correctness",
          "--angle", "changed-contract", "--tell", "signature changed", "--searches", "rg parse(",
          "--positive-control", "rg def parse finds it", "--result", cid)
    cv.ok("angle-na", "s1", "--as", FINDER, "--phase", "find", "--angle",
          "failure-path", "--lens", "security", "--reason", "no I/O in the diff")
    out = cv.ok("coverage", "s1").stdout
    assert "LENS correctness ran=changed-contract na=- missing=failure-path" in out
    assert "LENS security ran=- na=failure-path missing=changed-contract" in out
    assert "NA security failure-path no I/O in the diff" in out


def test_next_after_coverage(cv: Converge) -> None:
    cv.init(lenses="correctness")
    lines = cv.ok("coverage", "s1").stdout.splitlines()
    assert lines[0] == "LENS correctness ran=- na=- missing=changed-contract,failure-path"
    assert lines[-1] == ("next: continue the finder with the missing angles, then "
                         + _next(cv, "coverage s1 --dir {dir}"))
    for angle in ("changed-contract", "failure-path"):
        cv.ok("angle-na", "s1", "--as", FINDER, "--phase", "find", "--angle", angle,
              "--lens", "correctness", "--reason", "n/a")
    assert cv.ok("coverage", "s1").stdout.splitlines()[-1] == (
        "next: " + _next(cv, "status s1 --dir {dir} --json"))


# ---------------------------------------------------------------------------
# `next:` names the step after the command


def test_next_after_cutoff_and_converged(cv: Converge) -> None:
    cv.ready(cut="none")
    cv.batch_1()
    open_attack = cv.ok("converged", "s1", code=1).stdout.splitlines()
    assert open_attack == ["OPEN phase=attack claims=1", "F001 open in attack",
                           "next: attack: r2 attack F001 batch fresh-eye; plan: "
                           + _next(cv, "status s1 --dir {dir} --json")]
    cv.fresh_eye()
    assert cv.ok("converged", "s1", code=1).stdout.splitlines() == [
        "OPEN phase=cutoff claims=0", "next: " + _next(cv, "cutoff s1 --dir {dir}")]
    cutoff = cv.ok("cutoff", "s1").stdout.splitlines()
    assert cutoff[0].startswith("CUTOFF seq=")
    assert cutoff[-1] == "next: " + _next(cv, "render s1 --dir {dir}")
    assert "GATE ok s1" in cv("gate", "s1", "--dir", str(cv.dir)).stdout
    assert "## Findings" in cv.ok("render", "s1").stdout
    assert cv.ok("converged", "s1").stdout.splitlines() == [
        "CONVERGED", "next: end the slate with outcome converged"]


# ---------------------------------------------------------------------------
# catalog


def test_examples_cover_every_leaf_and_parse() -> None:
    parser = cli._parser()
    assert set(cli.EXAMPLES) == set(clikit.leaf_commands(parser))
    assert set(cli.FREQUENT) <= set(cli.EXAMPLES)
    for leaf, example in cli.EXAMPLES.items():
        args = parser.parse_args(shlex.split(example))
        assert args.command == leaf, example
