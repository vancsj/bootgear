# test-standard

severities: [must, should]
cutoff: must

## R001 [must]
A claimed fix or behavior change is verified by actually running the
relevant check and reading its real output — never asserted from reading
the code alone. This mirrors `test/SKILL.md`'s own "Running tests" step:
capture the actual output, never assume a result without seeing it.

## R002 [must]
A test failure is classified with the evidence that supports the
classification (the actual error text or stack trace), never guessed
from the test's name or a hunch — see `test/SKILL.md`'s "Reading and
triaging reports".

## R003 [should]
A script's own behavior (a CLI flag, an exit code, a validation rule) is
covered by at least one runnable example that exercises it — a
worked-through invocation with real output, not only a written
description of what it's supposed to do.

## R004 [must]
A bug fix starts with a test that reproduces the bug and fails before the
fix, and passes after it.

## R005 [must]
A change to how a plugin is installed, loaded or cached (manifest,
dependencies, hooks, bin/scripts wrappers, marketplace entries) is checked
in a fresh host session on each affected host, with its real output
recorded.
