# MODELS — Round 5: model discovery via nlmx (NotebookLM) for the 8 GB CPU Mini

Captured 2026-10-28 in worktree `wt-lab-research` (branch `research/assist`), agent `kiro-models`.
Tool: **nlmx** (NotebookLM wrapper), always `--profile langchain`, one-shot queries only, calls paced ~2s.
Notebook created this round: **lab-models-round5** — id `618189c0-ad81-47bc-a34a-edd5b2fabe13`
(35 sources after import). No other notebook created; nothing deleted; no `--force` used.

Lab envelope carried in (read-only from NOTEBOOK-round4.md, docs/MODEL-FIT.md, TRIALS-offbox.md,
SPARRING-round2.md §3): 2018 Intel Mac mini, i5-8500B (6c/6t, AVX2+FMA, **no AVX-512**), 8 GB RAM
(~5.9 GB usable, ~3.8–4.4 GB real model budget after OS + Caddy + sidecar), CPU-only Ollama, 4k
norm context, no 8B+. Verified CPU tuning block already lives in SPARRING §3 (`-t 5 -tb 6 -c 4096
-np 1 --cache-reuse 256 -ctk/-ctv q8_0 -fa on --mlock`, keep mmap, skip `--numa`). Embeddings are
the standing gap (`bge-m3`/`nomic-embed-text` not yet pulled per MODEL-FIT / TRIALS).

---

## 1. Variant scores and winner

Two research prompt variants were planned as separate `nlmx research` tasks into one notebook:
- **V1 (broad):** small efficient open-weight LLMs + GGUF/KV quants for CPU-only 8 GB inference/serving.
- **V2 (narrow):** Unsloth Dynamic GGUF selection + specialist distillation recipes for CPU serving.

### What actually happened (tooling constraint, recorded honestly)
- **V1 ran and completed:** `--mode deep`, **36 sources found**, full report returned, then
  **imported once** (32 sources added; never `--force`, no duplicate). This is the winning task.
- **V2 never registered.** Four separate `nlmx research start` attempts for V2 all **hung
  client-side and timed out** (before V1's import, two retries, and once more after import freed
  the research slot). `nlmx research status` never showed a second task appear on the notebook — it
  continued to report only the V1 task. The deep-mode start kickoff blocks and the client abandons
  it; I could not force a second task (`--force` is forbidden by the guard) and may only create the
  single `lab-models-round5` notebook. So a live head-to-head V1-vs-V2 comparison was **not
  achievable in this environment**.

### Scoring (authority / diversity / recency), 1–5

| Variant | Status | Authority | Diversity | Recency | Weighted score | Notes |
|---|---|---|---|---|---|---|
| **V1 broad** | completed + imported, 36 sources | 5 | 5 | 5 | **5.0** | arXiv (Qwen3 Technical Report), ggml-org/llama.cpp GitHub discussions (#27085, #20969, #572), Arm Learning Paths, Hugging Face + Ollama + ModelScope model pages, a ResearchGate PEFT PDF, plus bench blogs and r/LocalLLaMA threads. All 2026-dated. Primary engine docs + a peer-ish paper + measured benches = strong anchors with broad coverage. |
| **V2 narrow** | **never started (tool hang)** | — | — | — | **N/A** | No task registered after 4 attempts; nothing to score. See "Not-verified" below. |

**Winner: V1 (broad), by default and on merit.** Margin: **uncontested** — V2 produced no source set
to weigh against. Independent of that, V1's source profile is high on all three axes (authoritative
primary docs, diverse source types, uniformly recent), so it is a legitimate winner, not merely the
survivor. Usefully, V1's deep report and imported sources already span **most of V2's narrow scope**
(imatrix/dynamic quant, IQ4_XS, distillation), which let the notebook queries below cover the V2
topics anyway — the narrow angle was recovered at query time rather than at research time.

### V1 source profile (representative, from the completed task's reference list)
arXiv **Qwen3 Technical Report**; GitHub ggml-org/llama.cpp Discussions **#27085**, **#20969
(TurboQuant KV)**, **#572 (P-core-only 2–3× on Intel)**; **Arm Learning Paths** (llama.cpp
multithread analysis); Hugging Face `nomic-ai/nomic-embed-text-v1.5`; Ollama + ModelScope embed
pages; ResearchGate PEFT PDF (**Gemma/Qwen2.5/Llama3.2 code FT**); measured-bench blogs (SOTAAZ,
OpenClaw DC, Inventive HQ, AscentCore); the open-weight-models curated GitHub list; OpenRouter
model compare; several r/LocalLLaMA tuning/KV threads. (32 of these were imported into the notebook.)

---

## 2. One-shot notebook queries (Q/A with grounding)

All four queries ran against notebook `618189c0-…` with `--json --timeout 180 --profile langchain`.
**Grounding signal checked every time** (`sources_used` non-empty ⇒ grounded in notebook sources,
not pure model knowledge). All four returned non-empty `sources_used`.

### Q1 — Quant recipe for an 8 GB CPU box (weights + KV)
**A (grounded gist):** OS overhead ~1.5–2.0 GB ⇒ ~5.5–6.0 GB working budget. **Weights:** `Q4_K_M`
(~4.5 bpw, +0.0535 PPL, ~73% smaller than FP16) is the sweet spot; `Q5_K_M` (~5.1 bpw, +0.0142)
when RAM allows; `Q8_0` (~8 bpw, +0.0004, near-lossless) **only for ≤3B** on this box. Principle:
*a larger model at Q4_K_M beats a smaller model at Q8_0.* **KV cache** (`-ctk/-ctv`): `f16`
baseline; **`q8_0` is the safe RAM-saver** (~50% KV saved, well-behaved); **`q4_0` is a cliff** —
one source measured ~8–18% output similarity to f16 (near-total divergence) for only a tiny extra
saving, so avoid `q4_0` KV. Threads = **physical cores only** (memory-bandwidth-bound; SMT/E-cores
add contention). Example: `llama-server -m model-q4_k_m.gguf -c 16384 -ctk q8_0 -ctv q8_0 -fa on -t <physical_cores>`.
- **sources_used: 16** · **citations: 50** · Grounded? **Yes — HIGH confidence.**

### Q2 — Unsloth Dynamic GGUF picks (UD / imatrix / IQ4_XS)
**A (grounded gist):** **imatrix** (`llama-imatrix`) calibrates against a corpus (wikitext-2 / code)
to measure per-tensor importance; `llama-quantize` then does **non-uniform bit allocation** — high
bits (Q5_K/Q8_0) on embeddings/output/down-proj, aggressive (IQ4_XS/Q3_K) on less-critical FFN/MoE
expert layers. **Unsloth Dynamic (UD)** ships curated dynamic GGUFs (UD-Q5_K_S, UD-Q6_K_XL, etc.):
smaller files + lower PPL/KLD *per byte* than plain Q4_K_M, at slightly higher dequant/decode
overhead from variable block structure. **Picks for tight RAM:** when Q4_K_M is just too big for
context, use **`IQ4_XS`** (or `IQ4_NL`, strong on CPU); for sub-4-bit, **only imatrix I-quants**
(`IQ3_M`/`IQ4_XS`) — small models (<4B) collapse fast below 4-bit without imatrix. Otherwise
**Q4_K_M stays the default** unless you specifically need the ~200–500 MB IQ4_XS frees.
- **sources_used: 3** · **citations: 20** · Grounded? **Yes — MEDIUM-HIGH.** The IQ4_XS/imatrix/UD
  mechanics are well-grounded; some comparative size figures (e.g. ~35B-checkpoint byte counts)
  read like extrapolation beyond the Mini's scale — treat those specific numbers as indicative, not
  Mini-measured.

### Q3 — Specialist distillation recipes servable on CPU (1B–4B students)
**A (grounded gist):** Two methodologies. **Logit distillation** — off-policy (train student on a
large teacher's outputs across think/no-think modes) and on-policy (align student logits to teacher
via **KL divergence**); on-policy logit distillation reached higher Pass@1/Pass@64 at ~1/10th the
GPU hours of RL-from-scratch (cited ~1,800 vs ~17,920 GPU-h). **PEFT/QLoRA** — freeze base in 4-bit
NF4, train LoRA adapters in FP16; 1B–3B bases fine-tuned on targeted corpora beat larger untuned
bases on domain tasks. **Concrete small students:** DeepSeek-Distill-Qwen-**1.5B** (code-reasoning
FT, ROUGE-L 43%, beating the 7B/8B distills — architecture alignment > raw params); **Qwen3 0.6B/
1.7B/4B** distilled from flagship teachers with think/no-think control; a **Qwen2.5-Coder-1.5B**
shell-command specialist (InterCode-ALFA 0.620, edging an untuned 7B base); QLoRA legal/code
adapters on Gemma-2B / Qwen2.5-1.5B·3B / Llama-3.2-1B·3B (+54–55% on domain benches). **CPU serving:**
1.5B@Q4_K_M ≈ 0.94–1 GB disk / ~1.6 GB RAM, ~32–167+ tok/s on laptop CPUs, sub-second median
latency; 3B–4B@Q4_K_M/Q5_K_M ≈ 2.0–2.5 GB RAM — comfortable inside 8 GB with KV headroom. Threads =
physical cores.
- **sources_used: 9** · **citations: 20** · Grounded? **Yes — HIGH.** (Includes the arXiv Qwen3
  report and the ResearchGate PEFT PDF; the 1.5B shell-assistant number lines up with MODEL-FIT's
  own measured `smollm2:1.7b` 0.6 s/call datapoint.)

### Q4 — Embedding-model CPU perf (bge-m3, nomic, mxbai, qwen3-embedding)
**A (grounded gist):** **`nomic-embed-text:v1.5`** — 137M, ~150 MB (Q8) / ~274 MB (F16), 8k context,
Matryoshka dims (768→256), fastest; **`mxbai-embed-large`** — ~335M, ~237–350 MB, 512-token context,
stronger on long chunks but heavier; **`bge-m3`** — ~560M, ~0.6–1.2 GB, 8k context, multilingual +
multi-vector/sparse but **slowest on CPU** (~4× nomic's params); **`qwen3-embedding`** — ~0.6B scale,
~0.3–0.8 GB, 8k–32k, strong multilingual/code via Qwen's big vocab, moderate CPU speed. **Best pick
for an 8 GB CPU RAG box: `nomic-embed-text:v1.5`** — it keeps the embedder to ~150–270 MB so the
3B@Q4_K_M generator + vector store fit without swap, native 8k chunks, minimal TTFT, dims sliceable
to 256 to cut vector-DB RAM and CPU distance-calc cost.
- **sources_used: 7** · **citations: 11** · Grounded? **Yes — MEDIUM-HIGH.** nomic specifics are
  well-grounded (HF + Ollama pages in the corpus); the **bge-m3 / mxbai / qwen3-embedding** figures
  lean partly on model-knowledge — verify those three with a local probe before trusting the exact
  RAM/speed numbers. This directly informs the MODEL-FIT embeddings gap.

### Grounding scorecard

| Query | sources_used | citations | Grounded? | Confidence |
|---|---|---|---|---|
| Q1 quant recipe | 16 | 50 | Yes | **HIGH** |
| Q2 Unsloth Dynamic GGUF | 3 | 20 | Yes | **MED-HIGH** (big-checkpoint sizes = indicative) |
| Q3 distillation on CPU | 9 | 20 | Yes | **HIGH** |
| Q4 embedding CPU perf | 7 | 11 | Yes | **MED-HIGH** (nomic solid; others verify locally) |

---

## 3. Verdicts

### Ran (executed this round, observed output)
- Created notebook `lab-models-round5` and ran **V1 deep research → 36 sources → imported 32** (once,
  no `--force`). Verified final notebook holds **35 sources** via `nlmx notebook list`.
- Ran **4 one-shot grounded queries**; all returned non-empty `sources_used` (16 / 3 / 9 / 7) with
  50 / 20 / 20 / 11 citations.
- Confirmed profile access (`nlmx notebook list --profile langchain` returned 3 pre-existing
  notebooks before this round's create).

### Inferred (grounded answers mapped onto the lab's known envelope)
- **Q4_K_M weights + q8_0 KV is the correct Mini default**, and it *corroborates* SPARRING §3's
  already-verified `-ctk/-ctv q8_0` choice — and sharpens it with a measured warning: **do not drop
  KV to q4_0** (quality cliff). This strengthens the pending `OLLAMA_KV_CACHE_TYPE=q8_0` adoption.
- **"Bigger model at Q4_K_M beats smaller at Q8_0"** supports MODEL-FIT's Tier-1/Tier-2 bias toward
  3–4B@Q4_K_M over tiny-but-high-precision, within the ~3.8–4.4 GB budget.
- **IQ4_XS / imatrix I-quants** are a concrete new lever to fit a 3–4B model *plus* more context
  when plain Q4_K_M is marginally too big — a Round-5 addition not previously in the lab's notes.
- **Distillation evidence reinforces the lab's "specialist beats generalist tonnage" thesis**: a
  1.5B specialist edging a 7B base matches MODEL-FIT's measured `smollm2:1.7b` judge win; these are
  pull/FT candidates, not just reading.
- **`nomic-embed-text:v1.5` is the cheapest way to close the embeddings gap** (~150–270 MB) and is a
  lighter first pull than `bge-m3` for the mem0/anything-llm trials in TRIALS — it leaves far more
  of the 8 GB for the generator.

### Not-verified (do not treat as established)
- **V2 head-to-head comparison** — V2 research never started (4 timeouts; `--force` forbidden). The
  winner is V1 by default; a true V1-vs-V2 source-quality contest was **not performed**.
- **bge-m3 / mxbai / qwen3-embedding exact RAM & tok/s on the Mini** — partly model-knowledge in Q4;
  **measure on the box** before committing numbers.
- **Unsloth UD size/PPL deltas** — demonstrated on larger checkpoints in the sources, **not** on a
  sub-4B model on an i5-8500B. Benchmark locally if adopting UD/IQ4_XS.
- **Any tok/s figure** here — all throughput numbers are from other people's CPUs; the Mini's
  dual-channel DDR4 bandwidth is the real ceiling and must be confirmed with `llama-bench`.
- **nlmx `research start` reliability in deep mode** — it hung every time this session; treat
  multi-variant research on one notebook as currently unreliable via this wrapper/env.

---

## 4. Concrete model table (candidates for the Mini)

Sizes are Q4_K_M unless noted; "pull tag" is the Ollama tag to `ollama pull` fresh on the Mini.
Cross-checked against docs/MODEL-FIT.md Tier-1/2.

| Model | Pull tag | Approx size (Q4_K_M) | Why | Usage recipe |
|---|---|---|---|---|
| SmolLM2 1.7B | `smollm2:1.7b` | ~1.0 GB | MODEL-FIT measured best tiny judge (0.709 AUC, 0.6 s); Q3 corroborates 1.5–1.7B CPU sweet spot | Tiny judge / fast router; `num_ctx 4096`, KV `q8_0`, physical-core threads (`num_thread 5`) |
| Qwen2.5-Coder 1.5B | `qwen2.5-coder:1.5b` | ~1.0 GB | Proven in mml loop; Q3 shell-assistant shows a 1.5B coder beating a 7B base on domain | Code/shell helper; same KV/thread recipe; good QLoRA-specialization base |
| Llama 3.2 3B | `llama3.2:3b` | ~2.0 GB | Q1/Q3 balanced general baseline, GQA, 128k native (cap to 4k here) | General chat/summarize; `-c 4096 -ctk q8_0 -ctv q8_0 -fa on` |
| Qwen2.5 3B | `qwen2.5:3b` | ~2.0 GB | Q1 code/math/structured-output leader in class, GQA | Structured output / code; same recipe; strong JSON extraction |
| Gemma 2 2B | `gemma2:2b` | ~1.7 GB | High-throughput short-form; MODEL-FIT notes 8k effective ctx | Fast classification/short tasks; 8k ctx ok, KV `q8_0` |
| qwen3:4b (instruct-2507) | `qwen3:4b-instruct-2507` | ~2.5 GB | Current lab default class; Tier-2 A/B vs base qwen3:4b | Default quality lane; `-c 4096`, q8_0 KV, `--mlock` only if it clearly fits |
| **nomic-embed-text v1.5** | `nomic-embed-text:v1.5` | ~0.15–0.27 GB | **Q4 winner** for 8 GB RAG embedder; closes MODEL-FIT embeddings gap cheaply | Embedder for mem0/anything-llm trials; slice dims 768→256 to cut vector-DB RAM |
| bge-m3 (optional) | `bge-m3` | ~0.6–1.2 GB | MODEL-FIT's planned embedder; multilingual + hybrid retrieval | Only if multilingual/sparse needed; **verify CPU tok/s locally first** (Not-verified) |
| IQ4_XS variant (technique) | n/a (GGUF file) | ~0.2–0.5 GB < Q4_K_M | Q2 lever to fit 3–4B + more context when Q4_K_M is marginally too big | Prefer imatrix-calibrated I-quant; via raw `llama-server`, not Ollama tags |

Skip (unchanged from MODEL-FIT, reinforced by Q1): all 7–8B at any quant (Q1 shows 7B@Q8_0 ≈ 7 GB =
OOM on 8 GB; even 7B@Q4_K_M leaves almost no KV headroom), and `q4_0` KV cache (Q1 quality cliff).

---

## 5. Next actions for the lab

1. **Adopt q8_0 KV, never q4_0.** Proceed with the pending `OLLAMA_KV_CACHE_TYPE=q8_0`; Q1's measured
   q4_0 cliff is a hard "don't." Benchmark q8_0 vs f16 tok/s with `llama-bench` on the Mini.
2. **Pull `nomic-embed-text:v1.5` first (not bge-m3)** to close the embeddings gap at ~150–270 MB and
   unblock the TRIALS mem0 trial cheaply; keep bge-m3 as an optional multilingual follow-up *after*
   a local CPU-speed probe.
3. **Treat 3–4B@Q4_K_M as the quality lane and 1.5–1.7B specialists as the fast lane** (Tier-1/2 in
   MODEL-FIT), per Q1's "bigger@Q4_K_M > smaller@Q8_0" and Q3's specialist-beats-tonnage evidence.
4. **Prototype one imatrix/IQ4_XS build** of a 3–4B model via raw `llama-server` (Ollama can't emit
   I-quants) to test whether it buys context headroom on 8 GB — gated behind a local PPL/tok/s check
   (Not-verified at Mini scale).
5. **Run a local embedding probe** (nomic vs bge-m3 vs mxbai) to replace Q4's partly-model-knowledge
   numbers with Mini-measured tok/s + RAM before committing the RAG embedder choice.
6. **Flag the nlmx deep-research multi-variant limitation** to the notelab workflow: a second
   `research start` on a notebook with an unimported completed task hangs; plan single-variant deep
   research per notebook, or sequence import→start, until the wrapper handles it.

---

MODELS-DONE tasks=1 (V1 completed+imported; V2 did not start — 4 nlmx research start timeouts, --force forbidden) queries=4
