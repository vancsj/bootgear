# Source selections

Build the candidate set from supplied project context and the caller inventory. Never scan installed skills.
Read the optional project configuration through public `settings`.
The project can supply `.bootgear/config/self-review.json`:

```json
{"candidates": [{"name": "example-review"}]}
```

The caller supplies `candidates`, including an explicit empty list when appropriate.
Use entries with `name` and `origin`. Valid origins are `user-request`, `host-registration`, `caller-judgement` and `project-config`.
The helper unions candidates by public skill name and preserves project-config origins.
An empty caller inventory does not select `neither` for named project candidates.

Supply one selection per candidate:

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

Valid confirmation kinds are `user-message` and `user-confirmed-ledger-entry`. Each needs a nonempty `ref`.
Deputy advice does not confirm a selection. Check the actual confirmed reference and current scope.
Preserve the user's free-text scope, including selected phases or orchestration.
Do not reduce it to a stage bucket. Explain present artifact coverage explicitly.

| Mode | Action |
|---|---|
| `invoke` | Invoke the source skill and follow its workflow, selected scope and public handback. |
| `absorb` | Read and apply the selected instructions without invoking the source skill. |
| `neither` | Do not invoke or absorb that source skill. |

Supply applicable confirmed selections explicitly for each checkpoint and reconfiguration. Never copy modes automatically.
Ask the caller for missing selections before source-dependent work. Return every missing name together.
A changed scope with pending confirmation cannot retain an old mode silently.
Validate references and semantic coverage yourself. The helper checks structure and nonempty fields only.
