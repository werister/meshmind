# Local benchmarks, quantization formats & hyper-optimized small providers (2026-11-01)

agent-reach + web pass on three asks: (1) local benchmark suites the box can run, (2)
quantization versions worth evaluating, (3) hyper-optimized small-model providers. Scoped to a
CPU-only 8 GB Ollama box. Everything is a **lead/hypothesis pending the lab's own harness** —
and the recurring theme is that the lab should **borrow benchmark *methods* and quant *A/B
designs*, run them on its own box**, not trust external leaderboards.

---

## 1. Local benchmark suites to run on-box

| Suite | What it measures | Fit for the box |
| --- | --- | --- |
| **geerlingguy/ai-benchmarks** | Curated, reproducible local-AI bench scripts (Ollama tok/s across hardware) | 🟢 Best-known, script-based, CPU-runnable; good tok/s methodology to copy. ([repo](https://github.com/geerlingguy/ai-benchmarks)) |
| **JoniMartin27/inferbench** | Inference throughput/latency bench | 🟢 lightweight runner |
| **osolmaz/localperf / pepe-va/local-llm-bench-lab / SupermodularAI/local_bench** | Local tok/s + resource benches | 🟡 overlap with what the lab already does via `context-probe.py` / `run_ladder` |
| **webdevsamran/local-ai-hardware-bench** | Hardware-oriented (CPU/GPU) profiling | 🟡 hardware focus |
| **KleidiBench** | ARM/KleidiAI micro-kernel bench | 🔴 ARM-optimized — our box is x86 Intel; not a fit |

**The honest finding:** the lab **already has** the bench primitives these provide —
`context-probe.py` (context sweep), `run_ladder`/`run_8q` (prompt ladders), `eval-weekly.py`
(PASS/FAIL + tok/s), T11 coder bench, T12 tool bench. What's *missing* vs. these suites is not a
new tool but **two measurement types the lab doesn't do yet:**
1. **Perplexity (PPL) / KLD-vs-fp16** — a quality-under-quantization number (none of the lab's
   harnesses compute it; needs raw `llama-perplexity` from llama.cpp, not Ollama). This is the
   gate for the IQ4_XS question (§2).
2. **A standardized tok/s + RAM sweep across the whole model set** in one run (geerlingguy's
   shape) — the lab measures ad-hoc; a single `bench_all.py` producing a comparable table would
   feed the dashboard and the week-over-week diff (EVAL-from-behavior).

→ **Recommendation:** don't adopt a suite; add a **PPL/KLD check** (raw llama.cpp) + a
**one-shot tok/s-and-RAM sweep** to the lab's own harness, using geerlingguy's method as the
reference. Both are on-box-runnable and fill real gaps.

## 2. Quantization formats worth evaluating

The lab's current policy (MODEL-FIT round-5): **Q4_K_M default, q8_0 KV cache, never q4_0,
IQ4_XS flagged but unchecked.** The research adds three concrete things:

- **`quantdiff.com/leaderboard`** — ranks every GGUF quant by **KLD, accuracy, tool-call success,
  and speed.** This is *exactly* the lab's metric set (tool-calls matter after the T12 arc).
  Use it to **pre-select which quants to A/B**, then verify on-box. ([quantdiff](https://quantdiff.com/leaderboard/))
- **"One model, nine quants" field notes** + the Q8→Q3_K_M measured showdown — practical
  quality/size curves; the consistent finding is **Q4_K_M is the knee**, IQ4_XS buys size/ctx at
  a small quality cost, Q3 and below degrade sharply.
  ([talachu](https://talachu.com/blog/one-model-nine-quants/),
  [bric.pe.kr](https://bric.pe.kr/blog/gguf-quantization-showdown-q4-q5-iq4-2026),
  [logeshwaran](https://www.logeshwaran.org/2026/10/gguf-quantization-types-explained.html))
- **IQ4_XS / imatrix (I-quants)** — the lab's open lever: smaller weights → more RAM for context
  (ties to CONTEXT-MAX). Needs **imatrix-calibrated GGUFs + raw `llama-server`** (Ollama can't
  emit I-quants) + a **local PPL check** to confirm the quality cost is acceptable. Still untested.

**The counter-intuitive new finding — Liquid QAD Q4_0:** Liquid's **Quantization-Aware
Distillation** ships models where **Q4_0 is the *native distillation target*, not a degradation**
— the model is trained to be good *at* Q4_0. ([liquid.ai/blog/qad](https://www.liquid.ai/blog/qad))
→ This is a **documented exception to the lab's "never q4_0" rule**: the rule was measured on
*post-hoc* q4_0 (8–18% divergence); a QAD-Q4_0 model is a different animal. If the lab runs an
LFM QAD model, q4_0 may be correct *for that model*. Don't generalize the ban to QAD variants —
A/B it. (The lab already has `LFM3-1.7B` and `athena-slm` (LFM2) installed.)

→ **Recommendation:** (a) use quantdiff to shortlist quants per adopted model; (b) run a **PPL/KLD
A/B** for the one real open question — **IQ4_XS vs Q4_K_M on qwen3:4b-2507 / granite4.2:3b** — to
decide if I-quants buy usable extra context without quality loss; (c) treat **QAD-Q4_0 as its own
case** on the LFM models, not under the q4_0 ban.

## 3. Hyper-optimized small-model providers / families

| Provider / family | Why "hyper-optimized" | Lab status |
| --- | --- | --- |
| **Liquid AI LFM2.5 / LFM3** | Hybrid conv+attention, QAD quantization, edge-first; **LFM2.5-230M** (tiny), LFM3-1.7B (dual-mode, 256K ctx) | 🔄 **LFM3-1.7B installed, not benched**; LFM2 (athena-slm) running. QAD is the novel lever (§2). ([liquid](https://www.liquid.ai/blog/introducing-lfm2-5-the-next-generation-of-on-device-ai)) |
| **IBM Granite 4 / 4.1** | "Hyper-efficient high-performance **hybrid**" (Mamba/transformer hybrid); low KV footprint | ✅ granite4.2:3b adopted (reasoning lane), granite4:micro-h installed. ([ibm](https://www.ibm.com/new/announcements/ibm-granite-4-0-hyper-efficient-high-performance-hybrid-models)) |
| **NVIDIA Nemotron-3-Nano-4B / Nemotron-Flash** | Distilled/pruned 4B, agentic; Nemotron-Flash = efficiency-focused arch | 🕳️ untouched — a 4B agentic candidate at the top of the budget; worth a look vs qwen3:4b-2507. ([nvidia](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16)) |
| **TurinTech Artemis (compressed)** | Artemis-platform-compressed GGUFs | ✅ Artemis-0.8B adopted (tools lane). |

### Novel / non-transformer architectures (efficiency frontier, CPU-relevant)
- **Mamba / SSM hybrids** — `MambaHermes-3B-GGUF`, `BitMamba-2-1B`, `bitmamba.cpp` (Rust), Mamba-3
  (Together). SSMs have **linear attention** → cheaper long-context prefill, the exact CPU wall
  from CONTEXT-MAX. 🕳️ untested; **the most interesting architectural lever** for the box's
  prefill problem — but GGUF/llama.cpp support for Mamba is uneven, verify before pulling.
- **RWKV** (`ChatRWKV`) — attention-free RNN-like, very CPU-friendly, constant memory per token.
  🕳️ niche but genuinely CPU-optimized; worth a small-model probe.
- **Granite 4's Mamba-hybrid** is the *mainstream, already-adopted* version of this idea — so the
  lab is already partly on the SSM-efficiency curve via granite4.2:3b.

→ **Recommendation:** the hyper-optimized families worth *new* attention are **Nemotron-3-Nano-4B**
(agentic 4B, direct qwen3-2507 competitor) and a **Mamba/SSM small model** (linear-attention
prefill — tests the CONTEXT-MAX thesis that the CPU wall is prefill). Both are A/B candidates, not
adoptions. Liquid QAD and Granite-hybrid are already in the house — exploit them (bench LFM3-1.7B,
try QAD-q4_0) before chasing new providers.

---

## Ranked "what to actually run" (by ROI, on-box)
1. **PPL/KLD A/B: IQ4_XS vs Q4_K_M** on qwen3:4b-2507 / granite4.2:3b (raw llama.cpp) — settles
   the lab's one open quant question and the "more context via smaller weights" lever. *Decisive,
   cheap, long-overdue.*
2. **Bench the installed-but-untested LFM3-1.7B**, and **A/B QAD-q4_0** on an LFM model — tests
   the counter-intuitive "q4_0 is fine when it's the distillation target" finding against the ban.
3. **Add a one-shot tok/s + RAM sweep** (`bench_all.py`, geerlingguy's method) feeding the
   dashboard + week-over-week diff.
4. **Probe Nemotron-3-Nano-4B** vs qwen3:4b-2507 (agentic 4B at budget ceiling) — scouting, lower
   priority than exploiting what's installed.
5. **Experimental: a Mamba/SSM or RWKV small model** — linear-attention prefill is the one
   architecture that could move the CPU context wall; verify GGUF support first. Research-grade.
6. Use **quantdiff** only to *shortlist* quants to A/B — never as the verdict (the lab's harness
   is the verdict; same discipline as the vendor-BFCL lesson).

### Caveats
- External leaderboards/blogs are **shortlisting aids, not verdicts** — every number is a
  hypothesis until the lab's PPL/tok-s/tool-bench confirms it on the i5-8500B (the Artemis lesson).
- I-quants + Mamba/RWKV need **raw llama.cpp**, not Ollama — a tooling cost; only pursue if the
  PPL check or the prefill-wall payoff justifies leaving the Ollama lane.
- Most "novel arch" GGUFs have **uneven llama.cpp support** — confirm the build loads the arch
  before planning a bench.

### Evidence / cross-ref
Benches: geerlingguy/ai-benchmarks, inferbench, localperf, local_bench, KleidiBench(ARM, no-fit).
Quants: quantdiff.com/leaderboard (KLD/acc/tool/speed), talachu "nine quants", bric.pe.kr Q8→Q3
showdown, logeshwaran quant-types, liquid.ai/blog/qad (QAD-q4_0). Providers: Liquid LFM2.5/LFM3,
IBM Granite 4/4.1 hybrid, NVIDIA Nemotron-3-Nano-4B + Nemotron-Flash, TurinTech Artemis; novel:
MambaHermes-3B-GGUF, BitMamba, bitmamba.cpp, ChatRWKV, Mamba-3. Lab: MODEL-FIT (q8_0/q4_0 policy,
IQ4_XS note), CONTEXT-MAX (prefill wall, I-quant lever), GAPS-whats-left, context-probe.py/
eval-weekly.py/T11/T12. All external numbers are hypotheses pending the lab's harness.
*External content rephrased for licensing compliance.*
