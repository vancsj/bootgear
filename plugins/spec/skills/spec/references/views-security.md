# Views and security

Show the affected mechanism. Keep small local changes short.
For changed architecture, select only useful levels from [C4 guidance](https://c4model.com/diagrams).

| Mechanism | Show |
|---|---|
| Architecture | Boundaries, duties, and connections at one consistent level. |
| Stored, copied, derived, or overlaid values | Input, writer, source, capture operation and time, live or copy readers, and output. |
| Order or lifecycle | Calls, allowed transitions, reversals, updates, retries, and recovery. |
| Persistent relations | Ownership, update and deletion rules, affected callers, and side effects. |

Separate fields with different writers or effects. Trace dependencies and cache changes that affect output.
Distinguish business dates, recorded times, and operation order. Compare validation with application order across allowed sequences.

State observable outcomes, unchanged paths, and important event sequences.
Inspect fixtures and assertions. Show a plausible wrong result the check must reject.
State unit, integration, and full-workflow limits separately.

For changed trust boundaries, permissions, external inputs, or sensitive data, apply [STRIDE](https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats).

| Category | Check |
|---|---|
| Spoofing | Can a caller assume another identity? |
| Tampering | Can a caller change data without permission? |
| Repudiation | Can evidence identify who performed a sensitive action? |
| Information disclosure | Can data reach an unauthorized caller? |
| Denial of service | Can callers or dependencies exhaust resources and block work? |
| Elevation of privilege | Can a caller exceed its role's permissions? |

Trace applicable threats through real entry points and controls. Give a check that detects a faulty control.
Give short reasons for inapplicable categories. Omit threat sections when no trigger applies.
