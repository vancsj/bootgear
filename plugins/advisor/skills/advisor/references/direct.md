# Direct communication

Call the other CLI once. Use a fresh working directory, with no mailbox or saved conversation.
Put every task fact in the prompt. Mark uncertainty. Give the peer its role and scope.
For review, forbid Engine loops, other advisors, and work beyond the role.
Select channel for workflow-record or memory-ledger writes. Return unexpected write needs before attempting them.
Keep the chosen mode and honor sandbox limits. Use only the current host's example.

## Claude Code calls Codex

```bash
D=$(mktemp -d)
OUT=$(mktemp)
LOG=$(mktemp)
trap 'rm -rf "$D" "$OUT" "$LOG"' EXIT
ARGS=(--ephemeral -s read-only --skip-git-repo-check --ignore-user-config --ignore-rules -C "$D" -o "$OUT")
[ -n "${BOOTGEAR_ADVISOR_CODEX_MODEL:-}" ] && ARGS+=(-m "$BOOTGEAR_ADVISOR_CODEX_MODEL")
[ -n "${BOOTGEAR_ADVISOR_CODEX_EFFORT:-}" ] && ARGS+=(-c "model_reasoning_effort=\"$BOOTGEAR_ADVISOR_CODEX_EFFORT\"")
codex exec "${ARGS[@]}" "<prompt>" < /dev/null > "$LOG" 2>&1
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  printf 'Codex failed (exit %s). Read diagnostic log: %s\n' "$STATUS" "$LOG" >&2
  LOG=
  exit "$STATUS"
fi
cat "$OUT"
```

Use native model and effort defaults when the variables are unset.
Leave user config and rules unread. Keep the artifact read-only.
Read only `OUT` on success. On failure, read the retained log, report the actual error, and delete it.

## Codex calls Claude Code

```bash
D=$(mktemp -d)
OUT=$(mktemp)
ERR=$(mktemp)
trap 'rm -rf "$D" "$OUT" "$ERR"' EXIT
ARGS=(-p --safe-mode --tools "" --no-session-persistence --output-format text)
[ -n "${BOOTGEAR_ADVISOR_CLAUDE_MODEL:-}" ] && ARGS+=(--model "$BOOTGEAR_ADVISOR_CLAUDE_MODEL")
[ -n "${BOOTGEAR_ADVISOR_CLAUDE_EFFORT:-}" ] && ARGS+=(--effort "$BOOTGEAR_ADVISOR_CLAUDE_EFFORT")
(
  cd "$D" || exit
  claude "${ARGS[@]}" "<prompt>" < /dev/null
) > "$OUT" 2> "$ERR"
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  cat "$OUT" "$ERR" >&2
  exit "$STATUS"
fi
cat "$OUT"
```

Use native model and effort defaults when the variables are unset.
Keep safe mode, disabled tools, and the current login. Do not use `--bare` or switch authentication.
Report a missing CLI or rejected flag and stop.

## After the call

Allow two to three minutes. Use a quoted heredoc for a long prompt.
Verify checkable claims against sources, output, or official contracts.
Return one reconciled answer. Keep banners, streams, prompts, and reasoning private.
