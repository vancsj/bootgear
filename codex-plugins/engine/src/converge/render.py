"""Markdown report rendered from the replayed ledger only."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import effort, model, protocol
from .model import Slate


def _cell(text: str | None) -> str:
    return (text or "-").replace("|", "\\|").replace("\n", " ")


def _text(value: object) -> str | None:
    return None if value is None else str(value)


@dataclass
class LensCoverage:
    ran: list[str]
    na: dict[str, str]
    missing: list[str]


def coverage(slate: Slate) -> dict[str, LensCoverage]:
    """Per init lens: find angles run, n/a (with reason), and missing."""
    result: dict[str, LensCoverage] = {}
    for lens in slate.lenses:
        ran = sorted({r["angle"] for r in slate.find_runs if r["lens"] == lens})
        na = {r["angle"]: r["reason"] for r in slate.angle_na
              if r["phase"] == "find" and r.get("lens") == lens}
        applicable = [row["id"] for row in slate.angles
                      if row["tag"] == "find" and row.get("lens") in (None, lens)]
        missing = [a for a in applicable if a not in ran and a not in na]
        result[lens] = LensCoverage(ran, dict(sorted(na.items())), missing)
    return result


def _coverage_lines(slate: Slate) -> list[str]:
    lines = ["## Coverage", ""]
    cov = coverage(slate)
    if not cov:
        lines.append("No lenses.")
    for lens, row in cov.items():
        na_text = "; ".join(f"{a} ({reason})" for a, reason in row.na.items()) or "none"
        lines.append(f"- **{lens}** — ran: {', '.join(row.ran) or 'none'} · n/a: {na_text} · "
                     f"missing: {', '.join(row.missing) or 'none'}")
    return lines


def _killed_lines(slate: Slate) -> list[str]:
    """Each killed claim with the refuted attack its finder declined to rebut, and the
    refuter's disagree evidence when the decline answered it."""
    lines = []
    for claim in slate.claims.values():
        if claim.live:
            continue
        batch = next(b for b, replies in claim.state.replies.items()
                     if any(r["stance"] == "decline" for r in replies))
        attack = next(e for e in claim.state.attacks[batch] if e["outcome"] == "refuted")
        line = (f"- **{claim.id}** killed by {attack['as']} ({attack['angle']}, batch {batch}) "
                f"— {_cell(claim.text)} — evidence: {_cell(attack['evidence'])}")
        disagree = [v for v in claim.state.verdicts.get(batch, []) if v["verdict"] == "disagree"]
        if disagree:
            line += f" · verdict disagree: {_cell(disagree[0]['evidence'])}"
        lines.append(line)
    return lines


def claim_inputs(slate: Slate) -> list[dict[str, str]]:
    """Each claim's filed trigger, evidence and tier, in filing order."""
    return [{"id": c.id, "trigger": c.trigger, "evidence": c.evidence, "tier": c.tier}
            for c in slate.claims.values()]


RATED = (*model.CUT_FIELDS, *model.AFTER_FIELDS)
COLUMNS = ("rank", "claim", "lens", "loc", "text", *RATED, "status")


def _table(rows: list[model.CutoffRow], with_cut: bool) -> list[str]:
    """The Findings table (`with_cut`) or the Follow-up table, which carries each choice."""
    extra = ("cut",) if with_cut else ("choice",)
    columns = (*COLUMNS, *extra, "reason")
    if not rows:
        return ["None."]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        rating = row.claim.state.rating or {}
        last = row.cut if with_cut else _cell(rating.get("choice"))
        cells = [str(row.rank), row.claim.id, _cell(row.claim.lens), _cell(row.claim.loc),
                 _cell(row.claim.text), *(_cell(_text(rating.get(f))) for f in RATED),
                 row.status, last, _cell(row.reason)]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


FIX_COLUMNS = ("rank", "claim", "lens", "loc", "text", "impact", "reach", "difficulty",
               "patch lines")
# The result counts of the summary and of `converge cutoff`, in this order.
RESULT_COUNTS = (("fix-now", "fix-now"), ("fixed", "fixed"), ("findings", "finding"),
                 ("follow-up", "follow-up"), ("killed", "killed"))


def counts(rows: list[model.CutoffRow]) -> str:
    """`fix-now=N fixed=N findings=N follow-up=N killed=N`."""
    return " ".join(f"{label}={sum(row.result == result for row in rows)}"
                    for label, result in RESULT_COUNTS)


def _fix_table(slate: Slate, rows: list[model.CutoffRow]) -> list[str]:
    """Claims with a cheap fix to apply, or applied and checked, with the patch's changed
    lines."""
    if not rows:
        return ["None."]
    root = Path(slate.project_root) if slate.project_root else None
    globs = slate.config["cutoff"]["cheap"]["test_globs"]
    lines = ["| " + " | ".join(FIX_COLUMNS) + " |", "|" + "---|" * len(FIX_COLUMNS)]
    for row in rows:
        rating = row.claim.state.rating or {}
        size = effort.measure(rating["patch"], globs, root)
        cells = [str(row.rank), row.claim.id, _cell(row.claim.lens), _cell(row.claim.loc),
                 _cell(row.claim.text), _cell(rating.get("impact")), _cell(rating.get("reach")),
                 _cell(rating.get("difficulty")), str(size["lines"])]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _snapshot_lines(slate: Slate) -> list[str]:
    if slate.review_pass is None:
        return []
    line = f"pass: {slate.review_pass}"
    if slate.snapshot:
        line += f" · snapshot: {slate.snapshot}"
    lines = [line, ""]
    delta = model.delta_command(slate)
    if delta and slate.since:
        lines += [f"delta since `{slate.since['slate']}`: `{delta}`", ""]
    return lines


def render(slate: Slate) -> str:
    """The report from the cutoff rows of the current state; `cutoff:` says whether a
    `cutoff` event records them."""
    from .protocol import converged, slate_phase

    cutoff_state = "current" if slate.cutoff_valid else ("stale" if slate.cutoff else "none")
    rows = protocol.compute_cutoff(slate)
    findings = [r for r in rows if r.result == "finding"]
    fix_now = [r for r in rows if r.result == "fix-now"]
    fixed = [r for r in rows if r.result == "fixed"]
    follow_up = [r for r in rows if r.result == "follow-up"]
    choices = [r for r in findings if (r.claim.state.rating or {}).get("choice")]
    lines = [f"# converge slate `{slate.slate_id}`", "",
             f"{counts(rows)} converged={'yes' if converged(slate) else 'no'}", "",
             (f"lenses: {', '.join(slate.lenses)} · claims: {len(slate.claims)} · "
              f"phase: {slate_phase(slate)} · cutoff: {cutoff_state}"), "",
             *_snapshot_lines(slate)]
    lines += ["## Findings", "", *_table(findings, with_cut=True)]
    lines += ["", "## Fix now", "", *_fix_table(slate, fix_now)]
    lines += ["", "## Fixed", "", *_fix_table(slate, fixed)]
    lines += ["", "## Choices", ""]
    lines += [f"- **{r.claim.id}** ({r.result}) — {(r.claim.state.rating or {}).get('choice')}"
              for r in choices] or ["None."]
    lines += ["", "## Follow-up", "", *_table(follow_up, with_cut=False)]
    lines += ["", "## Killed", "", *(_killed_lines(slate) or ["None."])]
    lines += [""] + _coverage_lines(slate)
    return "\n".join(lines) + "\n"
