# What's left on the table — gap analysis across everything surfaced (2026-11-01)

Pulls together every repo/model/tool surfaced across the session (runtime scout, model scout,
ecosystem scout, context/fetch work) and asks: **what have we NOT yet done with it?** Grouped by
the five areas — local inference, functions/tools, agentic tools, extensions, dashboards.
Grounded in the committed docs, the ticket backlog (T1–T13), and the **live installed model set**
(re-checked 2026-11-01). Proposals only; no code changed.

## Status key
- ✅ done / adopted · 🔄 in-flight (ticket or installed-not-benched) · 🕳️ surfaced, untouched · ❌ ruled out

## Headline gap
Several scout recommendations **got pulled but not yet benched.** The live set now includes
`qwen3:4b-thinking-2507`, `qwen3:4b-instruct-2507`, `LFM3-1.7B`, `artemis-0.8B`, `granite4.2:3b`.
Of these, **only artemis + 2507-instruct have been run through a harness.** The biggest
untapped value is not new scouting — it's **benching models already on the box.**

---

## 1. Local inference (runtimes & models)

| Item | Status | What's left |
|---|---|---|
| Ollama 0.32.1 | ✅ default | 🕳️ **8 versions behind (latest v0.40.13)** — never evaluated an upgrade; 0.40 changed structured-output/tool-parsing/thinking. An upgrade A/B is untouched. |
| magnitude | ❌ REJECT (no Intel CPU kernels, v0.2.15) | 🕳️ revisit *only* on a future version with CPU kernel coverage — set a reminder, don't re-test now. |
| goethe / vllm-jev / runntime | ❌ no-fit (CUDA / arm64-Mac / WebGPU) | nothing — correctly closed. |
| **KV q8_0 + flash-attention** | 🕳️ **researched, never applied** | **The single biggest untapped inference lever.** CONTEXT-MAX E1/E2 proposed but not run: turn on `OLLAMA_FLASH_ATTENTION=1 + OLLAMA_KV_CACHE_TYPE=q8_0`, re-probe real `num_ctx` ceilings. Free ~2× context. **Highest ROI open item.** |
| `qwen3:4b-thinking-2507` | 🔄 **installed, NOT benched** | the reasoning-lane candidate is on the box — run the THINKING two-problem probe + latency check (does it over-think/stall at 4k like qwen3:1.7b?). Decides the reasoning lane. |
| `LFM3-1.7B` | 🔄 **installed, NOT benched** | the tiny tool/structured-output candidate is on the box — run it through T12 (does it hold the fence? tool accuracy at ~1 GB?). |
| I-quants (IQ4_XS) for more ctx | 🕳️ untouched | needs raw `llama-server` + a PPL check; MODEL-FIT notes it. Only worth it if the q8_0 lever isn't enough. |

## 2. Functions / tool-calling

| Item | Status | What's left |
|---|---|---|
| T12 tool bench + fence/schema fix | ✅ artemis adopted (11-12/12) | — the arc is closed. |
| `qwen3:4b-thinking-2507` on tools | 🕳️ untested on T12 | thinking models can tool-call; never benched — but low priority (artemis won the lane). |
| Grammar `--schema per-tool` | ✅ built + adopted | 🕳️ **generalize the schema catalog** beyond the fixed 4 fake tools — a real per-tool schema registry (ties to §4 `/tools`). |
| **p2 exact-args ceiling on 2507** | 🕳️ characterized, not improved | few-shot or a verifier step is the open path if a reasoning-grade tool model is ever needed. |
| Local `/v1/systemone` judge shim | 🕳️ **surfaced, untouched** | the one genuinely-new capability from the ecosystem scout: `gut` or `Kev` over Ollama → a typed PASS/FAIL/Score judge replacing prose-parsing in the weekly eval. **Weekend-spike candidate.** |

## 3. Agentic tools (fetch / search / act)

| Item | Status | What's left |
|---|---|---|
| T13 web_tools (fetch+search) | 🔄 built as a script | 🕳️ **not yet a sidecar endpoint** — the `/fetch` design (3 docs) is drafted, not implemented. |
| **SSRF guard / egress firewall** | 🕳️ **designed, P0, not built** | the infra-protection piece: block loopback + `169.254` + **CGN `100.64/10` (the tailnet)**; fail-closed; connection-pinned. Prerequisite for shipping `/fetch`. |
| Brave/Bing search upgrade | 🕳️ designed (env-keyed, WP fallback) | not built; optional after Wikipedia baseline. |
| HITL `409-until-approved` gate (from WTMW) | 🕳️ idea only | reserve for the first lab tool that can *write/send* — not needed for read-only fetch. Roadmap item. |
| MCP / A2A surface | 🕳️ untouched | nlm has `skill`/`setup` for MCP; the lab exposes no MCP server. Open question whether agents should reach the lab tools via MCP vs raw HTTP. |

## 4. Extensions (catalogs, registries, protocol surfaces)

| Item | Status | What's left |
|---|---|---|
| `GET /tools` machine-readable catalog | 🕳️ **designed, not built** | the durable discovery surface for all lab tools (fetch, search, rerank, judge) in the T12 schema format — nothing exists yet; agents can't auto-discover lab tools. |
| T10 `/rerank` endpoint + bge-m3 | 🔄 ticket open | bge-m3 is installed; the rerank endpoint isn't built. Ties to the context-compression lever (§1) and the RRF idea borrowed from WTMW. |
| RRF hybrid retrieval (from WTMW) | 🕳️ algorithm noted | borrow the Reciprocal Rank Fusion *algorithm* (not pgvector) for the rerank lane — untouched. |
| Prompt-compression middleware | 🕳️ **researched, not built** | CONTEXT-MAX E4 / LLMLingua pattern: a local 0.5b/3B rewriter with "never-larger fallback" in front of the 3–4B — cuts prefill, holds quality. No ticket yet. |
| `/v1/systemone` protocol endpoint | 🕳️ untouched | exposing the decision protocol (now in vLLM mainline) as a lab surface — see §2 judge shim. |

## 5. Dashboards & observability

| Item | Status | What's left |
|---|---|---|
| `/dashboard` + `/status` + `/calls` | ✅ live, accurate | — verified this session. |
| **Weekly eval: stale + all-FAIL rubric** | 🕳️ **found, not fixed** | the DASHBOARD-CHECK finding: 3/3-PASS bar reads 1-2/3 as FAIL on the *old* model set. **Loosen the bar + refresh the model list** — same strict-harness trap as the tool bench. High-value, cheap. |
| Stdlib dashboard ideas (from ecosystem scout) | 🕳️ harvested, not built | traffic-light health dot, tok/s burn-rate sparkline, per-agent leaderboard bars, self-coverage counter, p50/p95 latency panel, async severity-tagging. All stdlib additions to `feedback-server.py`. |
| OTLP emit (OpenLLMetry) | 🕳️ idea only | only if the lab outgrows its own JSON; off-box collector needed. Low priority. |
| Mini swap/memory pressure | 🔄 T6 telemetry done | 🕳️ but the box still thrashes under multi-model load — an operational guard (refuse/queue a 2nd model load) is unbuilt. |

---

## Ranked "what we could still be doing" (by ROI on this box)

1. **Turn on KV q8_0 + flash-attention (E1/E2).** Free ~2× context, matches existing policy,
   one env change + a re-probe. *Biggest lever, smallest effort.*
2. **Bench the 3 installed-but-untested models** — `qwen3:4b-thinking-2507` (reasoning lane),
   `LFM3-1.7B` (tiny tool lane), and thinking-2507 on T12. They're already pulled; the work is
   just running the harness. *Highest value-per-effort — no scouting, just measurement.*
3. **Fix the weekly eval** — loosen the 3/3 PASS bar, refresh to the current 18-model set. Cheap,
   and it's currently showing a misleading all-FAIL. *Same lesson as the tool-bench fix.*
4. **Ship `/fetch` with the SSRF/egress guard** — the infra-protection win; P0 guard first, then
   the endpoint, then `GET /tools` discovery.
5. **Weekend spike: local `/v1/systemone` judge shim** (`gut`/`Kev` over Ollama) — the one new
   capability; could de-flake the weekly eval's grading at the same time.
6. **Build the prompt-compression middleware (E4)** + T10 rerank with RRF — the context-lean lever
   from CONTEXT-MAX, reusing bge-m3 already on the box.
7. **Harvest the stdlib dashboard features** — traffic-light health, burn-rate, per-agent bars,
   self-coverage counter — incremental, all in `feedback-server.py`.
8. **Evaluate an Ollama 0.40 upgrade** (8 versions behind) — but A/B carefully; it touches
   structured-output/tool-parsing the lab now depends on.

## The through-line
The lab's biggest remaining wins are **not more scouting** — the funnel is healthy and most
candidates are correctly closed or already pulled. They are: **(a) apply the levers already
researched** (q8_0 KV, compression, the judge shim), **(b) bench the models already installed**,
and **(c) fix the measurement surfaces** (weekly-eval rubric, `/tools` discovery, the egress
guard). Measurement and application, not discovery, is where the value now sits — the same
"suspect/upgrade the apparatus, not hunt new models" lesson the tool-lane arc taught.

### Evidence / cross-ref
Live: `/api/tags` (18 models incl. newly-pulled thinking-2507 + LFM3-1.7B), ticket backlog
T1–T13, `tailscale status`, `lsof`. Docs: RESEARCH-runtime-scout, MODEL-SCOUT, SCOUT-ecosystem,
CONTEXT-MAX, THINKING-small-models, DASHBOARD-CHECK, FETCH-{endpoint,prior-art,infra-protection},
RETRO-tools-lane, SESSION-LOG. All vendor numbers remain hypotheses pending the lab's harness.
