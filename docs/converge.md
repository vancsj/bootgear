# Converge

Converge verifies claims through independent finding, refutation, and evaluation.
Project rules, lenses, and angles select the required coverage and the reporting cutoff.

## Shared workflow

The coordination store owns seat bindings, assignments, messages, coverage, and completion.
The store points to one active slate. Each slate keeps its claim evidence and status separately.
A session can finish a slate and open another. Unread results stay in the store.

Native subagents share their host ID and carry their own participant IDs.
An advisor joins a seat through a link from its shared host ID.
A seat keeps its requests and results when its participant changes.
The Engine session ledger owns the settlement and run progress.

## Work and evidence

A request can provide work. A poll can also admit the next eligible batch from Converge.
The planner reads the current workflow state and claim slate. It uses the configured role and coverage rules.
The store admits each batch once and records its executor and result receiver.
Converge validates claim actions under the same lock as seat authorization.
An assignment can complete with zero claims. A blocked report leaves its assignment open.

The cutoff applies after required claim work and coverage.
Historical reporting uses the recorded slate. The active slate resolves from the current store.
