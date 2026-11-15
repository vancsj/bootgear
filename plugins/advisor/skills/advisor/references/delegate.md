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

Include `discuss` or `delegate`, the question or work, relevant paths, decisions, constraints, and permitted changes.
Name the target artifact and each workflow record the role can write.
Permit memory-ledger lookup and record, including for roles that keep the target artifact read-only.
Select `channel` for these writes. The role verifies and records its own entries under its own identity.
Keep judging roles independent. Exclude author private analysis and another judging role's reasoning.

## Handling the response

- The peer's response is advisory; reconcile against the repo, contracts, and intent.
- Distinguish the peer's findings from verified facts. Claim it did work only when its response shows evidence.
- No commit, push, external contact, production mutation, or irreversible action from a delegated response alone, unless the original scope explicitly and safely authorized it.
