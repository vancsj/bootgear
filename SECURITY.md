# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/vancsj/bootgear/security/advisories/new).
Do not open a public issue for a security problem.

Include the affected plugin and version, the host (Claude Code or Codex CLI),
steps to reproduce, and the impact you expect.

## Supported versions

Only the latest version of each plugin on `main` receives fixes.

## Scope

bootgear plugins run hooks and scripts on your machine with your user's
permissions. Reports about a plugin running a command, reading or writing a
file, or sending data that its skill or hook does not state are in scope.
