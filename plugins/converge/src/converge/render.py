"""Markdown report rendered from the replayed ledger only."""
from __future__ import annotations

from dataclasses import dataclass

from . import model
from .model import Claim, Slate


def _cell(text: str | None) -> str:
    return (text or "-").replace("|", "\\|").replace("\n", " ")


def _angles_used(claim: Claim) -> str:
    return ", ".join(sorted(claim.used_angles)) or "none"


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


def _dead_lines(slate: Slate, kinds: tuple[str, ...]) -> list[str]:
    lines = []
    for claim in slate.claims.values():
        if claim.dead in kinds and claim.dead_event is not None:
            ev = claim.dead_event
            lines.append(f"- **{claim.id}** {claim.dead} by {ev['as']} ({ev['angle']}, round "
                         f"{ev['round']}) — {claim.text} — reason: {ev['evidence']}")
    return lines


def _claim_row(slate: Slate, claim: Claim, rank: int | None, extra: str) -> str:
    cut = claim.last_cut() or {}
    return "| " + " | ".join([
        str(rank) if rank is not None else "-", claim.id, _cell(claim.lens), _cell(claim.loc),
        _cell(claim.text), _cell(cut.get("frequency")), _cell(cut.get("severity")),
        _cell(cut.get("confidence")), _cell(cut.get("difficulty")),
        slate.refute_state(claim), model.cut_note(claim, slate.cap("cut_rounds")), _cell(extra),
    ]) + " |"


HEADER = ("| rank | claim | lens | loc | finding | frequency | severity | confidence | "
          "difficulty | refute | cut | note |")
RULE = "|" + "---|" * 12


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


def render_full(slate: Slate) -> str:
    cutoff_state = "current" if slate.cutoff_valid else ("stale" if slate.cutoff else "none")
    lines = [f"# converge slate `{slate.slate_id}`", "",
             (f"mode: full · lenses: {', '.join(slate.lenses)} · claims: {len(slate.claims)} · "
              f"cutoff: {cutoff_state}"), "", *_snapshot_lines(slate)]
    if slate.cutoff_valid:
        rows = model.compute_cutoff(slate)
        reported = [r for r in rows if r.result == "reported"]
        appendix = [r for r in rows if r.result == "appendix"]
        lines += ["## Reported", ""]
        if reported:
            lines += [HEADER, RULE]
            lines += [_claim_row(slate, r.claim, r.rank, r.reason) for r in reported]
        else:
            lines.append("None.")
        choices = [r for r in rows if (r.claim.last_cut() or {}).get("choice")]
        lines += ["", "## Choices", ""]
        lines += [f"- **{r.claim.id}** ({r.result}) — {(r.claim.last_cut() or {}).get('choice')}"
                  for r in choices] or ["None."]
        uncertain = [r for r in rows if slate.refute_state(r.claim) in ("inconclusive", "unconverged")]
        lines += ["", "## Inconclusive / unconverged", ""]
        lines += [f"- **{r.claim.id}** {slate.refute_state(r.claim)} — {r.claim.text} — angles: "
                  f"{_angles_used(r.claim)}" for r in uncertain] or ["None."]
        lines += ["", "## Appendix", ""]
        if appendix:
            lines += [f"<details><summary>{len(appendix)} below the cutoff</summary>", "",
                      HEADER, RULE]
            lines += [_claim_row(slate, r.claim, r.rank, r.reason) for r in appendix]
            lines += ["", "</details>"]
        else:
            lines.append("None.")
    else:
        lines += ["## Live claims (no current cutoff)", ""]
        live = sorted(slate.live_claims(), key=model.rank_key)
        if live:
            lines += [HEADER, RULE]
            lines += [_claim_row(slate, c, None, "-") for c in live]
        else:
            lines.append("None.")
    lines += ["", "## Killed / retracted", ""]
    lines += _dead_lines(slate, model.DEAD_OUTCOMES) or ["None."]
    lines += [""] + _coverage_lines(slate)
    return "\n".join(lines) + "\n"


def render_refute_only(slate: Slate) -> str:
    lines = [f"# converge slate `{slate.slate_id}`", "",
             f"mode: refute-only · claims: {len(slate.claims)}", "", *_snapshot_lines(slate)]
    live = list(slate.live_claims())
    downgraded = [c for c in live if c.downgrades]
    rest = [c for c in live if not c.downgrades]
    sections = (("Survived", "converged"), ("Inconclusive", "inconclusive"),
                ("Unconverged", "unconverged"), ("Open", "open"))
    for title, state in sections:
        claims = [c for c in rest if slate.refute_state(c) == state]
        if state == "open" and not claims:
            continue
        lines += [f"## {title}", ""]
        lines += [f"- **{c.id}** {c.text} — angles: {_angles_used(c)}" for c in claims] or ["None."]
        lines.append("")
    lines += ["## Downgraded", ""]
    lines += [f"- **{c.id}** {c.original} → {c.text} ({slate.refute_state(c)}) — forced by: "
              + "; ".join(f"{d['as']} ({d['angle']}): {d['evidence']}" for d in c.downgrades)
              for c in downgraded] or ["None."]
    for title, kind in (("Killed", "killed"), ("Retracted", "retracted")):
        lines += ["", f"## {title}", ""]
        lines += _dead_lines(slate, (kind,)) or ["None."]
    return "\n".join(lines) + "\n"


def render(slate: Slate) -> str:
    return render_full(slate) if slate.mode == "full" else render_refute_only(slate)
