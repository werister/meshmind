# STRESSTEST — 8 GB CPU reality + CPU-only research sprint

Captured 2026-10-27 in worktree `wt-lab-research` (branch `research/assist`).
Evidence: `agent-reach` github/web/reddit reads (read-only). No merges.

Box: 2018 Intel Mac mini, i5-8500B (6c/6t, AVX2+FMA, no AVX-512), 8 GB RAM,
**~5.9 GB usable** after macOS + Caddy + feedback sidecar, CPU-only Ollama,
4k typical context. Standing load before any model: macOS + WindowServer +
Caddy + Python sidecar ≈ **1.5–2.1 GB resident**, so the model + its KV cache +
inference overhead must live inside roughly **3.8–4.4 GB** of real headroom.
That tighter "model budget" (not the full 5.9 GB) is what the math below uses.

---

## 1. Research sprint — CPU-only / limited-RAM sources (read-only)

| # | URL | One-line takeaway |
|---|---|---|
| 1 | https://github.com/ggml-org/llama.cpp/discussions/21136 | **Best find.** Real CPU-only guide on a 2-core/8GB-DDR2 box runs 4B at ~2 t/s; names `--mlock` as the single biggest win, `--ctx-size` ≤4096, `-t=cores`, `-ngl 0`, and lowering OS **swappiness** so the kernel drops FS cache instead of swapping mmap'd model pages. |
| 2 | https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md | `llama-bench` is the official way to sweep `-t`, `-b`, `-ub` and compare builds — the tool to settle our batch/thread sweet spot empirically instead of guessing. |
| 3 | https://www.bigiron.cc/guides/llama-cpp-tuning-for-cpu-only-homelab-inference | Config-pattern walkthrough for CPU-only homelab llama.cpp: thread count = physical cores, keep context modest, benchmark before trusting defaults. |
| 4 | https://buildwithaitoday.com/track/local-llms/learn/cpu-inference-tuning | Explains the three CPU knobs that matter (threads, mmap, memory limits) and why over-threading past physical cores regresses throughput. |
| 5 | https://www.jakegroszewski.com/theblog/local-llms-cpu-only-low-power-hardware-quantization-ram-guide/ | Practical CPU/low-power guide: Q4_K_M is the realistic quant, set expectations to single-digit t/s, RAM is the hard wall not CPU speed. |
| 6 | https://bestllmfor.com/guide/llm-local-cpu-sans-gpu/ | Models-by-RAM-capacity table (8/16/32 GB): at 8 GB, stay at ≤3–4B Q4 and reserve ~2 GB for the OS — matches the lab's "no 8B+" rule. |
| 7 | https://www.reddit.com/r/LocalLLaMA/comments/1qszphr/what_are_the_best_collection_of_small_models_to/ | r/LocalLLaMA thread on best small models for 8GB RAM — community converges on sub-4B Q4 (Qwen2.5, Phi-3-mini, Gemma2-2b) as the comfortable ceiling. |
| 8 | https://www.reddit.com/r/LocalLLaMA/comments/1r734a3/running_mistral7b_vs_phi3mini_vs_tinyllama/ | Direct report: Mistral-7B vs phi3:mini vs TinyLlama via Ollama on 8GB + Intel i3 — 7B is painful, phi3-mini is the usable sweet spot on that class of box. |
| 9 | https://www.reddit.com/r/LocalLLaMA/comments/14jk108/llamacpp_and_thread_count_optimization_revisited/ | Thread-count-revisited thread: returns diminish (and can regress) past physical cores; hyperthreads rarely help llama.cpp — supports `-t 5` on our 6-core/6-thread chip. |
| 10 | https://docs.tokios.com/guides/llama-cpp-optimization | Vendor tuning guide tying together `--mlock`, KV-cache quant, and batch sizing for memory-constrained llama.cpp. |

Divergence vs the landscape survey's #19813: that thread had **no usable CPU flags**
(closed-source GPU promo). #21136 is the source #19813 pretended to be — an actual
CPU-only recipe. Treat #21136 as the lab's reference, not #19813.

---

## 2. Memory math for every fits-now / fits-with-work verdict

Model RAM = GGUF weights (Q4_K_M) + KV cache at 4k + inference scratch/overhead.
Rough KV at 4k for a 3–4B model ≈ 0.4–0.8 GB at f16, ~half that at q8_0. Scratch ≈
0.2–0.5 GB. "Tool base" = the tool's own process RAM **in addition** to the model.

Post round-1/round-2 verdict set being stresstested:
- fits-now: **ollama**, **llama.cpp** (and round-2-downgraded **llama-swap**→fits-with-work, **litellm**→does-not-fit)
- fits-with-work: **anything-llm**, **open-webui**, **SillyTavern**, **mem0**, **Vane/Perplexica**, **lobehub**, **cascadeflow**, **LLMRouter**

| Tool | Tool base RAM | + model (3–4B Q4_K_M) | Total vs ~5.9 GB usable | Standing math |
|---|---|---|---|---|
| ollama (daemon) | ~0.2–0.4 GB | 2.5–3.5 GB weights + 0.4–0.8 GB KV + scratch | ~3.3–4.7 GB | Fits **one** model with the OS; headroom is thin but real. |
| llama.cpp (llama-server) | ~0.1–0.3 GB | same model math | ~3.1–4.6 GB | Leanest runtime; most headroom of the three. |
| llama-swap | ~0.05 GB (Go proxy) + it spawns llama-server | proxy + 1 server's model | ~3.2–4.7 GB | Negligible proxy cost, but only ever one model resident on this box. |
| anything-llm | ~0.4–0.8 GB (Node + LanceDB in-proc) + embeddings model | +0.1–0.3 GB embedder + chat model via Ollama | **5–6+ GB combined** | RAG stack + chat model together brush the ceiling. |
| open-webui | ~0.5–1.0 GB (Python/Docker) | + chat model via Ollama | **5.5–6.5+ GB** | Docker + Python on-box is the heaviest UI; over budget with a model. |
| SillyTavern | ~0.2–0.4 GB (Node) | + chat model via Ollama | ~4–5 GB | Frontend itself is light; the model dominates. |
| mem0 | ~0.3–0.5 GB + **vector DB (Qdrant ~0.3–0.6 GB)** + embedder | + chat model | **5.5–6.5+ GB** | Memory layer is light, but Qdrant + embedder + chat model stack up. |
| Vane (ex-Perplexica) | ~0.4–0.8 GB + **SearXNG (~0.3 GB)** | + chat model | **5.5–6.5+ GB** | Two extra services before the model even loads. |
| lobehub | ~0.5–1.0 GB (Node web app) | + chat model | **5.5–6.5+ GB** | Heavy web app; same class as open-webui. |
| cascadeflow | ~0.2–0.4 GB (Python lib) | needs TWO model tiers to cascade | **model + bigger model = over budget** | "Escalate to heavier model" has no room; the heavy tier can't co-reside. |
| LLMRouter | ~0.2–0.4 GB + trained classifier | + model(s) it routes among | model-dependent | Router is light; value needs several models it can't hold at once. |

---

## 3. What breaks first — three pressure scenarios

**(A) Two concurrent calls.** On CPU, two inferences share 6 cores and, worse, share
memory bandwidth (the real bottleneck per source #5/#9) — so both calls slow to well
under half-speed, not parallel. If served via Ollama with `OLLAMA_NUM_PARALLEL>1` or
llama-server with `-np 2`, the **KV cache doubles** (one pool per slot), pushing a
4k×2 setup 0.4–0.8 GB over budget → swap. **First to break: KV cache RAM**, then token
rate collapses from bandwidth contention. Mitigation already in the tuning block:
`-np 1` / `OLLAMA_NUM_PARALLEL=1` — the box is single-user by physics.

**(B) Swap pressure.** The model is mmap'd; when RAM is tight macOS evicts model pages
to disk, and the next token fault re-reads them → multi-second stalls or effective
hangs. Source #21136's core insight applies: keep the model **pinned** (`--mlock`) and
starve nothing else into swap. **First to break: any tool stacked on top of the model**
(open-webui, mem0+Qdrant, Vane+SearXNG) — their RSS is what tips total over 5.9 GB and
triggers eviction of model pages. `--mlock` protects the model but then the *stacked
tool* gets OOM-killed instead. Either way the on-box combo loses.

**(C) Disk pressure.** `docs/MODEL-FIT.md` notes only ~30 GB free (30 GB already used).
Swap file growth competes with model storage; pulling a second model or a Docker image
(open-webui) can exhaust disk, and a full disk makes swap unable to grow → hard OOM /
kernel kills. **First to break: the Docker-based UIs and anything that pulls a second
model tier** (cascadeflow's heavy tier, a second Ollama model). Caddy + sidecar + logs
also write here; a runaway log under load competes too.

---

## 4. Revised verdicts after stresstest (no mercy)

| Tool | Round-1/2 verdict | After stresstest | Reason |
|---|---|---|---|
| ollama | fits-now | **fits-now (hold)** | Survives: one model + OS inside headroom with `OLLAMA_NUM_PARALLEL=1`. The baseline. |
| llama.cpp | fits-now | **fits-now (hold)** | Leanest; most headroom; `--mlock` + ≤4k ctx survive all three pressures. |
| llama-swap | fits-with-work (r2) | **fits-with-work (hold)** | Proxy cost negligible; still only one resident model, so no new break — but no new benefit on-box either. |
| litellm | does-not-fit (r2) | **does-not-fit (hold)** | Unchanged; redundant hop. |
| SillyTavern | fits-with-work | **fits-with-work (hold, off-box)** | Only survives if hosted on another tailnet device pointing at the Mini. On-box with a model it's borderline. |
| anything-llm | fits-with-work | **DOWNGRADE → does-not-fit on-box** | RAG stack + embedder + chat model brush/breach 5.9 GB; breaks under scenario B. OK only off-box. |
| open-webui | fits-with-work | **DOWNGRADE → does-not-fit on-box** | Docker+Python over budget with a model; worst under B and C. Off-box only. |
| mem0 | fits-with-work | **DOWNGRADE → does-not-fit on-box** | Qdrant + embedder + model exceed budget; breaks under B. Off-box only. |
| Vane (Perplexica) | fits-with-work | **DOWNGRADE → does-not-fit on-box** | SearXNG + app + model exceed budget. Off-box only. |
| lobehub | fits-with-work | **DOWNGRADE → does-not-fit on-box** | Heavy web app class; same as open-webui. Off-box only. |
| cascadeflow | fits-with-work | **DOWNGRADE → does-not-fit** | Cascade needs a heavy tier that cannot co-reside with the small tier on 8 GB; its core premise breaks under A/B. |
| LLMRouter | fits-with-work | **fits-with-work (hold, caveated)** | Router process is light and survives; but it can only route among models it swaps one-at-a-time, so value is deferred until there are several small specialists worth switching between. |

Key reframing: several round-1 "fits-with-work" calls were really **"fits-with-work on a
different machine."** On *this* box, on-box, they do not fit. The honest split is:
**runtime + proxy/router layer fits on-box; every UI/RAG/memory stack belongs off-box**,
pointed at the Mini over the tailnet. That is the correction the stresstest forces.
