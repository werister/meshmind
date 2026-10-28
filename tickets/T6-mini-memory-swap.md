# T6 — Mini memory + swap telemetry (BUILD then coordinator deploy)

## Problem
Headroom verdicts on 8 GB are inferred from tok/s because free RAM and
swap are not surfaced. The gateway headroom ladder needs measured numbers.

## Goal
Sample memory + swap on the Mini and expose them in /status. Builder
writes the code (tested against fixtures); the coordinator deploys
(sidecar restart with backup + revert path) BEFORE any ladder runs.

## Non-goals
- No alerting thresholds (lines only; the coordinator reads them this round).
- No dashboard changes (fields ride the existing /status; dashboard later).
- Builder touches nothing on the Mini; deploy is coordinator-only.

## Behavior
- `health-check.sh`: sample `vm_stat` (pages free/active/inactive/
  wired/compressed + page size) and `sysctl vm.swapusage`
  (total/used/free) at the existing 5-min cadence; log swap deltas
  around model loads; emit an alert line when swap_used grows
  during a load.
- `feedback-server.py`: expose `mem_free_mb`, `mem_compressed_mb`,
  `swap_used_mb` in /status next to totals. ADDITIVE fields only —
  no renames, no schema breaks.
- No new deps; negligible CPU.

## Failure modes
| Trigger | Visible result | Test |
|---|---|---|
| vm_stat parse drift (new macOS line) | fields null + stderr note, server keeps running | test_parse_drift (mutated fixture) |
| /status consumer expects old schema | additive = old readers unaffected | test_status_additive (old keys intact) |
| Deploy restart fails | coordinator reverts to backup (runbook) | live-verify, not unit-testable |

## Tests (named, stdlib only)
`tests/test_status_mem.py` (+ `tests/fixtures/status-mem.json`):
additive-keys, types/sanity (free ≤ total), parse-drift.
Plus `bash -n health-check.sh`.

## Ticket fields
- Door: build two-way; deploy is a restart (two-way with backup).
- Blast radius: small at build / medium at deploy (sidecar restart).
- Acceptance: `bash -n health-check.sh && python3 tests/test_status_mem.py` → exit 0, AND post-deploy /status carries the three fields with sane values.
- May touch: `feedback-server.py` (additive only), `health-check.sh` (additive only), `tests/test_status_mem.py`, `tests/fixtures/status-mem.json`.
- Must not: `Caddyfile`, `.env`, `mockups/`, `tickets/`, `scripts/`, anything on the Mini.
- Author: kiro crew C. Reviewer: coordinator (verify-close) + security lens at diff (deploy touch).
- Cost: $0. Disk note: MacBook <5GB free — targeted tests only, no installs.
