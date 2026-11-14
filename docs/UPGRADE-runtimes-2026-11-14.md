# Mini runtime upgrades — primary-source deep dive

Box: 2018 Mac Mini, Intel i5-8500B (6 cores, up to 4.10 GHz, 65 W, 14 nm —
https://www.intel.com/content/www/us/en/products/compare.html?productIds=/134892),
8 GB RAM (~5.9 usable), CPU-only, macOS 15.8.1, Ollama 0.40.16, serial load, 4k context cap.
Thread count: 6 (no Hyper-Threading on this SKU) [inference — verify with
`sysctl hw.physicalcpu hw.logicalcpu`].

How to read: every factual claim carries its exact primary-source URL
(official docs, upstream source, paper, or the named benchmark page).
Anything tagged **[inference]** is my extrapolation, not a sourced fact.
"No lab calls" applied — all "How to test" blocks are proposed commands, none executed.

Foundational fact for the whole document: on current Ollama main,
**all GGUF models are served via an upstream `llama-server` subprocess**
(https://raw.githubusercontent.com/ollama/ollama/main/llm/server.go —
`NewLlamaServer`: "All GGUF models are served via the upstream llama-server
subprocess"). The wrapper builds a minimal flag set and lets llama-server
auto-detect the rest
(https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go,
file header: "llama-server auto-detects GPU layers (-ngl), thread count (-t),
and flash attention (--flash-attn)"). So "Ollama vs llama.cpp" on this box is
"llama-server with Ollama-chosen flags + Go HTTP/scheduler layer" vs
"llama-server with hand-chosen flags". Keep that in mind for §1.

---

## 1. llama.cpp direct vs Ollama

### Mechanism
Ollama spawns `llama-server --model … --port … --host 127.0.0.1 --no-webui
--offline -c NumCtx*numParallel -np numParallel …` plus optional
`--cache-type-k/v`, `--flash-attn …`, `-t`, `-ngl`, `--keep`
(https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go,
"Build CLI flags" block). Two chat paths exist: models with Ollama
renderers/Go TEMPLATE go through `/completion` with Go-side rendering; other
GGUF chat models go through llama-server's own `/v1/chat/completions`
(same file, header comment). Wrapper overhead is therefore one extra HTTP
hop, JSON translation, and scheduler bookkeeping on top of the same engine.

### What the Qiita numbers actually say (and don't say)
- **xfgftt (the "10s → 26–30" claim)**:
  https://qiita.com/xfgftt/items/8d85a59f545ea0692db3.
  Same box (Windows, 2× RX 9060 XT), same file
  (`unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL`): Ollama **12.89 tok/s**,
  llama.cpp Vulkan **8.96 tok/s max (with MTP)**, llama.cpp ROCm/HIP
  **28.68 tok/s** (second run 29.25). The author states 28–29 is not stable
  and varies with MTP draft acceptance, and that the benchmark method changed
  mid-investigation. **The delta is a GPU-backend change (whatever Ollama
  used → ROCm/HIP build) plus speculative decoding, not wrapper removal —
  llama.cpp on Vulkan was *slower* than Ollama.** Nothing here transfers to a
  CPU-only Intel Mac [inference].
- **kenimo49 (same-GGUF, same-backend-class)**:
  https://qiita.com/kenimo49/items/6c72194d6602ca345d88.
  RTX 4070 12 GB, identical `.gguf`, ctx 4096, 10 runs median, Ollama 0.5.x
  left at defaults. 7B Q4_K_M (fits VRAM): llama.cpp **82** vs Ollama **76**
  tok/s (**~7%**), prompt-eval 2900 vs 2100 tok/s, load 3.1 s vs 4.8 s.
  14B Q4_K_M (VRAM-tight): llama.cpp **41** vs Ollama **22** tok/s —
  diagnosed as **KV cache spilling to CPU RAM under Ollama's default
  allocation**, and `OLLAMA_KV_CACHE_TYPE=q8_0` alone recovered Ollama to
  **22 → 35 tok/s**. Author's conclusion: "Ollama is not slow; running a
  VRAM-marginal model on defaults is slow."
- Takeaway for the Mini: the only same-backend wrapper-overhead number is
  **~7% on GPU**; the ~2× numbers are memory-fit/defaults artifacts, fixable
  by flags [inference from the two pages above].

### Expected gain on THIS box
~0–7% single-stream decode [inference: same engine, CPU backend has no
offload-placement cliff like the 14B/VRAM case; the Go-hop cost should be
proportionately similar or smaller than kenimo49's 7%]. The realistic prize
is not speed but **flag access** (batch/ubatch/threads/slots/cache types)
where Ollama exposes no knob [inference].

### OpenAI-compat gaps (both sides are subsets)
- Ollama: "Ollama supports a subset of the OpenAI API"
  (https://docs.ollama.com/api/openai-compatibility). Local `/v1` supports
  chat/completions, responses (**non-stateful only**: no
  `previous_response_id`/`conversation`), vision, audio with quirks
  (default `wav` not `mp3`, unsupported values 400 instead of ignored).
  Ollama extension: `/v1/chat/completions` accepts **`keep_alive`**
  ("without it an OpenAI-API client cannot release a model",
  https://raw.githubusercontent.com/ollama/ollama/main/openai/openai.go,
  `ChatCompletionRequest.KeepAlive`, passed through to the chat request).
  Ollama also surfaces `usage.prompt_tokens_details.cached_tokens` (same file,
  `Usage` struct).
- llama-server: "OpenAI API compatible chat completions, responses, and
  embeddings routes" is a listed feature, but for both `/v1/completions` and
  `/v1/chat/completions` the doc says **"no strong claims of compatibility
  with OpenAI API spec … in our experience it suffices to support many apps"**
  (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md).
  Chat completions needs a supported chat template (same page).
- Gap list between the two subsets is **not documented anywhere; it must be
  diff-tested per caller** [inference]. Known semantic deltas: model
  addressing (registry `name:tag` + auto-pull vs one resident model),
  `keep_alive` (Ollama extension; llama-server documents **no**
  keep-alive/idle-unload knob in its flag table — model stays resident for
  process lifetime [checked README flag table; confirm with
  `llama-server --help` in lab]).

### Cost / risk — what breaks on migration
1. **Model addressing**: every caller passes Ollama `model:tag` names;
   llama-server serves a single `--model` file. `/v1/models` output shape
   differs; whether a mismatched `model` field errors or is ignored is
   unverified from sources — test it.
2. **`/v1` callers**: envelope/usage-field diffs (Ollama has
   `cached_tokens`; tool-call parsing depends on `--jinja`/template handling
   on the llama-server side — `--jinja` default enabled, same README).
   Diff-test each caller with recorded requests.
3. **`keep_alive` semantics**: Ollama default 5 min idle unload, per-request
   override incl. `0`=unload-now and negative=pinned
   (https://raw.githubusercontent.com/ollama/ollama/main/docs/api.md).
   llama-server has no equivalent lifecycle [per flag table]; idle RAM stays
   pinned and "unload" means process restart [inference]. On a 1-model box
   this is benign, but `keep_alive: 0` calls from automation will silently
   stop doing anything.
4. **Sidecar Caddy Host-rewrite**: **unverifiable here — a content search for
   "caddy" in this checkout returns zero hits** (fresh checkout, lab proxy
   config not present). Generic risks: Ollama listens on 127.0.0.1:11434 by
   default (https://raw.githubusercontent.com/ollama/ollama/main/envconfig/config.go,
   `Host()`), llama-server takes `--host/--port` (same README); any
   Host-header or path-prefix (`/api/*` vs `/v1/*`, `/completion`) rewrite
   rules must be re-mapped. Test with `curl -H 'Host: …'` against both
   before cutover.
5. **Ops**: lose `ollama ps`/multi-model scheduler/auto-update; gain manual
   builds, manual GGUF fetch (or `-hf` download flags), manual restarts.

### Fit verdict
**Don't migrate for speed.** Expected single-stream gain ≈ 0 on CPU
[inference]; migration cost is a rewrite of model addressing, lifecycle
handling, proxy rules, and ops. Revisit only if a needed llama-server flag
(batch/ubatch/slots/templates) has no Ollama equivalent.

### How to test
1. `brew install llama.cpp` (or build); serve the **same GGUF bytes** Ollama
   uses (`~/.ollama/models/blobs/…`, resolve via `ollama show --modelfile`).
2. Match flags to Ollama's launch line (copy from server log,
   `slog.Info("starting llama-server", "cmd", cmd)` —
   https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go;
   log viewing per https://docs.ollama.com/troubleshooting.md): same
   `-c`, `-np 1`, same `--cache-type-k/v`, same `-t`.
3. Fixed prompt, `stream:false`, N≥10: compare `eval_count/eval_duration`
   (Ollama) vs llama-server `timings`. Then A/B one flag at a time.
4. Caller diff-test: replay recorded `/v1` requests at both, `diff` normalized
   JSON (status, `choices`, `usage`, error shapes); include a wrong-`model`
   request and a `keep_alive` request.

---

## 2. Exact Ollama CPU env flags on 0.40.x

Primary: https://raw.githubusercontent.com/ollama/ollama/main/envconfig/config.go
(all defaults below are from this file on main; 0.40.x confirmed by the
v0.40.15-sourced third-party table matching these defaults — treat minor
drift as possible, verify with `ollama --version` + server log),
scheduler default https://raw.githubusercontent.com/ollama/ollama/main/server/sched.go
(`defaultModelsPerGPU = 3`), behavior text https://docs.ollama.com/faq.
macOS note: app-launched Ollama takes env via `launchctl setenv` + app
restart (FAQ, "Setting environment variables on Mac").

| Flag | Default (source) | Safe Mini value | Why |
|---|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `0` → scheduler auto: **3 × GPUs, or 3 on CPU** (`MaxRunners`, `defaultModelsPerGPU`, FAQ) | **`1`** | Serial load, 8 GB. Prevents a second model ever pinning RAM alongside the first [inference]. |
| `OLLAMA_KV_CACHE_TYPE` | unset → **`f16`** (`KvCacheType`, AsMap desc "default: f16"; llama-server `-ctk/-ctv` default `f16`, https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md) | **`q8_0`, test-gated** | FAQ: q8_0 ≈ ½ the KV RAM, "very small loss … usually no noticeable impact … (recommended if not using f16)". Gate: FAQ says KV quant applies **"when Flash Attention is enabled"** — FA-on-CPU resolution is unverified (see below). |
| `OLLAMA_FLASH_ATTENTION` | unset → **auto** ("Ollama uses Flash Attention automatically when the selected backend and devices support it", FAQ; code: user-set → on/off, else `Auto` if `FlashAttentionSupported(gpus)`, `llama_server.go`) | **leave unset; A/B `1` vs `0`** | Whether `FlashAttentionSupported([])` (CPU-only, empty GPU list) is true is **not determinable from fetched sources** — must test. Forcing `1` on an unsupported backend risks slowdown or load failure [inference]. |
| `OLLAMA_NUM_PARALLEL` | **`1`** (`NumParallel = Uint(…, 1)`) | **`1`** | FAQ: each model's context is multiplied (`-c NumCtx*numParallel`, `-np` in `llama_server.go`); "Required RAM will scale by `OLLAMA_NUM_PARALLEL` × `OLLAMA_CONTEXT_LENGTH`" (FAQ). Serial load gains nothing from >1 (§7). |
| `OLLAMA_KEEP_ALIVE` | **`5m`** (`KeepAlive()`; per-request `keep_alive` overrides env, FAQ) | **`-1` (or `24h`)** | Single-model serial judge: pin the model + warm prefix cache (§6). Cost is pinned RAM you were going to use anyway [inference]. Negative = infinite (`math.MaxInt64`, `KeepAlive()`); `0` = unload immediately. |
| `OLLAMA_NOHISTORY` | unset/false | leave alone | "Do not preserve readline history" (`NoHistory`) — **no inference/perf effect**. |

Also relevant, same sources:
- `OLLAMA_CONTEXT_LENGTH` (default `0` → "4k/32k/256k based on VRAM", AsMap;
  FAQ: "By default, Ollama uses a context window size of 4096 tokens").
  CPU-only Mini should land on 4k [inference] — matches the stated 4k cap.
  Doc discrepancy flagged: Modelfile reference says num_ctx "Default: 2048"
  (https://raw.githubusercontent.com/ollama/ollama/main/docs/modelfile.mdx)
  while the FAQ says 4096. Resolve empirically via `/api/show` +
  `options.num_ctx` echo.
- `OLLAMA_NUM_PARALLEL`/`OLLAMA_MAX_QUEUE`(512)/`OLLAMA_CONTEXT_LENGTH` are
  the only memory-scaling knobs; `OLLAMA_DEBUG=1` + `OLLAMA_DEBUG_LOG_REQUESTS`
  exist for diagnosis (AsMap).

### Expected gain on THIS box
`KEEP_ALIVE=-1` + `MAX_LOADED=1`: eliminates reloads (~seconds each on CPU)
and eviction churn — the biggest free win if the judge currently idles past
5 min [inference]. `q8_0`: up to ~½ KV RAM IF it engages on CPU (test-gated).

### Cost / risk
Near zero. All are env flips, reversible by unsetting. Only `FLASH_ATTENTION=1`
forces behavior the auto path might reject — hence A/B rather than set-and-forget.

### Fit verdict
**Do this first** (with §6). Minutes of effort, no rebuild, no migration.

### How to test
1. `launchctl setenv OLLAMA_KEEP_ALIVE -1` (etc.), restart Ollama app, confirm
   in server log (`troubleshooting.md`) that the `starting llama-server` line
   shows expected `-c/-np/--cache-type-k/v/--flash-attn/-t`.
2. Idle 6+ min, re-request: `load_duration` should be ~0 (still resident).
3. FA matrix: `OLLAMA_FLASH_ATTENTION` unset vs `1` vs `0` × `OLLAMA_KV_CACHE_TYPE`
   unset vs `q8_0`: fixed prompt ×10, record tok/s + RSS + any load error in logs.
   If `q8_0`+auto shows no RAM drop vs f16, KV quant is not engaging — escalate
   to explicit FA=1 or abandon (§3).

---

## 3. KV-cache quant q8_0 vs q4_0

### Mechanism
KV cache holds per-token keys+values for the live context; its bytes scale
with context length × layers × heads × precision. llama-server exposes
`-ctk/--cache-type-k` and `-ctv/--cache-type-v` (common params, so every
llama.cpp tool including `llama-perplexity` accepts them) with allowed values
`f32, f16, bf16, f8_e4m3, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1`, default `f16`
(https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md).
Ollama maps one env var to both: `--cache-type-k X --cache-type-v X`, only
when `OLLAMA_KV_CACHE_TYPE` is non-empty
(https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go).
Asymmetric K/V is not exposable via Ollama [inference from the mapping code].

### Quality evidence (primary only)
- Ollama FAQ (https://docs.ollama.com/faq): `f16` "high precision and
  memory usage (default)"; **`q8_0`** "8-bit quantization, uses approximately
  1/2 the memory of `f16` with a very small loss in precision, this usually
  has no noticeable impact on the model's quality (**recommended** if not
  using f16)"; **`q4_0`** "4-bit quantization, uses approximately 1/4 the
  memory of `f16` with a small-medium loss in precision that **may be more
  noticeable at higher context sizes**". Quantization of the KV cache is
  described as applying "when Flash Attention is enabled".
- llama.cpp in-repo numbers are **weight** quants, not KV-cache quants — do
  not conflate. For orientation only: Llama-3-8B PPL Δ vs FP16 is +0.0027 for
  Q8_0 weights vs +0.469 for Q4_0 weights
  (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/perplexity/README.md,
  scoreboard). No KV-cache PPL table ships upstream.
- Independent datapoint (secondary, GPU, cited for direction only):
  kenimo49's 14B run recovered 22→35 tok/s on `q8_0` with quality impact
  "within error" (https://qiita.com/kenimo49/items/6c72194d6602ca345d88).

### Expected gain on THIS box
At 4k ctx with small (3–4B) models the KV cache is small in absolute terms
(tens to low-hundreds of MB at f16 — [inference]; exact: 2 × layers ×
kv_heads × head_dim × 4096 × 2 B from `/api/show` template/parameters).
Halving (q8_0) or quartering (q4_0) it therefore buys **RAM headroom, not
speed** [inference]. Its value is enabling a larger model/ctx within 8 GB,
or (per kenimo49's mechanism) avoiding swap/spill cliffs — on CPU-only RAM
the cliff is macOS swap, which is catastrophic for tok/s [inference].
Speed effect of KV quant on CPU proper: likely ±noise [inference — test].

### Cost / risk
- q8_0: vendor-recommended, "usually no noticeable impact" (FAQ). Low risk.
- q4_0: "small-medium loss … more noticeable at higher context" (FAQ). At 4k
  (not high) it may be fine, but judge quality is the product — gate on task
  eval, not vibes.
- Engagement risk (CPU-only): if FA resolves off and KV quant requires FA
  (FAQ wording), the flag may silently do nothing or error — verify, don't
  assume (§2 test matrix).

### Fit verdict
**q8_0: yes, test-gated on engagement. q4_0: only if headroom is still short
after q8_0, and only behind a quality eval.**

### How to test (incl. "what is currently applied")
1. **Currently applied**: read the Ollama server log line
   `starting llama-server "cmd" …` (emitted at Info —
   https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go).
   If `--cache-type-k/v` are absent, the llama-server default `f16` applies
   (server README). No `ollama ps`/API field exposes this [inference from
   fetched API docs].
2. **RAM effect**: same model+ctx, f16 vs q8_0 vs q4_0 → peak RSS
   (`/usr/bin/time -l` or Activity Monitor), `load_duration`, fixed-prompt
   tok/s ×10.
3. **Quality effect**: `llama-perplexity -m <same gguf> -f wikitext-2-test
   --kl-divergence-base … --kl-divergence -ctk {f16,q8_0,q4_0} -ctv …`
   (methodology + Wikitext-2 convention:
   https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/perplexity/README.md;
   `-ctk/-ctv` are common params, server README). Compare ΔPPL/KLD/mean-Δp.
   Then confirm on the judge's own task prompts (PPL ≠ task quality — the
   perplexity README itself warns PPL is for quant-vs-FP16 comparison).
4. FA interaction: repeat (2) with `OLLAMA_FLASH_ATTENTION` unset/`1`/`0`;
   check logs for FA/KV warnings.

---

## 4. Atomic Chat TurboQuant serving layer vs stock Ollama

### Mechanism
TurboQuant (Google Research, ICLR 2026): online vector quantization of the
**KV cache** — random rotation (PolarQuant) + per-coordinate scalar quantizer
+ 1-bit QJL residual correction; paper reports absolute quality neutrality
at 3.5 bits/channel, marginal degradation at 2.5
(https://arxiv.org/abs/2504.19874). Google's blog claims 16→~3 bits, ≥6× KV
memory cut, and up to 8× attention-logit speedup **on H100 GPUs**
(https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/).
Atomic Chat productizes this as a `llama.cpp` fork,
`atomic-llama-cpp-turboquant` (`turbo3`/`turbo4`), on macOS/Windows/Linux,
CPU and GPU (CUDA/Vulkan)
(https://raw.githubusercontent.com/AtomicBot-ai/Atomic-Chat/main/README.md,
engines table). Serving surface: **OpenAI-compatible server at
`http://localhost:1337/v1`**, loopback by default, "drop-in replacement for
the OpenAI SDK"; headless option is `atomic-chat-core serve …` (same README).
It is otherwise a Tauri desktop app (Node ≥ 20 badge, same README).

### The "8GB-for-3B" claim, precisely
README system requirements (same URL): "**macOS**: 13.6+ (**8GB RAM for 3B
models**, 16GB for 7B, 32GB for 13B)" — Intel and Apple Silicon both
supported ("Available on macOS 13.6+ (Intel and Apple Silicon)",
https://atomic.chat/turboquant). Companion guide: 8 GB total RAM →
3–4B models at Q4 (~2–3.5 GB quantized), Qwen 3.5 4B ≈ 3.4 GB recommended
(https://atomic.chat/blog/guides/best-local-llm-8gb). So the claim is a
**sizing guideline**, not a TurboQuant benchmark [inference].

### Discrepancy to note
Atomic's README claims "**up to ~4.3×** smaller KV cache footprint" for the
shipped fork, while https://atomic.chat/turboquant markets "**6×**" (the
paper's number) and "128k context using 6x less RAM". Implementation (4.3×)
vs paper (6×) — believe the README for capacity planning [inference].
Marketing FAQ also says speed stays "the same or slightly faster" and quality
is unchanged (same page) — vendor claims, no shipped numbers.

### Expected gain on THIS box
Small in absolute terms [inference]: at 4k ctx with small models the KV
cache is already the minor term (weights dominate); 4× of a small number is
a small number. No CPU tok/s win is evidenced (the paper's 8× is H100
attention kernels; Atomic claims parity-to-slightly-faster). The product's
value centers on **long-context** sessions ("chat 6× longer", "100k tokens",
same page) — the opposite of this 4k serial-judge workload.

### Cost / risk
- **Install/shape cost**: desktop Tauri app + model management inside the
  app ("Load a model in the app, then point any client at it", README) on a
  headless Mini; or the `atomic-chat-core` CLI path (documented in one line,
  same README — depth of headless support unverified).
- **Compat**: only the OpenAI surface (`:1337/v1`) — no `/api/*`, no
  `keep_alive`, Ollama model names, or `Modelfile` semantics; port change
  11434→1337; model ids are Atomic's catalog ids. Every caller + the Caddy
  sidecar needs re-pointing [inference].
- **Fork drift**: a llama.cpp fork lags upstream by construction; "MTP …
  Available on macOS and Windows", "DFlash … Apple Silicon only" (README)
  show feature availability is already platform-gated. Intel-mac CPU is the
  least-loved tier in 2026 [inference].
- **Eval burden**: KV compression at 3–4 bits needs the same quality proof as
  §3's q4_0, with less documentation.

### Fit verdict
**No fit for this box/workload.** Sizing guidance matches what Ollama already
does (3–4B at Q4 in 8 GB); the KV win is immaterial at 4k; the serving
surface is thinner than Ollama's; fork + app-shape costs are real.

### How to test (if revisited)
1. Install `atomic-chat-core` CLI (per README) on a non-prod machine; load
   the same GGUF bytes; serve `:1337`.
2. Same fixed prompts ×10 vs Ollama: tok/s, peak RSS, and judge-task quality;
   sweep ctx 4k→32k to find where (if ever) the KV win matters.
3. Failure-mode checks: model-id addressing from a stock `openai` client,
   restart/resident behavior, and what happens on client disconnect mid-stream.

---

## 5. imatrix I-quants pipeline

### Mechanism (primary: llama.cpp docs)
1. `llama-imatrix -m <fp-model.gguf> -f <calibration.txt> [-o imatrix.gguf]`
   computes per-tensor importance over calibration chunks (default output
   `imatrix.gguf`; `--no-ppl` skips per-chunk PPL; `-ngl` offloads to GPU)
   (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/imatrix/README.md,
   based on https://github.com/ggml-org/llama.cpp/pull/4861).
2. `llama-quantize --imatrix imatrix.gguf <src> <dst> <I-quant>`
   (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/quantize/README.md).
   `--allow-requantize` from an already-quantized file "can severely reduce
   quality" — quantize from F32/BF16 (same page).
3. **Ollama cannot produce imatrix files** — the tool is `llama-imatrix`, a
   llama.cpp binary [inference from the README's CLI-only interface]; the
   handoff back into Ollama is `FROM ./model.gguf` in a Modelfile
   ("Build from a GGUF model", absolute or Modelfile-relative path,
   https://raw.githubusercontent.com/ollama/ollama/main/docs/modelfile.mdx).
   ("llama-server-only emit" in the task brief reads as this: imatrix
   emission lives outside Ollama entirely.)
4. I-quants vs imatrix: the tool frontend does not hard-error without
   `--imatrix` (checked
   https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/quantize/quantize.cpp,
   `prepare_imatrix` path), but upstream publishes **all** IQ numbers with an
   imatrix (`WT 10m` rows) while K-quants carry both with/without rows
   (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/perplexity/README.md).
   Treat imatrix as **required in practice for IQ types** [inference].

### Quality/size evidence (Llama-3-8B scoreboard, same perplexity README)
`q8_0`: 7.96 GiB, ΔPPL +0.0027 · `q4_K_M`: 4.58 GiB, +0.175 (None) / +0.152
(WT 10m) · `iq4_XS`: 4.14 GiB-class, +0.228 (WT 10m) · `q4_0`: 4.34 GiB,
+0.469 (None). Tool help text agrees (Q4_K_M "4.58G, +0.1754 ppl",
Q8_0 "7.96G, +0.0026", IQ4_XS "4.25 bpw", IQ4_NL "4.50 bpw" —
https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/quantize/quantize.cpp).
Read: imatrix-aware IQ4 sits between Q4_0 and Q4_K_M on PPL at lower bpw —
a **size win at fixed quality**, not a speed win [inference].

### Expected gain on THIS box
A few hundred MB per small model (e.g. IQ4_XS ≈ 4.25 bpw vs Q4_K_M ≈ 4.9 bpw
weights) [inference from bpw + scoreboard sizes]. Matters only if it moves
the working set across a real boundary (avoiding swap, fitting a bigger
model, freeing ctx headroom). No decode-speed gain expected and none claimed
[inference].

### Cost / risk
- **Compute**: `llama-imatrix` over a calibration corpus on 6 CPU cores with
  no `-ngl` is slow (hours-scale for larger models [inference]); one-time per
  model+dataset, but must be re-run per model and ideally per domain.
- **Calibration sensitivity**: wrong/small/domain-mismatched calibration
  data silently biases all downstream quants [inference]; the README's
  knobs (`--chunks`, `--in-file` merging, `--process-output`) exist because
  of this.
- **PPL validation need (real)**: the perplexity README warns PPL is "not
  directly comparable between models" and that the toolchain's own numbers
  are "not directly comparable to those of other projects" (same URL) — so
  validation must be **same-model, same-data, same-binary**: candidate IQ vs
  the current Q4_K_M baseline, ΔPPL + KLD + mean-Δp + same-top-p, then the
  judge's task eval.

### Fit verdict
**Worthwhile iff RAM is still tight after §2+§3.** It's the cheapest quality
per byte available, but it's toil (calibrate → quantize → PPL-gate → import)
for hundreds of MB. Not a speed project.

### How to test
1. `convert_hf_to_gguf.py --outfile base-bf16.gguf --outtype bf16` (quantize
   README), `llama-imatrix -m base-bf16.gguf -f <domain-calibration>.txt`
   (CPU: no `-ngl`; time it), `llama-quantize --imatrix … base-bf16.gguf
   cand-IQ4_XS.gguf IQ4_XS`.
2. PPL-gate: `llama-perplexity` with `--kl-divergence-base` + `--kl-divergence`
   on Wikitext-2 (convention, perplexity README) for baseline Q4_K_M vs
   candidate; require ΔPPL/KLD/mean-Δp within noise, then task-eval.
3. Import: `FROM ./cand-IQ4_XS.gguf` Modelfile → `ollama create`; confirm
   resident RSS drop and unchanged judge scores.

---

## 6. Prompt / prefix caching for repeated system prompts

### Mechanism (primary chain)
- llama-server caches prompts by default: `--cache-prompt … (default:
  enabled)` (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md).
- Ollama's launch flag block passes **no** `--cache-prompt`/`--no-cache-prompt`
  (full block listed in §1,
  https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go),
  so the default (enabled) is inherited **[inference from the two sources]**.
- Therefore: a request whose token prefix exactly matches the still-resident
  cache skips prompt-eval for those tokens; Ollama exposes
  `prompt_eval_cached_count` ("number of prompt tokens read from the cache",
  https://raw.githubusercontent.com/ollama/ollama/main/docs/api.md) and maps it
  to OpenAI `usage.prompt_tokens_details.cached_tokens`
  (https://raw.githubusercontent.com/ollama/ollama/main/openai/openai.go).
- Two prerequisites fall out of the sources: (1) the model must still be
  loaded — default idle unload is 5 min (`KeepAlive()`, envconfig; "By
  default models are kept in memory for 5 minutes", FAQ), so caching
  effectiveness is `keep_alive`-gated; (2) the prefix must match at the
  **token** level, i.e. system prompt + template rendering must be byte-stable
  across calls [inference — cache key is the token sequence].
- **`num_keep` is NOT the caching knob** (common confusion): Ollama default
  `NumKeep: 4` with comment "set a minimal num_keep to avoid issues on
  context shifts" (https://raw.githubusercontent.com/ollama/ollama/main/api/types.go,
  `DefaultOptions()`); it is passed as llama-server `--keep` ("number of
  tokens to keep from the initial prompt", server README) and `n_keep` per
  request, and Ollama's own truncation preserves `num_keep` then frees half
  the window (`contextShiftPromptLimit`, `llama_server.go`). It controls
  **context-shift retention**, not cache size. Raising it does not enlarge any
  cache [inference].
- Advanced (llama-server only): per-slot prompt-cache save/restore/erase
  endpoints (`POST /slots/{id}?action=save|restore|erase`, server README) —
  not surfaced through Ollama [inference].

### Expected gain on THIS box
If the judge repeats a long system prompt per call, prefix hits convert
prompt-processing (CPU-slow; kenimo49 measured Ollama prompt-eval 880–2100
tok/s on GPU — CPU will be far lower [inference]) into a cache lookup.
Serial + pinned (`KEEP_ALIVE=-1`) + stable template = hits on nearly every
call after the first [inference]. This is plausibly the largest latency win
in the document for repeated-prompt workloads [inference].

### Cost / risk
Zero code, zero quality impact — same tokens, skipped recompute [inference].
Risks are operational: any per-call template jitter (timestamps, reordered
fields, nondeterministic tool schemas) silently destroys the prefix match
[inference]; unloading (5-min default) wipes the cache.

### Fit verdict
**Do this together with §2.** Highest gain-per-effort on the list for a
repeated-system-prompt judge [inference].

### How to test
1. Pin the model (`OLLAMA_KEEP_ALIVE=-1`), freeze the template.
2. Send the same system prompt + varying suffix twice; compare
   `prompt_eval_cached_count` (0 → N) and `prompt_eval_duration` across the
   pair (fields documented in `docs/api.md`).
3. Negative control: perturb one early token, confirm cache count collapses —
   proves the metric is really measuring prefix reuse.
4. If hits don't materialize: inspect rendered prompt stability (Ollama
   `show --modelfile`/template, `raw` mode A/B) before touching any runtime.

---

## 7. Parallel slots / throughput-vs-latency on 6-core CPU

### Mechanism
- Ollama: `OLLAMA_NUM_PARALLEL` (default 1) → `-np` slots; total ctx is
  multiplied (`-c NumCtx*numParallel`,
  https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go);
  "Parallel request processing for a given model results in increasing the
  context size by the number of parallel requests… Required RAM will scale by
  `OLLAMA_NUM_PARALLEL` × `OLLAMA_CONTEXT_LENGTH`"
  (https://docs.ollama.com/faq).
- llama-server: `-np/--parallel` "number of server slots (default: -1, -1 =
  auto)" with continuous batching + parallel decoding as headline features
  (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md).
  What `-1` resolves to in slots is **not pinned down from fetched sources**
  (no assignment found in `server-context.cpp`; Ollama always passes an
  explicit `-np`, so auto never applies on the Ollama path) — read it back
  from `/slots` (`total_slots` = `--parallel` value, same README).
- Threads: `-t/--threads` default `-1`; values ≤ 0 resolve to
  `std::thread::hardware_concurrency()` in arg parsing
  (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/common/arg.cpp);
  macOS physical-core detection via `hw.perflevel0.physicalcpu` /
  `hw.physicalcpu` sysctls, math-thread default from physical cores
  (https://raw.githubusercontent.com/ggml-org/llama.cpp/master/common/common.cpp).
  Ollama passes `-t` only when `num_thread > 0`, else auto
  (`llama_server.go`). On this 6C/6T box every auto path converges on **6
  threads** [inference].
- CPU contention reality: 6 threads total, no GPU to absorb batch growth —
  slots share the same 6 cores and the same memory bandwidth [inference].

### Expected gain on THIS box
Workload is stated serial: **np>1 buys nothing and costs latency + RAM**
[inference]. Even under future concurrency, CPU decode is memory-bandwidth
bound; batching two sequences on 6 cores yields sublinear throughput at
higher per-request latency [inference]. (GPU-measured slot scaling, e.g.
kenimo49's vLLM 8-way numbers, does not transfer to CPU [inference].)

### Cost / risk
- RAM: KV pool × slots at fixed ctx (FAQ formula above) — on 8 GB this can
  push into swap, which collapses all slots [inference].
- Latency: each request's tokens now compete for 6 threads; tail latency
  rises [inference].
- Only upside scenario: overlapping prompt-eval of one request with decode of
  another — marginal on CPU [inference].

### Fit verdict
**Keep `OLLAMA_NUM_PARALLEL=1` (and `-np 1` if ever direct).** Revisit only
when genuinely concurrent load exists; then scale by measurement, not by core
count.

### How to test (to confirm 1 is right, or to size future concurrency)
1. Baseline `OLLAMA_NUM_PARALLEL=1`: single-stream tok/s, p50/p99 latency,
   peak RSS (fixed prompt ×10).
2. `=2` and `=4`: fire N concurrent `stream:false` requests (N = slots),
   record per-request latency, aggregate tok/s, peak RSS, and any 503s
   (`OLLAMA_MAX_QUEUE` default 512, envconfig). Expect aggregate ≤ ~1.2–1.5×
   single-stream with ≥2× latency [inference — the test exists to check it].
3. If slots are ever adopted, re-verify §6 prefix hits per slot (each slot
   holds its own cache state [inference from the slot model in
   `server-context.cpp`]).

---

## Ranked by expected Mini gain-per-effort

| Rank | Item | Expected gain (this box) | Effort | Verdict |
|---|---|---|---|---|
| 1 | §6 prefix caching (keep_alive + stable template) | Large latency cut on repeated prompts [inf] | ~0 (env + template freeze) | Do now |
| 2 | §2 env flags (`KEEP_ALIVE=-1`, `MAX_LOADED=1`, ctx 4k) | Kills reloads/eviction churn [inf] | Minutes | Do now |
| 3 | §3 KV `q8_0` | ~½ KV RAM if FA engages (test-gated) | Small (matrix test) | Do gated |
| 4 | §7 keep `NUM_PARALLEL=1` | Avoids latency/RAM regression [inf] | Zero (decision) | Lock in |
| 5 | §5 imatrix I-quants | 100s of MB at fixed quality [inf] | Medium (pipeline + PPL gate) | Iff RAM still tight |
| 6 | §1 llama.cpp direct | ~0–7% single-stream [inf] | High (migration breaks §1.4) | Only for flag access |
| 7 | §4 Atomic TurboQuant | Immaterial at 4k/small/CPU [inf] | High (app+fork+recut callers) | No fit |

Suggested order of work: §6+§2 this session (env flips + cache-hit
confirmation) → §3 test matrix → §5 only if headroom still binds → §1/§4/§7
only on new evidence (a missing flag, long-context need, real concurrency).

## Source index (every URL cited above)
- Ollama envconfig (all flag defaults):
  https://raw.githubusercontent.com/ollama/ollama/main/envconfig/config.go
- Ollama scheduler (`defaultModelsPerGPU = 3`):
  https://raw.githubusercontent.com/ollama/ollama/main/server/sched.go
- Ollama llama-server wrapper (subprocess fact + full flag mapping + log line):
  https://raw.githubusercontent.com/ollama/ollama/main/llm/server.go
  https://raw.githubusercontent.com/ollama/ollama/main/llm/llama_server.go
- Ollama options struct + `DefaultOptions()` (num_keep 4, num_batch 512,
  num_thread 0, num_ctx from env):
  https://raw.githubusercontent.com/ollama/ollama/main/api/types.go
- Ollama REST docs (`keep_alive`, `prompt_eval_cached_count`, unload-on-0):
  https://raw.githubusercontent.com/ollama/ollama/main/docs/api.md
- Ollama Modelfile ref (`FROM gguf`, param table incl. num_ctx discrepancy):
  https://raw.githubusercontent.com/ollama/ollama/main/docs/modelfile.mdx
- Ollama OpenAI shim (`keep_alive` extension, `cached_tokens`):
  https://raw.githubusercontent.com/ollama/ollama/main/openai/openai.go
- Ollama FAQ (ctx/keep-alive/concurrency/FA/KV table, launchctl, origins):
  https://docs.ollama.com/faq
- Ollama OpenAI-compat doc (subset list, responses limits, audio quirks):
  https://docs.ollama.com/api/openai-compatibility
- Ollama log viewing: https://docs.ollama.com/troubleshooting.md
- llama-server flags + endpoints + compat caveats:
  https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md
- llama-server slot model: https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/server-context.cpp
- Arg parsing (threads→hw_concurrency, `-np -1`=auto default):
  https://raw.githubusercontent.com/ggml-org/llama.cpp/master/common/arg.cpp
- CPU topology (sysctl physical cores, math threads):
  https://raw.githubusercontent.com/ggml-org/llama.cpp/master/common/common.cpp
- imatrix: https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/imatrix/README.md
- quantize flow: https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/quantize/README.md
- quantize types + PPL help text + imatrix handling:
  https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/quantize/quantize.cpp
- PPL methodology + Llama-3-8B weight-quant scoreboard:
  https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/perplexity/README.md
- Qiita same-GGUF runtime comparison (41 vs 22, q8_0 → 35):
  https://qiita.com/kenimo49/items/6c72194d6602ca345d88
- Qiita backend/MTP comparison (12.89 → 28.68, Vulkan 8.96):
  https://qiita.com/xfgftt/items/8d85a59f545ea0692db3
- TurboQuant paper: https://arxiv.org/abs/2504.19874
- TurboQuant Google blog: https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/
- Atomic TurboQuant page: https://atomic.chat/turboquant
- Atomic 8 GB guide: https://atomic.chat/blog/guides/best-local-llm-8gb
- Atomic README (engines, :1337 API, reqs, core CLI):
  https://raw.githubusercontent.com/AtomicBot-ai/Atomic-Chat/main/README.md
- i5-8500B (Intel, 6C / 4.10 GHz / 65 W):
  https://www.intel.com/content/www/us/en/products/compare.html?productIds=/134892
