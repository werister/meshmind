# Maximizing context & reasoning on the 8 GB Intel box — deep dive (2026-11-01)

The deepest remaining lever: how far can usable context be pushed on this CPU box, and does
more context actually buy better reasoning? Grounded in **live measurement** (KV math from
each model's real architecture via `/api/show`), **current Ollama levers** (web, last-30-day),
the **grounded NotebookLM corpus** (nlmx cross-query, 14 sources_used — genuinely grounded),
and the **2026 long-context literature** (arXiv). All vendor/claimed numbers are hypotheses
pending the lab's own harness.

## TL;DR
1. **Context ceiling is dominated by model choice, not by a global "4k" rule.** The lab's
   stale "4k for most" assumption is wrong per-model: gemma3:4b can barely hold 4k (hence the
   swap), while qwen3:4b-2507 and granite4.2:3b can reach **~17–23k (f16 KV)** within budget,
   and the adopted artemis-0.8B is effectively **KV-unbounded** on this box.
2. **The single biggest free context lever is KV-cache quantization (`q8_0`) + flash
   attention — it roughly DOUBLES the context that fits**, at ~1/3 slower decode and
   negligible quality loss (matches the lab's existing round-5 "q8_0 yes, q4_0 no").
3. **More context does NOT buy better reasoning for 3–4B models.** YaRN lets them *accept*
   long context but not *attend* across it; CPU prefill is superlinear; "lost-in-the-middle" /
   "context rot" hits small models hard. **Spend the compute budget on lean targeted context +
   chain-of-thought, not on a bigger window.**

---

## 1. The KV-cache math (measured, per real architecture)

KV-cache bytes = `2 (K+V) × layers × kv_heads × head_dim × ctx × bytes_per_elem`, where
`head_dim = embedding/heads`. GQA (`kv_heads ≪ heads`) is what makes small models cheap.
Params pulled live from `/api/show` (2026-11-01):

| Model | layers | kv_heads | head_dim | weights | KV/1k tok (f16) | KV/1k (q8_0) |
|---|---|---|---|---|---|---|
| artemis-0.8B Q5 | 24 | 2 | 128 | 0.77 GB | **25 MB** | 12 MB |
| qwen3:1.7b Q4 | 28 | 8 | 128 | 1.36 GB | 115 MB | 57 MB |
| granite4.2:3b Q4 | 40 | 8 | 64 | 2.24 GB | 82 MB | 41 MB |
| qwen3:4b-2507 Q4 | 36 | 8 | 80 | 2.50 GB | 92 MB | 46 MB |
| gemma3:4b Q4 | 34 | 4 | **320** | 3.35 GB | **174 MB** | 87 MB |

Two architecture facts jump out:
- **gemma3:4b has a huge head_dim (320)** → its KV is ~7× artemis's per token *and* its
  weights are the largest. It is the **worst context-per-GB model** on the box — the one most
  likely to force swap. (This explains the live swap I measured today.)
- **artemis-0.8B (kv_heads=2, head_dim=128) is absurdly cheap** — 25 MB/1k tokens at f16.
  Context is essentially never its binding constraint.

### Max context that fits the ~4.4 GB model budget (weights + KV + 0.3 GB scratch)

| Model | max ctx @ f16 KV | max ctx @ q8_0 KV |
|---|---|---|
| artemis-0.8B | ~135k | ~271k (model cap) |
| granite4.2:3b | **~22.7k** | **~45k** |
| qwen3:4b-2507 | **~17.4k** | **~35k** |
| gemma3:4b | ~4.3k | ~8.6k |

**This overturns "4k for most."** Three of five models can hold **4–10× the lab's current 4k
default** inside the budget — the 4k cap is a conservative floor, not a hardware wall, for
everything except gemma3:4b. (Caveats: these are *memory-fit* ceilings; CPU *prefill latency*
is the separate wall — §3 — and the box's live free RAM is often <100 MB, so the practical
ceiling is lower than the budget math until the box is kept one-model-resident.)

---

## 2. The levers, concretely (Ollama 0.32.1 on the box)

### Lever A — KV cache quantization + flash attention (biggest, free)
- `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (values: f16 default / q8_0 / q4_0).
  KV quant **requires flash attention on**, and the setting is **server-wide**, set as an
  `Environment=` line on the Ollama launch (systemd/launchd).
  ([ssdnodes](https://www.ssdnodes.com/learn/ollama-kv-cache-quantization),
  [markaicode](https://markaicode.com/errors/tool-performance-degradation-fix/))
- Measured elsewhere: q8_0 ≈ half the cache, q4_0 ≈ 28%, at "a third slower" decode, "same
  facts in different words." ([dev.to/steefjan](https://dev.to/steefjan_wiggers_34a415b/quantizing-the-kv-cache-in-ollama-on-rtx-spark-half-the-memory-a-third-slower-5bhl))
  Flash attention alone trims ~10–20% footprint.
  ([luongnv89/skills](https://github.com/luongnv89/skills/blob/main/skills/ollama-optimizer/references/environment_variables.md))
- **Lab fit:** this is exactly the lab's own round-5 `MODEL-FIT` policy ("adopt q8_0, never
  q4_0 — q4_0 measured 8–18% output similarity"). So: **turn flash-attn on + KV q8_0** and the
  §1 "q8_0" column becomes the real ceiling — ~2× context per model, for free except ~⅓ slower
  decode. The q4_0 column is **banned** by lab policy and the external "different words"
  finding agrees.
- **Caveat worth checking on the box:** `OLLAMA_KV_CACHE_TYPE` is *server-wide*, so it applies
  to every model including the embedders (bge-m3/nomic) — verify those tolerate q8_0 KV (they
  have no KV in the generative sense, so low risk, but confirm the probe still returns clean
  768-dim vectors).

### Lever B — per-request `num_ctx` (already the lab's mechanism)
`num_ctx` sets the window per call; the lab already passes it (seen 4096 live). The §1 table
says `num_ctx` can safely rise to **8k (gemma), 16–22k (granite), 17–35k (qwen3-2507),
100k+ (artemis)** *if* KV q8_0 is on and the box is one-model-resident. **Do not set it
globally high** — KV is reserved up-front at `num_ctx`, so a high default wastes RAM on every
call. Raise it per-task only when the task needs it.

### Lever C — model choice for the context lane
If a genuinely long-context task appears, the right model is **not** gemma3:4b (worst
context/GB) — it's **granite4.2:3b or qwen3:4b-2507** (both ~8× better KV efficiency and
262k/131k train ctx), or **artemis** if the task is tool/decision-shaped. Route long-context
to the GQA-efficient models.

### Lever D (advanced, raw llama.cpp only) — I-quant weights for more ctx headroom
`MODEL-FIT` already notes IQ4_XS frees weight RAM for more ctx but needs raw `llama-server`
(Ollama can't emit I-quants) + a local PPL check. Still true; lower priority than A–C.

---

## 3. Does more context help reasoning? (the harder question — answer: mostly no)

Convergent evidence from the grounded corpus (nlmx cross-query, 14 sources) and the fresh
arXiv literature:

- **Capacity ≠ capacity to attend.** YaRN rope-scaling lets a 3–4B model *accept* 16–32k
  without crashing but does **not** grant the parameter capacity to maintain attention across
  that distance (nlmx grounded answer). A longer window you can't attend over is wasted RAM +
  latency.
- **CPU prefill is superlinear.** Without GPU/sparse-prefill, processing long contexts adds
  superlinear prefill latency — on this box, long context is *expensive* for *minimal* quality
  gain (nlmx grounded answer). This compounds the already-measured ~9–10 tok/s decode.
- **"Lost in the middle" / context rot** is real and worse for small models: performance is
  highest when the relevant info is at the start/end and drops sharply mid-context, and the
  drop **grows with context length** for vulnerable models.
  ([Liu et al. 2307.03172](https://arxiv.org/html/2307.03172v1),
  [Context Rot Eval 2605.23170](https://arxiv.org/pdf/2605.23170v1.pdf) — small models "drop
  sharply when the target task moves from the end to the middle"). Content rephrased for
  licensing compliance.
- **Shorter-but-targeted beats longer.** The RAG literature's standing result: shorter context
  is better *when the relevant info is preserved* — failures stem from ineffective context
  *utilization*, not missing info.
  ([2608.03297](https://arxiv.org/html/2608.03297v1), [2601.02023](https://arxiv.org/pdf/2601.02023v2))

**Grounded takeaway (nlmx, verbatim-sense):** keep inputs *lean and highly targeted* —
retrieve 1–3 precise passages rather than stuffing documents — and **spend the compute budget
on chain-of-thought / test-time thinking + 8-bit KV quantization**, not on a bigger window.

This dovetails exactly with the lab's own `THINKING-small-models` finding: **reasoning quality
on this box comes from thinking (granite4.2:3b, opt-in, budgeted), not from context size.** The
two levers point the same way — small models reason via CoT, not via long windows.

---

## 4. Synthesis — the context/reasoning policy this box should run

Ordered by value, all grounded above:

1. **Turn on flash-attn + `OLLAMA_KV_CACHE_TYPE=q8_0` (server-wide).** Free ~2× context
   headroom, matches existing q8_0 policy, ~⅓ slower decode accepted. Verify embedders still
   probe clean. *Biggest single win.*
2. **Keep `num_ctx` at 4k by default; raise per-task only**, and only on the GQA-efficient
   models (granite4.2:3b ~16–22k, qwen3:4b-2507 ~17–35k with q8_0 KV). Never raise it on
   gemma3:4b (it barely holds 4k and drives swap).
3. **Retire the flat "4k for most" line in `MODEL-FIT`** — replace with the per-model ceilings
   in §1 (they differ by ~30× across the fleet). gemma3:4b should carry a "worst context/GB,
   keep ≤4k" note.
4. **For reasoning, invest in CoT not context:** opt-in thinking on granite4.2:3b (per
   `THINKING` doc), lean/targeted prompts (1–3 passages), and — if RAG is ever added — a
   prompt-compression/rerank step (the lab already has a rerank ticket T10 and bge-m3) so the
   small model sees *less but better* context.
5. **Operational:** keep the box **one generative model resident** — today it was in 2.5–4 GB
   swap with multiple models loaded, which collapses tok/s and caused live `endpoint_error`s.
   Context headroom math assumes one model resident; multi-load erases it.

### Proposed experiments (for the coordinator to run live, one-model-resident)
- **E1 — KV q8_0 A/B:** same model/prompt at 4k, f16 vs q8_0 KV: measure RAM delta, tok/s
  delta, and output similarity (confirm the lab's round-5 q8_0 call at current Ollama; also
  re-test the q4_0 ban holds). *Cheap, high value.*
- **E2 — context-ceiling probe:** rerun `context-probe.py` with q8_0 KV on, per model, to
  record the *real* max `num_ctx` before OOM/swap — replaces the stale sweep. Expect
  granite/qwen3-2507 to clear 16k, gemma3:4b to stall near 4–8k.
- **E3 — context-vs-reasoning:** on granite4.2:3b, hold a reasoning task fixed and vary only
  padding/context length (needle at middle vs end) to measure the box's own "context rot"
  curve — does accuracy drop as the window grows? Confirms §3 locally before trusting it.

### Sources
Live: `/api/show` (arch params), `/api/ps`, `/status` (box swap state), 2026-11-01.
Levers: ssdnodes, markaicode, dev.to/steefjan, luongnv89/skills (Ollama KV/flash-attn,
last-30-day). Reasoning: nlmx cross-query over the grounded corpus (14 sources_used — grounded,
not model-knowledge); arXiv 2307.03172, 2605.23170, 2608.03297, 2601.02023 (lost-in-middle /
context rot, 2026). Lab cross-ref: `MODEL-FIT.md` (round-5 q8_0 policy, IQ4_XS note),
`THINKING-small-models-2026-10-31.md` (CoT > context), `context-probe.py`, T10 rerank.
All external numbers are hypotheses pending the lab's own E1–E3 runs. *External content
rephrased for licensing compliance.*
