# Runtime scout — 4 OSS repos vs the Local AI Lab box (2026-10-30)

> **Update 2026-10-30 (coordinator, live test — supersedes the magnitude
> recommendation below):** installed magnitude 0.2.15 on the Mini (macOS 15.8.1,
> so the OS gate passed), ran headless on :10100, and found it cannot serve
> anything on this Intel CPU target — zero catalog models compatible, all 13
> Ollama models refused ("No kernels for the arch"), bartowski Llama-3.2-3B
> unsupported in every quant. T7 verdict: REJECT, box restored to Ollama-only.
> See `tickets/T7-magnitude-runtime-eval.md`. The source analysis below stands;
> only the "worth installing" conclusion is overtaken by the live result.

Scope: fit-scouting four open-source inference/serving projects against our target
box. **No Mini SSH access** — all claims below come from primary sources (repo
READMEs, project docs, release notes, install scripts, **and the actual source
trees**), each cited inline by file or URL. This is the deepened pass: beyond READMEs,
I inspected each repo's git tree, install scripts, dependency locks, and — for the top
pick — the Rust CPU-backend source, plus I captured a **live measured Ollama baseline
on the Mini over the tailnet** so the T7 A/B has a real number to beat. Where a
project's own benchmarks exist, I note the hardware they ran on, because none of the
four benchmark our actual chip.

Method note on depth: a full `git clone` of magnitude (153 MB, Rust) timed out, so I
worked through the GitHub REST tree API + raw file fetches instead of a local clone —
same source, lighter transport. All four repos were confirmed live and active via the
API (magnitude 7,609★ Rust; vllm-jev 866★ Python; goethe 42★ Rust; runntime 110★ TS;
all Apache-2.0 except runntime MIT; all pushed within the last ~8 days as of
2026-10-30).

## Target box (recap, from the lab repo)

8 GB Intel Mac Mini — i5-8500B, AVX2, **CPU-only (no GPU usable for inference)**,
~5.9 GB usable RAM, ~30 GB disk free; runs Ollama behind Tailscale Serve; policy is
3–4B models max at 4k context, prefer small native binaries over heavy stacks.
Source: `README.md`, `AGENTS.md`, `docs/MODEL-FIT.md`, `tickets/T7-magnitude-runtime-eval.md`
in `/Users/hugohader/dev/local-ai-lab`.

One hard hardware fact that drives several verdicts below: the box is a 2018-class
Intel Mac mini (i5-8500B = Coffee Lake, the CPU Apple shipped in the 2018 Mac mini).
**macOS Tahoe 26 dropped all Intel Mac minis**, so the box tops out at macOS 15
(Sequoia). Sources: 9to5mac — "macOS Tahoe does not work with any Intel MacBook Air
or Mac mini"
([9to5mac](https://9to5mac.com/2025/06/09/apple-will-end-support-for-intel-macs/));
Apple Support discussion from a 2018 Mac mini owner confirming no macOS 26
([discussions.apple.com](https://discussions.apple.com/thread/256139610)); Apple's
own Tahoe compatibility list excludes it
([support.apple.com/122867](https://support.apple.com/en-us/122867)).

## Live Ollama baseline measured on the Mini (2026-10-30, over tailnet)

So the magnitude A/B in T7 has a concrete target, I probed the live box via `/api/chat`
(exact `eval_count` / `*_duration` fields) and `/status`:

| Lane | Model (resident) | Decode tok/s | Prefill tok/s | Resident RAM | ctx |
| --- | --- | --- | --- | --- | --- |
| 4B quality | `gemma3:4b` | **9.72** | 55.1 | 2.88 GB | 4k |
| fast | `qwen2.5:0.5b` | **56.7** | ~715 | 0.48 GB | 4k |

Runtime: **Ollama 0.32.1** (`/api/version`). Box state under this load: `mem_free`
~21–34 MB, `mem_compressed` ~1365 MB, **`swap_used` ~1364 MB** — i.e. the box already
leans on ~1.3 GB of swap with just the 0.5b + one 4B loaded (`/status`). This is the
live confirmation of `STRESSTEST-cpu-ram.md`'s "one model resident" physics, and of
T7's rule never to serve the same model from Ollama + magnitude concurrently (double
weights = guaranteed OOM on this box).

Two corrections to stale lab assumptions, found while probing: `AGENTS.md` names
`qwen3:4b` as the default 4B lane, but **it is not currently installed** — the live 4B
is `gemma3:4b` (full installed set: granite4.2:3b, gemma3:4b, qwen3:1.7b, smollm3-3b,
granite4:micro-h, phi4-mini, qwen2.5-coder:3b, qwen2.5:3b, phi3.5:3.8b, qwen2.5:0.5b,
plus bge-m3 / nomic-embed-text embedders). The `size_vram` field is 0 for every model,
re-confirming CPU-only. (Source: live `/api/tags`, `/api/ps`, `/api/chat`, `/status`.)

So the number magnitude must beat on this chip is **~9.7 tok/s decode at 4B / 4k**. Its
"2x" claim, if it held on AVX2, would mean ~19 tok/s — a clean, falsifiable target.

---

## 1. magnitudedev/magnitude

**What it is.** Open-source inference engine (Apache 2.0) that auto-tunes kernels per
model on your hardware to find the fastest schedule, claiming ">2x faster than
Ollama." Ships a desktop app + headless CLI (`magnitude serve`), an OpenAI-compatible
API, speculative-decoding drafters per model, and quantized flex KV cache. Source:
[repo README](https://github.com/magnitudedev/magnitude).

**Architecture (from source, not marketing).** The engine is **"Seismic"** — magnitude's
own numerical language/compiler/runtime with pluggable device backends for CPU, Metal,
CUDA, and Vulkan, plus a scheduler and headless serving CLI. Source:
[`inference/README.md`](https://github.com/magnitudedev/magnitude/blob/main/inference/README.md).
The CPU backend lives at `inference/seismic/backends/cpu/` and **JIT-compiles kernels
with Cranelift** for the detected CPU (not a fixed prebuilt binary) — that is the
mechanism behind the "tuned on your hardware" claim. Sources:
[`backends/cpu/build.rs`](https://github.com/magnitudedev/magnitude/blob/main/inference/seismic/backends/cpu/build.rs)
(derives the Cranelift toolchain fingerprint),
[`backends/cpu/src/profile.rs`](https://github.com/magnitudedev/magnitude/blob/main/inference/seismic/backends/cpu/src/profile.rs).

**The AVX2 question — now answered at source level (this is the T7 unknown).** T7 flagged
"claims >2x over Ollama on CPU. Unverified on AVX2-only Intel." Two source facts resolve
the *capability* half of that (not the speed half):
1. The compatibility contract sets the **x86 CPU floor at x86-64-v2 (SSE4.2, POPCNT)**
   and defines runtime-detected tiers above it. The **x86v3 tier is explicitly
   "AVX2, FMA, F16C, BMI1/2 — Intel Haswell and newer."** The i5-8500B (Coffee Lake) is
   Haswell-or-newer, so it sits squarely in **x86v3 — the AVX2 tier**, two tiers above
   the floor. AVX-512 (x86v4) is a *separate, optional* higher tier, never required —
   the opposite of vLLM's historical AVX-512 hard requirement. Source:
   [`inference/docs/compatibility.md`](https://github.com/magnitudedev/magnitude/blob/main/inference/docs/compatibility.md).
2. The detection is real code, not a doc promise: `profile.rs` `simd_tiers()` reads
   `has_avx2` → pushes the 256-bit SIMD tier (`SimdTier::Bits256`) and, independently of
   AVX-512, enables the native single-rounded FMA path for float matmuls. Source:
   [`backends/cpu/src/profile.rs`](https://github.com/magnitudedev/magnitude/blob/main/inference/seismic/backends/cpu/src/profile.rs)
   (`fn simd_tiers`, `has_avx2`/`has_avx512f` branches).

   So on our chip magnitude *will* light up 256-bit AVX2 + FMA kernels. Whether that
   beats Ollama's ggml AVX2 kernels in wall-clock tok/s is still unmeasured on this
   silicon — that remains T7's job — but "does magnitude even have an AVX2 CPU path?" is
   now a verified **yes**.

**Requirements (primary sources).**
- OS floor, confirmed in two places: the macOS install doc states **"macOS 15 Sequoia or
  later"** + "An Apple Silicon or Intel Mac. ... Intel Macs use CPU inference"
  ([`docs/installation/macos.mdx`](https://github.com/magnitudedev/magnitude/blob/main/docs/installation/macos.mdx)),
  and the compatibility table gives the CPU backend OS floor as **macOS 15**
  ([`compatibility.md`](https://github.com/magnitudedev/magnitude/blob/main/inference/docs/compatibility.md)).
  The installer enforces it: `case "$macos_version" in [0-9].*|1[0-4].*) fail ...`
  ([install.sh](https://magnitude.dev/install.sh)).
- **Intel Mac is a first-class, documented target** — the hardware doc's support table
  has an explicit row **"Intel Mac → CPU"**, with a dedicated "CPU-only machines"
  section naming Intel Macs. Source:
  [`docs/hardware.mdx`](https://github.com/magnitudedev/magnitude/blob/main/docs/hardware.mdx).
  (This is a material upgrade over the first pass, which only had the README's generic
  "or just a CPU.")
- Arch: installer accepts `x86_64`→`x64` and `arm64`; Linux needs glibc ≥ 2.34 (desktop
  installer) / 2.35 (CPU backend). Sources: [install.sh](https://magnitude.dev/install.sh),
  [compatibility.md](https://github.com/magnitudedev/magnitude/blob/main/inference/docs/compatibility.md).
- Headless: `magnitude serve` runs without opening the desktop app ("the installer does
  not require opening the desktop app"), and `magnitude server setup` runs it as a
  boot/persistent service — fits our launchd + tailnet model. Source:
  [`docs/installation/macos.mdx`](https://github.com/magnitudedev/magnitude/blob/main/docs/installation/macos.mdx),
  README "Run it on a server."
- RAM: no fixed minimum; app profiles the machine and estimates tok/s before download.
  Source: [`hardware.mdx`](https://github.com/magnitudedev/magnitude/blob/main/docs/hardware.mdx), README FAQ.
- Deps: self-contained native app + CLI; the Rust engine bundles its runtime
  components. Not a pip/heavy stack.

**Smallest/lightest config that could plausibly run here.** The catalog has genuinely
small members inside our envelope: Qwen3.5 4B (Q4 ≈ 4.4 GB), MiniCPM5 1B (Q4 ≈ 0.7 GB),
Liquid LFM3 1.7B (Q4-QAT ≈ 1.0 GB), Gemma 4 E2B (Q4 ≈ 3.7 GB). Source:
[magnitude.dev/models](https://magnitude.dev/models). The model side fits our 3–4B /
≤5.9 GB rule. **Remaining gates, in priority order:**
  1. **OS gate (the one true blocker):** installs only on macOS 15+. The 2018 Mac mini's
     hard ceiling *is* macOS 15 Sequoia, so the box lands on the exact minimum — it fits
     **iff the Mini is actually running Sequoia**. If it is on an older macOS (Sonoma/
     Ventura), it is a hard no until upgraded. `/status` does not expose the OS string,
     so this is the single fact to confirm on the box.
  2. **Perf unproven on our silicon:** every published benchmark is Apple Silicon
     (Mac mini **M4 Pro**, 48 GB, MLX) or **NVIDIA DGX Spark** (GB10); there is **no
     Intel/AVX2/CPU row**, and the "2x" average is stated "on Mac and NVIDIA." Sources:
     [benchmarks](https://magnitude.dev/benchmarks),
     [README](https://github.com/magnitudedev/magnitude). Capability is verified (AVX2
     tier exists); the tok/s win vs our measured 9.7 is open.
  3. **RAM headroom:** the box already swaps ~1.3 GB holding one 4B under Ollama (live
     `/status`). magnitude's quantized-KV ("memory that flexes") could *help* here, but
     its process overhead on CPU is unmeasured; the A/B must watch RAM + swap, not just
     tok/s.

**What it would add to the lab.** A potential faster CPU runtime for the 3–4B lane,
OpenAI-compatible (so `AGENTS.md` routing barely changes), with per-chip Cranelift-JIT
kernel tuning, quantized KV (ties into MODEL-FIT round-5's `q8_0`-KV policy), and
built-in speculative-decoding drafters — none of which Ollama gives us today.

**Relationship to T7 (do not duplicate).** T7 owns the magnitude-vs-Ollama A/B (separate
port, same GGUF, same 4k ctx, adopt only on measured i5-8500B wins). This scout does
**not** re-run that. It feeds T7 three concrete inputs it did not have: (a) the AVX2 CPU
path is confirmed present in source, so a zero-result is a *perf* loss, not a
missing-feature one; (b) the measured Ollama baseline to beat is **~9.7 tok/s decode @
4B/4k** (target ~19 if "2x" holds); (c) an OS-version precondition that can block the
install before any benchmarking effort is spent.

---

## 2. mode-io/vllm-jev

**What it is.** A vLLM-based server for "Jev-style" **structured-decision** checkpoints:
you send a question plus candidate answers and get a label + probability per candidate
(Choice / Noul yes-no / Score). It is a decision/classification scorer over HTTP
(`/v1/systemone`), not a general chat/generation server. Source:
[repo README](https://github.com/mode-io/vllm-jev).

**Requirements (primary sources).**
- Linux: native vLLM, **NVIDIA CUDA (vLLM 0.29.0, Python 3.12+)** or Ascend NPU.
  `uv pip install '.[cuda]'`. Source: README "Getting Started" / "Example".
- Apple Silicon: macOS 15+, via **MLX or PyTorch MPS** — i.e. Apple-Silicon GPU paths,
  not Intel. `source scripts/install_mac.sh`. Source: README.
- Windows x64: an **experimental CPU backend** for 24 validated checkpoints (PyTorch
  CPU or pinned per-model GGUF runtimes, four isolated venv profiles). Source: README
  "Windows support."
- CPU-on-macOS: **not offered.** The Mac path is explicitly MLX/MPS (Apple-Silicon GPU).

**Smallest/lightest config that could plausibly run here → no-fit (source-confirmed).**
Reasons:
  - Our box is **Intel macOS, CPU-only**. The Mac installer **hard-refuses non-Apple-
    Silicon**: `install_mac.sh` line 5 — `if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)"
    != arm64 ]; then echo "This installer requires an Apple Silicon Mac."`. The wheels it
    pulls are `vllm-0.29.0+cpu-...-macosx_11_0_arm64.whl` and
    `vllm_metal-0.29.0-...-macosx_15_0_arm64.whl`, and `pyproject.toml` pins
    `mlx-vlm==0.6.17; sys_platform == 'darwin'`. There is **no x86-64 Darwin wheel or
    code path at all**. Sources:
    [`scripts/install_mac.sh`](https://github.com/mode-io/vllm-jev/blob/main/scripts/install_mac.sh),
    [`pyproject.toml`](https://github.com/mode-io/vllm-jev/blob/main/pyproject.toml).
  - The only CPU path is **Windows x64** (`torch`/`transformers`/GGUF pinned under
    `sys_platform == 'win32'` in `pyproject.toml`), validated on one Windows 11 host; the
    README says Windows results "do not imply" other platforms. It does not transfer to
    macOS. Sources: README, `pyproject.toml`.
  - It is a **heavy stack** (vLLM + PyTorch + Triton + FlashInfer lineage) — the opposite
    of the "small native binary" preference.
  - Mission mismatch: it serves *decision scoring* (Choice/Noul/Score), not the
    chat/code/embed lanes the lab routes today (`AGENTS.md`).

**What it would add (if the box changed).** A structured-decision / classifier API
(Choice/Noul/Score) — conceptually adjacent to the lab's "tiny judge" use
(`smollm2` as judge in `MODEL-FIT.md`). Worth remembering as *prior art for a decision
endpoint*, but not runnable here.

---

## 3. meshapplied/goethe

**What it is.** A one-machine model server (Apache 2.0) that turns a Linux box into
your own OpenAI/Anthropic/LiteLLM-compatible API in three steps; multi-model,
multi-GPU, survives reboots. Source: [repo README](https://github.com/meshapplied/goethe).

**Requirements (primary sources).**
- OS: **Linux only** — "Linux on x86_64 or ARM64 (glibc 2.30 or newer)." No macOS.
- GPU: **NVIDIA required.** Supported archs Ampere → Blackwell (compute capability
  8.0–12.1); "Older GPUs (Volta, Turing) are not supported." Needs NVIDIA driver 535+
  (580+ for GeForce/TITAN). Source: README "GPU and CUDA compatibility."
- "Enough GPU memory for the model is the only other requirement." Built on SGLang,
  PyTorch, FlashInfer, Triton, nginx, CUDA. Source: README.

**Smallest/lightest config → no-fit, decisively (source-confirmed).** It is Linux-only
and NVIDIA-only. Our box is macOS on an Intel CPU with no supported GPU. There is no CPU
fallback and no macOS build. The source makes this unambiguous: every compute kernel in
the repo is CUDA (`engine/experimental/goethe-kernels/kernels/csrc/*.cu`,
`nvfp4-kernels/`, `ternary-kernels/.../csrc/*.cu`), and the Python dep lock is wall-to-
wall CUDA — `cuda-bindings`, `cuda-toolkit`, `cuda-python`, `flash-attn-4`,
`flashinfer-python`, `compressed-tensors` (from
[`engine/pyenv/requirements.in`](https://github.com/meshapplied/goethe/blob/main/engine/pyenv/requirements.in)).
There is no x86-CPU inference backend anywhere in the tree. Not runnable on this hardware
under any config. Sources:
[repo tree](https://github.com/meshapplied/goethe), README "GPU and CUDA compatibility".

**What it would add (elsewhere).** If the lab ever adds a Linux + NVIDIA node, goethe
is a clean many-models-one-URL gateway with key management and Tailscale/WireGuard
network scoping — architecturally similar to our Caddy+sidecar front door, but GPU-host
oriented. Not relevant to the current Mini.

---

## 4. software-mansion/runntime

**What it is.** A TypeScript/JavaScript framework ("ruNNtime") for running neural nets
on the **user's GPU via WebGPU**, built on TypeGPU; kernels compile to WGSL at runtime
(no WASM). Ships a `zoo` of task models: embeddings, speech-to-text, object detection,
segmentation, pose, depth, image classification. A drop-in backend for transformers.js.
Source: [repo README](https://github.com/software-mansion/runntime).

**Requirements (primary sources).**
- **Requires WebGPU** — Chrome/Edge/Safari 26+/recent Firefox, Electron, or React
  Native via `react-native-webgpu`. Source: README "Important: ruNNtime needs WebGPU."
- Half-precision vision/detection models need the `shader-f16` GPU feature (embeddings,
  STT, privacy filter can run without it). Source: README.
- It is an npm package (`npm install runntime` + TypeGPU); runs inside a browser/
  Electron/RN JS runtime, not as a standalone server. Source: README.

**Smallest/lightest config → effective no-fit for this box (source-confirmed).**
ruNNtime is a **GPU/WebGPU** engine (`engines: { node: ">=22" }`, built on TypeGPU;
source: [`package.json`](https://github.com/software-mansion/runntime/blob/main/package.json)).
Our box is explicitly **CPU-only for inference** with no usable GPU; WebGPU on this
integrated-graphics 2018 Intel Mac under a supported browser is, at best, unproven and
outside the lab's "native binary serving Ollama over Tailscale" model. It is also
browser/Node-embedded, not a tailnet HTTP model server, and its catalog is
vision/speech/embedding tasks — only the **embedding** task overlaps the lab's lanes,
and we already serve `nomic-embed-text` (and `bge-m3`) on CPU via Ollama, confirmed
live in `/api/tags`. No plausible server-side config fits.

**What it would add (different context).** If the lab grows a browser/Electron client
or an on-device mobile surface, ruNNtime gives client-side embeddings/vision/STT that
run on the *end-user's* GPU with zero server load — a genuinely different deployment
axis from our central Mini. Not a runtime for the Mini itself.

---

## Ranked fit (best-first)

1. **magnitude** — the only real fit, and confidence is now **source-grade, not README-
   grade**. Its Seismic CPU backend has a verified AVX2+FMA tier (`x86v3`) that our
   i5-8500B lands in, JIT-compiled per-chip via Cranelift; it documents Intel Mac as a
   first-class CPU target; it has a headless `magnitude serve` that fits our launchd +
   tailnet model; and its small-model catalog fits the RAM envelope. The one true
   blocker is the **macOS-15 floor vs. the box's Sequoia ceiling** — a yes/no fact to
   confirm on the box. Perf vs. the measured **9.7 tok/s** Ollama baseline is the open
   question T7 exists to answer. Clear #1 and the only one worth installing.
2. **vllm-jev** — no-fit on current hardware, now confirmed in source: `install_mac.sh`
   refuses non-arm64 Darwin and only Apple-Silicon/MLX wheels exist; the sole CPU path is
   Windows-x64. Ranked above goethe/runntime because (a) a CPU path at least *exists* in
   the project, and (b) its structured-decision scoring is the nearest conceptual match
   to the lab's tiny-judge use — worth remembering as prior art for a decision endpoint.
3. **goethe** — no-fit, source-confirmed (all-CUDA kernels + CUDA-only dep lock,
   Linux-only). Useful only if a GPU Linux node is ever added; above runntime because it
   is a direct server analog to our Caddy+sidecar front door.
4. **runntime** — no-fit for the Mini (WebGPU/GPU, Node/browser/RN-embedded). Only
   relevant to a future client-side surface, not central serving.

The bottom three are all hard no-fits on this exact box; the ordering reflects
nearness-of-miss and relevance to a *possible future* node, not any chance of running on
the Mini today.

## First experiment to run for the top pick (magnitude)

The deep dive changes the *content* of the first experiment but not its position: the
**macOS-version gate is still the first thing to settle**, because it is now proven to be
the single remaining blocker (capability/AVX2 is confirmed in source; only the OS floor
can still hard-stop the install). Run it as a cheap two-part check before any install
effort:

- **Experiment — "magnitude installability gate + baseline lock-in":**
  1. Confirm `sw_vers -productVersion` on the Mini is **≥ 15 (Sequoia)**. The 2018 mini's
     ceiling *is* Sequoia, so this is pass/fail with no headroom: `install.sh` hard-fails
     below 15. If **< 15** → T7 is blocked; record "magnitude needs macOS 15, box is on
     <version>" and the decision is upgrade-or-reject, **not** benchmark. If **≥ 15** →
     proceed.
  2. Lock in the Ollama baseline the A/B must beat, already captured here:
     **gemma3:4b ≈ 9.7 tok/s decode / 55 tok/s prefill / 2.88 GB resident at 4k**, with
     the box already at ~1.3 GB swap. T7's win bar is magnitude serving the *same GGUF* at
     4k and beating 9.7 tok/s decode **without** pushing swap higher or OOMing — tok/s
     alone is not adoption if RAM regresses.

This stays the *precondition* to T7's A/B (T7 owns the same-GGUF, same-4k-ctx,
tok/s + RAM + quality bench). Doing the OS gate first avoids T7 spending install effort
on a box the vendor script will refuse; carrying the measured baseline in means the A/B
starts with a real target number instead of the vendor's Apple-Silicon "2x."

---

## Addendum (2026-10-31) — two follow-ups: a compressed tool model + a gateway

Added after the original four-repo scout, in response to two items raised separately:
a compressed small model (TurinTech / Artemis Qwen3.5-0.8B) and an AI gateway
(eliasbiondo/antirion). Recent-signal gathering used the agent-reach skill (read-only
GitHub + web channels) plus the GitHub REST API; all claims cited.

### A. TurinTech `Qwen3.5-0.8B-Artemis-GGUF` — a tool-lane candidate (good fit)

**What it is.** A TurinTech/Artemis-**compressed** build of Qwen3.5 0.8B, published as a
llama.cpp GGUF, aimed at local tool calls + short chat. Verified against the HF model
card (not just the vendor post). Source:
[HF card](https://huggingface.co/turintech/Qwen3.5-0.8B-Artemis-GGUF),
[collection](https://huggingface.co/collections/turintech/compressed-llms).

**Verified claims (primary source).**
- Default **Q5_K_M = 0.569 GB** (confirmed: the file resolves with
  `x-linked-size: 569082048` ≈ 0.569 GB); smaller **Q4_K_M = 0.532 GB**; original 1.52 GB.
  130,184 downloads last month.
- **Tool calling: 163/258 BFCL-live**, and the card is explicit the "109" baseline is
  **bartowski's Q4_K_M (0.580 GB)** — a *same-size public GGUF*, not the uncompressed
  original. Also IFEval 308/541, GSM8K 124/250 (published eval-results on the card).
- 8,192-token context in tests; optional vision projector (+207 MB, skip with `--no-mmproj`).
- Installable on the lab stack via `ollama run hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M`
  (the HF→Ollama passthrough; no separate native `ollama.com/turintech/...0.8b` tag — the
  2B has one, the 0.8B does not, confirmed by a 405 on that URL).

**Two caveats the card itself flags.** (1) **Turn thinking OFF** for short answers/tool
calls — their test with thinking on burned all 1,500 output tokens and returned nothing.
(2) **Knowledge is weak** — MMLU-Pro 33/280 vs 44 for the original; don't use it as a
knowledge model (the card suggests Unsloth Q8_0 if knowledge matters).

**Honest limitation.** Every benchmark/memory number on the card is measured on an
**NVIDIA RTX 5090 with all layers on GPU** — not CPU. Tool-call *accuracy* is
hardware-independent and should transfer; **tok/s on our AVX2 CPU is unmeasured** (same
gap as magnitude).

**Fit for the box: good, fills a gap.** At 0.57 GB it sits far under the ~3.8–4.4 GB
model budget (`STRESSTEST-cpu-ram.md`), so unlike the 4B lane (measured pushing ~1.3 GB
swap live today) it co-resides trivially. It targets a lane the lab actively routes —
tools (`AGENTS.md`: `llama3.2:3b` / `phi4-mini` / `functiongemma`) — with a published
BFCL number beating a same-size public GGUF. The T11/T12 tool bench + weekly eval can
verify the claim on the i5-8500B and settle the CPU-tok/s question. Recommended Tier-1
tools-lane A/B candidate (thinking-off, knowledge-weak caveats noted).

### B. eliasbiondo/antirion — an AI *gateway*, not a runtime (off-box fit only)

**What it is.** An open-source **AI/LLM gateway** (self-hosted LiteLLM / Bifrost
alternative), Apache-2.0, one Rust binary with the admin console built in. It sits
*between apps and providers* — routing, auth, rate-limits, budgets, guardrails, caching,
observability — exposing OpenAI/Anthropic/Gemini/Bedrock-compatible APIs. It is the same
*architectural slot* as the lab's Caddy + feedback-sidecar front door, **not** the
model-serving layer. Source: [repo README](https://github.com/eliasbiondo/antirion).

**Verified from source.**
- **Memory is featherweight:** `docs/benchmarks.md` → **41 MiB idle / 215 MiB peak** at
  5k RPS. For contrast, the same bench shows LiteLLM idling at 1,653 MiB — exactly why
  `STRESSTEST-cpu-ram.md` ruled LiteLLM does-not-fit. Antirion is ~40× lighter at idle.
- **Can front a local Ollama:** supports an **"OpenAI-compatible" provider with an
  arbitrary Base URL** (how its own mock upstream is wired); Ollama serves
  `/v1/chat/completions`. README names "any OpenAI- or Anthropic-compatible server such
  as vLLM." Source: `docs/getting-started.md`, README.
- **Single self-contained binary** in standalone mode: dedicated `antirion-store`
  (embedded) crate separate from `antirion-redis` (cluster only) — no external DB needed.
- **Platform gate (the blocker on macOS):** release assets are **Linux amd64/arm64 only**
  (`antirion-v0.1.1-linux-*.tar.gz`, 110–118 MB). On macOS the only routes are the Docker
  image or a from-source build (Rust 1.98.1 + Node 22/pnpm for the console). Source: GitHub
  releases API, README "Binaries".

**Recent-activity signal (agent-reach + GitHub API, 2026-10-31).** The repo is **brand
new** (created 2026-10-17; releases v0.1.0/v0.1.1 both on 2026-10-18, nothing since) and
**single-author** (`eliasbiondo` 523/534 contributions; the only other "contributor" is
dependabot) — **bus-factor 1**. It does show serious engineering hygiene for its age:
nightly fuzzing + supply-chain CI (self-filed issues #59/#60), dependabot, RUSTSEC
tracking. **Independent third-party validation is essentially nil** — a web sweep found
only the project's own site and auto-generated repo-rating mirrors (one, m8ven.ai, scores
it "F 38/100"); no Hacker News or Reddit discussion.

**Cross-connection worth noting (ties this scout together).** An external contributor's
open PR #48 adds a **typed-decision endpoint `POST /v1/systemone`** to antirion — the
*same* Choice/Noul/Score decision protocol as scout repo #1 (vllm-jev). The PR documents,
and I independently verified, that this is now a published spec (`api.typesafe.ai`,
TypeSafe v0.2.0) served by LiteLLM and **merged into vLLM mainline**
([vllm-project/vllm#59299](https://github.com/vllm-project/vllm/pull/59299), merged
2026-10-08 by mmastrac, shipped v0.32.0). So the "decision models" ecosystem (vllm-jev,
plus TurinTech's Kev/Clef/Decider) is converging on one wire protocol, and gateways are
starting to speak it. Not actionable for the Mini today, but relevant if the lab ever
builds a decision/tiny-judge endpoint.

**Fit for the box: off-box only (same verdict class as LiteLLM/UI stacks).** The blocker
is *platform*, not RAM: no macOS binary → native route is a from-source build on a
memory-saturated box, and the Docker route is a known blocker (`TRIALS-offbox.md`). Its
value (multi-provider routing, budgets, guardrails, clustering at thousands of RPS) is
aimed at a fleet of paid providers, not a single-node single-user local Ollama. **Verdict:
"fits-with-work, off-box"** — strictly better than LiteLLM (40× lighter, single binary,
no Python), but gated on macOS and far too young (v0.1.1, one author, no external
validation) to put in front of the lab's only front door. If the lab ever adds a Linux
tailnet node and wants per-key budgets / guardrails / caching / a cost ledger in front of
the Mini's Ollama, antirion is worth a re-look *then*.

**Revised-verdict row (for `STRESSTEST-cpu-ram.md`'s tool table, if adopted there):**
`antirion | — | fits-with-work, off-box | Linux-only binary (Docker/build on mac); 41 MiB
idle beats LiteLLM 40×, but v0.1.1 / single-author / no external validation — off-box
front-door candidate only.`

---

### Source index
- Lab context: `README.md`, `AGENTS.md`, `docs/MODEL-FIT.md`, `STRESSTEST-cpu-ram.md`, `TRIALS-offbox.md`, `tickets/T7-magnitude-runtime-eval.md` (this repo).
- Live Mini probes (2026-10-30, over tailnet): `/api/version` (Ollama 0.32.1), `/api/tags`, `/api/ps`, `/api/chat` (gemma3:4b, qwen2.5:0.5b), `/status`.
- magnitude: https://github.com/magnitudedev/magnitude · https://magnitude.dev/install.sh · https://magnitude.dev/models · https://magnitude.dev/benchmarks · docs/hardware.mdx · docs/installation/macos.mdx · docs/faq.mdx · inference/README.md · inference/docs/compatibility.md · inference/seismic/backends/cpu/{build.rs,src/profile.rs}
- vllm-jev: https://github.com/mode-io/vllm-jev · scripts/install_mac.sh · pyproject.toml
- goethe: https://github.com/meshapplied/goethe · engine/pyenv/requirements.in · (CUDA kernels under engine/experimental/goethe-kernels, nvfp4-kernels, ternary-kernels)
- runntime: https://github.com/software-mansion/runntime · package.json
- Addendum A (TurinTech): https://huggingface.co/turintech/Qwen3.5-0.8B-Artemis-GGUF · https://huggingface.co/collections/turintech/compressed-llms · https://www.turintech.ai/blog/qwen35-family-compressed-with-artemis · HF resolve HEAD (x-linked-size)
- Addendum B (antirion): https://github.com/eliasbiondo/antirion · docs/benchmarks.md · docs/getting-started.md · releases API (v0.1.1 Linux-only) · issues/PRs #47/#48/#59/#60 · contributors API · https://github.com/vllm-project/vllm/pull/59299 (systemone merged 2026-10-08) · agent-reach (GitHub + web channels) for recent signal
- Repo liveness/metadata: GitHub REST API (stars, language, license, pushed_at, git trees) for all repos.
- Intel Mac mini / macOS 26 support: https://9to5mac.com/2025/06/09/apple-will-end-support-for-intel-macs/ · https://discussions.apple.com/thread/256139610 · https://support.apple.com/en-us/122867

*Content from external sources was rephrased for compliance with licensing restrictions.*
