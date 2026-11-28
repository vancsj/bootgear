# Advisor

Advisor connects Claude Code and Codex CLI for second opinions, rewrites, and scoped review.
Either host can request advice or listen for work.

Direct advice runs the peer CLI once with a full prompt.
Persistent advice sends assignments through the shared coordination store.
The requesting host reserves a seat and starts the invited advisor when work is ready.

See the [Advisor skill](skills/advisor/SKILL.md) for host instructions and handbacks.
