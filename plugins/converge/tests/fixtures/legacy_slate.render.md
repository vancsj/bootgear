# converge slate `legacy`

mode: full · lenses: correctness, security · claims: 8 · cutoff: current

## Reported

| rank | claim | lens | loc | finding | frequency | severity | confidence | difficulty | refute | cut | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | F005 | correctness | src/a.py:10 | retry duplicates the write | every-call | data-loss | reproduced | local | converged | accepted round 1 | report_if[0] |
| 2 | F001 | correctness | src/a.py:10 | None crashes the parser | common | wrong-behavior | traced | cross-cutting | converged | accepted round 1 | report_if[1] |
| 3 | F008 | security | src/a.py:10 | rate limit resets on deploy | every-call | degraded | traced | local | converged | capped at round 3 | cut-capped |
| 4 | F004 | security | src/a.py:10 | session cookie lacks SameSite | rare | degraded | inferred | local | inconclusive | accepted round 1 | inconclusive |
| 5 | F007 | correctness | src/a.py:10 | cache key ignores locale (r5) | contrived | degraded | inferred | local | unconverged | accepted round 1 | unconverged |
| 6 | F006 | correctness | src/a.py:10 | README example is stale | common | cosmetic | traced | trivial | converged | accepted round 1 | report_if_gap_hunt[0] |

## Choices

- **F001** (reported) — validate at the edge or in the parser

## Inconclusive / unconverged

- **F004** inconclusive — session cookie lacks SameSite — angles: boundary, reachability
- **F007** unconverged — cache key ignores locale (r5) — angles: boundary, carve-out, deliberate, dependents, inherited-bounds, inverse-reading, point-in-time, provenance, reachability, real-referent

## Appendix

<details><summary>1 below the cutoff</summary>

| rank | claim | lens | loc | finding | frequency | severity | confidence | difficulty | refute | cut | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 7 | F002 | correctness | src/a.py:10 | debug log lines leak the token | rare | cosmetic | traced | trivial | converged | held after rebut, round 2 | no rule matched |

</details>

## Killed / retracted

- **F003** killed by r1 (positive-control, round 1) — nobody calls legacy() — reason: read a.py:10

## Coverage

- **correctness** — ran: changed-contract · n/a: failure-path (no I/O in the diff) · missing: none
- **security** — ran: none · n/a: changed-contract (no contract change); failure-path (no I/O in the diff) · missing: none
