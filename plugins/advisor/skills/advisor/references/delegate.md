# task=delegate

Hand off investigation (`discuss`) or scoped work (`delegate`) to the peer.
Use channel mode when it must read files, run commands, or exchange several messages.

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

- The peer's response is advisory; reconcile against the repo, contracts, and intent.
- Distinguish the peer's findings from verified facts. Claim it did work only when its response shows evidence.
- No commit, push, external contact, production mutation, or irreversible action from a delegated response alone, unless the original scope explicitly and safely authorized it.
