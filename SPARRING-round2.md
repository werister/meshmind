# SPARRING — Round 2: defend/downgrade, reconcile, CPU tuning

Captured 2026-10-27 in worktree `wt-lab-research` (branch `research/assist`).
Evidence: `agent-reach` github/web reads (read-only). No merges.

Lab box: 2018 Intel Mac mini, i5-8500B (6 cores / 6 threads, AVX2+FMA, no AVX-512),
8 GB RAM (~5.9 GB usable), CPU-only Ollama 0.32.1, 4k typical context, no 8B+.
Existing: Caddy reverse proxy + feedback sidecar (metering) + weekly evals.

---

## 1. Defend or downgrade the two weakest fits-now verdicts

### Challenge A — mostlygeek/llama-swap vs Ollama's own keep_alive

What Ollama already does on our single-daemon box: it loads a model on first
request, keeps it resident for `OLLAMA_KEEP_ALIVE` (default 5m), unloads on expiry,
and can hold several models at once (`OLLAMA_MAX_LOADED_MODELS`, default 3×GPU — here
CPU, so effectively capped by RAM). So on-demand load/unload is **not** a gap.

What llama-swap actually adds: it is a swap proxy in front of **llama.cpp / vLLM
servers**, letting you expose many model *configs* (each with its own flags) on one
OpenAI endpoint and hot-swap the running `llama-server` process per request. Its value
is per-model **flag control** (different `-c`, `-np`, `-ctk/-ctv`, `--cache-reuse` per
model) and running raw `llama-server` — things Ollama hides behind Modelfile params.

Mini-specific test: is there a case where we need per-model llama.cpp flags that
Ollama can't express? Ollama already exposes `num_ctx`, `num_thread`, `num_batch`,
`OLLAMA_KV_CACHE_TYPE`, `OLLAMA_FLASH_ATTENTION` — covering the knobs that matter on
8 GB CPU. The only thing it can't do is per-model `--cache-reuse N` and per-model slot
counts. On a box that runs **one model at a time** for latency reasons, swapping
between many pre-configured servers is a solution to a problem we don't have.

**Verdict: DOWNGRADE fits-now → fits-with-work (low priority).** llama-swap is only
worth it if/when we deliberately run raw `llama-server` instead of Ollama to get
`--cache-reuse` and tuned slots. On today's Ollama-based stack it is redundant with
keep_alive. Concrete trigger to revisit: if we move the serving layer off Ollama to
llama-server for cache-reuse, llama-swap becomes the natural multi-config front door.

### Challenge B — BerriAI/litellm vs Caddy + sidecar (free local calls)

What the existing stack already does: Caddy reverse-proxies the tailnet endpoint;
the feedback sidecar meters usage (token totals, per-agent feedback). Local calls cost
$0, so "budget enforcement" and "cost tracking" — litellm's headline features — buy us
nothing on a free box. Load balancing across devices? We have one inference box.
Failover? One box. Rate limiting we can do at Caddy. So the obvious pitch is hollow here.

Is there any Mini-specific use case? Two candidates, both weak: (a) a uniform
OpenAI-compatible schema across future providers — but Ollama already serves
`/v1/chat/completions`, so Caddy already fronts an OpenAI-shaped API. (b) client-side
routing we'd otherwise hand-roll — but the lab's routing is already model-name-per-
request (AGENTS.md: "Every request names its model"), i.e. client-side by design, and
litellm's router would add a hop and a second metering truth to reconcile against the
sidecar.

**Verdict: DOWNGRADE fits-now → does-not-fit (today).** litellm solves multi-provider,
multi-node, paid-token problems the lab does not have; on a single free CPU box it is
a redundant hop that duplicates Caddy (proxy) and the sidecar (metering). Revisit only
if the lab adds paid cloud fallback or a second inference node — then litellm's gateway
earns its hop.

---

## 2. Reconciliation with the landscape survey (main:docs/RESEARCH-landscape-2026-10-27.md)

The two documents barely overlap by design: my round-1 map judged the **pasted master
list** (23 named tools), while your survey scanned the **live landscape** (engines,
orgs, hardware). The useful divergences are below.

| Topic | My round-1 map | Your survey | Who is right / reconciliation |
|---|---|---|---|
| **discussion #19813** | not covered | "REQUIRED READING… comments may hold CPU flags and serving tricks" | **Me, after reading it.** It is a closed-source commercial promo ("Source Code: Still Private"); no shareable flags. All benches are GPU (RTX 5050) or an i7-6500U **iGPU**, none CPU-only desktop. The only concrete tuning is one reply (RevolutionAI) with NUMA + CPU-governor + batch-sweep — Linux/dual-socket, mostly N/A to a single-socket macOS Mini. Downgrade it from "required reading" to "skim the one reply." |
| **incoai/splash** | missed | "try — MacBook, validates UD quants; not for Intel Mini" | **You.** Legit, Apple-silicon (M3+/Metal) only, so correctly not-for-Mini. I didn't surface it because it wasn't on the pasted list. Adopt your verdict. |
| **statefullm/lim** | missed | "Mini experiment — CPU build, never-discarded KV-cache" | **You, with a caveat I add.** Real and Mini-relevant (CPU `make GGML_CUDA=off`). But "NEVER-discarded KV cache, O(input)/turn" is exactly the RAM risk the Mini can't absorb at long context — it fits the *persistent agent* idea but will hit the 5.9 GB wall fast. Keep as experiment, flag the memory ceiling. |
| **intel/ipex-llm** | missed | "SKIP — archived, Intel ended support, security issues" | **You, fully.** I never raised Intel's XPU stack; you correctly killed it. Reinforces: no Intel-accel shortcut for this box, stay on generic CPU llama.cpp/Ollama. |
| **TensorSharp** | missed | "watch — .NET GGUF engine, managed C# CPU kernels, recheck in 6 mo" | **You.** Plausible alt runtime; immature vs Ollama. Correctly "watch," not adopt. |
| **vLLM / SGLang / LMCache** | does-not-fit (GPU/throughput) | not individually mapped (big-iron crowd in "watch") | **Agreement.** Your survey's "opposite scale, steal bench methodology only" is the same conclusion by another route. |
| **exllamav2 / AutoAWQ / unsloth** | does-not-fit (CUDA) | not covered (but B70/IPEX notes imply GPU-only accel) | **Agreement**, consistent with your "CPU-only, no GPU shortcut" throughline. |
| **Ollama as base** | fits-now (the runtime) | "stay on Ollama, endorsed everywhere incl. B70 guides + Starmorph" | **Agreement**, independently corroborated. Strongest shared signal. |
| **llama.cpp as foundation** | fits-now | "98.6k stars, the foundation, Q4_K_M practical quant" | **Agreement**; your Q4_K_M detail sharpens my generic "GGUF server." |

Net: no hard contradiction on tool verdicts; the one factual correction flows **from me
to the survey** — #19813 is not a flag mine. Everything Mini-specific you added (splash,
lim, ipex-llm-dead, TensorSharp) is correct and extends my list rather than conflicting.

---

## 3. llama.cpp CPU tuning for i5-8500B (AVX2+FMA, 6 cores/6 threads, 8 GB)

All flags verified in `tools/server/README.md` (ggml-org/llama.cpp, master, 2026-10-27)
with defaults and env names as quoted. Ollama equivalents verified in docs.ollama.com/faq.
Context: i5-8500B has **6 physical cores, no hyperthreading** (6 threads), AVX2+FMA but
**no AVX-512**. Memory bandwidth (dual-channel DDR4) is the real ceiling on token rate.

### Recommended tuning block (raw llama-server)

```
llama-server \
  -m <model>.Q4_K_M.gguf \
  -t 5 \           # threads for generation: cores-1, leave 1 for OS/Caddy/sidecar
  -tb 6 \          # threads-batch: all 6 for prompt processing (compute-bound)
  -c 4096 \        # context: match lab's 4k norm; do not overspend KV RAM
  -b 2048 -ub 512 \# keep logical batch default; ubatch 512 ok (memory-bound anyway)
  -np 1 \          # ONE slot: single-user box, avoid KV pool ×N blowup
  --cache-reuse 256 \ # reuse cached prefix chunks via KV shifting (needs prompt cache)
  -ctk q8_0 -ctv q8_0 \ # quantize KV cache to halve its RAM vs f16
  -fa on \         # flash attention: lower KV memory growth with context
  --mlock \        # pin weights in RAM: avoid being paged out under pressure
  --no-warmup      # skip warmup alloc spike on a tight RAM budget (optional)
```

### Per-setting effect and risk

| Setting | Verified default | Effect on our box | Risk |
|---|---|---|---|
| `-t 5` | `-1` (auto) | Leaves one core for OS + Caddy + sidecar; prevents generation thread thrash. On 6-thread CPU, `-t = ncores` often ties up the scheduler. | Slightly lower peak tok/s vs `-t 6` in isolation; safer under the lab's always-on sidecars. |
| `-tb 6` | same as `-t` | Prompt/batch phase is compute-bound; using all 6 speeds TTFT. | Momentary full-core saturation during prompt ingest; fine for a single-user box. |
| `-c 4096` | `0` (from model) | Caps KV cache to the lab's real need; a 32k-trained model would otherwise size huge KV. | Truncation on long inputs — acceptable per 4k norm. |
| `-np 1` | `-1` (auto) | KV pool is sized once, not ×slots. Critical: each extra slot multiplies KV RAM. | No concurrency — but 8 GB CPU can't serve concurrent calls at speed anyway (see round 3). |
| `--cache-reuse 256` | `0` (disabled) | Reuses matching prompt prefixes via KV shifting — real win for repeated system prompts (the lab's probes/evals reuse prompts). | Needs prompt caching on; only helps when prefixes actually repeat; tiny CPU cost to match chunks. |
| `-ctk/-ctv q8_0` | `f16` | ~halves KV-cache RAM; buys context headroom on 8 GB. | Minor quality/precision loss; q8_0 is conservative (q4_0 would be riskier). |
| `-fa on` | `auto` | Flash attention curbs KV memory growth as context grows; auto usually picks it but forcing avoids a bad auto-pick on CPU. | On some CPU builds FA is slower than non-FA; benchmark both — risk is speed, not correctness. |
| `--mlock` | off | Pins weights so the kernel can't page them out when RAM is tight — avoids catastrophic swap mid-inference. | Reserves physical RAM hard; on 8 GB a too-big model + mlock can OOM-kill instead of degrading. Use only when model clearly fits. |
| `--no-mmap` / `-lm none` | `-lm auto` (mmap) | **Do NOT set.** mmap lets the OS page weights from disk — on 8 GB this is what lets a model load at all. | Disabling mmap forces full load into RAM → OOM risk. Keep mmap on. |
| `--numa` | off | **Skip.** Single-socket consumer CPU; NUMA flags target multi-socket Xeons (the #19813 reply's context). | No benefit here; can mis-pin threads. |

### Ollama env equivalents (if staying on Ollama, which the survey endorses)

| Need | Ollama control | Verified source |
|---|---|---|
| threads | `num_thread` (Modelfile/param) | docs.ollama.com/faq |
| context | `num_ctx` (default via `/set parameter num_ctx 4096`) | faq |
| batch | `num_batch` | faq |
| KV quant | `OLLAMA_KV_CACHE_TYPE` (default f16 → set q8_0) | faq |
| flash attn | `OLLAMA_FLASH_ATTENTION` (auto; can force) | faq |
| keep model resident | `OLLAMA_KEEP_ALIVE` | faq |
| concurrency cap | `OLLAMA_NUM_PARALLEL` (default 1 — leave at 1; RAM scales ×N) | faq |
| loaded models cap | `OLLAMA_MAX_LOADED_MODELS` | faq |

Note: Ollama does **not** expose llama.cpp's `--cache-reuse` prefix-KV-shifting. That
single flag is the main reason to consider running raw `llama-server` (and thus
llama-swap as its front door) for the lab's repeated-prompt eval/probe workloads.

### #19813 techniques — what is actually usable

From the only substantive reply (RevolutionAI): NUMA interleave (N/A, single socket),
CPU-governor `performance` (Linux sysfs; on macOS no equivalent — the Mini runs a fixed
governor), and **batch sweep `-b 1 / -b 8 / -b 32`** (usable: worth micro-benchmarking
ubatch on our memory-bound CPU). The original post contributes no flags.
