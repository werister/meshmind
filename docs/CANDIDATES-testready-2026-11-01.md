# Pull-and-bench readiness — 5 scout candidates verified (2026-11-01)

Make the next pull-and-bench cycle test-ready. For each top-unknown from the model scout, verified
from primary sources against **OUR box: Ollama 0.32.1 (published 2026-07-16), Intel Mac, CPU-only,
~4 GB model budget**. The gating question throughout is the **LFM3 lesson: prove the architecture
loads on 0.32.1, don't assume.** Ollama 0.32.1's cutoff date (2026-07-16) is the hard filter — any
arch whose Ollama/llama.cpp support merged after mid-July 2026 is a no-go on the box as-is.

All sizes are from the **Ollama registry manifests** or HF repos (not the scout's secondhand
numbers — several of those were wrong, corrected below). All benchmark numbers remain hypotheses
pending the lab's own harness.

## Measured results (coordinator, 2026-11-02)
- **`granite4:1b-h`: NO-GO (measured).** Pulled (1.56 GB confirmed) and benched
  live on the Mini: **8/12** with per-tool schema (p3 abstain 0/2, p2 1/2 —
  semantic fails, not structural), **13.8 tok/s**, **1.7 GB** resident. Loses
  to artemis-0.8B+schema (11-12/12, 27.7 tok/s, ~1 GB) on every axis. Tools
  lane stays artemis. Next in line per bench order: `opencoder:1.5b`
  (coder lane) and the Qwen3-Reranker arch-load proof on raw llama-server;
  `granite4:1b` (3.27 GB) only if a bigger granite is explicitly wanted.
- **`opencoder:1.5b`: ADOPT for coder lane (measured).** Pulled (1.42 GB) and
  A/B'd live: **9/10** code executables vs incumbent qwen2.5-coder:3b **7/10**
  (incumbent fails 04-brackets, 06-datetime, 09-edge-trap with real assert/
  NameError errors). The single opencoder fail (01-median) is harness
  strictness, not wrong code: correct function + extra example fence, clipped
  at the token cap. Effectively 10/10 on correctness. **18.5 tok/s**,
  **2.36 GB** resident (note: slightly MORE than the 3B incumbent's 2.16 GB).
  License checked from HF source: custom INF Technology license (permissive
  grant incl. derivatives, revocable, no trademarks) — cleared for local
  eval/use, not OSI-approved; redistribution would need the agreement copy.
  Routing change (AGENTS.md coder lane) left as a proposal for owner review.

## Go/no-go table (test-priority order)

| # | Candidate | Pull tag | Size (verified) | Quant | License | Arch loads on 0.32.1? | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | granite4:1b-h | `granite4:1b-h` | **1.56 GB** | Q4_K_M | Apache-2.0 | ✅ proven (lab runs granite4.2:3b + micro-h) | **GO** |
| 2 | OpenCoder-1.5B | `opencoder:1.5b` | **1.42 GB** | Q4_K_M | other ("inf") | ✅ `LlamaForCausalLM` — safest arch | **GO** (license check) |
| 3 | granite4:1b | `granite4:1b` | **3.27 GB** | Q4_K_M | Apache-2.0 | ✅ plain transformer | **GO** (near budget ceiling) |
| 4 | Qwen3-Reranker-0.6B | `hf.co/...` / `pdurugyan/qwen3-reranker-0.6b-q8_0` | ~0.6–0.8 GB | Q8_0 | Apache-2.0 | ⚠️ arch yes (PR#14029, Jun 2026) but **Ollama rerank exposure is partial** | **CONDITIONAL** |
| 5 | RWKV-7 2.9B | community `ollama create` only | ~1.8–2.2 GB (Q4/Q5) | Q5_K_M rec. | Apache-2.0 | ❓ **unconfirmed on 0.32.1's engine** | **NO-GO / defer** |

---

## Per-candidate detail

### 1. `granite4:1b-h` — GO (highest test priority) ⭐
- **Tag/size:** `granite4:1b-h`, **1.56 GB** (Ollama registry manifest; NB the scout's "901 MB" was
  the HF Q4 file, not the Ollama default tag). Q4_K_M. Apache-2.0. 128K ctx (cap at 4k on the box).
- **Arch loads? YES — proven, not assumed.** Hybrid Mamba-2/transformer. The lab **already runs
  `granite4.2:3b` and `granite4:micro-h`** (both hybrid, both in `/api/tags`), so the Granite-4
  hybrid-Mamba2 graph demonstrably loads and serves on this exact Ollama build. The `granite4`
  library launched 2026-10-01 but the *engine* support predates the box's working set. This is the
  strongest arch-confidence of the five.
- **Gotchas:** none specific; the `-h` suffix is the hybrid build (IBM also ships non-`h`
  transformer fallbacks). Sits tiny in the 4 GB budget → lots of KV/context headroom.
- **Why test first:** zero arch risk + a genuinely new sub-1B Apache tier the lab lacks + a published
  IFEval ~78 / BFCL ~50 story to validate. Cheapest, safest, highest-info pull.

### 2. `opencoder:1.5b` — GO (coder-lane A/B; verify license before adopting)
- **Tag/size:** `opencoder:1.5b`, **1.42 GB** (registry; `opencoder:3b` is NOT in the library —
  1.5B and 8B only). Q4_K_M.
- **Arch loads? YES.** `config.json` → `LlamaForCausalLM`, `model_type: llama` — the single
  most-supported arch in llama.cpp/Ollama; loads on any version. No risk.
- **License: `other` / "inf"** (`infly/OpenCoder-1.5B-Instruct/blob/main/LICENSE`) — **verify it's
  acceptable before adoption** (likely permissive but not Apache/MIT; flag for whoever owns
  licensing).
- **Gotcha: `max_position_embeddings: 4096`** — exactly the box's 4k ceiling, **zero headroom**.
  Fine for the current envelope; can't be pushed longer.
- **Why test:** the only sub-4B coder worth A/B-ing vs the `qwen2.5-coder:3b` incumbent (competitive
  MBPP, ~40% smaller). Expectation (per scout): does NOT beat the incumbent on HumanEval/LiveCodeBench
  — the bench is to confirm that honestly, not to swap blind.

### 3. `granite4:1b` — GO (but note the real size)
- **Tag/size:** `granite4:1b`, **3.27 GB** (registry manifest). **Correction:** the scout said "~1 GB"
  — that's wrong; the Ollama default `1b` tag is **3.27 GB**, nearly the whole 4 GB budget, leaving
  little room for KV/context. Q4_K_M, Apache-2.0.
- **Arch loads? YES** — plain transformer (non-hybrid), zero Mamba-path risk, loads anywhere.
- **Trade vs 1b-h:** `1b` = max runtime compatibility + best BFCL/GSM8K in the Nano tier, but **2×
  the disk/RAM of 1b-h** and tight on budget. `1b-h` = smaller, higher IFEval, hybrid. **Test 1b-h
  first; only test 1b if 1b-h's quality disappoints**, because 1b's footprint competes with context.

### 4. `Qwen3-Reranker-0.6B` — CONDITIONAL (arch OK, Ollama exposure is the risk)
- **Tag/size:** no official Ollama-library tag; use `hf.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0` or the
  community `pdurugyan/qwen3-reranker-0.6b-q8_0` (ggml-org GGUF-my-repo conversion). ~0.6–0.8 GB Q8_0.
  Apache-2.0.
- **Arch loads? Qualified yes.** Qwen3 rerank/embed support merged in **llama.cpp PR #14029
  (2026-06-10)** — *before* the 0.32.1 cutoff, so the engine has it. **But two real caveats:**
  1. **Ollama's reranker exposure is partial** (ollama/ollama #17129, #10989, #16076) — raw
     `llama-server` has a `/v1/rerank` + `pooling=rank`, but Ollama may not surface reranking the
     same way; the lab's T10 endpoint may need raw `llama-server`, not Ollama's `/api/embed`.
  2. **Conversion gotcha (documented):** a wrongly-converted Qwen3-Reranker GGUF emits near-zero
     scores (~4.5e-23) — it must be converted with `pooling=rank` / correct `convert_hf_to_gguf.py`.
     Use a conversion known-good (the ggml-org one) and **validate scores in the harness before
     trusting** (ref: gist gf-mse/c49a215c…).
- **Verdict:** GO for the **T10 rerank lane specifically**, but **test on raw `llama-server` first**
  to confirm reranking works, before wiring it into the Ollama-fronted sidecar. Not a drop-in on
  the box's current Ollama path — hence CONDITIONAL.

### 5. RWKV-7 2.9B — NO-GO / defer (arch load unproven on 0.32.1 — the LFM3 lesson)
- **Tag/size:** no Ollama-library tag; community `ollama create` from a GGUF (e.g. zhiyuan8 /
  Mungert `rwkv7-1.5B-g1-GGUF`, `shoumenchougou/rwkv-7-g1i:2.9b`). ~1.8–2.2 GB at Q4/Q5. Apache-2.0.
- **Arch loads? UNCONFIRMED — the make-or-break gap.** RWKV-6/7 support exists in **raw llama.cpp**
  (RWKV wiki guide), but: (a) the RWKV wiki is about *raw llama.cpp*, not Ollama; (b) RWKV-7 is
  **not in the Ollama library** — it relies on importing a GGUF through 0.32.1's bundled engine, and
  **I found no primary source confirming Ollama 0.32.1 loads the RWKV-7 graph**; (c) Ollama's Sept-2026
  release dropped safetensors→GGUF conversion, so the GGUF must already be RWKV-correct. Per the LFM3
  lesson, "support exists in llama.cpp" ≠ "loads on our Ollama."
- **Additional risks even if it loads:** many RWKV-7 checkpoints are **base models** (not instruct);
  RWKV quality degrades sharply below Q5 (wiki: use ≥Q5_K_M); quantization tooling partially excludes
  RWKV (PR #12511).
- **Verdict: defer.** It's the most *interesting* candidate (pure attention-free → the CPU prefill-wall
  test), but it fails the pull-readiness bar today. **Prerequisite before it earns a bench slot:** a
  5-minute proof that `ollama create` + `ollama run` actually loads an RWKV-7 GGUF on 0.32.1 (no
  "unknown model architecture"). If that passes, promote to GO; until then it's a research spike, not
  a bench candidate.

---

## Recommended bench order (go-candidates only)
1. **`granite4:1b-h`** (1.56 GB) — zero arch risk, new Apache sub-1B tier, highest info/effort.
2. **`opencoder:1.5b`** (1.42 GB) — coder-lane A/B vs qwen2.5-coder:3b; confirm the "doesn't beat
   incumbent" hypothesis; clear the license.
3. **`granite4:1b`** (3.27 GB) — only if 1b-h underperforms; mind the near-budget footprint.
4. **`Qwen3-Reranker-0.6B`** — T10 rerank lane, but **on raw `llama-server` first** to prove
   reranking + validate non-zero scores; not a current-Ollama drop-in.
5. **RWKV-7** — DO NOT bench yet. Run the one-line arch-load proof first; promote only if it passes.

## Corrections to the scout (found while verifying)
- `granite4:1b-h` is **1.56 GB**, not 901 MB (that was the HF file). `granite4:1b` is **3.27 GB**,
  not ~1 GB — a material budget difference. Qwen3-Reranker has **no official Ollama-library tag**
  and a real conversion gotcha. RWKV-7 arch-load on Ollama is **unproven**, not "runs on stock."

## Prerequisite checks for the coordinator (before pulling)
- All GO pulls fit the ~4 GB budget except `granite4:1b` (3.27 GB — tight; watch KV/context room).
- For Qwen3-Reranker and RWKV-7, the **arch-load proof is a gate**, not a formality — the LFM3 and
  magnitude lessons both say capability-elsewhere ≠ runnable-here.
- Disk: 5 GO/conditional pulls ≈ ~8–9 GB total; the box has limited free disk — pull incrementally,
  bench, `ollama rm` the losers.

### Sources
Ollama registry manifests (granite4:1b-h/1b/micro-h/350m-h, opencoder:1.5b, granite-code:3b sizes);
ollama v0.32.1 release date (2026-07-16); HF `infly/OpenCoder-1.5B-Instruct` config.json
(LlamaForCausalLM, 4096 ctx) + LICENSE; llama.cpp PR #14029 (Qwen3 rerank/embed, Jun 2026), issue
#13275 / #16450 (Granite 4 hybrid), ollama/ollama #17129 (partial reranker exposure); RWKV-wiki
llamacpp.md + llama.cpp PR #12511; gist gf-mse/c49a215c (Qwen3-Reranker conversion fix); Ollama 0.30
GGUF blog. Lab: `MODEL-SCOUT`, `SCOUT-benchmarks-quants-providers`, `THINKING-small-models`
(LFM3 arch-load lesson), T10 rerank. All benchmark numbers are hypotheses pending the lab's harness.
