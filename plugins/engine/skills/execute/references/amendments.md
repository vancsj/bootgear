# Run amendments

Record an explicit user change as a new decision. Preserve the settlement.

```text
<gear> --host <host> engine task session record-decision --mode solo --summary "AMENDMENT <field>: <old value> -> <new value>, per user request"
```

Name the exact field. For structured values, give both complete values in the original shape.

```text
AMENDMENT debate_roster: [main-agent, independent-reviewer] -> [main-agent, independent-reviewer, security-reviewer]
AMENDMENT source_of_truth: {scope: ticket} -> {scope: ticket, correctness: tests plus manual QA}
```

For `state_machine`, save the YAML below the `state show` output's `MACHINE` line to a file. Edit the file.
Run `state amend --machine-file <file> --reason "<why>, per user request"`.
On refusal, correct every listed error and retry.

Reject `session_dir` and `task_folder` amendments. Report the real CLI diagnostic and fail the run. Keep both paths.
Use the next `recall` to apply effective changes.
