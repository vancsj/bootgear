"""Layered converge.yaml: defaults, host user path, project, task; validation; the init
event's config snapshot and `refuters`."""
from __future__ import annotations

import copy
import json
from typing import Any

from converge import config as config_mod
from converge import ledger, model

from conftest import HOST, MAIN, Converge

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
    assert set(eff["cutoff"]) == {"report_rules", "lenses", "rereview", "cheap", "difficulty_basis"}
    assert eff["cutoff"]["difficulty_basis"] == "artifact"
    assert eff["cutoff"]["lenses"] == {"default": {
        "attack_if": [{"reach": ["normal", "crafted"],
                       "impact": ["security", "data-loss", "wrong-output"]},
                      {"reach": ["normal", "crafted"], "tier": ["reproduced"]}],
        "report_if": [{"status": ["survived", "disputed"], "reach": ["normal", "crafted"],
                       "impact": ["security", "data-loss", "wrong-output"]}],
        "choice_if": []}}
    assert eff["cutoff"]["rereview"] == {"lenses": {}}
    assert eff["cutoff"]["report_rules"] == []
    assert "CONFIG valid" in cv("config", "validate", "--project-root", str(cv.project)).stdout


def test_layers_merge_later_wins(cv: Converge) -> None:
    (cv.home / f".{HOST}").mkdir()
    (cv.home / f".{HOST}" / "converge.yaml").write_text(
        "caps: {per_lens: {default: 5}, cut_rounds: 4}\n")
    project_cfg = cv.project / ".bootgear" / "config"
    project_cfg.mkdir(parents=True)
    (project_cfg / "converge.yaml").write_text("caps: {per_lens: {security: 2}}\n")
    task = cv.root / "task.yaml"
    task.write_text("caps: {angles_per_claim: 2}\nsteps: {cut: after, escalate: false}\n"
                    "cutoff: {lenses: {security: {report_if: [{impact: [security]}]}}}\n")
    eff = _effective(cv, "--config", str(task))
    assert eff["caps"] == {"cut_rounds": 4, "per_lens": {"default": 5, "security": 2},
                           "agents": 5, "angles_per_claim": 2, "batch_items": 30}
    assert eff["steps"] == {"escalate": False, "gap_hunt": True, "cut": "after"}
    assert eff["cutoff"]["lenses"]["security"] == {"report_if": [{"impact": ["security"]}]}
    assert eff["cutoff"]["lenses"]["default"] == config_mod.DEFAULTS["cutoff"]["lenses"]["default"]


def test_each_explicit_host_reads_its_own_user_path(cv: Converge) -> None:
    for host, value in (("claude", 7), ("codex", 9)):
        (cv.home / f".{host}").mkdir()
        (cv.home / f".{host}" / "converge.yaml").write_text(
            f"caps: {{per_lens: {{default: {value}}}}}\n")
    for host, value in (("claude", 7), ("codex", 9)):
        assert _effective(cv, env={"BOOTGEAR_HOST": host})["caps"]["per_lens"] == {"default": value}


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
        "cutoff: {lenses: {default: {report_if: [{impact: [catastrophic]}, {speed: [fast]}]}}, "
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
    assert any(("snapshot: missing section 'steps'") in problem for problem in problems)
    assert any(("snapshot: caps.batch_items is missing") in problem for problem in problems)
    assert any(("snapshot: cutoff.report_rules is missing") in problem for problem in problems)


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
    cv.cut("F001", 1, when="before")
    err = cv.cut("F001", 2, when="before", code=2).stderr
    assert "cut: round 2 exceeds caps.cut_rounds 1" in err


def test_init_event_validates_refuters_and_config() -> None:
    slate = model.Slate("s1")
    assert ledger.validate_event(slate, _init_event()) == []
    for value in (0, 3, "2", True):
        problems = ledger.validate_event(slate, _init_event(refuters=value))
        assert any((f"`refuters` must be 1 or 2; got {value!r}") in problem for problem in problems), problems
    assert "init: missing required field `refuters`" in ledger.validate_event(
        slate, _init_event(refuters=None))
    config = copy.deepcopy(config_mod.DEFAULTS)
    config["caps"]["per_lens"] = 3
    problems = ledger.validate_event(slate, _init_event(config=config))
    assert any(("config snapshot: snapshot: caps.per_lens must be a map; use per_lens: "
            "{default: <n>}") in problem for problem in problems)


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


# -- per-lens cutoff tables, the caller layer, `cheap` -------------------------------


CALLER_LENSES = """\
cutoff:
  lenses:
    security:
      attack_if: [{impact: [security]}]
      report_if: [{impact: [security], rate_at_least: 1}]
    correctness:
      attack_if: [{rate_at_least: 3}]
    contract:
      attack_if: [{reach: [normal]}]
      choice_if: [{difficulty: [cross-cutting, redesign]}]
  rereview:
    lenses:
      default:
        report_if: [{impact: [security, data-loss]}]
      security:
        report_if: [{impact: [security], rate_at_least: 5}]
      contract:
        report_if: [{impact: [security]}]
"""


def _defaults_file(cv: Converge, text: str = CALLER_LENSES) -> str:
    path = cv.root / "skill-cutoff.yaml"
    path.write_text(text)
    return str(path)


def _project_layer(cv: Converge, text: str) -> None:
    project_cfg = cv.project / ".bootgear" / "config"
    project_cfg.mkdir(parents=True, exist_ok=True)
    (project_cfg / "converge.yaml").write_text(text)


def test_rate_at_least_rule() -> None:
    rule = {"rate_at_least": 3, "impact": ["security"]}
    assert model.rule_matches(rule, {"rate": 3, "impact": "security"})
    assert model.rule_matches(rule, {"rate": 9, "impact": "security"})
    assert not model.rule_matches(rule, {"rate": 2, "impact": "security"})
    assert not model.rule_matches(rule, {"impact": "security"})
    assert not model.rule_matches(rule, {"rate": 3, "impact": "cosmetic"})
    assert model.rule_matches({"rate_at_least": 0}, {"rate": 0})
    assert "rate_at_least" in model.RULE_FIELDS


def test_rate_at_least_must_be_a_non_negative_integer(cv: Converge) -> None:
    err = _validate(cv, "cutoff: {lenses: {default: {attack_if: [{rate_at_least: -1}], "
                        "report_if: [{rate_at_least: '3'}], choice_if: [{rate_at_least: true}]}}}\n")
    for got in ("-1", "'3'", "True"):
        assert f"rate_at_least must be a non-negative integer; got {got}" in err
    assert "CONFIG valid" in _validate(
        cv, "cutoff: {lenses: {default: {report_if: [{rate_at_least: 3}]}}}\n", code=0)


def test_project_layer_overrides_caller_defaults_per_lens(cv: Converge) -> None:
    _project_layer(cv, "cutoff: {lenses: {security: {report_if: [{impact: [data-loss]}]}}}\n")
    cv.init("s1", "correctness,security", MAIN, "--defaults", _defaults_file(cv))
    lenses = cv.events()[0]["config"]["cutoff"]["lenses"]
    assert lenses["security"] == {"attack_if": [{"impact": ["security"]}],
                                  "report_if": [{"impact": ["data-loss"]}]}
    assert lenses["correctness"] == {"attack_if": [{"rate_at_least": 3}]}
    assert lenses["default"] == config_mod.DEFAULTS["cutoff"]["lenses"]["default"]


def test_caller_layer_sits_below_user(cv: Converge) -> None:
    (cv.home / f".{HOST}").mkdir()
    (cv.home / f".{HOST}" / "converge.yaml").write_text(
        "cutoff: {lenses: {correctness: {attack_if: [{rate_at_least: 1}]}}}\n")
    cv.init("s1", "correctness", MAIN, "--defaults", _defaults_file(cv))
    lenses = cv.events()[0]["config"]["cutoff"]["lenses"]
    assert lenses["correctness"] == {"attack_if": [{"rate_at_least": 1}]}
    assert lenses["security"]["attack_if"] == [{"impact": ["security"]}]
    assert config_mod.LAYER_NAMES == ("caller", "user", "project", "task")


def test_missing_defaults_file_refused(cv: Converge) -> None:
    err = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness",
                     "--project-root", str(cv.project), "--defaults", str(cv.root / "nope.yaml"))
    assert "caller config does not exist" in err
    assert not cv.path().exists()


def test_lens_policy_reads_lens_else_default(cv: Converge) -> None:
    cv.init("s1", "correctness,security", MAIN, "--defaults", _defaults_file(cv))
    slate = ledger.read(cv.path(), "s1")
    assert slate.lens_policy("security")["attack_if"] == [{"impact": ["security"]}]
    assert slate.lens_policy("simplicity") == config_mod.DEFAULTS["cutoff"]["lenses"]["default"]
    assert slate.lens_policy(None) == config_mod.DEFAULTS["cutoff"]["lenses"]["default"]


def test_complete_lenses_needs_default() -> None:
    snapshot = copy.deepcopy(config_mod.DEFAULTS)
    snapshot["cutoff"]["lenses"] = {"security": {"attack_if": []}}
    problems = config_mod.validate_config(snapshot, "snapshot", complete=True)
    assert problems == ["snapshot: cutoff.lenses needs a `default` key"]


def test_lens_tables_validate(cv: Converge) -> None:
    err = _validate(
        cv,
        "cutoff:\n"
        "  lenses: {security: {attack_if: [{speed: [fast]}], drop_if: []}, '': {}, tests: []}\n"
        "  rereview: {lenses: {default: {report_if: {impact: [security]}}}, extra: 1}\n")
    for fragment in ("cutoff.lenses.security.attack_if[0]: unknown field 'speed'",
                     ("cutoff.lenses.security: unknown key 'drop_if' (allowed: attack_if, "
                      "report_if, choice_if)"),
                     "cutoff.lenses keys must be non-empty strings",
                     "cutoff.lenses.tests must be a map of attack_if, report_if, choice_if",
                     "cutoff.rereview.lenses.default.report_if must be a list of rules",
                     "cutoff.rereview: unknown key 'extra' (allowed: lenses)"):
        assert fragment in err, err


def test_rereview_overlay_keeps_project_lens(cv: Converge) -> None:
    _project_layer(cv, "cutoff: {lenses: {tests: {report_if: [{impact: [cosmetic]}]}}}\n")
    defaults = _defaults_file(cv)
    cv.init("s1", "correctness,security", MAIN, "--defaults", defaults, "--pass", "1")
    first = cv.events("s1")[0]["config"]["cutoff"]["lenses"]
    assert first["security"]["report_if"] == [{"impact": ["security"], "rate_at_least": 1}]
    assert first["default"] == config_mod.DEFAULTS["cutoff"]["lenses"]["default"]
    cv.init("s2", "correctness,security", MAIN, "--defaults", defaults, "--pass", "2")
    second = cv.events("s2")[0]["config"]["cutoff"]["lenses"]
    builtin = config_mod.DEFAULTS["cutoff"]["lenses"]["default"]
    assert second["security"] == {"attack_if": [{"impact": ["security"]}],
                                  "report_if": [{"impact": ["security"], "rate_at_least": 5}]}
    assert second["default"] == {**builtin, "report_if": [{"impact": ["security", "data-loss"]}]}
    assert second["contract"] == {"attack_if": [{"reach": ["normal"]}],
                                  "report_if": [{"impact": ["security"]}],
                                  "choice_if": [{"difficulty": ["cross-cutting", "redesign"]}]}
    assert second["correctness"] == {"attack_if": [{"rate_at_least": 3}]}
    assert second["tests"] == {"report_if": [{"impact": ["cosmetic"]}]}


def test_default_test_globs(cv: Converge) -> None:
    cheap = _effective(cv)["cutoff"]["cheap"]
    assert cheap == {"enabled": True, "files": 1, "lines": 10, "trivial_lines": 3, "tests": 1,
                     "test_globs": ["**/test_*", "**/*_test.*", "**/tests/**", "**/*.test.*",
                                    "**/*.spec.*"]}
    _project_layer(cv, "cutoff: {cheap: {test_globs: ['spec/**'], lines: 20}}\n")
    cheap = _effective(cv)["cutoff"]["cheap"]
    assert cheap["test_globs"] == ["spec/**"]
    assert cheap["lines"] == 20 and cheap["files"] == 1


def test_old_cutoff_keys_are_refused(cv: Converge) -> None:
    err = _validate(cv, "cutoff: {report_if: [], report_if_gap_hunt: []}\n")
    assert ("unknown key cutoff.report_if (allowed: report_rules, lenses, rereview, cheap, difficulty_basis)"
            in err)
    assert "unknown key cutoff.report_if_gap_hunt" in err
    assert not hasattr(config_mod, "REREVIEW_CUTOFF")


def test_cheap_values_validate(cv: Converge) -> None:
    err = _validate(cv, "cutoff: {cheap: {enabled: 'no', files: -1, lines: true, "
                        "test_globs: ['', 3], speed: 1}}\n")
    for fragment in ("cutoff.cheap.enabled must be true or false; got 'no'",
                     "cutoff.cheap.files must be a non-negative integer; got -1",
                     "cutoff.cheap.lines must be a non-negative integer; got True",
                     "cutoff.cheap.test_globs must be a list of non-empty strings",
                     ("cutoff.cheap: unknown key 'speed' (allowed: enabled, files, lines, "
                      "trivial_lines, tests, test_globs)")):
        assert fragment in err, err


def test_implementation_difficulty_disables_automatic_cheap_fixes(cv: Converge) -> None:
    err = _validate(cv, "cutoff: {difficulty_basis: implementation}\n")
    assert "implementation requires cutoff.cheap.enabled false" in err
    assert "CONFIG valid" in _validate(
        cv, "cutoff: {difficulty_basis: implementation, cheap: {enabled: false}}\n", code=0)
    assert "difficulty_basis must be one of artifact, implementation" in _validate(
        cv, "cutoff: {difficulty_basis: document}\n")


# -- list append: `{append: [...]}` at a lens rule list ---------------------------------

DEFAULT_LENS = config_mod.DEFAULTS["cutoff"]["lenses"]["default"]
R1_RULE = {"impact": ["cosmetic"]}
R2_RULE = {"reach": ["crafted"]}
R3_RULE = {"rate_at_least": 2}


def _user_layer(cv: Converge, text: str) -> None:
    (cv.home / f".{HOST}").mkdir(exist_ok=True)
    (cv.home / f".{HOST}" / "converge.yaml").write_text(text)


def _task_layer(cv: Converge, text: str) -> str:
    path = cv.root / "task.yaml"
    path.write_text(text)
    return str(path)


def _lens_append(key: str, rule: str) -> str:
    return f"cutoff: {{lenses: {{default: {{{key}: {{append: [{rule}]}}}}}}}}\n"


def test_project_append_follows_the_default_rules(cv: Converge) -> None:
    _project_layer(cv, _lens_append("attack_if", "{impact: [cosmetic]}"))
    lens = _effective(cv)["cutoff"]["lenses"]["default"]
    assert lens["attack_if"] == [*DEFAULT_LENS["attack_if"], R1_RULE]
    assert lens["report_if"] == DEFAULT_LENS["report_if"]
    assert lens["choice_if"] == DEFAULT_LENS["choice_if"]


def test_init_snapshot_holds_plain_lists(cv: Converge) -> None:
    _project_layer(cv, _lens_append("report_if", "{impact: [cosmetic]}"))
    cv.init("s1", "correctness", MAIN, config={"cutoff": {"lenses": {
        "default": {"choice_if": {"append": [R2_RULE]}}}}})
    lens = cv.events()[0]["config"]["cutoff"]["lenses"]["default"]
    assert lens["report_if"] == [*DEFAULT_LENS["report_if"], R1_RULE]
    assert lens["choice_if"] == [R2_RULE]
    assert ledger.read(cv.path(), "s1").lens_policy("correctness")["choice_if"] == [R2_RULE]


def test_user_and_project_appends_keep_layer_order(cv: Converge) -> None:
    _user_layer(cv, _lens_append("attack_if", "{impact: [cosmetic]}"))
    _project_layer(cv, _lens_append("attack_if", "{reach: [crafted]}"))
    assert _effective(cv)["cutoff"]["lenses"]["default"]["attack_if"] == [
        *DEFAULT_LENS["attack_if"], R1_RULE, R2_RULE]


def test_task_append_follows_a_project_plain_list(cv: Converge) -> None:
    _project_layer(cv, "cutoff: {lenses: {default: {attack_if: [{reach: [crafted]}]}}}\n")
    task = _task_layer(cv, _lens_append("attack_if", "{impact: [cosmetic]}"))
    assert _effective(cv, "--config", task)["cutoff"]["lenses"]["default"]["attack_if"] == [
        R2_RULE, R1_RULE]


def test_task_plain_list_replaces_a_project_append(cv: Converge) -> None:
    _project_layer(cv, _lens_append("attack_if", "{impact: [cosmetic]}"))
    task = _task_layer(cv, "cutoff: {lenses: {default: {attack_if: [{reach: [crafted]}]}}}\n")
    assert _effective(cv, "--config", task)["cutoff"]["lenses"]["default"]["attack_if"] == [R2_RULE]


def test_appended_rule_equal_to_an_inherited_rule_stays_twice(cv: Converge) -> None:
    first = DEFAULT_LENS["attack_if"][0]
    _project_layer(cv, "cutoff:\n  lenses:\n    default:\n      attack_if:\n        append:\n"
                       "          - {reach: [normal, crafted], "
                       "impact: [security, data-loss, wrong-output]}\n")
    assert _effective(cv)["cutoff"]["lenses"]["default"]["attack_if"] == [
        *DEFAULT_LENS["attack_if"], first]


def test_append_on_a_new_lens_table_gets_no_default_rules(cv: Converge) -> None:
    _project_layer(cv, "cutoff:\n  lenses:\n    security:\n"
                       "      attack_if: {append: [{impact: [cosmetic]}]}\n"
                       "      report_if: {append: [{reach: [crafted]}]}\n"
                       "      choice_if: {append: [{rate_at_least: 2}]}\n")
    lenses = _effective(cv)["cutoff"]["lenses"]
    assert lenses["security"] == {"attack_if": [R1_RULE], "report_if": [R2_RULE],
                                  "choice_if": [R3_RULE]}
    assert lenses["default"] == DEFAULT_LENS


def test_caller_append_follows_the_inherited_list(cv: Converge) -> None:
    caller = _defaults_file(cv, _lens_append("attack_if", "{impact: [cosmetic]}"))
    cv.init("s1", "correctness", MAIN, "--defaults", caller)
    lens = cv.events()[0]["config"]["cutoff"]["lenses"]["default"]
    assert lens["attack_if"] == [*DEFAULT_LENS["attack_if"], R1_RULE]


def test_empty_append_in_any_layer_changes_nothing(cv: Converge) -> None:
    empty = "cutoff: {lenses: {default: {attack_if: {append: []}, report_if: {append: []}}}}\n"
    _user_layer(cv, empty)
    assert _effective(cv) == config_mod.DEFAULTS
    (cv.home / f".{HOST}" / "converge.yaml").unlink()
    _project_layer(cv, empty)
    assert _effective(cv) == config_mod.DEFAULTS
    assert _effective(cv, "--config", _task_layer(cv, empty)) == config_mod.DEFAULTS
    cv.init("s1", "correctness", MAIN, "--defaults", _defaults_file(cv, empty))
    assert cv.events()[0]["config"] == config_mod.DEFAULTS


APPEND_MISTAKES = """\
cutoff:
  lenses:
    default:
      attack_if: {append: [{speed: [fast]}], extra: 1, other: 2}
      report_if: {append: rule}
      choice_if: {append: [{impact: [catastrophic]}, {}]}
    tests:
      attack_if: {}
"""


def test_validate_groups_every_append_problem(cv: Converge) -> None:
    err = _validate(cv, APPEND_MISTAKES)
    for fragment in ("cutoff.lenses.default.attack_if must be a list of rules",
                     "cutoff.lenses.default.attack_if: unknown key 'extra' (allowed: append)",
                     "cutoff.lenses.default.attack_if: unknown key 'other' (allowed: append)",
                     "cutoff.lenses.default.attack_if.append[0]: unknown field 'speed'",
                     "cutoff.lenses.default.report_if.append must be a list of rules",
                     "cutoff.lenses.default.choice_if.append[0].impact: bad value 'catastrophic'",
                     "cutoff.lenses.default.choice_if.append[1] must be a non-empty mapping",
                     "cutoff.lenses.tests.attack_if must be a list of rules"):
        assert fragment in err, err
    assert "unknown key 'append'" not in err, err


def test_validate_checks_append_items_like_a_plain_list(cv: Converge) -> None:
    err = _validate(cv, "cutoff: {lenses: {default: {attack_if: {append: [{speed: [fast]}]}}}}\n")
    assert "cutoff.lenses.default.attack_if.append[0]: unknown field 'speed'" in err
    assert "CONFIG valid" in _validate(cv, _lens_append("choice_if", "{impact: [cosmetic]}"), code=0)


def test_init_refuses_an_append_layer_with_problems(cv: Converge) -> None:
    """A layer with append problems is refused and leaves no slate."""
    task = _task_layer(cv, APPEND_MISTAKES)
    err = cv.refused("init", "s1", "--as", MAIN, "--lenses", "correctness",
                     "--angles", str(cv.angles), "--project-root", str(cv.project),
                     "--config", task)
    assert "must be a list of rules" in err
    assert not cv.path().exists()


def test_mapping_at_other_list_keys_keeps_the_existing_refusal(cv: Converge) -> None:
    """A mapping at any other list key keeps that key's own refusal."""
    for layer, fragment in (
            ("cutoff: {report_rules: {append: [R001]}}",
             "cutoff.report_rules must be a list of non-empty strings"),
            ("angles: {files: {append: [a.md]}}",
             "angles.files must be a list of non-empty strings"),
            ("angles: {disable: {append: [x]}}",
             "angles.disable must be a list of non-empty strings"),
            ("cutoff: {cheap: {test_globs: {append: ['x/**']}}}",
             "cutoff.cheap.test_globs must be a list of non-empty strings"),
            ("finder_routing: {groups: {append: [{lenses: [security]}]}}",
             "finder_routing.groups must be a list")):
        assert fragment in _validate(cv, layer + "\n"), layer


def test_mapping_in_a_rereview_overlay_is_refused(cv: Converge) -> None:
    """A rereview overlay refuses a mapping at every rule list."""
    for key in ("attack_if", "report_if", "choice_if"):
        err = _validate(cv, f"cutoff: {{rereview: {{lenses: {{default: {{{key}: "
                            f"{{append: [{{impact: [cosmetic]}}]}}}}}}}}}}\n")
        assert f"cutoff.rereview.lenses.default.{key} must be a list of rules" in err


def test_snapshot_with_an_append_mapping_is_refused() -> None:
    """A snapshot that holds an append mapping fails validation."""
    for key in ("attack_if", "report_if", "choice_if"):
        snapshot = copy.deepcopy(config_mod.DEFAULTS)
        snapshot["cutoff"]["lenses"]["default"][key] = {"append": [R1_RULE]}
        assert config_mod.validate_config(snapshot, "snapshot", complete=True) == [
            f"snapshot: cutoff.lenses.default.{key} must be a list of rules"]


def test_plain_overlay_replaces_one_rule_list_at_pass_2(cv: Converge) -> None:
    """A plain overlay replaces one rule list at pass 2 and keeps the others."""
    _project_layer(cv, "cutoff:\n  lenses:\n    security:\n"
                       "      attack_if: [{impact: [security]}]\n"
                       "      report_if: [{reach: [crafted]}]\n"
                       "  rereview: {lenses: {security: {attack_if: [{reach: [unreachable]}]}}}\n")
    cv.init("s1", "security", MAIN, "--pass", "2")
    assert cv.events()[0]["config"]["cutoff"]["lenses"]["security"] == {
        "attack_if": [{"reach": ["unreachable"]}], "report_if": [R2_RULE]}


def test_plain_overlay_replaces_the_appended_rule_list_at_pass_2(cv: Converge) -> None:
    _project_layer(cv, "cutoff:\n  lenses:\n    security:\n"
                       "      attack_if: [{impact: [security]}]\n"
                       "      report_if: [{reach: [crafted]}]\n"
                       "      choice_if: [{rate_at_least: 2}]\n"
                       "  rereview: {lenses: {security: {attack_if: [{reach: [unreachable]}]}}}\n")
    task = {"cutoff": {"lenses": {"security": {"attack_if": {"append": [R1_RULE]}}}}}
    cv.init("s1", "security", MAIN, "--pass", "1", config=task)
    assert cv.events("s1")[0]["config"]["cutoff"]["lenses"]["security"]["attack_if"] == [
        {"impact": ["security"]}, R1_RULE]
    cv.init("s2", "security", MAIN, "--pass", "2", config=task)
    assert cv.events("s2")[0]["config"]["cutoff"]["lenses"]["security"] == {
        "attack_if": [{"reach": ["unreachable"]}], "report_if": [R2_RULE], "choice_if": [R3_RULE]}
