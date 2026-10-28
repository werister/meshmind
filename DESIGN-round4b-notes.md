# Dashboard round 4b: wired for real

Round 1 (the mockup) merged as `bfe92f3`. This round makes it live: the sidecar now keeps
metered rollups, `/status` exposes them, and `/dashboard` renders the round-4b design from
live data. Nothing is committed; the coordinator reviews, merges and deploys.

## What changed

### 1. Metering rollups (`feedback-server.py`)

- New state file `$METER_DIR/metering-aggregates.json`, bumped once per finalized call
  inside `_record_call` under `METER_LOCK`. It uses the same pattern as `proxy-token-total`:
  read, bump, then an atomic write (temp file + fsync + `os.replace`). It is never
  recomputed from `calls.log`, so rotation cannot move it backward.
- Keeps: per-model and per-agent `{calls, prompt_tokens, eval_tokens, failed, no_usage}`,
  14 daily columns (same counters plus `by_model` eval tokens; days older than 14 are pruned
  on every bump), and `failures {total, by_status}`.
- Rules:
  - Nulls never enter sums. A `/v1` stream without usage counts as a call and as `no_usage`.
  - A failure is `ok: false` and not `partial`: a client hanging up is not a backend failure.
  - X-Agent and model are caller-controlled, so each table caps at 64 distinct keys. Overflow
    goes to `(other)`, which keeps the file bounded.
  - Fail-open: a rollup error is swallowed and the ring append and totals still happen. A
    corrupt state file restarts the rollup instead of crashing.

### 2. `/status`

One new top-level key, `metering_breakdown`. Every existing block (`ts`, `ollama`, `health`,
`tokens`, `metering`, `feedback`, `calls`, `eval`, `models`, `activity`, …) is unchanged; a
test checks the `metering` keys and that the fixtures differ only by the new key.

```json
"metering_breakdown": {
  "since": "2026-10-21T08:12:40+00:00",           // first call the rollups saw
  "per_model": [{"model", "calls", "prompt_tokens", "eval_tokens", "failed", "no_usage"}],  // eval desc
  "per_agent": [{"agent", ...same counters}],       // agent is X-Agent: self-declared
  "daily": [{"date", ...same counters, "by_model": {"<model>": eval_tokens}}],  // 14, oldest first, zero-filled
  "failures": {"total": 2, "by_status": {"502": 1, "503": 1}}
}
```

The rollups start counting at deploy. Until they have seen all traffic, their sums are
smaller than the lifetime `metering` totals, and the dashboard says so: "Counted since …:
X of Y generated tokens. Earlier traffic is in the totals only." The page never backfills
from `calls.log` and never presents a partial sum as the lifetime figure.

### 3. One template, two callers

- `render_dashboard(st, mockup=False, …)` in the server holds the whole round-4b template.
  `round4b.css` is embedded as `CSS`, and a test checks it is identical to the file. The
  logos are inlined, so the deploy is still one file to paste.
- `build_dashboard(st)` is the live page: 30 s refresh, a hidden `<h1>`, no mockup notice.
- `mockups/build-mockup.py` is now a thin wrapper that renders the same template with
  `mockup=True` from `status-metered.json`. Regression bar: it rebuilds
  `mockups/dashboard-round4b.html` byte-identical. This is tested, and `--check` exits 1 on
  drift.

### 4. Data instead of literals

| Was hardcoded | Now |
|---|---|
| Sample splits pinned to 23,110 | `SAMPLE_*` shares scaled onto the live `eval_tokens_total` with largest-remainder; sums are exact for any total (tested 0 to 987,654) |
| "1 failed", "(502)" | rollup `failures` when present; otherwise failed rows in the ring (a lower bound, only for snapshots without rollups) |
| "4 streams without usage" | `metering.unmetered_stream_calls`, or rollup `no_usage` in the flow panel |
| Snapshot time, "probe 42 s ago" | `ts` and `health.at` |
| "13 installed · 2 too big" | `ollama.installed`; too big = over 8 GB or on the AGENTS.md do-not-run list |
| Speed, streak, eval date, "5 of 128", axis ticks, date labels | from the matching `/status` fields; y-axes pick a round step from the data |

Sample labeling stays honest:
- **Sample** appears only when `/status` has totals but no `metering_breakdown`, with a line
  saying so.
- With rollups, both panels say **Measured**.
- An empty panel carries no provenance tag at all.

## Before and after

- **Before (round 3, live):** a single long column of text cards, a unicode sparkline, and a
  colour-only heatmap. Per-model numbers were self-reported. The headline was `grand_total`,
  which mixed probe tokens with agent-reported ones.
- **Mockup (round 4b):** diagram panels with provider logos, the cost-avoided range, and one
  type scale. But it was static and its splits were hardcoded.
- **After:**
  - The same page, driven by live measured rollups: tokens per model per day, the agent →
    proxy → model flow, and failures by status.
  - It degrades in words: "proxy metering not reporting", "Nothing loaded", "Degraded",
    empty-state sentences.
  - All caller-controlled strings are escaped.

## Decisions to review

- **Per-day sample rows keep the mockup's algorithm** (round, then the residual goes on the
  last active day), not largest-remainder. Largest-remainder shifts 1 to 3 tokens between days
  and breaks the byte-identical bar. Sums are still exact. If a row ever goes negative, the
  code falls back to largest-remainder.
- **Mockup-only inputs.** `status-metered.json` has 3 models, so the builder takes the
  oversize model rows and the too-big count from `status-live-2026-10-27.json`. The live page
  uses its own `models`.
- **Fixture edit.** `status-metered.json` call rows gained `status` (200/502), which live
  ring rows already carry. The renderer no longer invents a 502.
- **Memory list** shows loaded models plus the 3 largest that fit, then everything over 8 GB.

## Verified (in this worktree, no network)

- `python3 tests/test_dashboard_render.py`: 147 checks pass, including the byte-identical
  mockup and the CSS sync.
- `python3 tests/test_metering_aggregates.py`: 6 pass (sums, nulls, partial vs failure,
  14-day prune, 64-key cap, rotation, atomic write, corrupt-file fail-open, `/status` blocks
  unchanged).
- `python3 tests/test_metering_proxy.py` over loopback only: 10 pass, 5 runs in a row,
  including the new `/status` rollup check. Skipped: `test_installed_smallest_ollama_model_probe`,
  which needs a real local Ollama.
- **One flake found and fixed in the harness.** The rotation test failed once (7 ≠ 9). The
  meter records each call after relaying the response (fail-open, by design), and the tests
  read `/status` straight after the response. The rollup roughly doubles the recording time
  per call, from 0.36 ms to 0.80 ms (measured on this Mac, 200 calls), which widened that
  window. The three affected tests now poll `/status` for up to 3 s with `status_when()`.
  The proxy behaviour is unchanged.
- `python3 tests/test_eval_weekly.py`: 17 checks pass.
- Headless Chrome screenshots at 1440 px of the real-rollup fixture and the no-metering
  fixture. Artifacts are in the gitignored `__pycache__/visual/`; the session rules forbid
  deletes, so they were left in place.

## Not verified

- On the Mini: first deploy with no state file, then live traffic bumping it. The
  coordinator's acceptance run covers this.
- State-file write cost on the Mini's disk and under the 16-way concurrency cap. Measured
  here as +0.44 ms per call on this Mac; not measured on the Mini.
- No second-model review of the diff yet.

DESIGN2-DONE
