# Spec-review lenses

- `request-fit`: requirements and design match the original request and acceptance criteria. Needs the request or ticket text; without one the review is `blocked`.
Out of scope: requirement clarity, design quality, tests.
- `clarity-completeness`: the request is clear enough to settle and no required behavior, boundary, or acceptance condition is missing. Includes angle `implied-requirement`: the cutter rates one the stated outcome needs `wrong-output` and any other `clarity`.
Out of scope: whether the artifact matches the request; design choices.
- `architecture-fit`: the design follows established architecture; if it redesigns architecture, minimal, clean, and pragmatic choices plus best practices are explicit. Includes angles `design-assumption` (the cutter rates a false assumption `wrong-output`) and `implementation-level` (typed `deferred`). A claim filed under a `design-patterns.yaml` angle states its cost scenario (the row's `cost`); without one, do not file it.
Out of scope: requirement wording.
- `simplicity`: a simpler clean implementation was considered and the chosen design does not add needless machinery. Includes angle `whole-design-alternative`.
Out of scope: fit to the request or to established architecture.
- `proportionality`: the requirements do not overcomplicate the request and the design does not overcomplicate the requirements.
Out of scope: correctness of the design.
- `testability`: tasks and acceptance criteria make the intended behavior and important boundaries verifiable.
Out of scope: whether the requirement or design is right.
