# NotebookLM workbook — Context & Reasoning on 8GB CPU (staging + deeper research)

**Status:** NotebookLM notebook creation is **throttled right now** — `nlmx notebook create`
returns RESOURCE_EXHAUSTED (code 8) on RPC `CCqFvf` despite near-empty plan usage (8.5% rolling
/ 0.4% weekly), i.e. a short-term server-side RPC rate limit, not a quota wall. Per the nlmx
rules I **stopped retrying in a loop** rather than hammer it. This file stages (a) the deeper
research and (b) the exact idempotent commands to build + query the notebook the moment the
throttle clears. Everything routes through `nlmx`, never raw `nlm`.

## Deeper research — the "spend budget on lean context" lever, quantified

`CONTEXT-MAX-2026-11-01.md` concluded: on this CPU box, don't grow the window — keep context
lean/targeted and spend compute on CoT + KV q8_0. This pass goes deeper on **how** to make
context lean cheaply, and on the CPU-prefill wall specifically. Fresh primary sources (all
arXiv, vetted via search; snippets quoted ≤30 words, rephrased for licensing):

1. **QUOKA — sparse attention on CPUs** (arXiv 2602.08722). Reports **~7× speedup on Intel
   Xeon CPUs** at near-baseline accuracy, using ~88% fewer KV pairs per attention evaluation.
   → Directly our box's class (Intel CPU, prefill-bound). Evidence that CPU prefill cost is
   attackable via sparsity without a GPU. Hypothesis pending our harness.
2. **Training-Free Long-Context Compression with Small Draft Models** (arXiv 2603.02631).
   Cross-model prompt compression retains **90–100% of full-prompt accuracy** (sometimes
   *better*, a denoising effect) while cutting **time-to-first-token** substantially. → A small
   model (we have artemis/qwen3:0.5b) could compress the prompt *before* the 3–4B sees it.
3. **LLMLingua in the wild** (arXiv 2604.02985). **Up to 18% end-to-end speedup** with response
   quality "statistically unchanged" across summarization/code/QA — *when prompt length,
   compression ratio, and hardware are matched*. → The caveat matters: gains are
   hardware-dependent, so this is an E-series experiment, not an assumption.
4. **LLMLingua-2 / task-agnostic compression** (arXiv 2403.12968, Microsoft). Frames
   compression as token-classification with a bidirectional encoder → faithful, task-agnostic.
   → The method behind (2)/(3); a BERT-class compressor (we run bge-m3) is the cheap path.
5. **Low-bit sparse-attention prefill** (arXiv 2505.24179) & **Sparse Pattern Sharing**
   (2505.19578). ≥3.36× prefill speedups at long context by exploiting attention sparsity. →
   Confirms the prefill wall from CONTEXT-MAX is a known, addressable bottleneck (though most
   work targets GPU/8B+; CPU/3–4B transfer is the open question).
6. **Draft-based approximate inference** (arXiv 2506.08373). Unifies KV-drop + sparse-attn +
   prompt-compression using a small draft model to predict token/KV importance. → Ties the
   whole cluster together: a tiny model guides what the big model can skip.

**Synthesis (adds to CONTEXT-MAX §3–4):** the cheapest reasoning/context win on this box is a
**pre-compression step** — use a tiny resident model (qwen2.5:0.5b) or bge-m3 to trim/rank the
prompt to 1–3 salient passages *before* the 3–4B model, cutting the superlinear CPU prefill
and sidestepping "lost-in-the-middle" by never sending the middle. This is strictly cheaper
than growing `num_ctx`, and the literature says it holds 90–100% quality. It also reuses assets
the lab already has (bge-m3 rerank = ticket T10; a 0.5b fast model). **Rank of levers, updated:**
KV q8_0 (free ~2× window) > lean/targeted context via rerank/compression > CoT on granite4.2:3b
> raw `num_ctx` increase (last resort, CPU-prefill-expensive).

## Deeper pass 2 — does compression transfer to SMALL/LOCAL models? (answer: yes, and here's the safe pattern)

The open question the first pass left was: most compression work targets GPU/8B+ — does it
hold for a *local 3–4B on CPU*? Two new primary sources answer it directly:

7. **Cross-Lingual Token Arbitrage — local-LLM prompt preprocessing** (arXiv 2606.03618, v2
   Jul 2026). This is almost exactly the lab's scenario: a **local Llama-3.2 3B** runs as
   *pre-flight middleware* that (a) translates non-English → English, (b) structurally rewrites
   the prompt into a compact task-oriented format, and (c) uses a **regex-validated
   rewrite-with-fallback that guarantees the optimized prompt is never larger than the
   original.** Result: **prompt tokens cut 34–47%**, total tokens up to 18.8%, **accuracy
   preserved or improved**, and it **beats LLMLingua-2 at matched compression**. The gains come
   from the *rewriting* stage, not naive keyword extraction. → A 3B model we already run can be
   the compressor; the "never larger + fallback" invariant is what makes it safe to deploy on a
   constrained box (worst case = pass-through, no regression).
8. **LLMLingua component-sensitivity guidance** (Microsoft LLMLingua docs + LLMLingua-2
   2403.12968). Key operational rule: **prompt components differ in compression sensitivity —
   contexts/documents are *less* sensitive (safe to compress hard), instructions and questions
   are *more* sensitive (compress lightly or not at all).** LLMLingua-2's small encoder is
   **3–6× faster than prior compression methods**, accelerating end-to-end latency 1.6–2.9× at
   2–5× compression. → Tells us *what* to compress: squeeze retrieved context, leave the task
   instruction intact.

**Updated synthesis (supersedes pass-1 ranking where they differ):** compression *does* transfer
to small/local, with two safety rails from the evidence —
- **(i) a "never larger than original + fallback" invariant** (2606.03618) so the compressor can
  never make things worse (worst case: it passes the prompt through unchanged);
- **(ii) component-aware compression** (LLMLingua) — compress the *retrieved context* hard, keep
  the *instruction/question* verbatim.
The lab can build this from assets it already has: a tiny resident model (qwen2.5:0.5b) or the
3B generalist as the rewriter, bge-m3 for rerank (T10). This is a **cheaper, safer win than
raising `num_ctx`** and is the concrete mechanism behind CONTEXT-MAX's "lean/targeted context"
recommendation. Net lever ranking, final: **KV q8_0 (free ~2× window) > component-aware
compression/rerank with a never-larger fallback > CoT on granite4.2:3b > raw num_ctx (last
resort)**.

New E-series experiment this unlocks:
- **E4 — local pre-compression A/B:** take a padded reasoning/judge prompt, run it (a) raw vs
  (b) through a qwen2.5:0.5b/3B rewriter with the never-larger fallback, feeding granite4.2:3b;
  measure prompt-token reduction, TTFT/prefill time, and PASS/FAIL accuracy delta. Hypothesis
  (pending harness): ≥30% prompt-token cut, prefill time down, accuracy flat-or-up — matching
  2606.03618's 34–47%/accuracy-preserved on commercial backends, to be verified on CPU 3–4B.

## The notebook plan (build when throttle clears)

Title: `Local AI Lab — Context & Reasoning on 8GB CPU (2026-11-01)`

Sources to add (nlmx `source add`, mix of the lab's own evidence + the primary research):
- Lab docs as `--text` or file: `CONTEXT-MAX-2026-11-01.md`, `THINKING-small-models-2026-10-31.md`,
  `MODEL-FIT.md` (round-5 q8_0 policy), `RETRO-tools-lane-2026-11-01.md`.
- Primary research `--url`: the six arXiv papers above.
- Ollama levers `--url`: ssdnodes KV-quant guide, dev.to q8_0/q4_0 measurement.

### Commands (idempotent; nlmx guards the non-idempotent import)
```bash
# 1. create (nlmx injects --confirm). Capture the id.
NB=$(nlmx notebook create "Local AI Lab — Context & Reasoning on 8GB CPU (2026-11-01)" --json | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")

# 2. add the primary research URLs (bulk, --wait)
nlmx source add "$NB" \
  --url https://arxiv.org/abs/2602.08722 \
  --url https://arxiv.org/abs/2603.02631 \
  --url https://arxiv.org/abs/2604.02985 \
  --url https://arxiv.org/abs/2403.12968 \
  --url https://arxiv.org/abs/2505.24179 \
  --url https://arxiv.org/abs/2506.08373 \
  --url https://arxiv.org/abs/2606.03618 \
  --url https://github.com/microsoft/LLMLingua \
  --url https://www.ssdnodes.com/learn/ollama-kv-cache-quantization \
  --wait

# 3. add the lab's own findings as text sources
nlmx source add "$NB" --title "CONTEXT-MAX" --file docs/CONTEXT-MAX-2026-11-01.md
nlmx source add "$NB" --title "THINKING-small-models" --file docs/THINKING-small-models-2026-10-31.md

# 4. research INSIDE the notebook (grounded; check sources_used != [] each time)
nlmx query notebook "$NB" "On an 8GB Intel CPU box, rank the levers for usable context and reasoning quality for a 3-4B model: KV q8_0, prompt compression/rerank, CoT, raw num_ctx. What does the evidence say is cheapest-per-quality?" --json --timeout 180
nlmx query notebook "$NB" "Does prompt compression with a small draft model preserve accuracy for a 3-4B judge model, and does it reduce CPU time-to-first-token? Cite the sources." --json --timeout 180
```

### Guardrails applied (per the nlm/nlmx rule)
- **Never raw `nlm`** — all via `nlmx`.
- **`notebook create`** silently no-ops without `--confirm`; nlmx injects it.
- **`source add` (research import) is non-idempotent** — nlmx's ledger refuses a duplicate
  re-run unless `--force`; so re-running step 2 is safe (it won't double the sources).
- **After every `query`, check `sources_used`** — if `[]` with empty citations, the answer is
  model knowledge (LOW CONFIDENCE), not grounded; re-ask narrower.
- **Don't use `chat start`** (interactive REPL an agent can't drive) — use `query notebook`.
- **Rate limit:** on RESOURCE_EXHAUSTED, back off and let it reset (rolling window resets
  2026-11-01 20:32 CET); don't loop retries.

## What I did vs. couldn't do this pass
- **Did:** deeper primary-source research (6 arXiv papers on CPU prefill / prompt compression /
  sparse attention), synthesized into the updated lever ranking above; verified the exact nlmx
  create/add/query API; staged idempotent build commands.
- **Couldn't (yet):** create the notebook — NotebookLM RPC throttle (RESOURCE_EXHAUSTED),
  near-zero plan usage so it's a transient burst limit, not a quota. Retry the block above after
  the 20:32 CET rolling-window reset (or whenever the per-second throttle clears). The commands
  are safe to run as-is.

### Sources
arXiv: 2602.08722 (QUOKA CPU sparse attn), 2603.02631 (draft-model compression), 2604.02985
(LLMLingua in the wild), 2403.12968 (LLMLingua-2), 2505.24179 (low-bit sparse prefill),
2505.19578 (sparse pattern sharing), 2506.08373 (draft-based approx inference). Ollama levers:
ssdnodes, dev.to/steefjan. Lab cross-ref: CONTEXT-MAX, THINKING-small-models, MODEL-FIT (T10
rerank). nlmx usage/create probes 2026-11-01. All external numbers are hypotheses pending the
lab's own E-series harness. *External content rephrased for licensing compliance.*
