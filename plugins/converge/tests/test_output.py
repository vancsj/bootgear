"""Output for an LLM reader: prose by default, explicit JSON, runnable refusals, caller paths, and `next:` steps."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from conftest import (
    BIN,
    CUT_EVIDENCE,
    CUTTER,
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


def _init_args(cv: Converge, mode: str = "full", lenses: str = "correctness,security") -> list[str]:
    return ["init", "s1", "--dir", str(cv.dir), "--as", MAIN, "--mode", mode,
            "--lenses", lenses, "--angles", str(cv.angles), "--project-root", str(cv.project)]


def _refute_args(cv: Converge, claim: str, angle: str, agent: str) -> list[str]:
    return ["refute", "s1", "--dir", str(cv.dir), "--as", agent, "--claim", claim, "--round", "1",
            "--angle", angle, "--tell", "t", "--outcome", "survived", "--evidence", "e",
            "--searches", "s", "--positive-control", "p"]


def _cut_args(cv: Converge, claim: str, rnd: int, frequency: str = "common") -> list[str]:
    return ["cut", "s1", "--dir", str(cv.dir), "--as", CUTTER, "--claim", claim,
            "--round", str(rnd), "--frequency", frequency, "--severity", "wrong-behavior",
            "--confidence", "traced", "--difficulty", "local", *CUT_EVIDENCE]


def _next(cv: Converge, rest: str) -> str:
    return f"converge {rest.format(dir=shlex.quote(str(cv.dir)))}"


# ---------------------------------------------------------------------------
# JSON per command


def test_explicit_json_is_json_for_every_command(cv: Converge) -> None:
    d = str(cv.dir)
    init = _json(cv, *_init_args(cv))
    assert init == {"slate": "s1", "mode": "full", "lenses": ["correctness", "security"],
                    "angles": init["angles"], "path": str(cv.path())}
    assert isinstance(init["angles"], int) and init["angles"] > 0
    initial_status = _json(cv, "status", "s1", "--dir", d)
    assert initial_status["phase"] == "find"
    assert {"file", "find-run", "angle-na"} <= set(initial_status["legal_event_types"])
    assert "cutoff" not in initial_status["legal_event_types"]
    initial_cutoff_error = _error(cv, "cutoff", "s1", "--dir", d)
    assert any("missing find angles" in item for group in initial_cutoff_error["problems"]
               for item in group["items"])

    assert _json(cv, "file", "s1", "--dir", d, "--as", FINDER, "--lens", "correctness",
                 "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1",
                 "--claim", "c", "--trigger", "t") == {"id": "F001"}
    run = _json(cv, "find-run", "s1", "--dir", d, "--as", FINDER, "--lens", "correctness",
                "--angle", "changed-contract", "--tell", "t", "--searches", "s",
                "--positive-control", "p", "--result", "F001")
    assert run == {"seq": run["seq"], "lens": "correctness", "angle": "changed-contract"}
    na = _json(cv, "angle-na", "s1", "--dir", d, "--as", FINDER, "--phase", "find",
               "--angle", "failure-path", "--lens", "security", "--reason", "no I/O")
    assert na == {"seq": run["seq"] + 1, "phase": "find", "angle": "failure-path"}

    for angle, agent in (("boundary", R1), ("reachability", R2)):
        refute = _json(cv, *_refute_args(cv, "F001", angle, agent))
        assert refute == {"seq": refute["seq"], "claim": "F001", "round": 1, "outcome": "survived"}
    assert _json(cv, "converged", "s1", "--dir", d, "--phase", "refute") == {
        "phase": "refute", "converged": True, "pending": []}

    cut = _json(cv, *_cut_args(cv, "F001", 1))
    assert cut == {"seq": cut["seq"], "claim": "F001", "round": 1}
    assert _json(cv, "converged", "s1", "--dir", d, "--phase", "cut", code=1) == {
        "phase": "cut", "converged": False, "pending": ["F001 cut=open cut_round=1"],
        "next": "continue the cutter with the listed claims"}
    accept = _json(cv, "accept", "s1", "--dir", d, "--as", FINDER, "--claim", "F001",
                   "--round", "1")
    assert accept == {"seq": accept["seq"], "claim": "F001", "round": 1}
    assert _json(cv, "converged", "s1", "--dir", d, "--phase", "cut") == {
        "phase": "cut", "converged": True, "pending": [],
        "next": _next(cv, "cutoff s1 --dir {dir}")}
    rebut = _json(cv, "rebut", "s1", "--dir", d, "--as", FINDER, "--claim", "F001",
                  "--stage", "cut", "--evidence", "prod shows every call")
    assert rebut == {"seq": rebut["seq"], "claim": "F001", "stage": "cut"}
    _json(cv, *_cut_args(cv, "F001", 2, "every-call"))
    _json(cv, "accept", "s1", "--dir", d, "--as", FINDER, "--claim", "F001", "--round", "2")

    assert _json(cv, "coverage", "s1", "--dir", d) == {
        "lenses": {"correctness": {"ran": ["changed-contract"], "na": {},
                                   "missing": ["failure-path"]},
                   "security": {"ran": [], "na": {"failure-path": "no I/O"},
                                "missing": ["changed-contract"]}},
        "next": "continue the finder with the missing angles, then "
                + _next(cv, "coverage s1 --dir {dir}")}
    assert _json(cv, "gate", "s1", "--dir", d, code=1) == {
        "slate": "s1", "ok": False, "cutoff_seq": None,
        "problems": ["lens correctness has missing find angles: failure-path",
                     "lens security has missing find angles: changed-contract",
                     "no current cutoff (run `converge cutoff` after the last state change)"]}
    incomplete_cutoff_error = _error(cv, "cutoff", "s1", "--dir", d)
    assert incomplete_cutoff_error["problems"] == [{"kind": "", "items": [
        "lens correctness has missing find angles: failure-path",
        "lens security has missing find angles: changed-contract"]}]
    _json(cv, "find-run", "s1", "--dir", d, "--as", FINDER, "--lens", "security",
          "--angle", "changed-contract", "--tell", "t", "--searches", "s",
          "--positive-control", "p", "--result", "none")
    _json(cv, "angle-na", "s1", "--dir", d, "--as", FINDER, "--phase", "find",
          "--angle", "failure-path", "--lens", "correctness", "--reason", "no I/O")
    cutoff = _json(cv, "cutoff", "s1", "--dir", d)
    assert cutoff == {"seq": cutoff["seq"],
                      "rows": [{"claim": "F001", "result": cutoff["rows"][0]["result"],
                                "rank": 1, "reason": cutoff["rows"][0]["reason"]}],
                      "next": _next(cv, "render s1 --dir {dir}")}
    assert _json(cv, "gate", "s1", "--dir", d) == {
        "slate": "s1", "ok": True, "problems": [], "cutoff_seq": cutoff["seq"]}

    rendered = _json(cv, "render", "s1", "--dir", d)
    assert rendered == {"slate": "s1", "markdown": cv.ok("render", "s1").stdout,
                        "choices": []}

    status = cv("status", "s1", "--dir", d, "--json", env=PIPE).stdout
    status_data = json.loads(status)
    assert status.startswith("{\n  ") and status_data["claims"][0]["id"] == "F001"
    assert {"phase", "round", "legal_event_types"} <= set(status_data)

    angles = _json(cv, "angles", "--tag", "decide", "--project-root", str(cv.project))["angles"]
    assert {row["tag"] for row in angles} == {"decide"}
    assert "reversibility" in {row["id"] for row in angles}
    validate = _json(cv, "config", "validate", "--project-root", str(cv.project))
    assert validate["valid"] is True and validate["sources"]
    assert {"layer", "present", "path"} <= set(validate["sources"][0])
    resolved = _json(cv, "config", "resolve", "--project-root", str(cv.project))
    assert resolved == json.loads(cv("config", "resolve", "--project-root", str(cv.project), "--json").stdout)


def test_pipe_default_is_prose(cv: Converge) -> None:
    result = cv(*_init_args(cv), env=PIPE)
    assert result.stdout.startswith("INIT s1")


def test_status_keeps_finder_events_until_coverage_is_complete(cv: Converge) -> None:
    cv.init()
    cv.file()
    status = _json(cv, "status", "s1", "--dir", str(cv.dir))
    assert status["phase"] == "refute"
    assert {"find-run", "angle-na"} <= set(status["legal_event_types"])


def test_prose_on_a_regular_file_and_with_prose_flag(cv: Converge, tmp_path: Path) -> None:
    cv.init()
    out = tmp_path / "out.txt"
    with out.open("w") as handle:
        subprocess.run([str(BIN), "status", "s1", "--dir", str(cv.dir)], stdout=handle,
                       env={**cv.env, **PIPE}, cwd=cv.project, check=True)
    assert out.read_text().startswith("SLATE s1 mode=full")
    piped = cv("status", "s1", "--dir", str(cv.dir), "--prose", env=PIPE).stdout
    assert piped.startswith("SLATE s1 mode=full")
    assert json.loads(cv("status", "s1", "--dir", str(cv.dir), "--json").stdout)["slate"] == "s1"


def test_both_mode_flags_refused(cv: Converge) -> None:
    cv.init()
    err = cv("status", "s1", "--dir", str(cv.dir), "--json", "--prose", code=2).stderr
    assert err.startswith("--json and --prose are mutually exclusive\n")
    assert f"example: converge {cli.EXAMPLES['status']}" in err


# ---------------------------------------------------------------------------
# refusals name the example, the sibling commands and the frequent ones


def test_argparse_refusal_prose(cv: Converge) -> None:
    err = cv("refute", "s1", "--dir", str(cv.dir), "--as", R1, code=2).stderr
    lines = err.splitlines()
    assert lines[0].startswith("converge refute: error: the following arguments are required: ")
    assert "usage:" not in err
    assert lines[1] == f"example: converge {cli.EXAMPLES['refute']}"
    assert lines[2] == "commands: " + ", ".join(k for k in cli.EXAMPLES if k != "refute")
    assert lines[3:] == [f"  converge {cli.EXAMPLES[k]}" for k in cli.FREQUENT if k != "refute"]


def test_domain_refusal_prose_keeps_first_lines(cv: Converge) -> None:
    cv.init()
    cv.file()
    err = cv.refused("refute", "s1", "--as", R1, "--claim", "F001", "--round", "1",
                     "--angle", "nope", "--tell", "t", "--outcome", "survived",
                     "--evidence", "e", "--searches", "s", "--positive-control", "p")
    lines = err.splitlines()
    assert lines[:2] == ["converge: refused:",
                         "  - unknown attack angle 'nope' (not in this slate's init snapshot)"]
    assert lines[2] == f"example: converge {cli.EXAMPLES['refute']}"
    assert lines[3].startswith("commands: init, file, ")


def test_domain_refusal_json_and_display_prog(cv: Converge) -> None:
    cv.init()
    result = cv(*_refute_args(cv, "F001", "nope", R1), "--json", code=2,
                env={**PIPE, "BOOTGEAR_PROG": "/p/scripts/converge"})
    error = json.loads(result.stderr)["error"]
    assert error["command"] == "refute"
    assert error["message"] == "converge: refused:"
    assert error["example"] == f"/p/scripts/converge {cli.EXAMPLES['refute']}"
    assert "refute" not in error["commands"] and "init" in error["commands"]
    assert set(error["examples"]) == {"file", "status", "converged"}


def test_argparse_refusal_json(cv: Converge) -> None:
    error = _error(cv, "init", "s1", "--dir", str(cv.dir), "--as", MAIN, "--mode", "bogus")
    assert error["command"] == "init"
    assert error["message"].startswith("converge init: error: argument --mode: invalid choice")
    assert error["example"] == f"converge {cli.EXAMPLES['init']}"


# ---------------------------------------------------------------------------
# every problem in one refusal


def test_every_ledger_problem_in_one_refusal(cv: Converge) -> None:
    cv.init()
    error = _error(cv, *_refute_args(cv, "F999", "nope", R1))
    assert error["problems"] == [{"kind": "", "items": [
        "unknown claim 'F999'",
        "unknown attack angle 'nope' (not in this slate's init snapshot)"]}]
    err = cv.refused("refute", "s1", "--as", R1, "--claim", "F999", "--round", "1",
                     "--angle", "nope", "--tell", "t", "--outcome", "survived",
                     "--evidence", "e", "--searches", "s", "--positive-control", "p")
    assert err.splitlines()[:3] == [
        "converge: refused:", "  - unknown claim 'F999'",
        "  - unknown attack angle 'nope' (not in this slate's init snapshot)"]


# ---------------------------------------------------------------------------
# relative paths resolve against the caller's directory


def test_relative_paths_resolve_against_caller_cwd(cv: Converge) -> None:
    caller = {"GEAR_CALLER_CWD": str(cv.root)}
    out = cv("init", "s1", "--dir", "ledgers", "--as", MAIN, "--mode", "full",
             "--lenses", "correctness", "--angles", "find-angles.yaml",
             "--project-root", "project", env=caller).stdout
    assert out.startswith("INIT s1 mode=full lenses=correctness ")
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
# `next:` names the step after the command


def test_next_after_cutoff_and_converged(cv: Converge) -> None:
    cv.init()
    for lens in ("correctness", "security"):
        for angle in ("changed-contract", "failure-path"):
            cv.ok("angle-na", "s1", "--as", FINDER, "--phase", "find", "--angle", angle,
                  "--lens", lens, "--reason", "n/a")
    cid = cv.file()
    open_refute = cv.ok("converged", "s1", "--phase", "refute", code=1).stdout.splitlines()
    assert open_refute[-1] == "next: " + _next(cv, "status s1 --dir {dir} --json")
    cv.quiet_round(cid, 1, ("boundary", "reachability"))
    done = cv.ok("converged", "s1", "--phase", "refute").stdout
    assert done == "CONVERGED phase=refute\n"
    cv.cut(cid, 1, CUTTER)
    open_cut = cv.ok("converged", "s1", "--phase", "cut", code=1).stdout.splitlines()
    assert open_cut[-1] == "next: continue the cutter with the listed claims"
    cv.accept(cid, 1)
    assert cv.ok("converged", "s1", "--phase", "cut").stdout.splitlines() == [
        "CONVERGED phase=cut", "next: " + _next(cv, "cutoff s1 --dir {dir}")]
    cutoff = cv.ok("cutoff", "s1").stdout.splitlines()
    assert cutoff[0].startswith("CUTOFF seq=")
    assert cutoff[-1] == "next: " + _next(cv, "render s1 --dir {dir}")


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


def test_next_after_refute_only_init(cv: Converge) -> None:
    out = cv(*_init_args(cv, mode="refute-only", lenses=""), "--json", env=PIPE).stdout
    assert json.loads(out)["next"] == (
        "file every slate claim: " + _next(
            cv, 'file s1 --dir {dir} --as slate --origin slate --loc <path:line> '
                '--claim "<text>" --trigger "<what reaches it>"'))
    full = cv.root / "full"
    assert "next" not in json.loads(cv(*_init_args(cv), "--dir", str(full), "--json", env=PIPE).stdout)


# ---------------------------------------------------------------------------
# catalog


def test_examples_cover_every_leaf_and_parse() -> None:
    parser = cli._parser()
    assert set(cli.EXAMPLES) == set(clikit.leaf_commands(parser))
    assert set(cli.FREQUENT) <= set(cli.EXAMPLES)
    for leaf, example in cli.EXAMPLES.items():
        args = parser.parse_args(shlex.split(example))
        assert args.command == leaf, example
