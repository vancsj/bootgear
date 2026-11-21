# Document content and status

Use sections or short labels for material content. Omit empty headings.

| Status | Include |
|---|---|
| Facts | Verified statement, evidence, and checked scope. |
| Assumptions | Unverified statement, specific check, and consequence if false. |
| Constraints | Mandatory limit and source. |
| Decisions | Confirmed meaning, scope, or selected approach with the confirmation reference. |
| Open questions | Missing intent, conflicting evidence, or unresolved material choices. |

If an assumption can invalidate requirements or architecture, resolve it before implementation.
Use a check that can detect a false assumption. Retain smaller assumptions with specific checks.
Move verified assumptions to Facts and confirmed choices to Decisions.
Check prose, diagrams, tables, and tasks for hidden assumptions.
Put contract questions in primary Open questions. Keep private hypotheses and author references with the caller.

Check every exclusion against the requested result. Return a blocking exclusion as a concrete scope choice.
Propagate confirmed changes through requirements, design, tasks, tests, diagrams, and drafts.
