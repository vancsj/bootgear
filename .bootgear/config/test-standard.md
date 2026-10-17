# test-standard

severities: [must, should]
cutoff: must

## R001 [must]
You must verify a claimed fix or behavior change. Run the relevant check and read its real output.
Do not state the result from a reading of the code only.

## R002 [must]
You must classify each test failure with the evidence that supports the classification. The evidence is the actual error text or stack trace.
Do not guess the classification from the test name or from a hunch.

## R003 [should]
A script should have at least one runnable example for its own behavior. The behavior can be a CLI flag, an exit code, or a validation rule.
The example should be a worked-through invocation with real output. A written description of the expected behavior is not enough.

## R004 [must]
A bug fix must start with a test that reproduces the bug.
The test must fail before the fix. The test must pass after the fix.

## R005 [must]
You must check a change to how a plugin is installed, loaded, or cached in a fresh host session on each affected host.
You must record the real output.
Such a change can be to the manifest, dependencies, hooks, `bin/` script wrappers, or marketplace entries.
