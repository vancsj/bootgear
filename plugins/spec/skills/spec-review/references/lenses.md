# Spec-review lenses

- `request-fit`: compare current confirmed intent, requirements, design, and acceptance criteria in both directions.
  Check stale ticket assumptions, stage boundaries, and exclusions that prevent the requested result.
  Require authoritative request evidence; return `blocked` without it.
Out of scope: wording alone, design quality, and test implementation.
- `clarity-completeness`: check required behaviour, boundaries, failure cases, and acceptance conditions.
  For implied requirements, identify the request sentence and show how the outcome fails without the requirement.
  Preserve primary Open questions. Leave local naming open when behaviour is fixed.
Out of scope: choosing among sound designs.
- `architecture-fit`: check contracts, established patterns, relationships, ownership, and affected callers.
  Check minimal, clean, and pragmatic alternatives when architecture changes.
  Search prose, diagrams, tables, and tasks for hidden assumptions.
  Verify load-bearing assumptions against exact code, contracts, configuration, and representations.
  Trace values through writers, storage, capture time, live/copy readers, and observable outputs.
  Check invariants across allowed transitions, reversals, later updates, retries, recovery, dependencies, and caches.
  Compare validation order with application order.
  Check update/deletion rules and side effects for changed relations.
  For changed trust boundaries, permissions, external inputs, or sensitive data, apply STRIDE through real controls.
  Verify applicable controls; require short reasons for inapplicable STRIDE categories.
  Use design-pattern angles only with their stated cost scenario.
  File `implementation-level:` only for details that preserve sound requirement and design contracts.
Out of scope: requirement wording without a behavioural effect.
- `simplicity`: check whether a simpler clean implementation meets the same requirement.
  Check unnecessary components, branches, fields, and whole-design alternatives.
Out of scope: request fit and established architecture fit.
- `proportionality`: check whether requirements overcomplicate the request or design overcomplicates the requirements.
Out of scope: factual correctness of the design.
- `testability`: check observable outcomes, important boundaries, unchanged paths, and event sequences.
  Inspect fixtures and assertions. Show a plausible wrong result that the verification must reject.
  State unit, integration, and full-workflow limits separately.
Out of scope: choosing the required behaviour or design.
