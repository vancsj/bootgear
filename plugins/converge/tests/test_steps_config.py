"""The `steps` config section and the batch caps: defaults, validation, legacy snapshots."""
from __future__ import annotations

import copy
import json

from conftest import Converge
from converge import config as config_mod


def _effective(cv: Converge, *args: str) -> dict:
    out = cv("config", "resolve", "--project-root", str(cv.project), *args).stdout
    return json.loads(out)["effective"]


def test_steps_and_batch_caps_default_on(cv: Converge) -> None:
    eff = _effective(cv)
    assert eff["steps"] == {"escalate": True, "early_cut": True, "gap_hunt": True}
    assert eff["caps"]["angles_per_claim"] == 5
    assert eff["caps"]["batch_items"] == 30
    assert eff["caps"]["cut_rounds"] == 5


def test_task_layer_turns_steps_off(cv: Converge) -> None:
    task = cv.root / "task.yaml"
    task.write_text("steps: {escalate: false}\ncaps: {batch_items: 10, angles_per_claim: 2}\n")
    eff = _effective(cv, "--config", str(task))
    assert eff["steps"] == {"escalate": False, "early_cut": True, "gap_hunt": True}
    assert eff["caps"]["batch_items"] == 10 and eff["caps"]["angles_per_claim"] == 2


def test_steps_values_must_be_booleans(cv: Converge) -> None:
    bad = cv.root / "bad.yaml"
    bad.write_text("steps: {escalate: 'no', early_cut: 0, colour: true}\n"
                   "caps: {batch_items: 0, angles_per_claim: true}\n")
    err = cv("config", "validate", "--project-root", str(cv.project), "--config", str(bad),
             code=2).stderr
    for fragment in ("steps.escalate must be true or false; got 'no'",
                     "steps.early_cut must be true or false; got 0",
                     "unknown key steps.colour",
                     "caps.batch_items must be a positive integer",
                     "caps.angles_per_claim must be a positive integer"):
        assert fragment in err


def test_snapshot_without_steps_or_batch_caps_is_valid() -> None:
    legacy = copy.deepcopy(config_mod.DEFAULTS)
    del legacy["steps"]
    for key in ("angles_per_claim", "batch_items"):
        del legacy["caps"][key]
    assert config_mod.validate_config(legacy, "snapshot", complete=True) == []


def test_init_snapshots_steps(cv: Converge) -> None:
    cv.init(defaults=True)
    config = cv.events()[0]["config"]
    assert config["steps"] == {"escalate": True, "early_cut": True, "gap_hunt": True}
    assert config["caps"]["batch_items"] == 30


def test_steps_snapshot_needs_the_batch_caps() -> None:
    snapshot = copy.deepcopy(config_mod.DEFAULTS)
    del snapshot["caps"]["batch_items"]
    problems = config_mod.validate_config(snapshot, "snapshot", complete=True)
    assert problems == ["snapshot: caps.batch_items is missing"]
