# Which small models actually "think" on the Mini — measured 2026-10-31

Follow-up to the runtime scout, answering a specific question: among the small models
the lab can run, **which deliver proper reasoning ("thinking") vs. a plain instruct/
"normal" answer, and is thinking a net win on this 8 GB CPU box?**

All numbers are **live over the tailnet** against the Mini (Ollama 0.32.1, i5-8500B,
CPU-only, 4k–5k ctx), via `POST /api/chat` with exact `eval_count` / `*_duration` /
`done_reason` fields and Ollama's native `message.thinking` channel (`"think": true`).
Two reasoning items were used to avoid single-prompt artifacts:
- **P1 (trap):** bat-and-ball — correct answer **$0.05** (intuitive-wrong is $0.10).
- **P2 (multi-step):** 3-box apples — correct answer **Box B = 10**.

## Capability map (what Ollama itself reports)

Ollama returns a typed error `"<model>" does not support thinking` for instruct-only
models, so capability is not guesswork:

| Model | Params/quant | Thinking channel? | Notes |
|---|---|---|---|
| **qwen3:1.7b** | 2.0B Q4_K_M | **Yes** (dual-mode) | `think:true/false`; `/no_think` style |
| **smollm3-3b** (`huggingfacetb-smollm3-3b-q4-k-m:bakeoff`) | 3.1B Q4_K_M | **Yes** (dual-mode) | HF SmolLM3 `/think` `/no_think` |
| **granite4.2:3b-q4_K_M** | 3.7B Q4_K_M | **Yes** (dual-mode) | IBM Granite 4 thinking toggle |
| granite4:micro-h | 3.2B Q4_K_M | Yes (family) | untested here; hybrid Granite |
| gemma3:4b | 3.9B Q4_K_M | **No** — "does not support thinking" | instruct-only |
| qwen2.5:3b | 3.1B Q4_K_M | **No** — "does not support thinking" | instruct-only |
| qwen2.5-coder:3b | 3.1B Q4_K_M | No (qwen2 family) | instruct/code |
| phi4-mini, phi3.5:3.8b | 3.8B | No (these tags) | instruct (Phi reasoning is a *separate* tag we don't have) |
| qwen2.5:0.5b | 0.5B | No | fast lane |
| athena-slm (lfm2 1.2B), functiongemma (268M) | — | No | specialist/tiny |

**So the only "proper thinking" small models on the box are the three dual-mode ones:
qwen3:1.7b, smollm3-3b, granite4.2:3b** (plus granite4:micro-h, same family). Everything
else is instruct-only and should never be sent `think:true` (it errors).

## Measured thinking behavior (the important part)

| Model | Prompt | think | thinking chars | out tok | done | tok/s | wall s | correct? |
|---|---|---|---|---|---|---|---|---|
| qwen3:1.7b | P1 | on | 1,780 | 600 | **length** | 18.8 | 36.9 | **NO — empty answer** (budget consumed inside thinking) |
| qwen3:1.7b | P1 | off | 0 | 200 | stop | 19.7 | 10.5 | **YES ($0.05)** |
| qwen3:1.7b | P2 | on | 2,398 | 1,051 | stop | 8.8 | 124.5 | **NO — no final answer** even at 2048-tok budget |
| smollm3-3b | P1 | on | 2,032 | 628 | stop | 10.0 | 73.3 | **YES ($0.05)** |
| smollm3-3b | P1 | off | 0 | 152 | stop | 12.4 | 13.8 | **YES ($0.05)** |
| smollm3-3b | P2 | on | 1,576 | 516 | stop | 11.9 | 51.8 | **NO — reasoned but no FINAL line** |
| granite4.2:3b | P1 | on | 1,354 | 498 | stop | 7.6 | 73.7 | **YES ($0.05)** |
| granite4.2:3b | P2 | on | 1,669 | 693 | stop | 10.5 | 93.0 | **YES (10)** |

## What this means for the lab

1. **Thinking is real but expensive here, and only three models have it.** A thinking
   pass costs **1,300–2,400 reasoning chars (~500–1,050 extra tokens)** before any
   answer. At this box's 8–20 tok/s that is **50–125 s per answer** — 5–9× the instruct
   path. On a CPU box where decode is the bottleneck, "thinking on by default" is a tax,
   not a free upgrade.

2. **Reliability ranking of the three thinkers (measured, 2 problems):**
   - **granite4.2:3b — most reliable.** Correct on both P1 and P2, both `done_reason:
     stop`. But the **slowest** (74–93 s). Use when correctness on a hard item matters
     more than latency.
   - **smollm3-3b — middle.** Correct P1, reasoned-but-didn't-converge P2 (no final
     line). Its **think-OFF path is the sweet spot**: correct on P1 in 13.8 s. Good
     default dual-mode pick — fast normally, thinking available when asked.
   - **qwen3:1.7b — least reliable *for thinking*.** It thinks, but **twice failed to
     deliver a usable answer** (empty at 600 tok; no final at 2048 tok) — it over-thinks
     past the budget. Its real value is the **`think:false` fast path**, where it was
     correct and fastest (10.5 s). Treat qwen3:1.7b as a *fast instruct* model on this
     box, not a reasoner.

3. **The empty-answer trap is confirmed on our own hardware.** This is the same failure
   the TurinTech Qwen3.5-0.8B card warned about (thinking burned the whole output budget,
   no answer). Here qwen3:1.7b hit it at 600 tokens. **Rule: never send `think:true`
   without a generous `num_predict` (≥800–1000), and even then small thinkers may not
   converge.** `AGENTS.md` already says append `/no_think` for short answers — this data
   says make **think-off the default** for qwen3-class small models and only opt *into*
   thinking for genuinely hard items, preferably on granite4.2:3b.

## Suggested routing (proposed, not yet applied to AGENTS.md)

- **Fast / default short answers:** qwen2.5:0.5b (instruct) or qwen3:1.7b with
  `think:false` (~10–20 s, correct on simple reasoning).
- **"Normal" quality instruct (no thinking):** gemma3:4b or qwen2.5:3b — instruct-only,
  so no risk of a thinking stall; gemma3:4b measured ~9.7 tok/s earlier.
- **Deliberate reasoning lane (opt-in only):** granite4.2:3b with `think:true` and
  `num_predict ≥ 900` — the one small model that finished and was correct on both
  problems. Budget ~75–95 s/answer and don't put it on the latency-sensitive path.
- **Avoid:** `think:true` on qwen3:1.7b (unreliable here); `think:true` on any
  instruct-only model (hard error).

### Caveats
- Two problems, one quant each (Q4_K_M), greedy-ish defaults; this maps *behavior and
  cost*, not a full accuracy benchmark — the T11/T12 + weekly-eval harness is the place
  to score accuracy at scale. KV cache was the server default (not forced q8_0).
- granite4:micro-h and phi-reasoning tags were not pulled/tested; worth a follow-up if a
  faster reliable reasoner is wanted (granite-micro is smaller than granite4.2:3b).

### Sources
Live Mini `POST /api/chat` and `/api/tags` (2026-10-31); Ollama 0.32.1 thinking channel.
Cross-ref: `docs/RESEARCH-runtime-scout-2026-10-30.md` (TurinTech empty-answer caveat),
`AGENTS.md` (existing `/no_think` guidance), `docs/MODEL-FIT.md`.
