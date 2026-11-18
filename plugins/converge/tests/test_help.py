"""Public help exposes values, conditions, and runnable command examples."""
from __future__ import annotations

import json
import re

import pytest

from conftest import Converge


@pytest.mark.parametrize("command,values,conditions", [
    ("reply", ("rebut", "decline"), ("evidence", "rebut", "fresh-eye")),
    ("verdict", ("agree", "disagree"), ("evidence", "disagree", "fresh-eye")),
    ("cut", ("before", "after"), ("choice", "required", "after")),
    ("file", ("lens", "gap-hunt"), ("origin", "required", "lens")),
    ("angle-na", ("find", "attack"), ("lens", "claim", "required")),
    ("attack", (), ("refuted", "fresh-eye", "positive integer")),
    ("clean", (), ("checks", "positive_control", "stdin")),
    ("act", (), ("source_seq", "role", "stdin")),
])
def test_leaf_help_exposes_values_and_conditions(cv: Converge, command: str,
                                                values: tuple[str, ...],
                                                conditions: tuple[str, ...]) -> None:
    text = cv(command, "--help").stdout
    assert "example:" in text
    for term in (*values, *conditions):
        assert term in text, (command, term, text)


def test_escalate_help_explains_the_no_widening_action(cv: Converge) -> None:
    text = cv("escalate", "--help").stdout
    assert "omit both" in text
    assert "still record" in text


def _argument_help(text: str, name: str) -> str:
    """Return one argument's help, including argparse's wrapped description."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(rf"^\s*{re.escape(name)}(?:\s|$)", line):
            continue
        fields = re.split(r"\s{2,}", line.strip(), maxsplit=1)
        description = [fields[1]] if len(fields) == 2 else []
        for continuation in lines[index + 1:]:
            stripped = continuation.strip()
            if not stripped or stripped.startswith(("-", "example:")):
                break
            if not continuation[:1].isspace():
                break
            description.append(stripped)
        return " ".join(description)
    return ""


def test_init_help_explains_snapshot_pass_and_since_requirements(cv: Converge) -> None:
    text = cv("init", "--help").stdout
    pass_help = _argument_help(text, "--pass").lower()
    snapshot_help = _argument_help(text, "--snapshot").lower()
    since_help = _argument_help(text, "--since").lower()

    assert ">= 1" in pass_help
    assert ">= 2" not in pass_help
    assert "--pass" in snapshot_help and "requires" in snapshot_help
    assert "--snapshot" in since_help and "requires" in since_help
    assert "previous" in since_help and "pass" in since_help
    assert "snapshot" in since_help and ("+ 1" in since_help or "one more" in since_help)


@pytest.mark.parametrize("command", ("attack", "escalate", "rebut", "reply", "verdict"))
def test_non_cut_evidence_help_uses_its_route_contract(cv: Converge, command: str) -> None:
    text = cv(command, "--help").stdout
    evidence_help = _argument_help(text, "--evidence")

    assert evidence_help
    assert "ANGLE=TEXT" not in evidence_help


def test_cut_evidence_help_explains_repeated_angle_values(cv: Converge) -> None:
    evidence_help = _argument_help(cv("cut", "--help").stdout, "--evidence")

    assert "ANGLE=TEXT" in evidence_help


@pytest.mark.parametrize("command,required_terms", [
    ("init", ("git", "refs/converge")),
    ("angles", (".bootgear/config",)),
    ("config", (".bootgear/config",)),
    ("prune", ("refs/converge",)),
])
def test_project_root_help_names_what_it_selects(cv: Converge, command: str,
                                                  required_terms: tuple[str, ...]) -> None:
    description = _argument_help(cv(command, "--help").stdout, "--project-root").lower()

    assert description
    for term in required_terms:
        assert term in description


def test_prune_help_explains_slate_ref_argument(cv: Converge) -> None:
    description = _argument_help(cv("prune", "--help").stdout, "slate").lower()

    assert "refs/converge/" in description


def test_status_json_help_explains_output_format(cv: Converge) -> None:
    description = _argument_help(cv("status", "--help").stdout, "--json").lower()

    assert "json" in description


def _action_example(text: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("action") in {"attack", "clean"}:
            return value
    pytest.fail("help must include a JSON action object example")


def _fill_action_context(value: dict[str, object], cv: Converge, claim: str) -> dict[str, object]:
    value = dict(value)
    value.update(slate="s1", source_seq=len(cv.events()), role="r1", claim=claim, batch=1)
    return value


def test_clean_help_json_example_runs_against_a_ready_slate(cv: Converge) -> None:
    [claim] = cv.ready()
    value = _action_example(cv("clean", "--help").stdout)
    assert value["action"] == "clean"
    checks = value.get("checks")
    assert isinstance(checks, list) and checks
    check = checks[0]
    assert isinstance(check, dict)
    assert check.get("angle") in ("cited-but-unread", "point-in-time", "provenance",
                                  "reachability", "absent-vs-default")
    for field in ("tell", "evidence", "searches", "positive_control"):
        assert isinstance(check.get(field), str) and check[field].strip()

    path = cv.root / "clean-help-example.json"
    path.write_text(json.dumps(_fill_action_context(value, cv, claim)))
    before = len(cv.events())
    result = cv("clean", "s1", "--dir", str(cv.dir), "--as", "r1", "--input", str(path))

    assert result.stdout.startswith("CLEAN seq=")
    assert len(cv.events()) == before + 1
    assert cv.events()[-1]["event"] == "clean"


def test_act_help_json_example_runs_against_a_ready_slate(cv: Converge) -> None:
    [claim] = cv.ready()
    value = _action_example(cv("act", "--help").stdout)
    action = value.get("action")
    assert isinstance(action, str) and action in {"attack", "clean"}
    if action == "attack":
        assert value.get("angle") in ("cited-but-unread", "point-in-time", "provenance",
                                      "reachability", "absent-vs-default")
        for field in ("tell", "evidence", "searches", "positive_control"):
            field_value = value.get(field)
            assert isinstance(field_value, str) and field_value.strip()
    else:
        checks = value.get("checks")
        assert isinstance(checks, list) and checks
        check = checks[0]
        assert isinstance(check, dict)
        for field in ("angle", "tell", "evidence", "searches", "positive_control"):
            field_value = check.get(field)
            assert isinstance(field_value, str) and field_value.strip()

    path = cv.root / "act-help-example.json"
    path.write_text(json.dumps(_fill_action_context(value, cv, claim)))
    before = len(cv.events())
    result = cv("act", "s1", "--dir", str(cv.dir), "--as", "r1", "--input", str(path))

    assert result.stdout.startswith(f"{action.upper()} seq=")
    assert len(cv.events()) == before + 1
    assert cv.events()[-1]["event"] == action
