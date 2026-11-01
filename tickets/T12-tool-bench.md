# T12 — 6-point tool-test harness (BUILD; coordinator runs live)

## Problem
Nobody has local evidence for tool-calling: functiongemma untested,
Granite 4.2's one smoke untested at rubric depth. Promotion needs exact
tool/argument success + abstention behavior, not vibes.

## Goal
`scripts/tool_bench.py`: scripted turns against a FIXED 4-tool catalog
(get_weather, calc, file_read, send_message — fake backends with scripted
answers) scoring Perplexity's 6 points: (1) correct tool selection,
(2) exact argument values/types, (3) abstention when args absent,
(4) correct no-tool decisions, (5) recovery after tool errors,
(6) correct use of tool results next turn. Runner drives turns via the
proxy (X-Agent: tool_bench), feeds scripted tool outputs back, scores
each point pass/fail. Output `findings.json` + console table.

Suite: 12 scripted scenarios (2 per point), fixed catalog, deterministic
fake backends. First live targets (coordinator): granite4.2:3b-q4_K_M
vs functiongemma:latest.

## Non-goals
- No live runs by the builder (canned-turn fixtures; coordinator runs).
- No real tool execution (fake backends only — no weather API, no FS).
- No multi-step agent loops beyond turn-2 result handling.

## Behavior
JSON to stdout, reasons to stderr, exit 0 = ran, exit 2 = infra.
`--models`, `--ollama`, `--scenarios DIR`. Per-scenario verdict +
per-point aggregates. A model emitting invalid JSON fails the scenario
(marked). Template/endpoint failures recorded SEPARATELY from reasoning
failures (distinct notes: `endpoint_error` vs `wrong_tool` etc.).

## Failure modes
| Trigger | Visible result | Test |
|---|---|---|
| Invalid tool-call JSON | scenario fail, note `bad_json` | test_bad_json |
| Host down mid-suite | exit 2, partial results kept to file | test_host_down |
| Scenario dir malformed | exit 2 naming the file | test_bad_scenarios |
| Tool error recovery | scored turn-2, not fatal | test_error_recovery (fixture) |

## Tests (named, stdlib only)
`tests/test_tool_bench.py` (+ fixtures: 2 sample scenarios with canned
turns covering pass/fail/abstain). No live calls.

## Ticket fields
- Door: two-way (new files only). Blast radius: small.
- Acceptance: `python3 tests/test_tool_bench.py` → exit 0 with PASS
  counts, AND all 12 scenario files validate (schema check in-suite).
- May touch: `scripts/tool_bench.py`, `tests/test_tool_bench.py`,
  `tests/fixtures/toolbench/*`.
- Must not: everything else, anything on the Mini.
- Author: kiro crew H (after T11). Reviewer: coordinator.
- Cost: $0. Disk note: MacBook tight — targeted tests, no installs.

## Live findings (coordinator, 2026-10-31)

- artemis-0.8B: 4/12; qwen3:4b-instruct-2507: 4/12 (identical shape); phi4-mini:
  5/12 (twice). Endpoint fails 0 throughout — all models fairly judged.
- Root cause (proven by raw-output capture): both Qwen models emit CORRECT tool
  JSON (`{"tool": "get_weather", "args": {...}}`) but WITHOUT the ``` fence the
  parser requires → scored `wrong_tool` on all 8 tool-call turns each. The
  failure is the harness's fence-only rule, not model tool ability.
- Next: harness fix (accept bare-JSON tool objects and/or grammar-constrained
  `format:json` decoding), then re-bench all three for true scores. Model
  verdicts on the tools lane are suspended until the fixed re-run.
- Re-bench with fixed parser (2026-10-31): **three-way tie at 7/12** — 2507
  (p1 2/2, p2 0/2, p3 0/2, p4 2/2, p5 1/2, p6 2/2), artemis (2/2, 0/2, 1/2,
  2/2, 0/2, 2/2), phi4-mini (2/2, 0/2, 0/2, 1/2, 2/2, 2/2); endpoint fails 0.
  Fence artifact confirmed gone (p1 0→2/2 on both Qwens). Nobody separates:
  all fail exact-args (p2 0/2 across the board) and phi4-mini varies ±1-2 run
  to run, so 7/12s are tied within noise. Efficiency nod to artemis (0.85 GB,
  27.7 tok/s at equal score). Lead next item: grammar-constrained `format:json`
  decoding aimed at p2 args precision.
