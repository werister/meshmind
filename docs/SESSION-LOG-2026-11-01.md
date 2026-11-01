# Session research log — consolidated evidence (2026-10-30 → 2026-11-01)

Raw evidence and analyses that otherwise lived only in the working session, gathered here so
the research trail is complete for handoff. The topic docs (listed at the end) hold the full
write-ups; this file preserves the **live measurements, verdicts, and grounded-query results**
that back them. Every vendor/external number is a hypothesis pending the lab's own harness.

## 1. Live measurements taken against the Mini (over tailnet)

Ollama **0.32.1** (latest upstream is v0.40.13 — box is ~8 minor versions behind). CPU-only
i5-8500B. All via `/api/chat`, `/api/show`, `/api/ps`, `/status`.

### Throughput (measured)
| Model | decode tok/s | prefill tok/s | resident | ctx |
|---|---|---|---|---|
| gemma3:4b | **9.7** | 55 | 2.88 GB | 4k |
| qwen2.5:0.5b | **56.7** | ~715 | 0.48 GB | 4k |
| artemis-0.8B (schema arm, per T12) | **27.7** | ~147 | 0.85 GB | — |

### KV-cache architecture params (from `/api/show`) and derived context ceilings
KV = 2·layers·kv_heads·head_dim·ctx·bytes; head_dim = emb/heads.
| Model | layers | kv_heads | head_dim | weights | max ctx @ f16 | max ctx @ q8_0 |
|---|---|---|---|---|---|---|
| artemis-0.8B Q5 | 24 | 2 | 128 | 0.77 GB | ~135k | model-capped |
| qwen3:1.7b Q4 | 28 | 8 | 128 | 1.36 GB | — | — |
| granite4.2:3b Q4 | 40 | 8 | 64 | 2.24 GB | ~23k | ~45k |
| qwen3:4b-2507 Q4 | 36 | 8 | 80 | 2.50 GB | ~17k | ~35k |
| gemma3:4b Q4 | 34 | 4 | **320** | 3.35 GB | ~4.3k | ~8.6k |
→ Context ceiling is **model-choice-dominated** (~30× spread); gemma3:4b is worst context/GB
and drives the swap. Full analysis: `CONTEXT-MAX-2026-11-01.md`.

### Structured-output `format` verification (the version-risk check)
Live on 0.32.1, qwen3:4b-2507 with a per-tool JSON-Schema in `format` returned pure JSON,
enum-correct (`unit:"f"`), exact key set: `{"args":{"city":"Tokyo","unit":"f"},"tool":"get_weather"}`.
→ The schema lever **works on the box's old Ollama** (key order may reorder; harmless to scorer).

### Box health / swap (operational, recurring)
Observed `mem_free_mb` 16–86, `swap_used_mb` 2,465–4,134 across the session whenever >1 model
was loaded. Heavy multi-model live benching pushed it to 4 GB swap; a direct artemis call then
timed out at 2.5 min (the `endpoint_error`s in live p2 runs were this, not a harness bug).
**Rule reinforced: keep one generative model resident; space out live benches.**

## 2. Model/runtime verdicts (evidence summary)

- **magnitude (T7): REJECT** — coordinator installed 0.2.15 on the Mini (macOS 15.8.1, OS gate
  passed); it serves nothing on Intel CPU (zero compatible catalog models, all 13 Ollama models
  "No kernels for the arch", bartowski Llama-3.2-3B unsupported every quant). My source analysis
  had verified the AVX2 *capability* (x86v3 tier, `profile.rs` detects `has_avx2`) but the live
  test proved **capability-in-source ≠ runnable** — no CPU kernel coverage in 0.2.15. Box
  restored to Ollama-only. Lesson: source capability is not a runnable model; only a live install
  settles it.
- **TurinTech Artemis-0.8B: ADOPTED (tools lane)** — vendor BFCL 163/258 (vs 109 same-size
  public GGUF); verified file Q5_K_M = 569,082,048 bytes; `ollama run
  hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M`. Benched 4/12 → 7/12 → **11-12/12** once the
  harness fence/arg artifacts were removed; adopted with per-tool schema at 0.85 GB / 27.7 tok/s.
  Caveats (card): all vendor numbers measured on RTX 5090; thinking OFF for tools; weak knowledge
  (MMLU-Pro 33/280). Full arc: `RETRO-tools-lane-2026-11-01.md`.
- **vllm-jev / goethe / runntime: no-fit** — arm64-only Mac wheels / CUDA-only / WebGPU
  respectively; source-confirmed. `RESEARCH-runtime-scout-2026-10-30.md`.
- **antirion (gateway): off-box only** — Rust AI gateway, Apache-2.0, 41 MiB idle (~40× lighter
  than LiteLLM) but **v0.1.1, single-author (bus-factor 1), no independent validation,
  Linux-only binary** (macOS = Docker/build). Recent-signal via agent-reach + GitHub API. Its
  PR #48 adds `/v1/systemone` — the same decision protocol merged into **vLLM mainline
  (PR #59299, 2026-10-08, verified independently)**. `RESEARCH-runtime-scout-2026-10-30.md`,
  `SCOUT-ecosystem-2026-11-01.md`.

## 3. Thinking vs instruct (live, measured — `THINKING-small-models-2026-10-31.md`)
Only three dual-mode thinkers on the box: **qwen3:1.7b, smollm3-3b, granite4.2:3b** (Ollama
errors "does not support thinking" for gemma3:4b, qwen2.5:3b, granite4:micro-h — tested).
Thinking costs 5–9× latency (50–125 s/answer). Reliability: **granite4.2:3b** most reliable
(correct both probes, slowest 75–93 s); smollm3-3b middle; **qwen3:1.7b unreliable for
thinking** (empty/no-final answers even at 2048-token budget). Reasoning comes from CoT, not
context size.

## 4. NotebookLM grounded-corpus query (nlmx, grounded — 14 sources_used)
Cross-query over the lab's grounded notebooks on "maximize context + reasoning for small CPU
models." Grounded answer (sources_used non-empty, so not model-knowledge): **YaRN lets 3–4B
models *accept* 16–32k but not *attend* across it; CPU prefill is superlinear; keep context
lean/targeted (1–3 passages) and spend budget on CoT + 8-bit KV quantization, not a bigger
window.** Converges with the 2026 "lost-in-the-middle / context rot" arXiv literature. Feeds
`CONTEXT-MAX-2026-11-01.md` §3.

## 5. Context-maximization levers (research → `CONTEXT-MAX` + `NOTEBOOK-context-reasoning`)
Final lever ranking for the box:
1. **`OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`** — ~2× window, ~⅓ slower decode,
   negligible quality loss; matches the lab's round-5 policy (q8_0 yes, q4_0 banned).
2. **Component-aware prompt compression with a "never larger than original" fallback** — local
   3B-as-rewriter pattern (arXiv 2606.03618: prompt tokens −34–47%, accuracy preserved/improved,
   beats LLMLingua-2); compress retrieved context hard, keep instruction/question verbatim
   (LLMLingua, Microsoft-maintained, EMNLP'23/ACL'24 — confirmed real/maintained via agent-reach).
3. **CoT on granite4.2:3b** (opt-in, budgeted).
4. **Raw `num_ctx` increase** — last resort (CPU-prefill-expensive).

Proposed experiments E1–E4: KV q8_0 A/B; re-run context-probe with q8_0; local context-rot
curve; local pre-compression A/B. (All for the coordinator, one-model-resident.)

## 6. Ecosystem scout (50 links / 5 clusters, 5 subagents — `SCOUT-ecosystem-2026-11-01.md`)
Adopt nothing; the lab owns the data layer (metering proxy + `/status`/`/dashboard`/`/calls`)
and front door (Caddy). Harvest: stdlib dashboard/self-monitoring features (traffic-light
health, tok/s burn-rate, per-agent bars, self-coverage counter, latency panel). One genuinely
new capability: a **local `/v1/systemone` judge shim** (gut/Kev over Ollama) matching the lab's
smollm2-as-judge use. Monitors/routers/heavy-observability = cloud/fleet tools, off-box-or-skip.

## 7. Hosted dashboard check (`DASHBOARD-CHECK-2026-11-01.md`)
All 6 endpoints live; dashboard accurate and self-consistent vs `/status` (21,521 = metering
eval tokens; 22,657 = probe+feedback grand_total). Correctly reveals: **weekly eval stale
(5 days) + all-FAIL — a 3/3-PASS rubric artifact** (models scored 1–2/3, healthy tok/s) on the
**old model set**; and the Mini's swap pressure. No dashboard defect. Follow-ups: loosen the
eval PASS bar (same trap as the tool bench), refresh the eval model list.

## 8. Blocked / incomplete (handled, not abandoned)
- **NotebookLM notebook creation: throttled** (RESOURCE_EXHAUSTED on create RPC; plan usage
  near-zero so transient server cooldown). Stopped looping per nlmx rules. Fully staged
  idempotent build+query commands in `NOTEBOOK-context-reasoning-2026-11-01.md` — runs when the
  throttle clears.
- **Coordinator MacBook disk** hit 100% mid-session (freed back to ~2.4 GB). Recurring per
  `TRIALS-offbox.md`.

## Index of this session's docs
Committed earlier: `RESEARCH-runtime-scout-2026-10-30.md`, `THINKING-small-models-2026-10-31.md`,
`MODEL-SCOUT-2026-10-31.md`, `GBNF-tools-draft-2026-11-01.md`; `MODEL-FIT.md` (addendum).
Committed with this log: `RETRO-tools-lane-2026-11-01.md`, `SCOUT-ecosystem-2026-11-01.md`,
`CONTEXT-MAX-2026-11-01.md`, `NOTEBOOK-context-reasoning-2026-11-01.md`,
`DASHBOARD-CHECK-2026-11-01.md`, and this `SESSION-LOG-2026-11-01.md`.
