# RESEARCH: LLM-infra master list — verification + Local AI Lab fit map

Captured 2026-10-27 in worktree `wt-lab-research` (branch `research/assist`).
Verification evidence: `agent-reach github read <owner/repo>` (gh backend, live GitHub
metadata) and `agent-reach web read/search` for flag + deployment claims. All repo
timestamps are `pushed_at` from the GitHub API at capture time.

Lab envelope (from `AGENTS.md` + `docs/MODEL-FIT.md`): 2018 Intel Mac mini, 8 GB RAM
(~5.9 GB usable), **CPU-only** Ollama, 4k typical context, no 8B-plus models, existing
Caddy reverse proxy + feedback sidecar + weekly evals. "No GPU" and "no CUDA" are hard
constraints here.

---

## 1. Verification table

Legend: **verified** = repo exists under the stated owner/name, is alive (recent pushes,
not archived), and the specific flag/deployment claim checked out. **unverified** = repo
is real and alive but a sub-claim could not be fully pinned. **wrong** = the stated owner,
name, state, or a specific flag/claim is false or stale.

### Group 1 — Compute layer

| # | List entry | Status | Evidence (one line) |
|---|---|---|---|
| 1 | vllm-project/vllm | **verified** | Live, pushed 2026-10-27, Apache-2.0, 95.7k★; README lists prefix caching + EAGLE/speculative decoding + PagedAttention — exactly the stated claims. |
| 2 | sgl-project/sglang | **verified** | Live, pushed 2026-10-27, 38.3k★; RadixAttention confirmed (LMSYS blog + `python/sglang/srt/mem_cache/radix_cache.py` + official docs) — prefix-tree KV sharing is real. |
| 3 | ggml-org/llama.cpp | **verified (one flag wrong)** | Live, pushed 2026-10-27, 132.5k★; `--cache-reuse N` is real in `tools/server/README.md`. BUT `--lookup-ngram-min` does **not** exist — real flags are `--spec-ngram-mod-n-min` / `-lcs,-lcd --lookup-cache-static/dynamic`. Flag claim = wrong. |
| 4 | LMCache/LMCache | **verified** | Live, pushed 2026-10-27, 12.2k★; self-described "Fastest KV Cache Layer," integrates with vLLM/SGLang — matches the stated role. |
| 5 | ollama/ollama | **verified** | Live, pushed 2026-10-27, 185k★, MIT, Go; background daemon with CLI/API — matches claim. (This is the lab's current runtime.) |
| 6 | LocalAI/LocalAI | **wrong (owner)** | `LocalAI/LocalAI` returns HTTP 404. Canonical repo is **mudler/LocalAI** (live, pushed 2026-10-27, 50k★, Go). Also note: written in **Go**, not "C++" as the note claims; "drop-in OpenAI API, no GPU required, text/vision/audio/embeddings" is otherwise correct (localai.io). |

### Group 2 — Orchestration / routing

| # | List entry | Status | Evidence (one line) |
|---|---|---|---|
| 7 | lm-sys/RouteLLM | **unverified (stale)** | Exists, Apache-2.0, 5.6k★, **but last push 2024-08-10** — effectively dormant. Routes by predicted difficulty (claim plausible, repo alive-but-idle). |
| 8 | lemony-ai/cascadeflow | **verified** | Live, pushed 2026-09-25, 3.9k★, MIT; "cascading runtime… optimize cost/latency/quality inside the agent loop" — matches the escalation claim. |
| 9 | BerriAI/litellm | **verified** | Live, pushed 2026-10-27, 62k★; "AI Gateway… 100+ LLMs, cost tracking, load balancing, logging" — matches the gateway/budget claim. |
| 10 | ulab-uiuc/LLMRouter | **verified** | Live, pushed 2026-10-19, 3k★, MIT; "Open-Source Library for LLM Routing" — trainable-router claim consistent. |
| 11 | llama-swap (no owner given) | **verified (owner supplied)** | List gave no owner. Canonical is **mostlygeek/llama-swap** (live, pushed 2026-10-26, 6.1k★, Go): "reliable model swapping for any local OpenAI/Anthropic server — llama.cpp, vllm." Matches claim. |

### Group 3 — Compression / quantization

| # | List entry | Status | Evidence (one line) |
|---|---|---|---|
| 12 | turboderp/exllamav2 | **wrong (owner moved)** | `turboderp/exllamav2` redirects to **turboderp-org/exllamav2** (live, pushed 2026-03-04, 4.6k★). EXL2 bitrate quantization claim is correct; stated owner is stale. |
| 13 | casper-hansen/AutoAWQ | **wrong (archived)** | Exists but **archived** (read-only), last push 2025-05-11. 4-bit AWQ claim is accurate, but "alive" is false — the project is no longer maintained. |
| 14 | unslothai/unsloth | **verified** | Live, pushed 2026-10-27, 78.6k★, Apache-2.0; low-VRAM fine-tuning → GGUF/EXL2 export claim is standard-correct. (API-returned description string looked mismatched, but repo identity is right.) |

### Group 4 — Dashboards / web UIs

| # | List entry | Status | Evidence (one line) |
|---|---|---|---|
| 15 | open-webui/open-webui | **verified** | Live, pushed 2026-10-27, 157k★; "User-friendly AI Interface (Supports Ollama, OpenAI API…)" — self-hosted ChatGPT-style UI + RAG claim correct. |
| 16 | Mintplex-Labs/anything-llm | **verified** | Live, pushed 2026-10-26, 67.6k★; README states "**LanceDB (default)**" vector store — the embedded-LanceDB RAG claim is literally confirmed. |
| 17 | ItzCrazyKNS/Perplexica | **wrong (name/owner stale)** | Owner casing is `ItzCrazyKns` (not `…KNS`) and repo was **renamed to `Vane`** (redirects, live, 37.8k★). SearXNG + local-LLM cited-answers claim confirmed via README + install guides. |
| 18 | lobehub/lobe-chat | **wrong (renamed)** | `lobehub/lobe-chat` redirects to **lobehub/lobehub** (live, pushed 2026-10-27, 83.5k★). Modern chat dashboard supporting local endpoints — claim correct, name stale. |
| 19 | SillyTavern/SillyTavern | **verified** | Live, pushed 2026-10-02, 35k★, AGPL-3.0; "LLM Frontend for Power Users" — prompt-engineering / lorebook / roleplay claim correct. |

### Group 5 — Agents / voice / memory

| # | List entry | Status | Evidence (one line) |
|---|---|---|---|
| 20 | OpenClaw/openclaw | **verified** | Live, MIT, pushed today; 393,196★ independently confirmed via the GitHub API (user-verified 2026-10-27) — the count is real, not implausible. GitHub owner names are case-insensitive, so `OpenClaw` vs `openclaw` is a non-issue. "Background local-agent runner" claim is consistent with the repo. |
| 21 | livekit/agents | **verified** | Live, pushed 2026-10-27, 15k★, Apache-2.0; "framework for building realtime voice AI agents" — WebRTC + STT/TTS claim correct. |
| 22 | mem0ai/mem0 | **verified** | Live, pushed 2026-10-26, 67.9k★, Apache-2.0; OSS stack extracts facts/preferences into a local vector store (Qdrant default, per mem0 docs) — claim correct. |

---

## 2. Mapping — verified entries vs the Local AI Lab

Only entries that verified (or verified with a corrected owner/name) are mapped. The two
**wrong-and-dead** entries (AutoAWQ archived; LocalAI/LocalAI 404) are flagged but not
recommended on that basis. OpenClaw verified fine but is excluded on hardware grounds
(below). Hard filter: **CPU-only,
8 GB, 4k context, no 8B+.**

Verdicts: **fits now** / **fits with work** / **does not fit**.

| Tool (corrected id) | Verdict | Why (one line) |
|---|---|---|
| ollama/ollama | **fits now** | Already the lab's runtime; the entire envelope is defined around it. |
| ggml-org/llama.cpp | **fits now** | CPU/Apple-Silicon-first GGUF server; `--cache-reuse` prompt caching is a real win on a slow CPU box. Ollama already embeds it. |
| BerriAI/litellm | **fits now** | Pure proxy/gateway, negligible RAM; drops in front of Ollama for cost tracking + budgets alongside existing Caddy. |
| mostlygeek/llama-swap | **fits now** | Lightweight Go swap-proxy; manages loading/unloading the small GGUF models the lab already juggles under 8 GB. |
| Mintplex-Labs/anything-llm | **fits with work** | Embedded LanceDB RAG runs CPU-only, but comfortable use wants more RAM; viable for small doc sets with a tiny embedder (bge-m3 is already a planned pull). |
| open-webui/open-webui | **fits with work** | Talks to Ollama directly, but Docker + Python stack is heavy on 8 GB — run it on another tailnet device pointing at the Mini, not on the Mini. |
| SillyTavern/SillyTavern | **fits with work** | Node frontend is light; just point it at the Mini's OpenAI-compatible endpoint. Better hosted off-box. |
| mem0ai/mem0 | **fits with work** | Memory layer itself is light, but needs a vector DB (Qdrant) + an embedding model running somewhere; feasible if embeddings stay tiny/off-box. |
| ItzCrazyKns/Vane (ex-Perplexica) | **fits with work** | Works with local Ollama, but requires a separate SearXNG instance; stack is best hosted off the Mini, querying it over the tailnet. |
| lobehub/lobehub (ex-lobe-chat) | **fits with work** | Supports local endpoints; heavy web app — host off-box, point at the Mini. |
| lemony-ai/cascadeflow | **fits with work** | Cascade/escalation maps well to the lab's tiny-first routing, but on one CPU box "escalate" means a bigger slow model, not a second GPU — value is capped by having no large local tier. |
| ulab-uiuc/LLMRouter | **fits with work** | Trainable routing is useful across the lab's small models, but it adds a classifier to train/host; worth it only once there are several specialized micro-models online. |
| lm-sys/RouteLLM | **does not fit** | Dormant since 2024-08 and its premise (route cheap-vs-expensive) needs a strong large tier the 8 GB CPU box cannot host. |
| sgl-project/sglang | **does not fit** | GPU-oriented high-throughput server; RadixAttention's benefit assumes GPU + concurrency this box does not have. |
| vllm-project/vllm | **does not fit** | CPU build exists but it targets NVIDIA/AMD throughput; on an 8 GB CPU Mini it offers no advantage over llama.cpp/Ollama. |
| LMCache/LMCache | **does not fit** | KV-cache layer designed to sit on vLLM/SGLang across GPU nodes — no substrate for it here. |
| turboderp-org/exllamav2 | **does not fit** | EXL2 inference is consumer-GPU (CUDA) only; useless on a CPU-only box. |
| casper-hansen/AutoAWQ | **does not fit** | AWQ is GPU-targeted *and* the repo is archived; double no. |
| unslothai/unsloth | **does not fit** | Fine-tuning needs a CUDA GPU; the Mini can consume the GGUF/EXL2 *outputs* but cannot run unsloth itself. |
| livekit/agents | **does not fit** | Real-time voice (Whisper STT + TTS) on CPU-only 8 GB won't hold low latency; infra-heavy (WebRTC) for this box. |
| openclaw/openclaw | **does not fit** | Metric now verified (393k★, live), but a local autonomous-agent runner is an always-on process the 8 GB CPU box has no headroom for alongside Caddy + sidecar + an inference model. Excluded on hardware grounds alone. |

---

## 3. Sources

- GitHub repo metadata (existence, `pushed_at`, archived, stars, license):
  `agent-reach github read <owner/repo>`, gh backend, 2026-10-27.
- llama.cpp flags: `raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md`
  — confirms `--cache-reuse N`; shows `--lookup-ngram-min` absent (real: `--spec-ngram-mod-n-min`).
- SGLang RadixAttention: LMSYS blog (lmsys.org/blog/2024-01-17-sglang), repo
  `python/sglang/srt/mem_cache/radix_cache.py`, official SGLang docs.
- anything-llm LanceDB default: `raw.githubusercontent.com/Mintplex-Labs/anything-llm/master/README.md`.
- Perplexica→Vane + SearXNG + Ollama: GitHub redirect + README + install guides.
- mem0 local vector store (Qdrant default): docs.mem0.ai/open-source/configuration.
- LocalAI drop-in / no-GPU: localai.io (canonical repo mudler/LocalAI).
- Lab envelope: workspace `AGENTS.md` and `docs/MODEL-FIT.md` (surveyed 2026-10-27).

Content from external sources was rephrased for compliance with licensing restrictions.
