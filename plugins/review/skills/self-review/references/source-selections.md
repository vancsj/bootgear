# Source selections

Use project context and caller inventory. Never scan installed skills.
Run public `settings` for project config at `.bootgear/config/self-review.json`.

```json
{"candidates": [{"name": "example-review"}]}
```

The caller supplies `candidates`, including an empty list when appropriate. Each has `name` and `origin`.
Allowed origins are `user-request`, `host-registration`, `caller-judgement`, and `project-config`.
The helper combines candidates by public name and keeps project origins. An empty caller list does not select `neither`.

Give each candidate one selection.

```json
{
  "candidates": [{"name": "example-review", "origin": "user-request"}],
  "selections": [{
    "name": "example-review",
    "mode": "absorb",
    "scope": "Author checks, including selected phases and orchestration",
    "coverage": "These instructions cover the present artifact and the selected author workflow.",
    "confirmation": {"kind": "user-message", "ref": "conversation:choice"}
  }]
}
```

Use `user-message` or `user-confirmed-ledger-entry` with a nonempty `ref`.
Verify the user confirmation and current scope. Deputy advice supplies no confirmation.
Preserve free-text scope, phases, and orchestration. A stage label is insufficient. State how the source covers this artifact.

| Mode | Action |
|---|---|
| `invoke` | Invoke the skill. Follow its workflow, scope, and public handback. |
| `absorb` | Read and apply the selected instructions without invoking the skill. |
| `neither` | Skip the skill. |

Resupply confirmed selections at each checkpoint and configuration. Never copy a mode automatically.
Before source-dependent work, return all missing names to the caller. Stop on unconfirmed scope changes.
Verify reference meaning and coverage. The helper checks structure and nonempty fields only.
