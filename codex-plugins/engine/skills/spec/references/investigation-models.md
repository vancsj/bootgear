# Investigation and models

Before drafting, record conclusions in task-local `investigation.md`.
Include current behaviour, exact evidence, checked paths and boundaries, and unresolved facts.
Record conclusions rather than a command diary.
Trace similarly named fields separately until their writers, readers, and meanings establish a shared contract.
Read the implementation path, an analogous test, and the authoritative external contract before an actionable conclusion.
Verify installed versions, configuration, regions, forms, and exact representations when they affect the claim.

Form both models before choosing implementation details:

| Model | State |
|---|---|
| Mental model | How the user expects the feature to work, including scope and limits. |
| Conceptual model | Main concepts, responsibilities, relationships, and boundaries. |

When either model is uncertain or materially changed, show both models and identify the uncertainty or change.
Return the required checkpoint to the caller before affected drafting.
Include checkpoint kind `models`, current models, affected scope, unresolved question, and existing confirmation references.
Reuse exact confirmation only when it covers the current payload and scope.
User clarification requires another model check.
Clear, unchanged models proceed without another question.
Do not use a model checkpoint for routine design choices or action permission.
