# Advisor

Advisor supports one-shot prompts and persistent advice between Claude Code and Codex CLI.
Persistent advice uses the coordination store for requests, open assignments, and results.
One host requests work. The other host joins an advisor seat and polls it.

The requester can reserve a seat before the advisor starts.
The requester starts an advisor when work is ready and supplies its seat invitation.
The same store can accept standalone advice while a Converge slate is active.
