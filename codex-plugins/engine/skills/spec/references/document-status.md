# Document content and status

Keep primary specs focused on behaviour, material choices and acceptance checks.
Select relevant arc42 sections. Use architecture or runtime views only when they explain a material change.
Keep requirements clear about the goal, boundaries, behaviour and acceptance checks.
Keep design clear about material choices, consequences and useful structure or runtime views.
Derive ordered tasks from primary source statements. Reference those statements instead of repeating their detail.
State each contract once. Keep run controls in the settlement.
Remove avoidable descriptive counts. State the rule or cite its source instead.
Preserve behaviour-defining numbers, identifiers and useful citations.

Keep material status information clear in requirements and design.
Use separate sections or concise labels for the following content. Omit empty headings.

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
Search diagrams, tables, tasks and prose for assumptions without a clear status.
Keep contract questions in primary Open questions for independent review.
Keep private author hypotheses and unresolved references with the caller.

Check each exclusion against the requested result.
Return an exclusion that blocks that result as a concrete caller scope decision.
Apply confirmed changes across requirements, design, tasks, tests, diagrams, and supporting drafts.
