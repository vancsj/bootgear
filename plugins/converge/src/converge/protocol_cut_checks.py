"""Check ratings, cutoff replies, and fix evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import effort, ledger, model
from .model import Claim, Slate
from .protocol import (
    CALLERS,
    FIX_CHECK_OUTCOME,
    MIGRATION,
    WHEN,
    _first_match,
    _live,
    _program,
    _rule_values,
)


def _cut_evidence(slate: Slate, event: dict[str, Any], fields: tuple[str, ...],
                  problems: list[str]) -> None:
    """Every evidence key is an evaluate angle, and the angles cover each of `fields`."""
    evidence = event.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        problems.append("`evidence` must map evaluate angle ids to evidence text")
        return
    covered: set[str] = set()
    for key, text in evidence.items():
        row = ledger.angle(slate, "evaluate", key, problems)
        if not isinstance(text, str) or not text.strip():
            problems.append(f"evidence for {key!r} must be non-empty text")
        if row is not None and row.get("field"):
            covered.add(row["field"])
    for name in fields:
        if name not in covered:
            problems.append(f"cut: no evidence for `{name}` (give an evaluate angle whose field is {name})")


def _cut_choice(slate: Slate, claim: Claim, event: dict[str, Any], problems: list[str]) -> None:
    """An after cut needs `choice` when the lens's `choice_if` matches, or, while
    `cutoff.cheap.enabled` is true, when `difficulty` is cross-cutting or redesign."""
    if ledger.given(event, "choice"):
        return
    difficulty = event.get("difficulty")
    if (slate.config["cutoff"]["cheap"]["enabled"]
            and difficulty in model.CHOICE_DIFFICULTY):
        problems.append(f"cut: {claim.id} has difficulty {difficulty}; "
                        f"a non-empty `choice` is required")
        return
    values = _rule_values(claim, {"rate": 0, **event}, *model.CUT_FIELDS, *model.AFTER_FIELDS)
    values["status"] = claim.state.status
    matched = _first_match(slate.lens_policy(claim.lens).get("choice_if", []), values)
    if matched is not None:
        problems.append(f"cut: {claim.id} matches choice_if[{matched}]; "
                        f"a non-empty `choice` is required")


def _cut_patch(slate: Slate, claim: Claim, event: dict[str, Any], problems: list[str]) -> None:
    """Validate production remedy context or artifact-based patch classification."""
    if slate.config["cutoff"]["difficulty_basis"] == "implementation":
        for key in ("callers", "migration"):
            if not ledger.given(event, key):
                problems.append(f"cut: {claim.id} implementation remedy needs `{key}`")
            elif event.get("difficulty") in model.CHEAP_DIFFICULTY and event[key] != "none":
                problems.append(f"cut: {claim.id} difficulty {event.get('difficulty')} "
                                f"needs `{key}` none; got {event[key]!r}")
        patch = event.get("patch")
        if isinstance(patch, str) and patch.strip():
            try:
                effort.measure(patch, slate.config["cutoff"]["cheap"]["test_globs"],
                               Path(slate.project_root) if slate.project_root else None)
            except effort.EffortError as exc:
                problems.append(f"cut: {claim.id} `patch`: {exc}")
        return
    difficulty = event.get("difficulty")
    cheap_class = difficulty in model.CHEAP_DIFFICULTY
    where = f"cut: {claim.id} difficulty {difficulty}"
    if cheap_class:
        for key in ("callers", "migration"):
            if event.get(key) != "none":
                problems.append(f"{where} needs `{key}` none; got {event.get(key)!r}")
    patch = event.get("patch")
    if not isinstance(patch, str) or not patch.strip():
        if cheap_class:
            problems.append(f"{where} needs `patch`")
        return
    if slate.project_root is None:
        problems.append("cut: the slate's init records no project_root; a patch cannot be "
                        "measured")
        return
    limits = slate.config["cutoff"]["cheap"]
    root = Path(slate.project_root)
    try:
        size = effort.measure(patch, limits["test_globs"], root)
    except effort.EffortError as exc:
        problems.append(f"cut: {claim.id} `patch`: {exc}")
        return
    if not cheap_class:
        return
    lines_key = "trivial_lines" if difficulty == "trivial" else "lines"
    for count, key, text in ((size["files"], "files", "touches {} non-test files"),
                             (size["test_files"], "tests", "touches {} test files"),
                             (size["lines"], lines_key, "changes {} lines")):
        if count > limits[key]:
            problems.append(f"{where}: the patch {text.format(count)}; cutoff.cheap.{key} is "
                            f"{limits[key]}")
    loc_path = claim.loc.rsplit(":", 1)[0]
    for path in size["paths"]:
        if not effort.same_file(path, loc_path, root):
            problems.append(f"{where}: patch file {path} is not the claim's loc file {loc_path}")
    if difficulty == "local" and size["lines"] <= limits["trivial_lines"]:
        problems.append(f"{where}: the patch changes {size['lines']} lines, within "
                        f"cutoff.cheap.trivial_lines {limits['trivial_lines']}; type trivial")


def _validate_cut(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    when = ledger.enum(event, "when", WHEN, problems)
    rnd = ledger.round_number(event, problems)
    for name in ("impact", "size", "reach"):
        ledger.enum(event, name, model.FIELD_ENUMS[name], problems)
    rate = event.get("rate")
    if "rate" in event and (not isinstance(rate, int) or isinstance(rate, bool) or rate < 0):
        problems.append(f"`rate` must be a non-negative integer; got {rate!r}")
    if when == "before":
        for key in ("difficulty", "patch"):
            if key in event:
                problems.append(f"cut: a before cut carries no `{key}`")
    elif when == "after":
        if "difficulty" not in event:
            problems.append("cut: an after cut needs `difficulty`")
        else:
            ledger.enum(event, "difficulty", model.DIFFICULTY, problems)
    for key, allowed in (("callers", CALLERS), ("migration", MIGRATION)):
        if key in event:
            ledger.enum(event, key, allowed, problems)
    for key in ("choice", "patch"):
        if key in event:
            ledger.nonempty(event, key, problems)
    claim = _live(claim, problems)
    counts_rate = claim is not None and slate.counts_rate(claim.lens)
    fields = tuple(f for f in model.CUT_FIELDS if f != "rate" or counts_rate)
    _cut_evidence(slate, event, (*fields, *model.AFTER_FIELDS) if when == "after" else fields,
                  problems)
    if claim is None:
        return
    if counts_rate and "rate" not in event:
        problems.append(f"cut: {claim.id}'s lens {claim.lens} has a rate_at_least rule; "
                        f"`rate` is required")
    ledger.roles(slate, claim, agent, "cut", problems)
    if when == "after":
        _cut_choice(slate, claim, event, problems)
        _cut_patch(slate, claim, event, problems)
    if when is None:
        return
    track = claim.state.cuts[when]
    if track.awaits_finder():
        problems.append(f"cut: {claim.id} {when} round {track.round} awaits its finder; "
                        f"the finder must accept or rebut it first")
    if rnd is not None:
        expected = track.round + 1
        cap = slate.cap("cut_rounds")
        if rnd > cap:
            problems.append(f"cut: round {rnd} exceeds caps.cut_rounds {cap}")
        elif rnd != expected:
            problems.append(f"cut: {claim.id} next {when} cut round is {expected}, got {rnd}")


def _validate_accept(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    when = ledger.enum(event, "when", WHEN, problems)
    rnd = ledger.round_number(event, problems)
    claim = _live(claim, problems)
    if claim is None or rnd is None or when is None:
        return
    if agent != claim.finder:
        problems.append(f"accept: only {claim.id}'s finder {claim.finder} may accept")
    track = claim.state.cuts[when]
    last = track.round
    if last == 0:
        problems.append(f"accept: {claim.id} has no {when} cut round to accept")
    elif rnd != last:
        problems.append(f"accept: {claim.id} latest {when} cut round is {last}, got {rnd}")
    elif track.accepted == last:
        problems.append(f"accept: {claim.id} {when} cut round {last} is already accepted")
    elif track.pending == last:
        problems.append(f"accept: {claim.id} {when} cut round {last} was rebutted; "
                        f"answer the next cut round")


def _validate_rebut(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """The finder challenges the latest cut round with new evidence."""
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    when = ledger.enum(event, "when", WHEN, problems)
    evidence = ledger.rebut_evidence(event, problems)
    claim = _live(claim, problems)
    if claim is None or when is None:
        return
    if agent != claim.finder:
        problems.append(f"rebut: only {claim.id}'s finder {claim.finder} may rebut")
    if claim.state.cuts[when].round == 0:
        problems.append(f"rebut: {claim.id} has no {when} cut round to rebut")
    if evidence is not None and ledger.evidence_hash(evidence) in claim.state.rebut_hashes["cut"]:
        problems.append(f"rebut: this evidence was already given for {claim.id}; "
                        f"a rebut needs new evidence")


def _validate_fix_check(slate: Slate, event: dict[str, Any], problems: list[str]) -> None:
    """After the cutoff, once per fix-now claim, by anyone but its finder; `pass` names the
    patch-only re-review slate, which the CLI reads before writing."""
    agent = event.get("as")
    claim = ledger.known_claim(slate, event, problems)
    outcome = ledger.enum(event, "outcome", FIX_CHECK_OUTCOME, problems)
    ledger.nonempty(event, "evidence", problems)
    review = event.get("review_slate")
    if "review_slate" in event:
        if not (isinstance(review, str) and model.ID_RE.match(review)):
            problems.append(f"`review_slate` must match {model.ID_RE.pattern}; got {review!r}")
        elif review == slate.slate_id:
            problems.append(f"fix-check: `review_slate` must name another slate than "
                            f"{slate.slate_id}")
    elif outcome == "pass":
        problems.append("fix-check: outcome pass needs `review_slate`, the slate that "
                        "re-reviewed only the patch")
    claim = _live(claim, problems)
    if claim is None:
        return
    if agent == claim.finder:
        problems.append(f"fix-check: {agent} filed {claim.id} and may not check its fix")
    if claim.fix_check is not None:
        problems.append(f"fix-check: {claim.id} already has a fix-check; a fix is checked once")
    if slate.cutoff is None:
        problems.append(f"fix-check: the slate has no cutoff event; run `{_program()} cutoff` first")
        return
    stored = {row["claim"]: row["result"] for row in slate.cutoff["results"]}
    if stored.get(claim.id) != "fix-now":
        problems.append(f"fix-check: {claim.id}'s cutoff result is {stored.get(claim.id)}; "
                        f"fix-check takes a fix-now claim")
