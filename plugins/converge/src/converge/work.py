"""Role work and editable actions derived from the validated slate."""
from __future__ import annotations

import copy
from typing import Any

from . import ledger, model, protocol, render, seats
from .model import Claim, Slate

ACTION_KINDS = tuple(kind for kind in model.EVENTS if kind != "init")
META = {"slate", "source_seq", "role", "seat", "action", "context"}
COMPUTED = {"event", "as", "seq", "ts", "id", "results", "evidence_sha256"}


def seat(slate: Slate, actor: str, requested: str | None = None) -> str:
    if requested is not None:
        return requested
    if actor == slate.events[0]["as"]:
        return "main"
    for role, agent in protocol.role_agents(slate).items():
        if actor == agent:
            return role
    for claim in slate.claims.values():
        if actor == claim.finder:
            return protocol.finder_role(claim)
        if actor in claim.state.cutters:
            return "cutter"
    if actor in seats.SEATS:
        return actor
    raise ledger.LedgerError([(f"work: no saved seat for {actor!r}; supply --role "
                              f"from {', '.join(seats.SEATS)}")])


def _check(angle: str) -> dict[str, str]:
    return {"angle": angle, "tell": "", "evidence": "", "searches": "", "positive_control": ""}


def _claim(claim: Claim, row: dict[str, Any]) -> dict[str, Any]:
    item = {"id": claim.id, "claim": claim.text, "loc": claim.loc, "trigger": claim.trigger,
            "evidence": claim.evidence, "tier": claim.tier, "lens": claim.lens,
            "status": claim.state.status,
            **{key: value for key, value in row.items() if key != "claim"}}
    batch = row.get("batch")
    if batch is not None:
        item.update(attacks=claim.state.attacks.get(batch, []),
                    replies=claim.state.replies.get(batch, []),
                    verdicts=claim.state.verdicts.get(batch, []))
    elif row["action"] == "cut-after":
        attacks = [check for checks in claim.state.attacks.values() for check in checks
                   if check["outcome"] == "refuted"]
        batches = {check["batch"] for check in attacks}
        item["attacks"] = sorted(attacks, key=lambda event: event["seq"])
        for field in ("replies", "verdicts"):
            responses = getattr(claim.state, field)
            item[field] = sorted((event for batch in batches for event in responses.get(batch, [])),
                                 key=lambda event: event["seq"])
    if row["action"] in ("cut-before", "cut-after", "accept"):
        item["cuts"] = {when: {"rounds": list(track.rounds.values()), "pending": track.pending,
                               "accepted": track.accepted}
                        for when, track in claim.state.cuts.items() if track.rounds}
    return item


def package(slate: Slate, actor: str, role_host: str,
            requested: str | None = None) -> dict[str, Any]:
    role = seat(slate, actor, requested)
    if role == "main" and actor != slate.events[0]["as"]:
        raise ledger.LedgerError([f"work: main is {slate.events[0]['as']}; use that --as value"])
    bound = protocol.role_agents(slate).get(role)
    if bound is not None and bound != actor:
        raise ledger.LedgerError([f"work: {role} is {bound}; use that --as value"])
    phase = protocol.slate_phase(slate)
    actions: list[dict[str, Any]] = []
    definitions: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []

    def add(kind: str, fields: dict[str, Any], required: list[str] | None = None,
            conditions: list[str] | None = None, context: dict[str, Any] | None = None) -> None:
        value = {"slate": slate.slate_id, "source_seq": len(slate.events), "role": actor,
                 "seat": role, "action": kind, "context": {"phase": phase, **(context or {})},
                 **fields}
        actions.append({"input": value, "required": required or [], "conditions": conditions or []})

    if phase == "find" and role == "finder":
        for lens, coverage in render.coverage(slate).items():
            for angle in coverage.missing:
                definitions.add(("find", angle))
                items.append({"lens": lens, "angle": angle, "action": "find"})
                add("file", {"lens": lens, "angle": angle, "origin": "lens", "loc": "",
                             "claim": "", "trigger": "", "evidence": "", "tier": ""},
                    ["loc", "claim", "trigger", "evidence", "tier"],
                    ["tier: reproduced, traced, or inferred; file each supported claim"])
                add("find-run", {"lens": lens, "angle": angle, "tell": "", "searches": "",
                                 "positive_control": "", "result": ""},
                    ["tell", "searches", "positive_control", "result"],
                    ["result: none or a list of filed claim ids"])
                add("angle-na", {"phase": "find", "lens": lens, "angle": angle, "reason": ""},
                    ["reason"], ["use only when the angle's tell does not apply"])

    gap_open = (slate.init_refuters == 2 and slate.config["steps"]["gap_hunt"]
                and phase not in ("find", "done")
                and not any(event["event"] in ("escalate", "cut", "clean", "attack")
                                                for event in slate.events))
    if role == "r2" and gap_open:
        items.append({"action": "gap-hunt", "rule": "find what the lenses missed; report when done"})
        definitions.update(("find", angle["id"]) for angle in slate.angles if angle["tag"] == "find")
        add("file", {"origin": "gap-hunt", "lens": "", "angle": "", "loc": "", "claim": "",
                     "trigger": "", "evidence": "", "tier": ""},
            ["lens", "angle", "loc", "claim", "trigger", "evidence", "tier"])

    for chunk in protocol.batch_plan(slate):
        for row in chunk:
            if row["agent_role"] != role:
                continue
            claim = slate.claims[row["claim"]]
            if row["action"] in ("cut-before", "cut-after", "attack", "verdict"):
                problems: list[str] = []
                ledger.roles(slate, claim, actor, "cut" if role == "cutter" else "attack", problems)
                if role in ("r1", "r2"):
                    protocol._refuter_role(slate, claim, actor, row["batch"], "attack", problems)
                if problems:
                    continue
            if role in ("finder", "r2") and row["action"] in ("escalate", "accept", "reply") \
                    and claim.finder != actor:
                continue
            items.append(_claim(claim, row))
            kind, batch = row["action"], row["batch"]
            base = {"claim": claim.id}
            if batch is not None:
                base["batch"] = batch
            if kind == "escalate":
                add("escalate", base, conditions=["no widening: submit this action without wider or evidence"])
                add("escalate", {**base, "wider": "", "evidence": ""}, ["wider", "evidence"],
                    ["widening needs a concrete route in evidence"])
            elif kind == "attack":
                names = row["angles"] if batch != protocol.FRESH_EYE else [""]
                definitions.update(("attack", name) for name in row["angles"])
                add("clean", {**base, "checks": [_check(name) for name in names]},
                    ["checks[].angle", "checks[].tell", "checks[].evidence", "checks[].searches",
                     "checks[].positive_control"],
                    ["keep only checked clean angles; record refutations separately",
                     "fresh-eye: choose unused names; last=true closes below the cap"])
                add("attack", {**base, **_check("")}, list(protocol.CHECK_FIELDS),
                    ["choose one angle from the current item; fresh-eye uses a new name",
                     "records one refuted angle; fresh-eye permits last=true"])
                if batch != protocol.FRESH_EYE:
                    add("angle-na", {"phase": "attack", "claim": claim.id, "angle": "",
                                     "reason": ""}, ["angle", "reason"],
                        ["choose one angle from the current item"])
            elif kind == "reply":
                add("reply", {**base, "stance": "rebut", "evidence": ""}, ["evidence"],
                    ["new evidence is required; text may clarify the claim"])
                add("reply", {**base, "stance": "decline"})
            elif kind == "verdict":
                add("verdict", {**base, "verdict": "agree"})
                add("verdict", {**base, "verdict": "disagree", "evidence": ""}, ["evidence"])
            else:
                when = kind.removeprefix("cut-") if kind.startswith("cut-") else phase.removeprefix("cut-")
                track = claim.state.cuts[when]
                context = {"claim": claim.id, "when": when, "round": track.round}
                if kind == "accept":
                    add("accept", {**base, "when": when, "round": track.round}, context=context)
                    add("rebut", {**base, "when": when, "evidence": ""}, ["evidence"], context=context)
                else:
                    fields = [field for field in model.CUT_FIELDS if field != "rate" or slate.counts_rate(claim.lens)]
                    if when == "after":
                        fields.extend(model.AFTER_FIELDS)
                    evaluate = [angle for angle in slate.angles if angle["tag"] == "evaluate"
                                and angle.get("field") in fields and angle.get("lens") in (None, claim.lens)]
                    definitions.update(("evaluate", angle["id"]) for angle in evaluate)
                    values = {field: "" for field in fields}
                    if when == "after":
                        values.update(patch="", callers="", migration="", choice="")
                    add("cut", {**base, "when": when, "round": track.round + 1, **values,
                                "evidence": {angle["id"]: "" for angle in evaluate}},
                        [*fields, "evidence"],
                        ["after: difficulty is required; choice is required when policy needs a decision",
                         "artifact trivial/local: supply patch, callers=none, migration=none",
                         "implementation: supply callers and migration; patch is optional",
                         "blank optional keys are omitted; callers: none or changed; migration: none or needed"], context=context)

    if role == "main":
        items.extend({"action": "dispatch", **row} for chunk in protocol.batch_plan(slate) for row in chunk)
        if phase == "cutoff":
            add("cutoff", {})
        if slate.cutoff_valid:
            for row in protocol.compute_cutoff(slate):
                if row.result == "fix-now" and row.claim.fix_check is None:
                    rating = row.claim.state.rating or {}
                    items.append({**_claim(row.claim, {"action": "fix-check"}),
                                  "patch": rating.get("patch"), "rating": rating,
                                  "rule": "the applying caller runs checks and an independent patch review before recording pass"})
                    for outcome in ("pass", "fail"):
                        values = {"claim": row.claim.id, "outcome": outcome, "evidence": ""}
                        if outcome == "pass":
                            values["review_slate"] = ""
                        add("fix-check", values, ["evidence", *(["review_slate"] if outcome == "pass" else [])])

    state = "ready" if actions else "complete" if phase == "done" else "waiting"
    return {"slate": slate.slate_id, "source_seq": len(slate.events), "role": actor, "seat": role,
            "role_host": role_host, "phase": phase, "state": state, "items": items,
            "definitions": [copy.deepcopy(angle) for angle in slate.angles
                            if (angle["tag"], angle["id"]) in definitions],
            "difficulty_basis": slate.config["cutoff"]["difficulty_basis"],
            "caps": slate.config["caps"], "steps": slate.config["steps"],
            "policies": {claim.lens or "default": slate.lens_policy(claim.lens)
                         for claim in slate.claims.values()
                         if role in ("main", "cutter")},
            "patch_limits": slate.config["cutoff"]["cheap"] if role == "cutter" else None,
            "actions": actions}


def event(slate: Slate, value: dict[str, Any], actor: str) -> dict[str, Any]:
    """Build one event while append holds the current slate's write lock."""
    problems = []
    if value.get("slate") != slate.slate_id:
        problems.append(f"action: slate must be {slate.slate_id!r}")
    if value.get("role") != actor:
        problems.append(f"action: role must match --as {actor}")
    kind = value.get("action")
    if kind not in ACTION_KINDS:
        problems.append(f"action: choose from {', '.join(ACTION_KINDS)}")
    for key in sorted(COMPUTED & set(value)):
        problems.append(f"action: `{key}` is computed; omit it")
    source = value.get("source_seq")
    if not isinstance(source, int) or isinstance(source, bool) or source < 1 or source > len(slate.events):
        problems.append("action: source_seq must identify an existing slate snapshot")
    context = value.get("context", {})
    if not isinstance(context, dict):
        problems.append("action: context must be an object")
    else:
        if "phase" in context and context["phase"] != protocol.slate_phase(slate):
            problems.append(f"action: stale phase {context['phase']!r}; refresh work")
        if "round" in context:
            claim_id = context.get("claim")
            claim = slate.claims.get(claim_id) if isinstance(claim_id, str) else None
            when = context.get("when")
            if claim is None or when not in protocol.WHEN or claim.state.cuts[when].round != context["round"]:
                problems.append("action: stale cut round; refresh work")
    if kind not in ACTION_KINDS:
        raise ledger.LedgerError(problems)
    fields = {key: field for key, field in value.items() if key not in META | COMPUTED
              and not (kind == "cut" and key in ("patch", "callers", "migration", "choice") and field == "")}
    built = {"event": kind, "as": actor, **fields}
    if kind == "file":
        built["id"] = model.claim_id(len(slate.claims) + 1)
    if kind in ("reply", "rebut") and isinstance(built.get("evidence"), str):
        built["evidence_sha256"] = ledger.evidence_hash(built["evidence"])
    if kind in ("cutoff", "fix-check") and actor != slate.events[0]["as"]:
        problems.append(f"action: only main {slate.events[0]['as']} may record {kind}")
    if kind == "cutoff":
        built["as"] = model.CONVERGE_AGENT
        built["results"] = protocol.cutoff_results(protocol.compute_cutoff(slate))
    problems.extend(ledger.validate_event(slate, built))
    if problems:
        raise ledger.LedgerError(problems)
    return built
