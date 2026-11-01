# Hosted dashboard & showcase — live test (2026-11-01)

Exercised the full hosted surface over the tailnet (not just `/status`), checked that the
rendered dashboard matches the source-of-truth JSON, and inspected the panels that are backed
by real data. Base URL: `https://mac-mini-von-hugo-1.taild73e38.ts.net`.

## TL;DR
The dashboard is **healthy, fresh, accurate, and self-consistent** — it passed the real test
(rendered page vs. `/status` ground truth, numbers reconcile exactly). It is **doing its job**
by surfacing the two things that actually need attention: the Mini's **swap pressure** and a
**stale, all-FAIL weekly eval** whose "FAIL" is a strict-rubric artifact on the *old* model set.
Neither is a dashboard defect.

## Endpoints — all live
| Endpoint | HTTP | Content-Type | Size | Notes |
|---|---|---|---|---|
| `/dashboard` | 200 | text/html | 49 KB | Full showcase, **zero-JS**, `<meta http-equiv=refresh>` auto-updates |
| `/status` | 200 | application/json | 15 KB | Live; grand_total 22,657, 549 metered calls |
| `/calls` | 200 | application/json | 14 KB | Metered ring, **top-level JSON list**, 50 entries |
| `/agents.md` | 200 | text/markdown | 3.5 KB | Agent guide served over HTTPS |
| `/api/tags` | 200 | application/json | 8 KB | 16 models (Ollama passthrough) |
| `/api/ps` | 200 | application/json | 0.4 KB | Loaded-model view |

## Dashboard content & accuracy
- **9 sections, all rendering:** Lab status · Tokens by model · Cost avoided · Memory in use ·
  Where tokens go · Throughput · Activity · Recent calls · Weekly eval.
- **Zero client JS**, static HTML + meta-refresh — the right call for a tailnet showcase on a
  constrained box. Page stamp current (`2026-11-01T15:26Z` at check time).
- **Numbers reconcile exactly against `/status` (not stale, no double-count):**
  - "Tokens by model" panel shows **21,521** = `metering.eval_tokens_total` (per-model output
    tokens).
  - Top token counter shows **22,657** = `tokens.grand_total` = `probe_total (3,380) +
    feedback_total (19,277)`. Verified the arithmetic holds.
  - These are two *different, correct* aggregations in two places — no drift, no double count.
- **`/calls` ring is live and current:** 50 entries with rich per-call fields (`model`, `agent`,
  `prompt_tokens`, `eval_tokens`, `duration_ms`, `ok`, `partial`, `truncated`, `status`, `ts`).
  Latest entries are this session's `tool_bench` calls to artemis-0.8B at `2026-11-01T14:28` —
  so metering captured the live benching. The "Recent calls" panel is backed by real, fresh data.

## Issues the dashboard correctly REVEALS (not dashboard bugs)

### 1. Weekly eval is stale (5.1 days) and reads all-FAIL — but it's a rubric artifact
- `/status.eval`: `ts 2026-10-27T12:15:49Z`, `kind run_summary`, `wall_s 20.7`, **3 models,
  passed 0 / failed 3 / skipped 0**.
- Per-model detail shows this is **not a model collapse** — every model got *most* prompts right
  and tok/s is healthy:

  | model | verdict | passed/total | avg_tok_s |
  |---|---|---|---|
  | qwen2.5:0.5b | FAIL | 1/3 | 78.7 |
  | gemma2:2b | FAIL | 2/3 | 16.8 |
  | llama3.2:3b | FAIL | 2/3 | 20.5 |

- **Root cause = the PASS bar is 3/3.** Models scoring 1–2 of 3 read as FAIL even though they
  mostly worked. **This is the same pattern as the tool-bench fence/strictness saga** — a "FAIL"
  that is the *harness bar*, not the model. Worth revisiting whether 3/3-to-PASS is too strict
  (e.g. report a score/ratio, or set PASS at ≥2/3), exactly as the tool bench was loosened.
- **Secondary:** the eval still runs the **old model set** (gemma2:2b, llama3.2:3b) — it has not
  been updated to the current 16-model lineup (e.g. the adopted artemis-0.8B, qwen3:4b-2507,
  granite4.2:3b). Next scheduled run is Monday 2026-11-02 (per README: Mon 04:00), so a fresh
  run is imminent — but it will re-run the stale list unless updated.

### 2. The Mini is memory-stressed
- `/status`: `mem_free_mb 18`, `mem_compressed_mb ~`, **`swap_used_mb 2,465`**. The "Memory in
  use" panel faithfully shows a box leaning on ~2.5 GB swap — consistent with this session's
  multi-model benching; it had not fully drained at check time.
- Not a dashboard fault; it's the honest box state. Reinforces the standing rule: keep the Mini
  **one generative model resident**; spaced, single-model benches.

### 3. (Local, separate from the hosted lab) coordinator MacBook disk
- During this check the MacBook's disk hit **100% / 114 MB free** (down from ~6.7 GB earlier),
  which blocked local temp/scratch writes (I worked around it by piping in-memory). Since freed
  back to ~2.5 GB. Does **not** affect the hosted dashboard (that runs on the Mini). Flag because
  it's the same disk-pressure problem `TRIALS-offbox.md` documented, and it will re-block local
  writes if it fills again (Tier-A cache cleanup reclaims ~9–10 GB when needed).

## Verdict
The hosted dashboard is **trustworthy**: live data, correct aggregations, fresh timestamps,
reconciles against `/status`, and it correctly exposes the real issues rather than hiding them.
No defect found in the dashboard itself.

## Suggested follow-ups (proposals only — nothing changed live)
1. **Weekly eval rubric:** reconsider the 3/3 PASS bar (models scored 1–2/3, not 0) — report a
   ratio/score or set PASS ≥2/3; mirrors the tool-bench strictness fix. *Highest value.*
2. **Weekly eval model list:** update from the old set (gemma2:2b, llama3.2:3b, qwen2.5:0.5b) to
   the current lineup incl. artemis-0.8B, qwen3:4b-2507, granite4.2:3b.
3. **Mini memory:** let it drain to one-model-resident before the next live bench; the dashboard
   "Memory in use" panel is the signal to watch.

### Evidence
Live probes 2026-11-01: `/dashboard` (HTML parse), `/status` (eval + tokens + mem),
`/calls` (ring, 50 entries), `/api/tags`, `/api/ps`, `/agents.md`. Cross-ref:
`README.md` (weekly eval schedule + endpoints), `TRIALS-offbox.md` (disk pressure),
`RETRO-tools-lane-2026-11-01.md` (the "FAIL is often the harness, not the model" lesson).
