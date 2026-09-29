# communication=direct

One `codex exec` call. No persistence, no mailbox. Codex sees only the prompt — it cannot open a file, run a command, or fetch anything. Put every fact it needs directly in the prompt; mark anything unverified as unverified.

## Invocation

Set `dangerouslyDisableSandbox: true` on the Bash call. Append `< /dev/null`. Run from an empty scratch directory with `-C`.

```bash
D=$(mktemp -d)
OUT=$(mktemp)
trap 'rm -rf "$D" "$OUT"' EXIT
ARGS=(-s read-only --skip-git-repo-check --ignore-user-config --ignore-rules -C "$D" -o "$OUT")
[ -n "${BOOTGEAR_ADVISOR_CODEX_MODEL:-}" ] && ARGS+=(-m "$BOOTGEAR_ADVISOR_CODEX_MODEL")
[ -n "${BOOTGEAR_ADVISOR_CODEX_EFFORT:-}" ] && ARGS+=(-c "model_reasoning_effort=\"$BOOTGEAR_ADVISOR_CODEX_EFFORT\"")
codex exec "${ARGS[@]}" "<prompt>" < /dev/null > /dev/null 2>&1
cat "$OUT"
```

`--ignore-user-config --ignore-rules` skip `~/.codex/config.toml` and its plugins, hooks, and MCP servers, so no hooks fire on the call. Because the config is skipped, `BOOTGEAR_ADVISOR_CODEX_MODEL` and `BOOTGEAR_ADVISOR_CODEX_EFFORT` are how the user chooses the model and reasoning effort. Each flag is passed only when its variable is set; when unset, the flag is omitted and Codex uses its own default.

Timeout 2–3 minutes; typical runs take 30–60 seconds. `-o` writes the final message to a file; stdout carries streamed reasoning banner/tokens — always redirect it to `/dev/null` (as above) so only the final-answer file ever reaches the transcript. Never drop the redirect to "watch progress" — that's what floods context.

Use a quoted heredoc for a long prompt instead of a shell argument.

## After the call

Treat Codex's output as unverified. Check anything checkable (file, command, contract) before reporting or acting on it. Separate Codex's claims from independently verified facts.
