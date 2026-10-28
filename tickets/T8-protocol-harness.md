# T8 — protocol harness: 8Q probe + ladder runner (BUILD)

## Problem
The gateway bake-off protocol needs two runners that do not exist yet:
the 8-question yes/no filter (kills always-yes models fast) and the
4k / two-parallel headroom ladder (tok/s + measured memory).

## Goal
`scripts/run_8q.py` + `scripts/run_ladder.py` implementing
[docs/GATEWAY-CONTRACTS.md](../docs/GATEWAY-CONTRACTS.md) v1.2 exactly,
tested against fixtures. The coordinator runs them on the Mini;
the builder never touches the Mini.

## Non-goals
- No bake-off composition (T9 consumes these scripts via the frozen contract).
- No logprob screen changes (borrowed from mml-stack at run time).
- No question authoring: ship a clearly-marked PLACEHOLDER question set;
  the reviewed set swaps in via `--questions` without rebuilding.
- No pulls, no network beyond stdlib HTTP to `--ollama` / `--status` flags.

## Behavior
Per contracts v1.2. Defaults: `--ollama http://127.0.0.1:11434`,
`--status http://127.0.0.1:8081/status`, per-question timeout 120s,
ladder-step timeout 600s (flags override). `mem_kb` is `mem_free_mb`
× 1024 from `/status` when reachable, else JSON `null` — never
fabricated, never zero-filled.

## Failure modes
| Trigger | Visible result | Test |
|---|---|---|
| Ollama host down | exit 2, stderr reason | test_host_down |
| Question timeout | answer null, run completes, pass=false | test_probe_timeout |
| Ladder step timeout | step ok:false, verdict=false, run continues | test_ladder_timeout |
| Always-yes answers (on mixed-truth set) | pass=false | test_always_yes |
| /status unreachable | mem_kb null + note, run continues | test_status_null |
| /status carries mem_free_mb | mem_kb = value×1024 in output (null must NOT be the only tested path) | test_mem_populated |

Unload verification (`ollama stop` + `ollama ps`) is runbook-level,
owned by the coordinator — not this ticket.

## Tests (named, stdlib only — no pytest on this box)
`tests/test_run_8q.py`, `tests/test_run_ladder.py`,
fixtures under `tests/fixtures/gateway/` (incl. a placeholder
questions file and a mixed-truth fixture). Every behavior above
tested; no test without a regression it would catch.

## Ticket fields
- Door: two-way (new files only, nothing deployed).
- Blast radius: small.
- Acceptance: `python3 tests/test_run_8q.py && python3 tests/test_run_ladder.py` → exit 0 with printed PASS counts.
- May touch: `scripts/run_8q.py`, `scripts/run_ladder.py`, `tests/test_run_8q.py`, `tests/test_run_ladder.py`, `tests/fixtures/gateway/*`.
- Must not: `feedback-server.py`, `Caddyfile`, `health-check.sh`, `.env`, `mockups/`, `tickets/`, anything on the Mini.
- Author: kiro crew A. Reviewer: coordinator (verify-close) + security lens at diff.
- Cost: $0. Disk note: MacBook <5GB free — targeted tests only, no installs.
