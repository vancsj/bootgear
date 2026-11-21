# Spec-review lenses

- **`request-fit`:** compare confirmed intent, requirements, design, and acceptance in both directions.
  Check stale ticket assumptions, stage boundaries, and exclusions that block the result. Block without authoritative request evidence.
  Leave wording alone, design quality, and test implementation to other lenses.
- **`clarity-completeness`:** check behavior, boundaries, failures, and acceptance. Preserve primary Open questions.
  For an implied requirement, cite the request and show how the result fails without it.
  Leave local names open if behavior is fixed. Leave sound design choices to the caller.
- **`architecture-fit`:** check contracts, patterns, relationships, ownership, and callers. Compare minimal, clean, and pragmatic designs when architecture changes.
  Check assumptions in prose, diagrams, tables, and tasks against exact code, contracts, config, and representations.
  Trace writers, storage, capture time, live or copy readers, and output.
  Check transitions, reversals, updates, retries, recovery, dependencies, and caches. Compare validation and application order.
  Check relation updates, deletion, and side effects.
  For changed trust, permissions, external input, or sensitive data, trace STRIDE through controls. Verify them and explain omissions.
  Apply design-pattern angles only with their cost scenario. Use `implementation-level:` only when both contracts hold.
  Leave requirement wording with no behavior effect to other lenses.
- **`simplicity`:** look for simpler designs that meet the same requirement. Check components, branches, fields, and whole-design alternatives.
  Leave request and architecture fit to their lenses.
- **`proportionality`:** check if requirements overcomplicate the request or design overcomplicates requirements. Leave correctness to its lens.
- **`testability`:** check visible results, important boundaries, unchanged paths, and event sequences. Inspect fixtures and assertions.
  Show a plausible wrong result the check must reject. State unit, integration, and full-workflow limits separately.
  Leave required behavior and design to their lenses.
