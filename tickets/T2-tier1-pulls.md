# T2 — Tier-1 model pulls

**Assignee:** coordinator (needs Mini SSH). **Needs:** docs/MODEL-FIT.md.

## Goal

Pull the 8 Tier-1 models onto the Mini without disturbing the lab.

## Scope

Sequential pulls, off-hours, one at a time, verifying each with a
one-token probe + unload before the next:
smollm2:1.7b, qwen2.5-coder:1.5b, gemma3:270m, LFM2.5-1.2B,
LFM2.5-350M, Qwen3-1.7B, MiniCPM5-1B, qwen3.5:0.8b, bge-m3.
(9 pulls; ~8 GB. Skip on any disk/RAM alarm.)

## Pass/fail

- Each pull probed OK at 4k (or its documented envelope) then unloaded.
- Dashboard `/status` shows the new models; health.log stays OK.
- Mini disk stays above 15 GB free; abort list recorded if cut short.

## Guardrails

Never pull 8B/14B; never run pulls in parallel; stop on thermal/load alarms.
