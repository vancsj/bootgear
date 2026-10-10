"""Layered converge.yaml: defaults, host user path, project, task; validation; the init
event's config snapshot and `refuters`."""
from __future__ import annotations

import copy
import json
from typing import Any

from conftest import MAIN, Converge
from converge import config as config_mod
from converge import ledger, model

DEFAULT_CAPS = {"cut_rounds": 5, "per_lens": {"default": 50}, "agents": 5,
                "angles_per_claim": 5, "batch_items": 30}


def _effective(cv: Converge, *args: str, env: dict[str, str] | None = None) -> dict:
    out = cv("config", "resolve", "--project-root", str(cv.project), *args, env=env).stdout
    return json.loads(out)["effective"]


def _validate(cv: Converge, text: str, code: int = 2) -> str:
    layer = cv.root / "layer.yaml"
    layer.write_text(text)
    result = cv("config", "validate", "--project-root", str(cv.project), "--config", str(layer),
                code=code)
    return result.stderr if code else result.stdout


def _init_event(**fields: Any) -> dict[str, Any]:
    event = {"seq": 1, "ts": "2026-10-09T00:00:00Z", "event": "init", "as": MAIN,
             "lenses": ["correctness"], "angles": [], "config": copy.deepcopy(config_mod.DEFAULTS),
             "refuters": 2, **fields}
    return {k: v for k, v in event.items() if v is not None}


# -- defaults and layers ---------------------------------------------------------


def test_defaults(cv: Converge) -> None:
    eff = _effective(cv)
    assert eff == config_mod.DEFAULTS
    assert eff["caps"] == DEFAULT_CAPS
    assert eff["steps"] == {"escalate": True, "gap_hunt": True, "cut": "both"}
    assert eff["angles"] == {"files": [], "disable": []}
    assert eff["cutoff"]["report_if"][0] == {"severity": ["security", "data-loss"],
                                             "frequency": ["every-call", "common", "rare"]}
    assert eff["cutoff"]["report_if"][2] == {
        "confidence": ["reproduced"],
        "severity": ["security", "data-loss", "wrong-behavior", "degraded"],
        "frequency": ["every-call", "common", "rare"]}
    assert eff["cutoff"]["report_if_gap_hunt"] == [
        {"frequency": ["every-call", "common"]},
        {"frequency": ["rare"], "severity": ["security", "data-loss"]}]
    assert eff["cutoff"]["report_rules"] == []
    assert "CONFIG valid" in cv("config", "validate", "--project-root", str(cv.project)).stdout


def test_layers_merge_later_wins(cv: Converge) -> None:
    (cv.home / ".claude").mkdir()
    (cv.home / ".claude" / "converge.yaml").write_text(
        "caps: {per_lens: {default: 5}, cut_rounds: 4}\n")
    project_cfg = cv.project / ".bootgear" / "config"
    project_cfg.mkdir(parents=True)
    (project_cfg / "converge.yaml").write_text("caps: {per_lens: {security: 2}}\n")
    task = cv.root / "task.yaml"
    task.write_text("caps: {angles_per_claim: 2}\nsteps: {cut: after, escalate: false}\n"
                    "cutoff: {report_if: [{severity: [security]}]}\n")
    eff = _effective(cv, "--config", str(task))
    assert eff["caps"] == {"cut_rounds": 4, "per_lens": {"default": 5, "security": 2},
                           "agents": 5, "angles_per_claim": 2, "batch_items": 30}
    assert eff["steps"] == {"escalate": False, "gap_hunt": True, "cut": "after"}
    assert eff["cutoff"]["report_if"] == [{"severity": ["security"]}]
    assert len(eff["cutoff"]["report_if_gap_hunt"]) == 2


def test_codex_host_reads_codex_user_path(cv: Converge) -> None:
    (cv.home / ".claude").mkdir()
    (cv.home / ".claude" / "converge.yaml").write_text("caps: {per_lens: {default: 7}}\n")
    (cv.home / ".codex").mkdir()
    (cv.home / ".codex" / "converge.yaml").write_text("caps: {per_lens: {default: 9}}\n")
    assert _effective(cv)["caps"]["per_lens"] == {"default": 7}
    assert _effective(cv, env={"CONVERGE_HOST": "codex"})["caps"]["per_lens"] == {"default": 9}


def test_missing_task_config_refused(cv: Converge) -> None:
    err = cv("config", "validate", "--project-root", str(cv.project), "--config",
             str(cv.root / "nope.yaml"), code=2).stderr
    assert "task config does not exist" in err


def test_config_has_no_version_option(cv: Converge) -> None:
    err = cv("config", "resolve", "--version", "2", "--project-root", str(cv.project),
             code=2).stderr
    assert "unrecognized arguments: --version 2" in err


# -- validation --------------------------------------------------------------------


def test_validate_lists_every_problem(cv: Converge) -> None:
    err = _validate(
        cv,
        "colour: blue\n"
        "caps: {cut_rounds: 0, per_lens: {default: 3}, extra: 1, agents: 6}\n"
        "cutoff: {report_if: [{severity: [catastrophic]}, {speed: [fast]}], report_if_gap_hunt: [], "
        "report_rules: [R001, '']}\n"
        "angles: {files: [1], disable: [x]}\n"
        "steps: {retries: 2}\n")
    for fragment in ("unknown key 'colour'", "caps.cut_rounds must be a positive integer",
                     "unknown key caps.extra", "caps.agents must be at most 5",
                     "bad value 'catastrophic'", "unknown field 'speed'",
                     "angles.files must be a list of non-empty strings",
                     "cutoff.report_rules must be a list of non-empty strings",
                     "unknown key steps.retries (allowed: escalate, gap_hunt, cut)"):
        assert fragment in err


def test_caps_are_positive_integers(cv: Converge) -> None:
    err = _validate(cv, "caps: {cut_rounds: 0, agents: 6, batch_items: true, "
                        "angles_per_claim: -1}\n")
    assert "caps.cut_rounds must be a positive integer; got 0" in err
    assert "caps.agents must be at most 5" in err
    assert "caps.batch_items must be a positive integer; got True" in err
    assert "caps.angles_per_claim must be a positive integer; got -1" in err
    for value in ("0", "true", "-1"):
        assert "caps.agents must be a positive integer" in _validate(
            cv, f"caps: {{agents: {value}}}\n")
    assert "CONFIG valid" in _validate(cv, "caps: {agents: 3}\n", code=0)


def test_caps_keys(cv: Converge) -> None:
    err = _validate(cv, "caps: {retries: 3}\n")
    assert ("unknown key caps.retries (allowed: cut_rounds, per_lens, agents, angles_per_claim, "
            "batch_items)") in err


def test_per_lens_map_merges_across_layers(cv: Converge) -> None:
    project_cfg = cv.project / ".bootgear" / "config"
    project_cfg.mkdir(parents=True)
    (project_cfg / "converge.yaml").write_text("caps: {per_lens: {security: 10}}\n")
    task = cv.root / "task.yaml"
    task.write_text("caps: {per_lens: {default: 20}}\n")
    assert _effective(cv, "--config", str(task))["caps"]["per_lens"] == {
        "default": 20, "security": 10}


def test_scalar_per_lens_is_refused(cv: Converge) -> None:
    err = _validate(cv, "caps: {per_lens: 3}\n")
    assert "caps.per_lens must be a map; use per_lens: {default: <n>}" in err


def test_per_lens_values_and_keys(cv: Converge) -> None:
    err = _validate(cv, "caps: {per_lens: {security: 0, correctness: true, '': 3}}\n")
    assert "caps.per_lens.security must be a positive integer; got 0" in err
    assert "caps.per_lens.correctness must be a positive integer; got True" in err
    assert "caps.per_lens keys must be non-empty strings" in err


def test_steps_values(cv: Converge) -> None:
    for value in ("before", "after", "both", "none"):
        assert "CONFIG valid" in _validate(cv, f"steps: {{cut: {value}}}\n", code=0)
    err = _validate(cv, "steps: {cut: sometimes, escalate: 'yes', gap_hunt: 1}\n")
    assert "steps.cut must be one of before, after, both, none; got 'sometimes'" in err
    assert "steps.escalate must be true or false; got 'yes'" in err
    assert "steps.gap_hunt must be true or false; got 1" in err


def test_complete_snapshot_needs_every_key() -> None:
    assert config_mod.validate_config(config_mod.DEFAULTS, "snapshot", complete=True) == []
    snapshot = copy.deepcopy(config_mod.DEFAULTS)
    del snapshot["steps"]
    del snapshot["caps"]["batch_items"]
    del snapshot["cutoff"]["report_rules"]
    problems = config_mod.validate_config(snapshot, "snapshot", complete=True)
    assert "snapshot: missing section 'steps'" in problems
    assert "snapshot: caps.batch_items is missing" in problems
    assert "snapshot: cutoff.report_rules is missing" in problems


def test_complete_per_lens_needs_default() -> None:
    snapshot = copy.deepcopy(config_mod.DEFAULTS)
    snapshot["caps"]["per_lens"] = {"security": 4}
    problems = config_mod.validate_config(snapshot, "snapshot", complete=True)
    assert problems == ["snapshot: caps.per_lens needs a `default` key"]


def test_init_refuses_an_invalid_layer(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("caps: {per_lens: 3}\n")
    err = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness",
                     "--angles", str(cv.angles), "--project-root", str(cv.project),
                     "--config", str(task))
    assert "caps.per_lens must be a map" in err
    assert not cv.path().exists()


# -- the init event ---------------------------------------------------------------


def test_init_snapshots_the_config_and_refuters(cv: Converge) -> None:
    cv.init()
    init = cv.events()[0]
    assert init["config"] == config_mod.DEFAULTS
    assert init["refuters"] == 2
    assert "mode" not in init and "version" not in init
    slate = ledger.read(cv.path(), "s1")
    assert slate.init_refuters == 2


def test_refuters_option_is_recorded(cv: Converge) -> None:
    cv.init("s1", "correctness", MAIN, "--refuters", "1")
    assert cv.events()[0]["refuters"] == 1
    assert ledger.read(cv.path(), "s1").init_refuters == 1


def test_init_has_no_mode_or_version_option(cv: Converge) -> None:
    for flag, value in (("--mode", "full"), ("--version", "3")):
        err = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness",
                         "--project-root", str(cv.project), flag, value)
        assert f"unrecognized arguments: {flag} {value}" in err
    assert not cv.path().exists()


def test_init_snapshot_ignores_later_config_edits(cv: Converge) -> None:
    cv.ready(cut="before", claims=2, cut_rounds=1)
    (cv.root / "s1.task.yaml").write_text("caps: {cut_rounds: 5}\n")
    cv.cut("F001", 1, when="before", confidence="inferred")
    err = cv.cut("F001", 2, when="before", confidence="inferred", code=2).stderr
    assert "cut: round 2 exceeds caps.cut_rounds 1" in err


def test_init_event_validates_refuters_and_config() -> None:
    slate = model.Slate("s1")
    assert ledger.validate_event(slate, _init_event()) == []
    for value in (0, 3, "2", True):
        problems = ledger.validate_event(slate, _init_event(refuters=value))
        assert f"`refuters` must be 1 or 2; got {value!r}" in problems, problems
    assert "init: missing required field `refuters`" in ledger.validate_event(
        slate, _init_event(refuters=None))
    config = copy.deepcopy(config_mod.DEFAULTS)
    config["caps"]["per_lens"] = 3
    problems = ledger.validate_event(slate, _init_event(config=config))
    assert ("config snapshot: snapshot: caps.per_lens must be a map; use per_lens: "
            "{default: <n>}") in problems


def test_init_with_mode_and_version_fails_replay(cv: Converge) -> None:
    """An init event with `mode`, `version` and a scalar `per_lens` is refused on replay."""
    config = copy.deepcopy(config_mod.DEFAULTS)
    config["caps"]["per_lens"] = 3
    del config["steps"]["cut"]
    event = _init_event(mode="full", version=2, config=config, refuters=None)
    cv.dir.mkdir()
    cv.path().write_text(json.dumps(event) + "\n")
    err = cv.refused("status", "s1")
    assert "ledger is corrupt or out of order; every command refuses it:" in err
    for fragment in ("line 1: init: missing required field `refuters`",
                     "line 1: init: unknown field `mode`", "line 1: init: unknown field `version`"):
        assert fragment in err


def test_lens_cap_reads_the_per_lens_map(cv: Converge) -> None:
    cv.init(config={"caps": {"per_lens": {"security": 7}}})
    slate = ledger.read(cv.path(), "s1")
    assert slate.config["caps"]["per_lens"] == {"default": 50, "security": 7}
    assert slate.lens_cap("security") == 7
    assert slate.lens_cap("correctness") == 50
