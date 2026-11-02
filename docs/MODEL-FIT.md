# SSD → Mini model fit (surveyed 2026-10-27)

Source: 65-model Ollama store on AthenaSSD (`ollama list` on the MacBook)
plus mml-tests evidence (`smollm2:1.7b` AUC 0.709 @ 0.6 s/call,
`granite3.1-dense:2b` AUC 0.613 @ 22.7 s/call) and the Mini context sweep.

Mini envelope: 8 GB total / ~5.9 GB usable / CPU-only / 30 GB disk free
(30 GB already used by the current 13). Transfer = `ollama pull <tag>`
fresh on the Mini. Effective context: 4k for most, 8k gemma2:2b,
16k functiongemma, ~2k for phi3/phi3.5/athena-slm.

## Tier 1 — pull now (~8 GB)

| Model | Size | Why |
|---|---|---|
| smollm2:1.7b | 1.8 GB | Measured best tiny judge (0.709 AUC, 0.6 s) |
| qwen2.5-coder:1.5b | 986 MB | Proven in mml loop |
| gemma3:270m | 291 MB | Instant tiny |
| LFM2.5-1.2B / 350M | 730 / 229 MB | Novel LiquidAI arch, CPU-friendly |
| Qwen3-1.7B (unsloth) | 1.1 GB | Best small Qwen quant |
| MiniCPM5-1B | 688 MB | Strong small |
| qwen3.5:0.8b | 1.3 GB | Newest Qwen small |
| nomic-embed-text:v1.5 | ~274 MB | **Pulled 2026-10-28** — first embeddings lane (probed live, 768-dim vector OK) |
| bge-m3 | 1.2 GB | Optional multilingual follow-up (verify CPU tok/s first) |
| Qwen3.5-0.8B-Artemis (TurinTech) | 0.57 GB (Q5_K_M) | Tools lane: ADOPTED with per-tool schema (11-12/12 live, 27.7 tok/s); see T12 |
| qwen3:4b-instruct-2507 | 2.5 GB (Q4_K_M) | Tools lane: 7/12 plain, 8/12 schema arm — p2 value errors persist (semantic, not format); 9.8 tok/s CPU, 3.18 GB resident; see T12 |
| qwen3:4b-thinking-2507 | 2.5 GB (Q4_K_M) | Reasoning: rejected — correct but 4-5x slower than granite (75s vs 16s trap); over-thinks on CPU |
| phi4-mini | 3.8B (Q4_K_M) | Tools lane: 7/12 plain + schema (recovery 2/2, drifts run to run); 10.0 tok/s CPU, 3.09 GB resident; fallback behind artemis+schema |
| qwen3:8b | ~5.2 GB (Q4_K_M) | REJECTED for all lanes: runs + reasons correctly (trap ok) but 4.3-4.8 tok/s, 747-tok think burns, swap 2.5->4.7/6 GB — drowns the box; llmfit marginal confirmed |
| LFM3-1.7B (LiquidAI) | ~1 GB (Q4_K_M) | BLOCKED: pulled OK but Ollama 0.32.1 cannot load it (unknown arch 'lfm3'); needs Ollama upgrade, not judged on merit |
| granite4:1b-h | 1.56 GB (Q4_K_M) | Tools lane: NO-GO — 8/12 schema (p3 abstain 0/2, semantic), 13.8 tok/s, 1.7 GB resident; loses to artemis+schema on every axis; see CANDIDATES |
| opencoder:1.5b | 1.42 GB (Q4_K_M) | Coder lane: ADOPT (measured 9/10 executables vs qwen2.5-coder:3b 7/10; sole fail = multi-fence harness strictness on correct code), 18.5 tok/s, 2.36 GB resident; custom INF license cleared for local use; AGENTS.md routing = proposal, see CANDIDATES |
| RWKV-7-G1g-1.5B (Q5_K_M) | 1.18 GB | GO: loads on 0.32.1 (arch rwkv7, cards' 0.33.2 floor was conservative); tools 10/12 (p1-p5 perfect, p6 turn-2 discipline), think:false required; 20.1 tok/s, 72 tok/s prefill, 1.27 GB resident; strong tools fallback, see CANDIDATES |

## Tier 2 — quality A/Bs (pick 2–3, ~8 GB)

`qwen3:4b-instruct-2507` vs base qwen3:4b; `gemma3:4b` vs gemma2:2b;
`Nemotron-3-Nano-4B`; `ministral-3:3b`; `starcoder2:3b` / `codegemma:2b`.

## Skip

All 7–8B (llmfit Marginal 86–90%, swap risk on 8 GB);
`granite3.1-dense:2b` (measured 22.7 s/call, pathological);
`codex2/3/4` tags (byte-identical aliases); HF hub caches (configs only,
no weights; laya needs Apple-Silicon MLX anyway).

## Round 5 addendum (2026-10-28, nlmx research)

- KV cache: adopt `q8_0`, **never `q4_0`** (measured 8–18% output similarity —
  near-total divergence for a tiny extra saving).
- Principle: a bigger model at Q4_K_M beats a smaller model at Q8_0; keep the
  3–4B quality lane plus 1.5–1.7B fast/specialist lane bias.
- `IQ4_XS`/imatrix I-quants: possible lever for 3–4B + more context; raw
  `llama-server` only (Ollama can't emit I-quants); needs a local PPL check.
- Distillation (see tickets/T5): QLoRA specialists beat bigger bases on domain;
  the next judge upgrade path after smollm2.

## Scout addendum (2026-10-30, TurinTech Artemis 0.8B)

- Source: HF `turintech/Qwen3.5-0.8B-Artemis-GGUF` (130k DL/mo); file verified
  (Q5_K_M = 569082048 bytes). Install: `ollama run
  hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M` (no native ollama.com 0.8b
  tag; the 2b tag exists).
- Published: BFCL-live 163/258 vs 109 for bartowski Q4_K_M same-size baseline;
  IFEval 308/541; GSM8K 124/250; 8k ctx in tests.
- Caveats (from the card): all numbers measured on RTX 5090, all layers on GPU —
  quality should transfer, CPU tok/s on our i5-8500B unmeasured; thinking OFF for
  short/tool calls; weak knowledge (MMLU-Pro 33/280) — tools lane only.
- Validation: A/B vs llama3.2:3b / phi4-mini / functiongemma via the T11/T12
  tool bench + weekly eval, on the box.
- Measured 2026-10-31 (coordinator, live): 27.7 tok/s decode / ~147 prefill,
  847 MB resident, think-off clean stop. Tool bench (T12, 12 scenarios, live):
  artemis **4/12** vs phi4-mini **5/12** — artemis 4/4 on non-tool turns but 0/8
  on tool calls: it never emitted the instructed JSON fence (likely Harmony-style
  output). Not adopted for the tools lane on this protocol. Follow-ups: retest
  with Harmony-aware parsing/few-shot, or try the 2b tag
  (`ollama.com/turintech/qwen3.5-2b-artemis`).
- Update (parser fixed, re-bench): artemis now **7/12 in a three-way tie**
  (p1 fixed 0→2/2; p2 args still 0/2). Efficiency-best at equal score (0.85 GB,
  27.7 tok/s) but no outright winner — tied within noise. See T12 findings.
- Update (schema arm): artemis **12/12 then 11/12 replicated** with per-tool
  schema — its errors were structural, not reasoning. ADOPTED for the tools
  lane with schema (only p3 abstain wobbles 1-2/2). The vendor BFCL did
  transfer after all; the harness was the blocker twice over.
