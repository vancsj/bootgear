---
name: spec-review
description: Independently review requirements, design, or a ticket. Use before implementation or ticket delivery.
---

## Inputs and outcomes

Take the request, confirmed amendments, primary artifacts, base commit, and project root.
In Engine, take the session directory and cumulative visit `<n>`.
Read primary Open questions. Verify current behavior with evidence.
Accept an optional raw inventory as `observations_path`.

Return the render path, slate, directory, and results to `execute` in Engine or the standalone user.

| Result | Handback |
|---|---|
| `blocked` | Missing role, evidence, request, coverage, resumable slate, or passing gate. Include the diagnostic and affected IDs. |
| `revise` | Claim IDs and text for author revision. |
| `choices` | Claim IDs and text for caller decisions. |
| `inline` | Claim IDs, text, and eligible patches. These permit `ready`. |
| `unchecked` | Follow-ups with reason `unverified`, without attack. |
| `deferred` | IDs and text for implementation and code review. |
| `follow-up` | Other follow-ups, each with status. |
| `ready` | Revise and choices are empty and the required gate passes. |

With observations, also return `observations_path`, `checks_path`, and independent `checks`.
At visit five, any `revise` or `choices` returns `blocked` with those claims.

Use the current machine in Engine. Send choices to debate then drafting. Send revise to drafting.
Only `ready` permits implementation or ticket delivery.
For ready with inline patches, return through drafting. Use the same slate and required exit gate after application.

## Procedure

### Choose an override and brief roles

In Engine, read settlement through the public session command. Use `spec_review_override` with the latest valid amendment.
Use its bare name or matching stage. Otherwise use this workflow.
Standalone, delegate once to a matching registered project skill. Require the same handback.

Fill this block yourself for each new or continued role, advisor request, and override.

```text
Tests already ran:
- latest test: <recorded command>; result: <one recorded result line>
```

Use the latest recorded command, even when narrow. Exclude exit code and record path. Keep separate commands separate.
Use `none recorded` if absent. Pass these instructions to overrides and require the block in each role brief.
Tell roles to skip covered runs and probe gaps. Allow memory-ledger reads and writes within role limits.

Give fresh roles confirmed intent, primary artifacts, relevant repo evidence, standards, and role scope.
Include raw observations when present. Keep author notes, transcripts, hypotheses, private lists, and other role reasoning out.
Retain the advisor `r2` listener's earlier slate context.
Name host user principles and project principles and standards, when present. Include settlement principles in Engine.
Tell roles to read them before finding, attacking, or cutting.

### Start or resume the slate

Use separate finder, refuter, and cutter roles. Resume an existing slate through public role work.
Each later visit starts a new slate and fresh roles except the retained advisor.

| Run | Slate | Directory |
|---|---|---|
| Engine | `<run-id>-spec-review-<n>` | `<session-dir>/converge` |
| Standalone | `spec-review-<YYYYMMDD-HHMMSS>` | `$HOME/.bootgear/converge` |

Use public `work` with actor and receiving host. Use its definitions, evidence, actions, and handoffs.
Each role submits its own evidence and judgment through `act` or a direct public command.
Refresh after each state change or stale refusal. Use the printed waiting and completion steps.

Supply the project root and lenses.

```text
request-fit,clarity-completeness,architecture-fit,simplicity,proportionality,testability
```

Pass absolute [angles.yaml](references/angles.yaml) and [design-patterns.yaml](references/design-patterns.yaml) paths in one `--angles`.
Pass absolute [cutoff.yaml](references/cutoff.yaml) as `--defaults`. Let the CLI load these files.
Use `--pass <n>` only in Engine from visit 3. Omit `--snapshot` and `--since`.
In Engine, pass the exported settlement with `--settlement`.

```text
<gear> --host <host> engine task session read --section settlement --prose > <converge-dir>/<slate>.settlement.yaml
```

Use only the selected lens sections of [lenses.md](references/lenses.md) when briefing.
When observations are supplied, read [observations.md](references/observations.md) for independent checks and the gate.
Skip other reference sections. Apply architecture checks wherever architecture appears, even in requirements alone.
Check hidden assumptions in prose, diagrams, tables, and tasks. Trace STRIDE when trust, permissions, external input, or sensitive data changes.
Mark a check inapplicable only when the affected mechanism is absent.

Cover each find angle from both files or record inapplicability. For an absent spec-only trigger, use `angle-na` with `trigger absent: <why>`.
Run gap hunt for missed concerns and request fit in both directions.
Keep normal escalation, cuts, attacks, finder replies, narrowing, withdrawal, verdicts, coverage, and gates.

### Write and rate claims

Use these rules for lens and gap-hunt claims.

- Set `loc` to the primary artifact's absolute path and line.
- In `claim`, state expected behavior, dependent party, and visible consequence. In `trigger`, name the action or input.
- In `evidence`, cite the governing requirement or contract and each path step. Name unverified links. Set the checked tier.
- Keep context on replacement. Include any new anchors, trigger details, and unverified links.

Rate the current claim and its updated trigger and evidence. For `cosmetic`, name the outcomes and actions left intact.
Use `wrong-output` for a required implied behavior or false design assumption.
Use `clarity` for simplicity and proportionality unless they cause a wrong result. If so, give the applicable impact and choice.
Use `implementation-level:` only for code details that preserve sound requirement and design contracts.
Keep contract defects in spec review regardless of remedy difficulty, severity, or reach.

Use production remedy difficulty from public status. Cite paths, callers, scope, and migration needs.
Measure artifact patch difficulty separately. Document size cannot determine production remedy difficulty.
For inline correction, submit a real unified diff. Use only CLI-derived `artifact_patch_eligible`.
Use no fix-now or fix-check treatment. The cutoff disables automatic cheap fixes.
Visits 1–2 can report clarity, security, data loss, and wrong output.
Later visits retain security, data loss, and wrong output. Only request fit retains clarity.

### Render, map, and gate

```text
<gear> --host <host> <converge-plugin> converge render <slate> --dir <converge-dir> > <converge-dir>/<slate>.md
```

Read public status. Apply the cutoff, then map in order.

1. Missing role, coverage, evidence, open claim work, or failed gate gives `blocked`.
2. A disputed finding gives `revise` except simplicity or proportionality under rules 4–5.
3. A survived `implementation-level:` trigger gives `deferred` only when the current claim preserves the contract.
4. A simplicity or proportionality finding without choice goes to follow-up.
5. A choice in the cut goes to `choices` even when `revise` also has claims.
6. A survived, trivial, contract-preserving clarity finding with `artifact_patch_eligible: true` goes to `inline`.
7. Other findings go to `revise`.

Send follow-ups with reason `unverified` to `unchecked`. Use `follow-up` for the rest.
At visit five, block on remaining revise or choices. Before ready, run the public Converge gate.
If observations apply, run their public gate too. Use only the selected exit's public check inputs.
Keep the slate and directory in all results.

## Rules

Keep code and artifacts read-only. Main writes only init on the slate. Each other role writes its own events.
Allow assigned records and memory-ledger reads and writes. Preserve other write limits and independence.
Use authoritative intent to decide desired behavior. Use code, tests, and contracts for current behavior.
Apply the settlement's source order for contested facts. Leave choices and disputed intent with the caller.
A sound contract detail can defer even if its remedy spans components or its patch is large.
A passing rerun or empty claim list alone cannot prove coverage. A factual result grants no mutation or delivery permission.

## Fallbacks

Return `blocked` for unavailable roles, public capabilities, or evidence.
Include actual diagnostic, missing mechanism, pending work, and next action. Keep missing request evidence explicit.

## Host mechanics

Read only the current host's section. Use `converge` for `<converge-plugin>`.
Keep `session_dir`. Use `--dir` only for a custom session directory.

### Claude Code

Use `claude` for `<host>` and `$CLAUDE_CODE_SESSION_ID` for `<run-id>`.
Invoke skills through Skill. Take the absolute path from `cli:gear`.
Run `<gear> --host claude engine task <command>` and `<gear> --host claude spec spec-feedback <command>`.
Use `converge:converge` through the declared dependency. If needed, run `/plugin install cli@bootgear`.

### Codex

Use `codex` for `<host>` and `$CODEX_SESSION_ID` for `<run-id>`.
Invoke skills by public name. Take the absolute path from `cli:gear`.
Run `<gear> --host codex engine task <command>` and `<gear> --host codex spec spec-feedback <command>`.
If needed, run `codex plugin add cli@bootgear`.
If a required sibling is missing, return `blocked` with the diagnostic and `cli:setup` for `spec`. Resume after verification.
