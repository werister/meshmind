# T6 — Mini memory + swap telemetry (monitor)

Owner: coordinator. Effort: ~30 lines. Risk: negligible (read-only telemetry).

Why: headroom verdicts on 8 GB are inferred from tok/s because free RAM and
swap are not surfaced. The gateway headroom ladder needs measured numbers.

Scope:
- Sample `vm_stat` (pages free/active/inactive/wired/compressed + page size)
  and `sysctl vm.swapusage` (total/used/free) in health-check.sh (5-min cadence).
- Expose mem_free_mb, mem_compressed_mb, swap_used_mb in /status next to totals.
- Log before/after swap deltas around model loads in health.log.
- Alert line when swap_used grows during a load (the true OOM/thrash signal).

Acceptance: /status carries the three fields, sampled ≥ every 5 min; a model
load shows a swap delta; no new deps; negligible CPU.
