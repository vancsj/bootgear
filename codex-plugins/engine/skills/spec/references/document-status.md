# Document status

Use these separate sections in both `requirements.md` and `design.md`.
Write `None` when a section is empty.

| Section | Required content |
|---|---|
| Facts | Verified statements with evidence references and checked scope. |
| Assumptions | Unverified statements, a concrete verification step, and the consequence if false. |
| Constraints | Mandatory limits with their source. |
| Decisions | Confirmed meanings, scope choices, or selected approaches with their confirmation reference. |
| Open questions | Missing intent, conflicting signals, unresolved evidence, and material design choices. |

Resolve an assumption before implementation if its failure can invalidate requirements or architecture.
Use a check that detects the false condition, rather than only a successful nearby command.
Promote verified assumptions into Facts with evidence.
Promote confirmed choices into Decisions.
Keep smaller assumptions visible with specific verification steps.
Search diagrams, tables, tasks, and prose for hidden assumptions outside the Assumptions section.
Keep contract questions in primary Open questions for independent review.
Keep private author hypotheses and unresolved references with the caller.

Check each exclusion against the requested result.
Return an exclusion that blocks that result as a concrete caller scope decision.
Apply confirmed changes across requirements, design, tasks, tests, diagrams, and supporting drafts.
