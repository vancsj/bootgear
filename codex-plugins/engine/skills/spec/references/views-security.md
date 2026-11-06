# Views and security

Choose views that explain the affected mechanism. Keep small local changes terse.
Use the relevant levels from [C4 guidance](https://c4model.com/diagrams) for changed architecture.
Do not require every C4 level or diagram type.

| Affected mechanism | Explain |
|---|---|
| Architecture | Boundaries, responsibilities, and connections at one consistent level. |
| Stored, copied, derived, or overlaid values | Origin, writer, stored source, copy time, readers, and observable result. |
| Order or lifecycle | Calls, allowed transitions, reversals, later updates, retries, and failure recovery. |
| Persistent relations | Ownership, update and deletion rules, affected callers, and side effects. |

For each affected value, name its exact input, setter, source, capture operation, and live or copy readers.
Keep similarly named fields separate when their writers or effects differ.
Trace dependencies and cache changes where they affect output.
For time-dependent behaviour, distinguish business dates, recorded times, and operation order where relevant.
Check invariants across allowed action sequences, including validation order and application order.

State observable outcomes, unchanged-path checks, and important event-sequence tests.
Inspect fixtures and assertions; show a plausible wrong result that the verification must reject.
State unit, integration, and full-workflow limits separately.

Apply [STRIDE](https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats) for changed trust boundaries, permissions, external inputs, or sensitive data.

| Category | Check |
|---|---|
| Spoofing | Can a caller use another identity? |
| Tampering | Can a caller change data without permission? |
| Repudiation | Can evidence establish who performed a sensitive action? |
| Information disclosure | Can data reach a caller who must not see it? |
| Denial of service | Can callers or dependencies exhaust resources and block valid work? |
| Elevation of privilege | Can a caller obtain permissions beyond its role? |

Trace applicable threats through real entry points and controls.
State the control and an observable verification that fails when the control is wrong.
Give a short reason for each inapplicable category.
Do not add six empty threat essays when no trigger applies.
