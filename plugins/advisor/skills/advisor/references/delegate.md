# task=delegate

Hand off investigation (`discuss`) or scoped work (`delegate`) that Codex does on its own — reading files, running commands — over one or more rounds.

## Request body

```
TYPE: discuss
USER_REQUEST:
...
CONTEXT:
...
SCOPE:
...
```

Include: `discuss` or `delegate`, the actual question/work, relevant paths/symbols/decisions/constraints, requested response format, allowed scope (read-only vs. changes permitted, and exactly what's authorized).

## Handling the response

- Codex's response is advisory; reconcile against the repo, contracts, and intent.
- Distinguish Codex's findings from independently verified facts — claim it did work only when the response shows evidence.
- No commit, push, external contact, production mutation, or irreversible action from a delegated response alone, unless the original scope explicitly and safely authorized it.
