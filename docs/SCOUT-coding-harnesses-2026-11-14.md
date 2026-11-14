# Coding-harness sweep for the Mini lab (35 repos)

Context: Intel Mac Mini lab, 8 GB RAM, CPU-only, Ollama 0.40.16, ~38 small
(0.5B–8B) models with serial load; plus an Apple Silicon MacBook. Goal: put the
small models inside a coding harness and find what is missing locally.

Sources: `/tmp/reach6/*.json` (README text fetched via `gh`, `105-reddit-agents`
was empty so 35 repos), plus `/tmp/harness-voices-sub.md`. No network used.
Anything not stated in a fetched README is marked **(inferred)**.

Verdict key: **fits Mini** · **MacBook-only** · **needs GPU** ·
**dead-deprecated** · plus **Windows-only** where the README states it.

## The 35 repos

### 1. SiliconScope — https://github.com/kennss/SiliconScope
Sudoless Apple Silicon system monitor: SwiftUI dashboard + menu-bar suite with
ANE (Neural Engine), GPU, and memory-bandwidth tracking, plus remote agents for
other machines. Runs no models itself; it watches them (names Ollama models,
ComfyUI queues, per-process VRAM). License MIT (name/icon excluded).
**Verdict: MacBook-only** (requires macOS 14+ on Apple Silicon; Intel Mini excluded).
**Teaches us:** measure what local-AI loads actually stress (bandwidth vs
compute) before blaming the model.

### 2. LocalAI — https://github.com/mudler/LocalAI
Open-source AI engine: one OpenAI/Anthropic/ElevenLabs-compatible API over 60+
on-demand backends (llama.cpp, vLLM, MLX, whisper.cpp, …), pulled only when a
model needs them. CPU-only Docker run is documented; no GPU required. MIT.
**Verdict: fits Mini** (CPU-only image stated; 8 GB Docker hosting is tight — inferred).
**Teaches us:** the portable pattern — one compatible API, swappable backends —
so harnesses never hard-code a runner.

### 3. LocalAGI — https://github.com/mudler/LocalAGI
No-code self-hosted agent platform: Web UI agents with Skills, MCP servers,
chat connectors, REST + OpenAI-Responses-compatible APIs. CPU `docker compose`
is the default (text models only); default text model `gemma-3-4b-it-qat`.
MIT, no API keys, no subscriptions.
**Verdict: fits Mini** (CPU default stated; swap defaults down for 8 GB — inferred).
**Teaches us:** per-agent skills + MCP tool injection is how small models get
leverage without bigger weights.

### 4. llama.cpp — https://github.com/ggml-org/llama.cpp
LLM inference in C/C++ (the engine under Ollama-class tools — inferred),
with a `llama-server` REST API. MIT.
**Verdict: fits Mini** (the CPU-inference baseline everything else compares to).
**Teaches us:** when Ollama hides a knob you need (ctx, cache, grammar), this is
the layer below it.

### 5. SmallCode — https://github.com/Doorman11991/smallcode
Terminal coding agent built for 8B–35B local models: budget-managed context,
forgiving multi-format tool parser, TODO-file plan decomposition,
search-and-replace patching instead of full rewrites. Talks to LM Studio,
llama.cpp, Ollama, or any OpenAI-compatible endpoint; Node 18+, prebuilt
binaries; has a CPU-slow-server timeout knob. MIT (README ends `## License / MIT`).
**Verdict: fits Mini** (client-side; endpoint can be the Mini's Ollama).
**Teaches us:** the small-model harness playbook in one repo — this is the
closest thing to our target design. (The "declared dead" badge points at a
joke certificate site and the "No longer maintained" note is about a transitive
npm dep — inferred alive; verify with a fresh `gh` look before depending on it.)

### 6. local-deep-research — https://github.com/LearningCircuit/local-deep-research
Local deep-research agent (LangGraph): models run in bundled Ollama, search via
SearXNG, Docker or pip on Win/Mac/Linux. MIT.
**Verdict: fits Mini** (Ollama-backed; its benchmarked 27B models won't fit 8 GB —
run a 4B and accept slower research — inferred).
**Teaches us:** the search→read→synthesize agent loop works with local models;
it also warns locality is judged by endpoint, so a "local" proxy can still exfil.

### 7. nanobot — https://github.com/HKUDS/nanobot
Ultra-lightweight Python personal-agent framework: WebUI/terminal/chat channels,
shell/web/MCP tools, cron, memory, multi-agent delegation. Connects to any
provider or local server (Ollama, vLLM, OpenAI-compatible); needs Python 3.11+.
MIT; model fees depend on the service you choose.
**Verdict: fits Mini** (light client + Ollama backend).
**Teaches us:** the minimal viable agent shape — providers + tools + channels +
memory — without framework bloat.

### 8. Codewhale — https://github.com/codewhale-hq/Codewhale
Open-source Rust terminal coding agent, 40+ providers, any OpenAI-compatible
endpoint; auto-offers a local model when a local Ollama server answers.
DeepSeek is the default provider. MIT; one-line install, no account.
**Verdict: fits Mini** (Ollama local path stated).
**Teaches us:** provider abstraction with graceful local fallback, plus splitting
one task across several agents.

### 9. llamafile — https://github.com/mozilla-ai/llamafile
Single-file executable LLM runner: llama.cpp + Cosmopolitan libc, runs locally
on most OS/CPU combos with no install; plus `whisperfile` for speech-to-text.
Apache 2.0 badge.
**Verdict: fits Mini** (one binary, CPU-friendly, zero-install).
**Teaches us:** distribution is the feature on weak hardware — one binary beats
one container when RAM is the budget.

### 10. OmniGet — https://github.com/tonhowtf/omniget
Local MCP server giving a coding agent a desktop toolbox (downloads, media,
files, chats, computer control). Free, open source, runs on your machine.
GPL-3.0.
**Verdict: fits Mini** (model-agnostic tool server; a big tool surface strains
small models — inferred).
**Teaches us:** MCP is the tool bus — but tool *count* is a small-model hazard,
so expose few tools, not many.

### 11. Soup — https://github.com/MakazhanAlpamys/Soup
One-command LLM fine-tune/post-train CLI + Web UI (VRAM guide, pip extras
matrix). NVIDIA + QLoRA, Apple Silicon MPS, CPU experimental and very slow.
Apache 2.0; Python 3.11–3.13.
**Verdict: needs GPU** (CPU path explicitly very slow; MacBook MPS possible — inferred).
**Teaches us:** post-training small models for tool-calling could fix their
weakest skill — but the training itself can't happen on the Mini.

### 12. Locally Uncensored — https://github.com/PurpleDoubleD/locally-uncensored
All-in-one desktop AI studio: chat, images, video, coding agent in one app;
local mode runs on your machine, no Docker/terminal. AGPL v3; free open source
(app; some models carry non-commercial terms). Vulkan build covers
NVIDIA/AMD/Intel with a CPU/mesa fallback path.
**Verdict: MacBook-only** (macOS row: Apple Silicon beta, "Intel Macs are not
supported"; desktop app needs a graphical session, no `--host` flag). Would fit
only if the Mini ran Linux with a desktop (AppImage/.deb/.rpm).
**Teaches us:** Vulkan as the cross-vendor GPU escape hatch, and studio-UX ideas
worth stealing for the lab.

### 13. Rapid-MLX — https://github.com/raullenchai/Rapid-MLX
OpenAI- and Anthropic-compatible LLM server for Apple Silicon on MLX, built for
reliable tool calling with coding agents (`rapid-mlx launch codex|…` for Codex,
Claude Code, OpenCode, Pi, Hermes, Crush, Goose). Apache 2.0; requires M-series.
**Verdict: MacBook-only.**
**Teaches us:** reliable tool calling is *the* server feature for coding agents;
also a model for honest benchmarking (per-task numbers, method, raw data).

### 14. Surf — https://github.com/deta/surf
Local-first open-source AI notebook (Svelte/TS/Rust) for Mac/Windows/Linux:
multi-media library, notes, web, generated applets. Models are your choice:
BYOK, cloud, or local LLMs. Apache 2.0 with some MPL-2.0 files.
**Verdict: fits Mini** (app-side; local-LLM path stated, exact endpoint in docs
not fetched — inferred Ollama-compatible).
**Teaches us:** notebook UX over local-first open formats; openness to model
choice as a design principle.

### 15. claude-code-local — https://github.com/nicedreamzapp/claude-code-local
Lets Claude Code keep going on a local model when Claude usage runs out: same
tools, same project, no API key. Ships 18 MLX builds on Hugging Face; stated
working on a 16 GB Mac; Mac/Linux/Windows. MIT.
**Verdict: MacBook-only** (MLX builds are Apple-Silicon-only and 16 GB is the
stated floor; no Intel/CPU path stated).
**Teaches us:** the "frontier first, local fallback" workflow — exactly the XDA
split — packaged as one command (`keep going`).

### 16. awesome-local-llm — https://github.com/rafska/awesome-local-llm
Curated awesome-list of local-LLM platforms, inference engines, UIs, models,
agent frameworks, coding agents, and hardware. A document, not software.
**Verdict: fits Mini** (reading material; zero RAM).
**Teaches us:** where to look next — its coding-agents and inference-engine
sections are the map for round two of this sweep.

### 17. Algernon — https://github.com/xyproto/algernon
Self-contained Go web/app server (HTTP/2/3, Lua, Markdown, JSX/TS, SQLite, …)
with built-in Ollama support: an `index.prompt` file (content-type + model +
prompt) generates page content from a local model, default `qwen2.5-coder:1.5b`.
BSD license; runs down to Raspberry Pi class hardware.
**Verdict: fits Mini** (tiny binary + local Ollama; 1.5B default sips RAM).
**Teaches us:** LLM-as-a-web-template is a legit 1.5B use case — serving small
models behind plain HTTP takes almost nothing.

### 18. Project Maya — https://github.com/mw00/project-maya
Runs 300B–750B MoEs (GLM-5.3, DeepSeek V4.1, MiniMax M3.1) on your own GPU(s):
1–16 NVIDIA cards, tiered GPU→RAM→NVMe expert offload, OpenAI/Anthropic API.
Free and open source (mixed upstream licenses). Needs ~95 GB+ memory pools.
**Verdict: needs GPU** (by two orders of magnitude).
**Teaches us:** the far end of the fit spectrum — expert offloading across tiers
is *the* technique, and our tier is RAM→nothing.

### 19. MTPLX — https://github.com/youssofal/MTPLX
Native Mac app + CLI for Apple Silicon using models' own multi-token prediction
(MTP) heads for ~2× decode (measured 1.6× on 16 GB M4 mini, 2.24× on M5 Max).
Apache 2.0; requires M1+, macOS 14+.
**Verdict: MacBook-only.**
**Teaches us:** speculative/MTP decoding is the biggest free speedup available —
and the Mini's CPU stack has no equivalent story (gap, see below).

### 20. HyperQwen — https://github.com/syv-ai/HyperQwen
vLLM-based serving setup for big Qwen on consumer GPUs: Qwen3.8-27B, 150K ctx,
OpenAI-compatible API on a single 24 GB card (127 tok/s single-stream on an
RTX 3090). Apache 2.0; Docker.
**Verdict: needs GPU.**
**Teaches us:** vLLM continuous batching is the throughput answer when a GPU
exists — a reference point, not a tool, for this lab.

### 21. mlx-serve — https://github.com/ddalcu/mlx-serve
Native Mac app + local server for Apple Silicon: chat, coding agents, media;
speaks OpenAI, Anthropic, and Ollama APIs; offline, no Python, no account.
MIT; needs macOS 26.2+ on Apple Silicon; suggests a model that fits your Mac.
**Verdict: MacBook-only.**
**Teaches us:** Ollama-API compatibility as the interchange standard, and
per-machine model-fit suggestions — the feature the Mini needs most (gap).

### 22. Parlor — https://github.com/fikrikarim/parlor
Fully on-device real-time multimodal voice AI (GPT-Live-like), built to run on
a MacBook M3 Pro: cascade of smart-turn → Gemma 4 E4B via llama.cpp → Kokoro
TTS (MLX on Mac, ONNX on Linux). Research preview; Python 3.12+, new llama.cpp.
License not stated in fetched text.
**Verdict: MacBook-only** (M3 Pro stated; real-time cascade won't hold on a
CPU-only 8 GB Mini — inferred).
**Teaches us:** cascade beats grafting — the author *failed* to fine-tune a
full-duplex small model and won with a classic pipeline; also streams
prompt-cache while the user is still talking.

### 23. ATLAS — https://github.com/inferstep/ATLAS
Local coding agent putting "frontier-style reasoning" around compact open
models: planning, candidates, verification, sandboxed TUI pipeline via
llama.cpp, no API key. AGPL-3.0. Requirements state 16 GB+ VRAM.
**Verdict: needs GPU** (16 GB+ VRAM stated).
**Teaches us:** same thesis as SmallCode — intelligence in the system around
the model — but GPU-gated, which sharpens the question: how much of that
system transfers to CPU-only 8 GB?

### 24. USB-Uncensored-LLM — https://github.com/techjarves/USB-Uncensored-LLM
Portable USB/SSD air-gapped local-AI environment (portable Python, custom
Ollama engine, AVX CPU builds, cross-platform shared model volume).
**Verdict: dead-deprecated** (README states all development moved to
Uncensored-Local-Studio).
**Teaches us:** the portable/zero-dependency distribution pattern — and to
evaluate the successor repo, not this one.

### 25. Atomic Chat — https://github.com/AtomicBot-ai/Atomic-Chat
Local AI app + inference engine for agents: upstream llama.cpp for GGUF
(default on Win/Linux), own TurboQuant KV-cache fork (up to ~4.3× smaller KV
footprint, CPU and GPU), MLX on Apple Silicon; supported provider in OpenCode,
Goose, Kilo, OpenClaude. Requirements: macOS 13.6+, 8 GB RAM for 3B models.
Tauri + Node 20. License not stated in fetched text.
**Verdict: fits Mini** (8 GB-for-3B and CPU TurboQuant path stated).
**Teaches us:** KV-cache quantization is an 8 GB survival technique — and the
pasted benchmark's "zero broken calls" datapoint came from this family.

### 26. Observer — https://github.com/Roy3838/Observer
Local-first When-X-Then-Y agent watching screen/camera/audio (calls/messages
you on events). Desktop app ships llama.cpp (any GGUF+mmproj) or points at any
OpenAI-compatible endpoint (Ollama, vLLM). AGPLv3; macOS/Windows/Linux/browser.
**Verdict: fits Mini (soft)** — client-side, Ollama endpoint unverified
(README only says "Use Local Language Models"; Electron shell unbudgeted
at ~0.5–1 GB on this box).
**Teaches us:** the Sensors→Model→Code micro-agent loop, and that polling
cadence is the weak-hardware design variable.

### 27. Row-Bot — https://github.com/siddsachar/row-bot
Local-first desktop assistant: conversations, goals, delegated agents, local
knowledge-graph memory, approvals before risky actions. Models via Ollama,
provider keys, subs, or any OpenAI-compatible endpoint. Apache 2.0;
Windows/macOS/Linux; React + FastAPI + LangGraph.
**Verdict: fits Mini** (Ollama path stated; full desktop stack is heavier than
a CLI — inferred).
**Teaches us:** approvals-before-risk plus a local knowledge graph — the trust
and memory patterns every lab agent should copy.

### 28. NobodyWho — https://github.com/nobodywho-ooo/nobodywho
On-device inference engine (built for game NPCs, usable anywhere): any chat LLM
(Gemma/Qwen/Mistral), fast type-safe tool calling via auto-generated grammars,
multimodal input, local TTS/STT. EUPL-1.2 (free commercial use; open-source
your fork changes). Uses GPU where available.
**Verdict: fits Mini** (README states "Inference uses the GPU where available
and CPU where not", plus an experimental OpenAI-compatible local server).
**Teaches us:** grammar-constrained tool calling is the principled fix for
small-model tool fumbling — the #1 harness reliability lever.

### 29. Ouroboros — https://github.com/razzant/ouroboros
Self-described persistent general-purpose agent: identity/memory/history across
restarts, specialist swarm, can rewrite its own implementation. Native desktop
app (macOS AS, Windows/Linux x86_64) or headless CLI; inference via configured
remote APIs or a local GGUF model; no telemetry. MIT; Python 3.10+.
**Verdict: fits Mini** (local-GGUF + Linux-x86_64 paths stated; run lean, not
the full swarm — inferred).
**Teaches us:** durable memory + continuity as the architecture, and a skills
marketplace (OuroborosHub) as the extension model.

### 30. vllm-mlx — https://github.com/waybarrios/vllm-mlx
vLLM-style inference server for Apple Silicon: continuous batching, paged KV,
prefix caching, SSD-tiered cache; OpenAI + Anthropic APIs from one process.
Apache 2.0; pip install.
**Verdict: MacBook-only.**
**Teaches us:** the server-side caching bag of tricks (prefix/KV/SSD tiers) —
check which have llama.cpp-server equivalents for the Mini (inferred partial).

### 31. gawkbot — https://github.com/najmuzzaman-mohammad/gawkbot
Open-source "Grok bot": always-on bots on your machine that adopt your existing
Claude Code/Codex/OpenCode CLIs (plus Ollama, MLX-LM, Hermes gateways) under
one Chief of Staff with approval gates on every external action. Free to
self-host; Sustainable Use License (source-public, not OSI-open); Go.
**Verdict: fits Mini** (orchestrator over existing CLIs/Ollama; notch UI is
Mac-only but Intel is still a Mac — inferred).
**Teaches us:** adopt-don't-replace — wrap the CLIs you already run instead of
building another agent — with human gates as the safety story.

### 32. rpocket-AI-Coding-Agent-Toolkit — https://github.com/AcrossCryrepo/rpocket-AI-Coding-Agent-Toolkit
Only a one-line description was fetched (252 chars): "all-in-one AI Coding
Agent toolkit for Claude Code, OpenAI Codex, and more … simple setup …
flexible workflows." License, cost, and model backend: not stated.
**Verdict: unverifiable** — cannot judge from a tagline (1.4 KB fetch);
re-fetch before any decision. Excluded from the fits tally.
**Teaches us:** nothing yet — it teaches us to distrust thin fetches.

### 33. Nexus-AI-Studio — https://github.com/RDunbar01/Nexus-AI-Studio
Local AI workspace with *custom* WebGPU and Nexus.cpp inference engines and
GGUF chat with hardware profiles. Browser trial needs a WebGPU adapter and has
no CPU fallback; native app needs CPython 3.10+. Custom license: distribution,
modification, production, and commercial use need express written consent.
**Verdict: needs GPU** (WebGPU required, no CPU fallback stated; native CPU
path unproven — inferred).
**Teaches us:** the negative example — a custom engine means exact
arch/tokenizer/quant matching per model; stick to llama.cpp/Ollama and skip
bespoke runtimes.

### 34. E.L.L.A. — https://github.com/AndreZ1971/E.L.L.A.-Embedded-Local-Logic-Agent
Windows-only offline assistant (operates your PC) with a hardcoded safety
"Directive"; LLM via local Ollama, model is your choice. Proprietary —
license key required. Needs 16–32 GB RAM and an NVIDIA GPU (CPU fallback
stated at 3–5 tok/s).
**Verdict: needs GPU** (and Windows-only — a double miss for this lab).
**Teaches us:** a sealed, non-overridable safety directive as product
differentiator — a pattern worth copying into lab agent prompts.

### 35. Dunju Local Custom AI — https://github.com/dunjuai/dunju-local-custom-ai
Private local assistant: modern chat, 6 pin-able AI experts (per-expert Ollama
model), whole-document RAG (local `nomic-embed-text` + SQLite, BM25+semantic
hybrid, citations), doc export, folder automation. Default model Qwen3.5 4B.
MIT, "free forever". Needs Windows 10/11, 8 GB RAM (16 recommended),
Python 3.10+, Ollama.
**Verdict: Windows-only** (spec-wise it fits 8 GB + 4B Ollama, but the backend
is stated Windows-specific).
**Teaches us:** per-expert model pinning and SQLite RAG with no vector DB —
both directly portable to a Mini setup.

## PART H — Widely-adopted harness comparison + proposal (2026-11-14)

Sources: agent-reach github reads (`/tmp/reach7/110-117,122-125`), host web
search (Pi/Crush/OpenClaw identity, Hermes v0.22 local story, opencode home
redirect sst→anomalyco verified by GitHub 301), stars from READMEs,
user-pasted 5-task benchmark
(Pi 1m36s, goose 2m51s, Crush 3m31s, Atomic 4m38s zero-broken-calls, Cline
5m56s, OpenClaw 5m44s lean-mode, OpenCode 17m43s overthinking, Hermes failed
T3 overfit, Qwen Code 6m00s miscount).

| harness | local story (stated?) | bench | license | fit |
|---|---|---|---|---|
| Pi (earendil-works, MIT, 112k★) | unified providers; Ollama UNSTATED in README | 1m36s win | MIT | PROVE FIRST: 4 tools/<1k prompt is small-model-shaped |
| Crush (charmbracelet, FSL) | ollama/llamacpp/lmstudio/litellm provider types | 3m31s clean | FSL (not fully open) | strongest stated local story |
| goose (Linux Fdn) | 15+ providers incl Ollama | 2m51s solid | open | big-backing fallback |
| Cline (VS Code ext) | Ollama/LM Studio + OpenAI-compat + MCP | 5m56s | open | IDE-bound, headless-hard |
| Qwen Code (QwenLM) | Ollama/vLLM, runtime switch, subagents, MCP | 6m00s | open | Qwen-roster experiment |
| Atomic (bastani-inc) | llama.cpp/Ollama/LMStudio/vLLM/SGLang/HF | 4m38s, zero false | check repo | verifiable-graphs angle |
| Aider | "almost any LLM incl local" | untested | open | veteran, stable |
| SmallCode | small-model-designed (parser/budgets/timeouts) | untested (its own suites exist) | MIT | ONLY purpose-built pick; 8B floor |
| Hermes (NousResearch, MIT, 260k★) | one-click llama.cpp + fit rater (articles; README thin) | failed T3 | MIT | overweight scope; borrow fit-rater idea |
| OpenCode (anomalyco) | 75+ providers/Ollama (comparison source) | 17m43s WORST | open; free tier app-locked | overthinks small; frontier-only |
| OpenClaw | local-models doc demands 2× Mac Studios | 5m44s lean | open | EXCLUDE for Mini |
| Continue | dead upstream (read-only) | — | — | EXCLUDE |

Proposal (search-first: compose + extend, install needs owner yes):
1. TRIAL Pi + Crush + SmallCode on the MacBook, all pointed at the Mini's
   Ollama endpoint, same 5 tasks, qwen2.5-coder:3b first. Measure wall time,
   broken tool calls, overfit/miscount. Pi is the hypothesis (leanest wins
   small); Crush the hedge (explicit local types); SmallCode the baseline.
2. ADOPT winner + SmallCode's benchmark suites as the lab's timed loop.
3. Qwen Code as second-round experiment (subagent teams on the Qwen roster).
4. EXCLUDE OpenCode-as-primary (small-model overthink), OpenClaw (big iron),
   Continue (dead), Hermes-as-harness (scope); revisit Hermes fit-rater +
   OpenCode frontier overflow later.
5. All harnesses run on the MacBook, Mini only serves /v1 (per w46 lane split).

## Tally

- fits Mini: LocalAI, LocalAGI, llama.cpp, SmallCode, local-deep-research,
  nanobot, Codewhale, llamafile, OmniGet, Surf (soft), awesome-local-llm (doc),
  Algernon, Atomic Chat, Observer, Row-Bot, NobodyWho, Ouroboros, gawkbot — 18
- unverifiable: rpocket (tagline-only fetch) — 1
- MacBook-only: SiliconScope, Rapid-MLX, claude-code-local, MTPLX, mlx-serve,
  Parlor, vllm-mlx, Locally Uncensored (Intel excluded by name) — 8
- needs GPU: Soup, Project Maya, HyperQwen, ATLAS, Nexus-AI-Studio, E.L.L.A.
  (also Windows-only) — 6
- Windows-only (spec fits): Dunju — 1
- dead-deprecated: USB-Uncensored-LLM — 1

## Top-5 actionable recommendations (ranked, sparring-corrected)

1. **Make SmallCode + Mini Ollama the primary coding harness this week —
   with a dual baseline.** It is the only repo in the set designed for small
   local models (forgiving tool parser, context budgets, TODO decomposition,
   patch-not-rewrite, a timeout knob that names "slow CPU-only llama.cpp
   servers"). Caveat: its own floor is 8B while the Mini's proven tier is
   ≤4B — so baseline at BOTH 8B Q4 and 4B on the 5 pasted tasks; if 8B swaps,
   the pick is provisional.
2. **Stand up Atomic Chat as the Mini's serving layer.** Sole in-set stack
   with stated 8GB-for-3B + CPU TurboQuant (~4.3× smaller KV) + OpenAI-compat
   server + integrations for OpenCode/Goose/Kilo/OpenClaude. Evaluate it
   against stock Ollama on the same 5 tasks.
3. **Constrain tool calls by grammar, not by hope.** NobodyWho generates
   structured grammars from function signatures (stated, with CPU fallback
   and an experimental OpenAI-compat server). Copy the pattern into whatever
   harness wins, and count broken calls as the headline reliability metric
   next to wall time.
4. **Standardize every harness on the Ollama/OpenAI-compatible endpoint and
   serialize heavy work.** Codewhale, nanobot, Observer, Row-Bot, gawkbot, and
   LocalAI all speak it — so models swap without workflow changes (the Unsloth
   pattern from the voices note). One inference job at a time on the Mini;
   queue embeddings/OCR behind it (the Paperless lesson: qwen3.5:4b Q4_K_M is
   the proven CPU tier on 16 GB; 8 GB still unproven in-set).
5. **Extend SmallCode's shipped benchmark instead of building one — with
   MacBook overflow.** Its smoke/polyglot-mini/tool-use suites + CI diff
   already run "against any local model": adopt them as the lab's timed loop
   (wall time, broken calls, overfit/miscount axes), reject harnesses that
   can't beat the SmallCode baseline on reliability-adjusted time, and route
   7B+/big-ctx overflow to the MacBook via an MLX server (Rapid-MLX for
   tool-call reliability, mlx-serve for Ollama-API compat).

## Gap analysis — what nobody in this set solves for 8 GB CPU-only

- **No coding harness targets ≤4B.** SmallCode wants 8B–35B and says ≤4B
  "struggles with multi-step tool use"; ATLAS wants 16 GB+ VRAM. The Mini's
  actual tier (0.5B–4B CPU) has no purpose-built harness.
- **No CPU speculative-decoding story.** All MTP/speculative speedups here are
  MLX- or CUDA-side (MTPLX, Atomic-on-MLX, HyperQwen). Nothing shows how to get
  that ~2× on CPU-only llama.cpp/Ollama.
- **No 8 GB model-fit picker for the Ollama path.** mlx-serve suggests models
  per Mac and Unsloth picks quants per device, but both are app/GPU-side. The
  Mini needs: given RAM + quant + ctx, which model runs without swap death.
  (Pattern exists in-set: NobodyWho `auto` fit-mode, LU model manager —
  neither on the Ollama path.)
- **No standalone tool-call repair proxy.** Self-healing retries live inside
  apps (Unsloth) and grammars need per-harness integration (NobodyWho). No
  drop-in "endpoint that fixes small-model tool JSON" exists here.
- **No job serializer / RAM-budget enforcer.** Paperless serializes manually;
  nothing in this set queues OCR/embed/inference or refuses a load that would
  OOM 8 GB.
- **No published CPU-only numbers.** SmallCode ships the harness
  (smoke/polyglot-mini/tool-use + CI diff) — extend it instead of building
  from scratch. The lab's Pi-vs-OpenCode timing has no public counterpart
  to compare against.

## Note on the pasted harness benchmark

Claimed results on 5 small-model coding tasks: Pi v1.3.0 1m36s (winner), goose
2m51s, Crush 3m31s, Hermes 4m36s FAILED T3 (overfit the visible test), Atomic
Agent 4m38s (zero broken tool calls), OpenClaw 5m44s, Cline 5m56s, Qwen Code
6m00s (miscount), OpenCode 17m43s (overthinking, ~11× slowest).

What it implies for harness choice:

- **Harness overhead dominates small-task latency** (1m36s vs 17m43s on
  identical tasks), so the first selection filter is leanness: step budgets,
  call budgets, no unprompted exploration. This corroborates SmallCode's
  anti-OpenCode thesis from the README set.
- **Reliability separates the middle more than speed.** Hermes lost by
  overfitting, Qwen Code by miscounting, Atomic won its tier with zero broken
  calls — so score verification (holdout tests, not visible ones) and tool-call
  validity above raw tok/s.
- **Frontier-oriented harnesses punish small models.** OpenCode assumes 128K+
  context and perfect tools (per SmallCode's comparison table); on a small
  model that assumption becomes 17 minutes of overthinking. Never evaluate a
  harness without naming the model tier it was built for.
- **Practical takeaway:** shortlist Pi-style lean harnesses, verify with
  holdout tasks, and treat Atomic's "zero broken calls" as the reliability bar
  the lab's grammar-constrained setup must clear.
