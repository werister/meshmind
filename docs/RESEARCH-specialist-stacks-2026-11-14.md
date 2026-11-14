# Specialist stacks research: local multi-model coding setups + lightweight-stack optimization

Date: 2026-11-14. Author: stacks-researcher (child agent).
Method: PRIMARY sources only (official docs, source repos, specs, first-party papers/blogs).
Every claim cites the source that owns it with its exact URL.
No calls were made to the local lab; agent-reach was not used.
Leads verified: `/tmp/reach/05-gh-awesome.json` (8 repos), `/tmp/reach/07-web-agents.json` (8 articles),
plus llama.cpp router/speculative/quantize docs, Ollama Modelfile/API/FAQ/import docs,
Panda Router/PandaCode, Magpie, Lynkr, NeMo Switchyard, Copilot Fusion, Peen, Mixture-of-Agents.

Lab context (from parent): Intel Mac Mini, 8 GB RAM, CPU-only Ollama 0.40.16, ~41 small
models (0.5B–8B), serial load only.

---

## PART A — Lightweight CPU-stack optimization (official docs)

### A1. Ollama: what is actually tunable and where

**Modelfile `PARAMETER` (bake into the model).**
Source: https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx
Valid parameters include `num_ctx` ("size of the context window", default 2048),
`num_predict` (max tokens, default -1 infinite), `draft_num_predict` (speculative draft
tokens per step; separate draft models default to 4; embedded MTP tensors require setting it;
0 disables speculative drafting), `temperature` (0.8), `top_k` (40), `top_p` (0.9),
`min_p` (0.0), `repeat_last_n` (64), `repeat_penalty` (1.0), `seed` (0), `stop`.
Correction to a common assumption: `num_batch`, `num_thread`, `num_gpu` are **not**
Modelfile PARAMETERs. They are per-request API `options` (see below). `num_ctx` exists in both.

**API `options` + `keep_alive` (per request).**
Source: https://github.com/ollama/ollama/blob/main/docs/api.md
`keep_alive` "controls how long the model will stay loaded into memory following the request
(default: `5m`)" on `/api/generate`, `/api/chat`, embeddings endpoints. Empty prompt/messages
with `keep_alive: 0` unloads the model. The options-object example shows `num_ctx`, `num_batch`,
`num_gpu`, `main_gpu`, `use_mmap`, `num_thread` as runtime options.

**Keep-alive semantics.**
Source: https://github.com/ollama/ollama/blob/main/docs/faq.mdx
`keep_alive` accepts a duration string ("10m", "24h"), seconds (3600), or any negative number
to pin in memory. `OLLAMA_KEEP_ALIVE` sets the server-wide default; the per-request parameter
overrides it. `keep_alive: 0` unloads and frees memory. Serial-load implication: pin one model
with -1, or explicitly unload (`keep_alive: 0`) before switching to avoid two residents in 8 GB.

**Concurrency / memory knobs (server env).**
Source: https://github.com/ollama/ollama/blob/main/docs/faq.mdx
- `OLLAMA_MAX_LOADED_MODELS`: max concurrently loaded models "provided they fit in available
  memory. The default is 3 * the number of GPUs or 3 for CPU inference." On an 8 GB CPU box the
  fit-check, not the count, is the binding constraint; set 1 for strict serial load.
- `OLLAMA_NUM_PARALLEL`: "maximum number of parallel requests each model will process at the
  same time, default 1. Required RAM will scale by `OLLAMA_NUM_PARALLEL` * `OLLAMA_CONTEXT_LENGTH`."
- `OLLAMA_MAX_QUEUE`: "maximum number of requests Ollama will queue when busy", default 512;
  over-limit returns `503` overloaded.

**Context length.**
Source: https://github.com/ollama/ollama/blob/main/docs/context-length.mdx
VRAM-based defaults: <24 GiB → 4k; 24–48 GiB → 32k; ≥48 GiB → 256k. Override with
`OLLAMA_CONTEXT_LENGTH=64000 ollama serve` (agents/coding tools "should be set to at least
64000 tokens" per this doc — unrealistic on 8 GB CPU; treat as cloud-oriented advice).
`ollama ps` shows per-model PROCESSOR/CONTEXT/UNTIL for verifying placement and residency.

**Memory-saving inference features.**
Source: https://github.com/ollama/ollama/blob/main/docs/faq.mdx
- Flash Attention "can significantly reduce memory usage as the context size grows. Ollama uses
  Flash Attention automatically when the selected backend and devices support it";
  `OLLAMA_FLASH_ATTENTION=1` forces on, `=0` forces off.
- `OLLAMA_KV_CACHE_TYPE`: "quantization type for the K/V cache. Default is `f16`." Global option:
  all models run with the specified type. This is the cheapest context-memory lever on CPU.

**Quantization / import (important negative result).**
Source: https://github.com/ollama/ollama/blob/main/docs/import.mdx
"Ollama does not quantize GGUF models during import. Prepare and quantize them first with a GGUF
tool such as llama.cpp's `llama-quantize`." (Source links
https://github.com/ggml-org/llama.cpp/tree/master/tools/quantize.)
`FROM` accepts a Safetensors directory, a single `.gguf`, or split shards via wildcard
(`FROM ./model-*.gguf`). So the lab's quant pipeline must be llama.cpp-side (A3), not Ollama-side.

### A2. llama.cpp router mode (multi-model serving from one endpoint)

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

- Launch `llama-server` **without specifying any model** to enter router mode: the main process
  exposes load/unload APIs and forwards each request to the appropriate per-model child instance.
- Three model sources: (1) cache (`LLAMA_CACHE`; add HF models with `llama-server -hf user/model:tag`,
  restart required after adding), (2) `--models-dir ./dir` (flat GGUFs; multimodal = subdir with
  `mmproj*` file; multi-shard = subdir of shards), (3) `--models-preset ./my-models.ini`.
- Flags: `--models-dir`, `--models-preset` (INI path), `--models-max N` ("maximum number of models
  to load simultaneously (default: 4, 0 = unlimited)"), `--models-memory-margin N` (MiB free per
  device, LRU-unload until a new model fits; default 0 = disabled), `--models-autoload /
  --no-models-autoload` (default enabled; per-request `?autoload=true|false` override).
- Child instances inherit CLI args and env from the router; router-wide defaults can be passed on
  the router command line (e.g. `llama-server -ctx 8192 -n 1024 -np 2`).
- Preset INI: each section is a preset; keys are CLI flags without dashes (`n-gpu-layers = 123`);
  short forms (`c`, `ngl`) and env names (`LLAMA_ARG_N_GPU_LAYERS`) also work; `[*]` is the global
  section. Precedence: CLI args > model-specific section > `[*]`. Router-controlled keys (host,
  port, API key, HF repo, alias) are removed/overwritten. Preset-only keys: `load-on-startup`
  (bool), `stop-timeout` (seconds, default 10), `dedup-cache-models` (bool).
- Routing: POST endpoints use the `"model"` JSON field; GET endpoints (`/props`, `/metrics`) and
  the `/v1/realtime` WebSocket use the `model` query param. `POST /models/load` (+ unload/status,
  `GET /models`, `/models/sse` events) manage residency. Unlisted-model sections need at least
  `model = /path/to/model.gguf` or an `hf-repo`.
- **CPU-lab caveat, stated in the doc:** "Host (CPU) memory is assumed to be unlimited, as with
  `--fit`. On a build without GPU devices the memory limit has no effect." I.e. `--models-memory-margin`
  does nothing on a CPU-only box; use `--models-max 1` + small pinned `-c` per preset to serialize.
  The router "never touches a GPU"; measurements come from short-lived child probes (`min` at
  `--fit-ctx`, `max` at largest fitting ctx, `effective` at load), exposed in `GET /models`.

### A3. GGUF quantization pipeline (llama.cpp)

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/quantize (README.md)
Two phases: (1) `convert_hf_to_gguf.py --outfile model-bf16.gguf --outtype bf16 --remote <hf-repo>`;
(2) `llama-quantize <in-bf16.gguf> <out.gguf> Q4_K_M`. Notable options: `--allow-requantize`
("can severely reduce quality compared to quantizing from 16bit or 32bit"), `--leave-output-tensor`,
`--pure` (disable k-quant mixtures), `--imatrix` + `--include-weights/--exclude-weights`,
`--output-tensor-type`, `--token-embedding-type`, `--keep-split`, `--tensor-type <regex>=<quant>`
(multi), `--prune-layers`, `--override-kv`. Multimodal projectors "are usually kept in a
high-quality format such as bf16 or q8" because quant impact on speed/memory is negligible but
quality impact is direct. No-setup alternative: https://huggingface.co/spaces/ggml-org/gguf-my-repo
("syncs from llama.cpp `main` every 6 hours").

### A4. Speculative decoding (llama-server; Ollama hook)

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Mechanism: draft tokens fast, verify with the target in one batch; wins when drafts are
  frequently accepted. A draft-model method "can be mixed with" a non-draft method.
- `--spec-type` (comma-separated, default `none`): `draft-simple` (standalone small draft model,
  "the most used approach"), `draft-eagle3` (1-layer transformer reading target hidden states;
  convert with `--target-model-dir`; shares tokenizer; supported checkpoints listed incl.
  AngelSlim/Qwen3-*_eagle3, Tengyunw/qwen3_8b_eagle3), `draft-dflash` (block-diffusion, whole block
  per step; `--spec-draft-n-max` clamped to trained block size), `draft-dspark`, `draft-mtp`
  (MTP heads from the main model), plus **no-draft-model** n-gram types: `ngram-cache`,
  `ngram-simple`, `ngram-map-k`, `ngram-map-k4v` (experimental), `ngram-mod`.
- Draft flags: `--spec-draft-model, -md, --model-draft FNAME`; draft cache types
  (`--cache-type-k/v-draft`), `--override-tensor-draft`, `--cpu-moe-draft`,
  `--n-cpu-moe-draft`; per-ngram size/hits tunables (`-size-n`, `-size-m`, `-min-hits`).
- Observability: per-run stats (`draft acceptance rate`, `#gen/#acc drafts/tokens`,
  `dur(b,g,a)`); end-to-end comparison via SPEED-Bench:
  https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- Ollama-side hook: Modelfile/API `draft_num_predict` (source A1) — "Separate draft models
  default to 4; embedded MTP tensors require setting this parameter."
- CPU-lab note: draft-model spec decoding needs **two** models resident (draft + target), which
  fights an 8 GB serial budget; the n-gram `--spec-type` variants need no second model and are
  the cheap experiment. (Inference from the doc's flag structure, not a quoted claim.)

---

## PART B — Combining specialist models for coding (patterns + primary implementations)

### B1. Request routing (classify once, run one model)

**B1a. Panda Router: 31 MB local ONNX profiler + deterministic policy.**
Source: https://github.com/AICodeKing/PandaOrchestrator (README.md)
Ettin-32M int8 ONNX encoder (distilled from a 150M teacher) reads task text and emits category,
difficulty 1–10, skill levels, flags, token estimate. A learned success head gives calibrated
P(success) per trained model; untrained cards use a conservative prior. A deterministic policy scores
~65 model cards (Claude, Codex/GPT, Grok, GLM, Kimi, top OpenRouter, **Ollama library models**) by
P(success), expected cost (failures included), latency, under modes `max_utility` (default),
`max_quality`, `cheapest_above_threshold` (+ `--min-p`, `--max-cost`, `--local-only`).
Returns choice + ranking + `escalation_ladder` + trace_id; a route takes "roughly 10-25 ms on a CPU.
Nothing leaves your machine." Explicit scope: "The router returns a model *name*. It does not call
the model or check its answer." Interfaces: CLI (`panda-router route`), HTTP server
(`panda-router-serve`, `/route` `/escalate` `/outcome`), MCP server (`route_task`, `escalate_task`,
`record_outcome`, `list_models`), Python API, SQLite outcome logging. Trained artifacts ship in-repo
(`artifacts/panda-router-v4/`: int8 ONNX, heads.json, tokenizer); outside a checkout it falls back
to a weaker keyword-heuristic profiler. Companion docs: `docs/INTEGRATIONS.md` (mapping picks to
`claude --model` / `codex -m` / `ollama run` / OpenRouter slugs), `docs/BEST_RESULTS.md`
(route→verify→escalate loop), `docs/API.md`. Requires Python 3.12+; core serving deps are
onnxruntime + tokenizer + numpy/scipy/jsonschema (no torch).
Sibling project PandaCode (https://github.com/aicodeking/pandacode): Tauri 2 desktop workspace that
runs many coding CLIs side by side; PandaCode License = MIT + fork-attribution clause; no account,
no telemetry; ships macOS Intel builds.

**B1b. Lynkr: 4-tier complexity routing with local-first tiers.**
Sources: https://github.com/Fast-Editor/Lynkr (README.md),
https://github.com/Fast-Editor/Lynkr/blob/main/documentation/routing.md
Apache-2.0 Node.js proxy. Pipeline: Thinking-Budget → Force Patterns → Risk → Anchor-embedding
intent score + LLM classifier → Agentic detection → Tier → Cost optimization → kNN/Bandit → Provider.
Tiers: SIMPLE 0–19 / MEDIUM 20–50 / COMPLEX 51–75 / REASONING 76–100, configured by mandatory
`TIER_SIMPLE/MEDIUM/COMPLEX/REASONING=provider:model` (all four required or tiering disables to
static `MODEL_PROVIDER`). Canonical local pattern from the doc: `TIER_SIMPLE=ollama:llama3.2`
(free, local) with cloud models above; sticky sessions pin one routing decision per conversation
(content fingerprinting) with auto-escalation; `lynkr wrap claude` injects routing under coding
CLIs; TOON/RTK compression and sub-300ms semantic cache ride along. Self-reported numbers (label:
vendor's own claims in its README, not independently verified): 84% JSON / 53% tool-token reduction;
11/11 routing scenarios vs LiteLLM Auto Router v2 heuristic 4/11 and LLM-classifier 6–8/11
(`MODE=routing node benchmark-tier-routing.js`); Terminal-Bench core 42/80 for $1.54 vs
openrouter/auto 44/80 for $4.72; RouterArena (ICLR 2026, 8.4k queries) 67.65 arena / 68.41% acc at
$0.29 per 1K queries.

**B1c. NeMo Switchyard: embeddable Rust routing library + server.**
Sources: https://github.com/NVIDIA-NeMo/Switchyard (README.md),
https://github.com/NVIDIA-NeMo/Switchyard/blob/main/docs/routing_algorithms/overview.md,
https://github.com/NVIDIA-NeMo/Switchyard/blob/main/docs/getting_started.md,
https://docs.nvidia.com/nemo/gym/model-server/switchyard
"You own the model clients, credentials, and service. Switchyard supplies the routing decision"
via `Algorithm::run_stream` (`Step::CallModel` / `Step::CallDecision` / `Step::Done`). Route types
(TOML `llm_clients` → `targets` → `routes`, served as one model ID over OpenAI Chat / Anthropic
Messages / OpenAI Responses): `auto` (recommended preset, Execution with fixed settings, no extra
calls), `llm_classifier` capability/custom (judge picks strong/weak per request/turn/session),
`stage_router` (tool-result history picks the tier each turn, optional judge; plan/execute =
`capable_first`), `composite` (judge sets per-turn default, stage runs between), escalation
(`mode="escalation"`: weak serves until a judge reports the same failure on consecutive turns, then
latches to strong; needs session ID), `advisor` (one executor serves; stronger advisor reviews plans
and "done" claims; `fail_open` default true), `vgr` (efficient drafts, verified stay efficient),
`prefill_router` (experimental, no checkpoint supplied), `random`, `passthrough` (fixed baseline),
`subagents` table. Integrations: Envoy-based Agent Router (OpenAI-compatible), LiteLLM plugin
(experimental, pinned LiteLLM 1.102.0, stage+random only), NeMo Relay plugin (≥0.10, <1.0.0),
OpenRouter hosted (`model: nvidia/switchyard`), NeMo Gym `switchyard_model` server for benchmarked
route-vs-baseline comparison. Docs stress: "Evaluate the complete agent, model pool, and routing
configuration against your single-model baseline. A cheaper model call does not guarantee a cheaper
successfully completed task" (README; tuning loop in `docs/tuning/`).

**B1d. Copilot Fusion: cloud router with Single / Cascade / Critique patterns + local preview.**
Source: https://docs.github.com/en/copilot/concepts/models/copilot-fusion
"Intelligent runtime model router and orchestrator" choosing per request the execution pattern,
reasoning effort, and models from capability signals (reasoning, code generation, debugging, tool
use), plus real-time system health; routes along cache boundaries / complexity shifts to avoid
cache-cost churn. Patterns: Single (one model); Cascade ("efficient model drafts, judge inspects,
accept or escalate to stronger"); Critique ("one model drafts while multiple models independently
critique it in parallel... aggregated... original revises"). Effort levels Standard/High/Max/Fast
(plan-gated); no own context window (conservative minimum of member models); billed per model used
at standard rates, no Fusion surcharge (30% discount on paid plans through 2026-11-30); keeps the
main conversation on one model for cache, assistants get minimal context; limitations: no subagents,
discarded drafts' workspace edits are not undone, pool changes over time. Local routing
("Selecting local models in Copilot Fusion", public preview, Standard only, opt-in experimental):
MAI Code 1.1 Flash on qualifying Windows (CLI/app/VS Code) and Qwen3.8 Flash Next BYO via a provider
such as Ollama, identified as `qwen3.8-flash-next-local` (CLI only, Win/Mac/Linux); enable via
app setting "Local model auto routing" or CLI `--experimental` / `/experimental on`. Alternative the
doc names: pin a custom agent to a specific local model and delegate focused tasks to it.
Companion: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-llm-models —
CLI auto-discovers Ollama at `http://127.0.0.1:11434` (`OLLAMA_HOST` override; same-machine only,
else provider file), lists Discovered models under "Local and self-hosted", persists to
`providers.json`; model requirements: tool calling + streaming; "Configure token limits to match
your model, especially for smaller local models... default 128,000 prompt tokens... Setting a higher
limit does not increase the model's context window."

**B1e. llama.cpp router as a local specialist switch.**
Source: §A2 (same README). For the lab this is the zero-dependency router: per-role presets
(completer ctx 4k, reasoner ctx 16k, draft model attached only to one preset) behind one endpoint,
`--models-max 1` for serial discipline, routing by `"model"` field. No intelligence — the caller
(or Panda Router's pick) chooses the name.

**B1f. Magpie: local gateway + routing groups (failover, not intelligence).**
Sources: https://github.com/yetone/magpie (README.md), https://usemagpie.ai/docs/start,
https://usemagpie.ai/docs/local-models
MIT, Go. Gateway at `127.0.0.1:3425` speaks OpenAI Chat/Responses, Anthropic Messages, Gemini and
translates between them (streaming, tool calls, reasoning included), so e.g. Claude Code runs on
Ollama (`ollama/…`) and Codex on DeepSeek. Local presets: Ollama `http://localhost:11434`
(Chat + Anthropic passthrough), LM Studio `:1234`, oMLX `:8000`, MLX-Serve `:11234`, plus any
OpenAI-compatible URL (vLLM, llama.cpp server, other hosts). Every model is `provider/model`;
`magpie claude ollama/qwen3` rewrites the agent's own config. Routing groups (`group/<id>`,
`routing=smart`) fail over across models/accounts "when a quota runs out... so the agent never sees
the error"; privacy masking of keys/passwords/emails on-device (off by default); profiles
(`magpie save/use`), `magpie quota`, TUI/web/CLI, Docker, Termux. Install: `curl -fsSL
https://usemagpie.ai/install.sh | sh` or `go install github.com/yetone/magpie@latest`.
Positioning vs B1a–B1c: Magpie multiplexes and fails over; it does not score tasks or judge quality.

### B2. Cascades / escalation (try cheap, verify, escalate)

Same primitives recur across primaries: Panda `escalation_ladder` + `/escalate` after a failed
verify (B1a); Switchyard escalation route latching on repeated judged failure (B1c); Fusion Cascade
with a judge gate (B1d); Lynkr sticky-session auto-escalation (B1b). The shared contract the docs
agree on: the escalate step needs a **verifier** (judge model, tests, or deterministic checks) —
without it a cascade is just retries. EffGen's complexity routing (§B4) is the pre-execution mirror
image (predict difficulty before spending), while cascades are post-execution.

### B3. Parallel critique / Mixture-of-Agents (spend N models per step for quality)

**Mixture-of-Agents paper + code.**
Sources: https://arxiv.org/abs/2406.04692 (Wang et al., ICLR 2025, CC-BY-4.0),
https://github.com/togethercomputer/MoA (README.md, Apache-2.0)
Layered architecture: each layer holds several LLM agents; "Each agent takes all the outputs from
agents in the previous layer as auxiliary information in generating its response." MoA with only
open-source models scored 65.1% on AlpacaEval 2.0 vs 57.5% for GPT-4 Omni, and led MT-Bench/FLASK.
Code: `moa.py` (2 layers, 4 proposers + 1 aggregator, ~50 LOC over the Together API),
`advanced-moa.py` (3+ layers), `bot.py` interactive CLI. Cost shape: quality scales with layers ×
agents per layer — the opposite direction from a serial 8 GB box, but the 2-layer
propose→aggregate shape is directly portable (small proposers, one stronger aggregator).
**Local analogues in primaries:** Fusion Critique pattern (B1d); SGDe "structural consensus"
fan-out/fan-in with deterministic voting (§B4); Switchyard advisor gate (B1c). Sameer Kumar's
evaluator-optimizer rule (§B4): never let one model grade its own work; cap loops at 3–5.

### B4. Role splits + harness engineering for small models (the SLM-agent literature)

All eight `/tmp/reach/07-web-agents.json` items verified against their primary:

1. **EffGen** (ICML'26). https://arxiv.org/abs/2602.00887, https://proceedings.mlr.press/v306/srivastava26a.html,
   code https://github.com/ctrl-gaurav/effGen, package https://pypi.org/project/effgen/,
   site https://effgen.org/. Four contributions: tool-calling prompt optimization (70–80% max,
   57% average compression, semantics preserved), dependency-aware task decomposition
   (parallel/sequential), 5-factor complexity routing (pre-execution), unified short/long/vector
   memory; unifies MCP/A2A/ACP. 13 benchmarks beat LangChain/AutoGen/Smolagents on success, speed,
   memory. Scaling split: optimization helps SLMs more (11.2% @1.5B vs 2.4% @32B), routing helps
   large models more (3.6% @1.5B vs 7.9% @32B).
2. **SGDe / "Compiling Deterministic Structure into SLM Harnesses".**
   https://arxiv.org/abs/2604.17450, full text https://arxiv.org/html/2604.17450v3.
   Frontier teacher compiles workflows into DAG topology + prompts + deterministic code under PAC
   bounds (converges at m=3 examples). GSM-Hard-derived: 91.3% @m=5, 99.3% @m=3 (+26.3–34.3 abs over
   prompt optimizers). Two structures: **capability offloading** (delegate to Python where the SLM
   is unreliable — per-node, trace-driven, generalizing PAL/PoT) and **structural consensus**
   (fan-out/fan-in + deterministic voting on variance-sensitive steps).
3. **Bud ContextCompact 2.0.** https://arxiv.org/abs/2610.25516.
   Compaction to 16K lifted a 1.2B model to 0.335 recall (vs 0.247 truncated / 0.176 full-32K,
   p<0.001); 9B 32K: 0.515→0.577 (p=0.04). 100 SWE-bench Verified tasks (27B reasoner, 49K window,
   556 sessions): long sessions 41%→53% resolve (+12.3pp, CI +1.6–23, p=0.043), short unchanged,
   equal total tokens, 13% fewer tokens per solve. Dominant failure without compaction: a reasoning
   turn exhausting the room history left. Gain vanishes under a 45-min budget (median 161 s per
   summary) and unless the threshold fires early (~half the input budget for reasoning models).
   An 8B model (≈10 turns, 5–8K tokens) never needed compaction. Authors: accuracy transfers across
   hardware "including CPU inference" for equal model+window; time cost scales with hardware.
4. **Context-Aware Precision Scheduling.** https://arxiv.org/abs/2610.15640.
   Mixed-precision tensor schedule chosen per context length from a calibrated timing model +
   sensitivities under a latency or accuracy budget; "fewer bits do not always mean faster
   execution", so latency is predicted from measured costs, not weight bytes. Latency budget → lower
   precisions as KV-cache growth eats the budget; runtime follows a precomputed schedule while
   retaining the KV cache. Evaluated with executed schedules on a laptop GPU incl. a 3-format
   longer-context schedule and a tool-use benchmark.
5. **Mingbird (local-first harness for Ollama).** https://arxiv.org/abs/2610.02001,
   code https://github.com/Mingbird/Mingbird-agent. Ten mechanisms M1–M10: net-zero byte prefill
   budget, chat/task layering, finish gate + plan re-injection, signature anti-loop, false-finish /
   format rescue, edit safety (.bak), resilience layer, security boundary, capability surface,
   quality base. Backend is "whatever Ollama serves" with auto model detection (default 128K ctx, up
   to 256K). LRAB (4 harnesses × 4 models × 18 tasks): 0.886 vs 0.631 goose / 0.479 opencode / 0.405
   agent-mini, all 288 cells published; τ²-bench 0.856 vs 0.791/0.737; frontier probe spans
   0.997–0.478 across harnesses. Ablation directional only (±0.069 same-night noise; +0.10 paired for
   completion guards). Stated limits: self-built bench, single machine, single-trial scoring.
6. **Three Roles, One Model.** https://arxiv.org/abs/2604.11465.
   Frozen Qwen3-8B on AppWorld (single 24 GB GPU; FP16/12K and AWQ/32K): raw 5.4% / 3.0% goal
   completion → with summarizer (artifact-preserving) + main agent + isolated corrector (no history
   access): 8.9% / 5.9% — roughly doubling; difficulty-1 FP16 15.8%→26.3%, AWQ 5.3%→14.0%.
   Scaffolded 8B beats DeepSeek-Coder 33B Instruct (7.1%). Formalized as a scaffolded policy over
   frozen weights (test-time compute scaling). Direct evidence for completer/reviewer role splits —
   with absolute rates still <10%.
7. **Small-Model Hierarchy (Sameer Kumar, first-party blog).**
   https://sameerkumar.dev/blog/small-model-hierarchy-beats-the-giant-agent. Prescription: cheap
   router (output constrained by Pydantic `Literal`) → task SLMs; worker / service (QA, compliance) /
   support (oversight, data-flow) roles; MCP for tools/data, A2A for peer coordination; weight-only
   AWQ/GPTQ ("halve memory and latency"); 1B Gemma 4-bit LoRA ≈15 min on a laptop <9 GB RAM;
   evaluator-optimizer with separate generator/critic, 3–5 iteration cap; critical-path latency
   <1 s/step; fast path only for narrow outputs with bounded error cost + fallback. (Author's own
   synthesis; benchmarks cited are his claims, verify before quoting.)
8. **Microtask Eligibility Gap (caution).** https://arxiv.org/abs/2610.00025.
   4 harness microtasks (approve shell, write memory, select tools, rank turns) × Qwen3
   0.6/1.7/4/8B at best (FP16, greedy, frozen prompt): **0 of 16** configs clear CI-backed thresholds
   anchored to cheap non-LLM baselines; 4-bit RTN/GPTQ/AWQ move none into eligibility; replicates on
   Llama-3.x (12/12 ineligible) and across τ-sweeps + paraphrases (0/112). Prescription: put the SLM
   **behind** a baseline that meets the threshold; use it only where the baseline fails (e.g. 4B
   re-ranker over BM25 shortlist: +0.047 [0.020, 0.073], itself still uncertified).

**Peen: JSON tool-call CLI shaped to what local models already speak.**
Source: https://github.com/codazoda/peen (README.md; by Joel Dare).
Node.js "Claude Code / OpenCode"-style CLI over Ollama HTTP (`PEEN_HOST`, default
`http://127.0.0.1:11434`, `/api/tags` reachability check). Rationale (author's): local models are
trained mostly on JSON and stumble on the XML tool protocols of big-CLI tools, so Peen has the model
emit one-line JSON (`{"tool":"run","cmd":"ls -la"}`), executes with time/output limits, streams the
reply, and helps the model fix its own mistakes. `PEEN_MODEL` env or `--model`; recommended
qwen2.5-coder:7b / :14b, qwen3-coder:30b (GPU); self-updates from GitHub each start.
Community supplement (labeled as such, verbatim URL from search): Show HN thread
https://news.ycombinator.com/item?id=46899362.

---

## PART C — Awesome-SLM lists: all 8 verified against the repos themselves

Source of the lead list: `/tmp/reach/05-gh-awesome.json` (titles/descriptions/stars below cross-checked
by reading each repo's README).

| # | Repo (primary) | What it actually is | Relevance to specialist stacks |
|---|---|---|---|
| 1 | https://github.com/ro-ko/Awesome-SLM (CC0-1.0, last push 2024-06-24) | Milestone-papers table (2017–2024, citation badges) + SLM leaderboard / open SLM / data / eval sections | Historical map only; stale, pre-dates the routing literature |
| 2 | https://github.com/OpenCSGs/Awesome-SLMs | Survey: base models (OPT→2024), pretrain/SFT/synthetic/preference datasets, benchmarks; Chinese annotations | Data-side reference; no routing content |
| 3 | https://github.com/context-labs/awesome-open-workhorse-models | 2025+ only, open-weight **task specialists with named enterprise deployments**: ClipTagger-12B, ReaderLM-v2, Foundation-Sec-8B (Cisco/Splunk), ShieldGemma 2, Llama Guard 4, Qwen3-Coder, Schematron-8B/3B, SWE-grep + mini (Cognition/Windsurf) | Strongest direct support for the specialist thesis; entry criterion is literally "narrowly focused SLMs often beat general models on accuracy, latency, cost, control" |
| 4 | https://github.com/lif314/Awesome-SLMs | Small (vision)-language models + small VLAs / spatial VLMs; survey/blog/insight sections | Multimodal extension; peripheral to coding routing |
| 5 | https://github.com/4IK1d/awesome-slm (Apache-2.0) | Two-line stub: "SLMs ≤7B; Phi-2, Qwen-1.8B, TinyLLaMA" | Negligible; do not cite |
| 6 | https://github.com/ishandutta2007/Awesome-Small-Language-Models (MIT) | Essay history: encoders → early decoders → over-trained inference-optimal (Llama 3 8B/15T tokens, Phi) → R1-distilled reasoning SLMs; defines SLM as <10B, typically 1–8B | Background on why the lab's 0.5–8B range is the active frontier |
| 7 | https://github.com/ishandutta2007/Awesome-Edge-Small-Language-Models (MIT) | Edge/on-device ≤4B: engines, runtimes, quantized weights, toolchains; privacy/latency/opex/offline rationale | Closest to the 8 GB CPU constraint; engine shortlist source |
| 8 | https://github.com/madnessmichael/awesome-slm-agents (CC BY-4.0 docs / MIT scripts; AI-assisted provenance disclosed) | SLM-agent papers ≤10B: training/distillation, planning/recovery, memory, **multi-agent collaboration** (mesh RL, orchestrator+workers, latent codec), on-device, benchmarks | Direct reading list for role splits and collaboration |

## PART D — Lead-verification checklist

Every tasked lead resolved to a primary (exact URL read):

- [x] 8 awesome-SLM repos → Part C (READMEs read via raw.githubusercontent.com).
- [x] 8 agent articles → §B4 items 1–8 (arXiv abs pages + PMLR + first-party blog read).
- [x] llama.cpp router mode (`--models-preset`) → §A2.
- [x] Ollama Modelfile params (`num_ctx`, `draft_num_predict`, …) → §A1 (+ correction: `num_batch` /
      `num_thread` / `num_gpu` are API options, not Modelfile PARAMETERs).
- [x] Ollama `keep_alive` / `OLLAMA_KEEP_ALIVE` → §A1.
- [x] Ollama quantization stance → §A1 ("does not quantize GGUF during import").
- [x] llama-server speculative decoding (`--model-draft`, `--spec-type`) → §A4.
- [x] Panda Router / Panda Code → §B1a.
- [x] Magpie → §B1f.
- [x] Lynkr hierarchical/tiered routing → §B1b.
- [x] NeMo Switchyard → §B1c.
- [x] Copilot Fusion local routing → §B1d.
- [x] Peen → §B4 (tail).
- [x] Mixture-of-Agents (objective named it; not in lead list, verified anyway) → §B3.

Not verified / out of scope: Reddit/HN/X sentiment (only one HN URL recorded, labeled supplement);
any claim about the lab's own models (no local calls made by design); vendor benchmark numbers in
Lynkr/Mingbird readmes beyond reporting them as self-claims.

## PART E — What this means for the owner's lab (8 GB Intel Mac Mini, CPU-only, serial)

Grounded combines — each follows from a cited section above; no local probing was done.

1. **Serialize residency explicitly.** `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`,
   per-request `keep_alive` discipline (pin with -1 during a run, `keep_alive: 0` before switching),
   `ollama ps` to verify (§A1). If llama.cpp is the server instead: `--models-max 1`; do not expect
   `--models-memory-margin` to help (CPU memory "assumed unlimited", §A2).
2. **Shrink context per role.** Bake small `num_ctx` into role Modelfiles / preset `c` values
   (completer 2–4k, reasoner larger), since RAM scales with parallel×context and KV cache dominates
   (§A1); try `OLLAMA_KV_CACHE_TYPE` (q8/q4) + forced Flash Attention for the same window at lower
   bytes (§A1). Trigger compaction-style summarization at ~half the input budget for reasoning roles
   (ContextCompact, §B4.3).
3. **Quantize llama.cpp-side.** Ollama will not do it (§A1); pipeline is convert→bf16→`llama-quantize`
   with imatrix for the important tensors, Q4_K_M default, IQ quants for the 8B end, mmproj at
   bf16/q8 (§A3).
4. **Cheapest routing experiment that fits 8 GB:** Panda Router (31 MB, 10–25 ms CPU, Ollama cards
   included, `panda-router route` → `ollama run <pick>`) in front of 2–4 local specialists, with the
   route→verify→escalate loop from its BEST_RESULTS doc (§B1a). Zero-new-infra alternative: llama.cpp
   router presets as a name-based switch (§B1e).
5. **Cheapest cascade:** Lynkr's `TIER_SIMPLE=ollama:<small-coder>` pattern with sticky sessions
   (§B1b), or a hand cascade (0.5–1.7B draft → 7–8B verify/fix) with tests as the judge — every
   primary agrees the verifier is the load-bearing piece (§B2). Heed the Microtask Gap: keep a
   non-LLM baseline (linters, tests, BM25) in front and use the SLM where it fails (§B4.8).
6. **Cheapest role split:** Three-Roles shape on one frozen 8B (artifact-preserving summarizer,
   agent, isolated corrector) — ~2× on hard tasks in the paper, still <10% absolute (§B4.6); Peen's
   one-line-JSON tool protocol for the coder tier (§B4 tail); Mingbird's net-zero prefill budget +
   finish gate as harness rules (§B4.5).
7. **Speculative decoding:** skip draft-model setups under serial 8 GB (two residents); try n-gram
   `--spec-type` (no draft model) or Ollama `draft_num_predict`/MTP where supported (§A4).
8. **Unification across CLIs:** Magpie puts every agent's Ollama picks behind one gateway with
   failover groups (§B1f); Copilot CLI already auto-discovers local Ollama (§B1d) — set its token
   limits down for ≤8B models.

## Source list (every URL read for this report)

Ollama: https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx
https://github.com/ollama/ollama/blob/main/docs/api.md
https://github.com/ollama/ollama/blob/main/docs/faq.mdx
https://github.com/ollama/ollama/blob/main/docs/import.mdx
https://github.com/ollama/ollama/blob/main/docs/context-length.mdx
llama.cpp: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
https://github.com/ggml-org/llama.cpp/tree/master/tools/quantize
https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
Routers/gateways: https://github.com/AICodeKing/PandaOrchestrator
https://github.com/aicodeking/pandacode
https://github.com/yetone/magpie https://usemagpie.ai/docs/start https://usemagpie.ai/docs/local-models
https://github.com/Fast-Editor/Lynkr https://github.com/Fast-Editor/Lynkr/blob/main/documentation/routing.md
https://github.com/NVIDIA-NeMo/Switchyard
https://github.com/NVIDIA-NeMo/Switchyard/blob/main/docs/getting_started.md
https://github.com/NVIDIA-NeMo/Switchyard/blob/main/docs/routing_algorithms/overview.md
https://docs.nvidia.com/nemo/gym/model-server/switchyard
https://docs.github.com/en/copilot/concepts/models/copilot-fusion
https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-llm-models
https://github.com/codazoda/peen
Papers/code: https://arxiv.org/abs/2406.04692 https://github.com/togethercomputer/MoA
https://arxiv.org/abs/2602.00887 https://proceedings.mlr.press/v306/srivastava26a.html
https://github.com/ctrl-gaurav/effGen https://pypi.org/project/effgen/ https://effgen.org/
https://arxiv.org/abs/2604.17450 https://arxiv.org/abs/2610.25516 https://arxiv.org/abs/2610.15640
https://arxiv.org/abs/2610.02001 https://github.com/Mingbird/Mingbird-agent
https://arxiv.org/abs/2604.11465 https://arxiv.org/abs/2610.00025
https://sameerkumar.dev/blog/small-model-hierarchy-beats-the-giant-agent
Awesome lists: https://github.com/ro-ko/Awesome-SLM https://github.com/OpenCSGs/Awesome-SLMs
https://github.com/context-labs/awesome-open-workhorse-models https://github.com/lif314/Awesome-SLMs
https://github.com/4IK1d/awesome-slm https://github.com/ishandutta2007/Awesome-Small-Language-Models
https://github.com/ishandutta2007/Awesome-Edge-Small-Language-Models
https://github.com/madnessmichael/awesome-slm-agents
Community supplement (labeled): https://news.ycombinator.com/item?id=46899362

---

## PART F — Community voices (forums, Asia, video, hackathons, recent papers)

Method: agent-reach batches (reddit public-web, YouTube, Bilibili, V2EX, Xiaohongshu,
GitHub, web) + host web search (HN, general), 2026-11-14. Raw JSON in
`/tmp/reach/`, `/tmp/reach2/`–`/tmp/reach5/`. Everything below is labeled
community evidence (anecdotes/claims by the poster), NOT primary-verified,
except where it corroborates a Part A–E primary (noted). URLs verbatim.

### F1. Reddit: production local stacks and router setups

- **llama-server router in daily use.** Qwen 27B workhorse + Qwen 9B agent + Hyte
  translations behind `--models-max 1` + `router-config.ini` presets, model picked
  per request (`-fa on`, `-t 5`, lookup-cache flags).
  https://www.reddit.com/r/LocalLLaMA/comments/1sb3ecw/switching_models_locally_with_llamaserver_and_the/
- **Hybrid local coding agent (MCP `delegate_code`).** Cloud IDE-agent orchestrates;
  local 2–7B models do boilerplate. Two named failure modes: context bloat (KV cache
  eats 8 GB, speed collapses) and schema failures (small models panic-loop on generic
  tool errors). Fix: narrow delegated tasks + specific errors.
  https://www.reddit.com/r/LocalLLaMA/comments/1vq128f/making_small_local_models_actually_us/
- **Jev: tiny decider model over a 3B→26B-MoE ladder.** Picks the model per question
  (~0.5 s) AND checks each answer, re-routing refusals/empties to the bigger model.
  Matches Panda Router's shape (B1a) as a home-grown build.
  https://www.reddit.com/r/LocalLLaMA/comments/1wk0st3/routing_between_a_3b_a_4b_a_12b_and_a_26b_moe/
- **Multi-agent coding squad fully local (M5 Max 128 GB).**
  https://www.reddit.com/r/LocalLLM/comments/1uen4nv/i_run_a_multiagent_coding_squad_fully_l/
- **Qwen3 as first-class agent next to Claude/GPT-5.**
  https://www.reddit.com/r/LocalLLaMA/comments/1rkqs6p/local_llms_as_firstclass_agents_qwen3/
- **Fully-local multi-agent guide on RTX 3090 (pi.dev).**
  https://www.reddit.com/r/PiCodingAgent/comments/1tcxdc3/guide_running_a_fully_local_multia/
- **Production local-LLM fleet after 3 months of logged benchmarks.**
  https://www.reddit.com/r/LocalLLaMA/comments/1s1u02n/show_and_tell_my_production_local_llm/
- **Finetune+quantize 1–3B on 8 GB RAM (LoFT CLI).**
  https://www.reddit.com/r/LocalLLaMA/comments/1luiigi/tool_release_finetune_quantize_13b_ll/
- **Best small model on Intel Mac 8 GB CPU** (exact lab hardware class).
  https://www.reddit.com/r/LocalLLaMA/comments/1eq3v2z/whats_the_best_small_model_to_run_on_/
- **Gemma 4 12B Q3: +8.55% coding from tensor-level quant allocation.**
  https://www.reddit.com/r/LocalLLaMA/comments/1vnltec/gemma_4_12b_q3_855_coding_performance/
- **MoE quant comparison (LFM2-8B, OLMoE-1B-7B).**
  https://www.reddit.com/r/LocalLLaMA/comments/1rb5nxs/quick_moe_quantization_comparison_lfm/

### F2. V2EX (CN dev forum): framework wars + measured Mac setups

- **2026 deployment-framework shootout.** Crowd pick: cloud-perf TensorRT-LLM,
  flexible vLLM, agents SGLang, Mac oMLX, trial Ollama, phones MLC LLM. Commenters
  revolt: "Ollama/LM Studio are still llama.cpp underneath", "Ollama unsuitable —
  new-model support got slow since the cloud push" (corroborates our LFM3/0.32.1
  experience), "for IoT/debug/8 GB the most convenient is still llama.cpp".
  https://www.v2ex.com/t/1204848
- **Measured Mac inference-framework pick ("拒绝感觉有效").**
  https://www.v2ex.com/t/1214544
- **Mac local-model measured: 54 tok/s, "API savings ≈ one Mac mini/year".**
  https://www.v2ex.com/t/1251179
- **Ollama + Open WebUI + CPU advice for beginners.**
  https://www.v2ex.com/t/1107344

### F3. Hacker News (host web search; threads not deep-read)

- **Lynkr proxy thread** (hierarchical routing over local backends).
- **NeMo Switchyard thread** (smart routing lib; MoE skepticism for agentic coding).
- **Peen thread** (minimal JSON-tool-call CLI for local models).
  https://news.ycombinator.com/item?id=46899362
- **VT Code thread**: "most local models below 70B struggle with multi-turn tool use
  even when raw code generation is decent."
- **FrontierCode thread**: small fast models for routing + skill/prompt loading.
- **FunctionGemma 270M thread**: train-your-own function router idea.

### F4. Japan: measured flags and agent benchmarks (Qiita + Zenn)

- **llama.cpp flags measured on 8 GB: up to 5×.** ngl-by-binary-search, KV-cache
  math table, cache quant profiles (q8_0/q8_0 recommended ≈0 quality loss;
  V-cache weaker than K). Directly transferable to CPU budgeting.
  https://qiita.com/plasmon/items/7900af97e50390f74243
- **MoE-on-CPU flags measured** (Qwen 35B without experts on GPU going faster;
  3 extra flags).
  https://qiita.com/kenimo49/items/17f2160d71f71c98bf44
  https://qiita.com/kenimo49/items/dff3c8a2a0ee563ca16f
- **Same GGUF, Ollama slower than raw runtimes (4070 measured).**
  https://qiita.com/kenimo49/items/6c72194d6602ca345d88
- **LM Studio 10 tok/s → bundled llama-server direct 26 tok/s
  (`--n-cpu-moe 32` → 30).**
  https://qiita.com/mukai3/items/6fac7701e57360cc9c94
- **Ollama env-var memo for low-resource boxes.**
  https://qiita.com/ntrlmt/items/09492f437451a9595b3f
- **8 model types for agents + selection strategy** ("design multi-model
  architecture from day one", SLMs for routing/workers).
  https://zenn.dev/shineos/articles/ai-agent-llm-types-guide
- **On-prem tool-calling accuracy measured (20 tasks, pre-registered bars).**
  qwen3-coder:30b wins; gemma3:12b native tool-calling IMPOSSIBLE (HTTP 400);
  "general-bench rank does not predict tool-calling — measure on your own rig."
  Direct support for per-axis lab benchmarking.
  https://zenn.dev/daishiro/articles/local-llm-tool-calling-agent-benchmark
- **Nemotron-Nano-9B Japanese trial; Liquid Nanos (LFM2 task specialists).**
  https://zenn.dev/kun432/scraps/9363e45440d22f
  https://zenn.dev/kun432/scraps/41a34569d88037

### F5. Korea (velog): small-coder shortlists + hands-on quants

- **7 small coding models for 2026 local dev** (gpt-oss-20b MoE, Qwen3-VL-32B,
  Apriel thinker, Seed-OSS-36B, Phi-3.5-mini, StarCoder2, CodeGemma).
  https://velog.io/@sunny_123/2026%EB%85%84-%EB%A1%9C%EC%BB%AC-%EA%B0%9C%EB%B0%9C%EC%9D%84-%EC%9C%84%ED%95%9C-%ED%95%84%EC%88%98-%EC%86%8C%ED%98%95-%EC%BD%94%EB%94%A9-AI-%EB%AA%A8%EB%8D%B8-7%EA%B0%80%EC%A7%80
- **Gemma 4 E2B self-quantized to 4-bit + Ollama run (walkthrough).**
  https://velog.io/@wordi/Gemma-4-E2B-%EC%A7%81%EC%A0%91-%EC%96%91%EC%9E%90%ED%99%94-%EC%97%90%EC%84%9C-Ollama%EC%97%90%EC%84%9C-%EC%8B%A4%ED%96%89%ED%95%98%EA%B8%B0

### F6. China video (Bilibili titles; descriptions only, no content claims)

12 specialist small models; Taobao 0.3B phone model; Qwen 破甲版 by VRAM;
taming dead-looping local models; llama.cpp quant+deploy walkthroughs;
llama.cpp + MCP web search; **LFM3-VL-2B end-side <2 GB RAM**;
4 multi-agent collaboration patterns; Lorca local multi-agent group chat;
multi-agent dev hand-holding. Search JSON: `/tmp/reach2/13-*.json`,
`/tmp/reach2/14-*.json`, `/tmp/reach3/36-*.json`, `/tmp/reach4/43-*.json`,
`/tmp/reach4/44-*.json`. Subtitles need Bilibili login (not done).

### F7. Xiaohongshu: low signal for local stacks

Hits are Claude Code courses and AI-career workshops, not local optimization.
Search JSON: `/tmp/reach2/20-*.json`, `/tmp/reach3/37-*.json`,
`/tmp/reach4/47-*.json`. Not worth a login for this topic.

### F8. YouTube: titles + 1 transcript

Titles: "local LLM 10× slower than it should be", llama.cpp-vs-Ollama,
35B-on-6GB-VRAM guide, CPU ×4 speed, speculative decoding, KV-cache explainer.
One transcript read (small-vs-large trade-offs) was generic explainer content.
JP/KR searches hit the channel rate limit (retry after ~55 min); text coverage
via Qiita/Zenn/velog above substitutes. Search JSON: `/tmp/reach2/10-*.json`,
`/tmp/reach2/11-*.json`, `/tmp/reach3/34 attempted (rate-limited)`.

### F9. Hackathons: small-model wins are specialist splits

- **Build Small (OpenBMB × Hugging Face, $10k, 946 apps).** Winners split tasks
  across models: MiniCPM-V 4.6 (vision/docs) + MiniCPM5-1B (extraction/QA) in the
  travel-CRM winner; preference-understanding 1B + classic algorithms in routing.
  https://openbmb.cn/en/blog/build-small-hackathon-openbmb-awards
- **Small Models Hack (12 h, 100% laptop-local):** Pocketcoder (on-device coding
  assistant), Clawhive (swarm), air-gapped agents.
  https://the-open-accelerator.com/hackathon/past/SundAI-LLM/
- **2026 MCP & AI Agents winners (Solo.io).**
  https://www.solo.io/blog/celebrating-the-winners-of-the-2026-hackathon-for-mcp-ai-agents
- **GemmaGate (AMD hackathon).** https://lablab.ai/submissions/bl22l6dsfuhy0c5340cv3o4u

### F10. Recent academia: routing/cascades for code (abstracts or better)

- **Model Cascading for Code** (each model writes solutions + tests; climb only on
  failures; −26% avg cost, up to −70%): https://arxiv.org/html/2405.15842v1
- **SynConfRoute** (token-confidence + syntax validation router; 3B≈32B on
  routine FIM; −58% accelerator): https://arxiv.org/pdf/2605.04894
- **MCCom** (small-first completion, user-action deferral, −47.9% latency):
  https://arxiv.org/pdf/2603.05974
- **Routing-vs-cascades survey + review** (production combines both):
  https://arxiv.org/abs/2603.04445
  https://web.stanford.edu/~shuhuiq/blog/review-routing-cascades.html
- **Kiro Auto cascade** (async progress judge, handoff carries crux):
  https://kiro.dev/blog/model-cascade/
- **New variational routers** (abstracts): UCCI 2605.18796, RouteNLP 2604.23577,
  RLCascadeRouter 2608.15817, Pro-Router 2608.28726, Who-Pays 2610.23249,
  Signed-Rescue 2609.07786. JSON: `/tmp/reach4/51-web-arxiv.json`.

### F11. Gaps and limits of this sweep

- Bilibili subtitles: NEED_LOGIN (owner can `agent-reach login bilibili`).
- YouTube: rate-limited mid-sweep (retry ≥55 min); JP/KR video pending.
- Reddit opencli backend broken; public-web fallback worked (16 threads).
- V2EX node names unresolved (`machinelearning`, `llm`, `ai` 404); used hot +
  web-found threads instead.
- X/Twitter, TikTok, HN-deep-reads: not covered (login/key friction).

## PART G — Combined takeaways for the lab (community + primaries)

1. **Route, don't scale.** Every layer (papers, routers, home labs, hackathons)
   converges: tiny decider/router → specialist per task → verify → escalate.
   The lab's measured specialists (voters vs coders vs reasoners) are exactly the
   pool such a router needs.
2. **Verifiers are load-bearing.** Tests-as-gate (cascade-for-code), syntax checks
   (SynConfRoute), separate critic (never self-grade), async progress judges
   (Kiro). A cascade without a verifier is retries.
3. **Measure on your own rig.** General rank ≠ tool-calling (Zenn), Ollama ≠ raw
   llama.cpp speed (Qiita), new-model support lags on Ollama (V2EX + our LFM3).
   The lab's per-axis numbers are the asset; keep them coming.
4. **CPU levers that transfer:** KV-cache quant (q8_0/q8_0 ≈ free), per-role ctx
   budgets, `--models-max 1` serial discipline, n-gram speculative decoding before
   draft-model setups, quantize llama.cpp-side with imatrix.
5. **End-to-end coding is the missing benchmark.** Micro-benches (26-case, 100-bank)
   rank code-writing; nobody in this sweep published a full-app-build comparison
   across local SLMs. That is the Flappy Bird benchmark's opening.

