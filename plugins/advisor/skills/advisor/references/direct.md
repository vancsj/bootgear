# communication=direct

Make one call to the other CLI: Claude Code calls Codex; Codex calls Claude Code.
Use no mailbox or saved conversation. Put all task facts in the prompt. Mark unverified facts as unverified.
Give the peer its role scope. For a review, forbid engine loops, other advisors, and work beyond that role.

## Claude Code calls Codex

Set `dangerouslyDisableSandbox: true` on the Bash call. Run this example from the calling host:

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

Pass model and effort flags only when their variables are set. Otherwise, use Codex's native defaults.
Do not read user config or rules for this call.
Keep streamed output in `LOG`. Read only the final answer from `OUT` after success.
On failure, read the retained diagnostic log. Report only the actual error, then delete that log.
Never print the full stream, prompt, banner, or reasoning.

## Codex calls Claude Code

Run this example with the shell tool:

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

Pass model and effort flags only when their variables are set. Otherwise, keep Claude Code's native defaults.
Use safe mode and disable tools. Keep the current login; do not use `--bare` or switch authentication.
If the CLI is missing or rejects a flag, report its output and stop. Do not change transport silently.

## After either call

Allow two to three minutes for the call. Use a quoted heredoc for a long prompt.
Treat the reply as advisory. Check its claims against source files, command output, or official contracts.
Return one reconciled answer. Do not show banners, streamed reasoning, or the raw exchange.
