# Mini decoding + routing upgrades — primary-source deep dive

Box: Intel Mac Mini i5-8500B, 8 GB RAM, CPU-only, Ollama 0.40.16, small chat
models as voters/coders/reasoners via native `/api/chat` and `/v1`, serial load.
Method: primary sources only (official docs / source code / specs). Every
factual claim carries its exact URL. `[INFERENCE]` = my derivation, not a
source statement. Read-only work; no lab calls.

## 1. Grammar-constrained decoding for tool JSON

### Mechanism

- llama.cpp constrains sampling with GBNF grammars (GGML BNF); supported in
  `tools/cli`, `tools/completion` and `tools/server` —
  https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
- `llama-server` flags: `--grammar` / `--grammar-file`, plus
  `-j, --json-schema` / `-jf, --json-schema-file` ("JSON schema to constrain
  generations") —
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Per-request body fields `grammar` and `json_schema`; OpenAI-compat
  `response_format` supports `{"type":"json_object"}` and
  `{"type":"json_schema","schema":{...}}` including the OpenAI wrapper form
  `{"type":"json_schema","json_schema":{"name","strict","schema"}}` — same
  server README.
- JSON-Schema→grammar subset is defined by
  https://github.com/ggml-org/llama.cpp/blob/master/tests/test-json-schema-to-grammar.cpp
  (verified by reading it): const, enum, minimum/maximum, min/maxLength,
  items/minItems/maxItems, pattern/regexp, required/optional/additional
  properties, `$ref`, `anyOf`/`allOf`. Conversion FAILS only on unknown/invalid
  `type`, empty integer ranges, and unbalanced regexps.
- llama.cpp function calling (`chat.h`, server needs `--jinja`) supports native
  tool formats for Llama 3.x, Qwen 2.5 (+Coder), Hermes 2/3, Mistral Nemo,
  Functionary, Command R7B, GPT-OSS/Harmony, others; unrecognized templates fall
  back to a Generic handler that "may consume more tokens and be less
  efficient" —
  https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md
- Ollama native path (no sidecar): `format: "json"` or a full JSON Schema in
  `format` on `/api/chat` and `/api/generate`; docs advise also putting the
  schema in the prompt and lowering temperature (e.g. 0); "Structured outputs
  work through the OpenAI-compatible API via `response_format`" —
  https://docs.ollama.com/capabilities/structured-outputs and
  https://github.com/ollama/ollama/blob/main/docs/api.md
- Ollama `/v1/chat/completions` marks `response_format` and `tools` supported —
  https://docs.ollama.com/api/openai-compatibility.md
- Ollama tool calling is template-based (`tools` param in, `tool_calls` out;
  capability list at https://ollama.com/search?c=tool) — api.md above.
  `[INFERENCE]` No Ollama doc ties tool-call arguments to the grammar engine,
  so tool args on Ollama are model-generated text, not provably constrained.
- NobodyWho: "Fast, type-safe tool calling — automatically generates structured
  grammars from your function signatures, no schema writing needed"; Rust core
  wrapping llama.cpp —
  https://github.com/nobodywho-ooo/nobodywho/blob/main/README.md
- Outlines: "Guaranteed valid structure", same code across OpenAI/Ollama/vLLM;
  server integrations = vLLM and Ollama; local models = transformers and
  llama.cpp —
  https://github.com/dottxt-ai/outlines/blob/main/README.md
- llguidance: arbitrary CFG enforcement at "~50μs of CPU time per token (for
  128k tokenizer) with negligible startup costs"; "large subset" of JSON
  Schema; merged into llama.cpp in PR #10224, enabled with
  `-DLLAMA_LLGUIDANCE=ON`; v1.0.0 2025-06-23; shipped in OpenAI 2025-05-20 —
  https://github.com/guidance-ai/llguidance/blob/main/README.md

### Expected gain on THIS box

- `[INFERENCE]` Grammar/structured output eliminates the *syntax* failure class
  (unparseable JSON, truncated objects, wrong types) → expect that class to go
  to ~0. It does NOT fix semantic errors (wrong tool, wrong args, hallucinated
  enum values outside `enum:` — actually `enum` IS enforced, so closed
  vocabularies become reliable; open-ended strings stay fallible).
- `[INFERENCE]` Net broken-call reduction = current share of syntax-caused
  failures. On small CPU chat models doing tool JSON, syntax is typically a
  large share, so this is the highest-leverage single change — but measure the
  failure mix first (see test).

### Cost / risk

- Ollama `format` + temperature 0: ~zero cost, zero new deps, works on 0.40.16
  via both native and `/v1` paths (sources above).
- llama-server sidecar for true per-request `json_schema`/GBNF: second runtime
  beside Ollama, splits the 8 GB, adds ops surface. `[INFERENCE]`
- Outlines against local transformers on this CPU box: slow; against Ollama
  server it is a client wrapper, not a stronger guarantee. `[INFERENCE]`
- llguidance needs a custom llama.cpp build (`-DLLAMA_LLGUIDANCE=ON`); no
  Ollama integration documented. Build-from-source cost on an i5 Mac.
  `[INFERENCE]`
- NobodyWho is a client SDK (Swift/Kotlin/Python/Flutter/Godot bindings over
  its own llama.cpp core), not an Ollama plugin — adopting it means leaving
  Ollama serving. `[INFERENCE from its README architecture diagram]`

### Fit verdict

Do the Ollama-native layer now (`format` = schema, temperature 0, validate
with Pydantic-style code as the docs show). Reserve a llama-server sidecar
(side-by-side with Ollama, one model loaded at a time) for tool-call args only
if native `format` still leaves broken calls.

### How to test

A/B harness, no new infra: fix N tool-call prompts; run each with and without
`format` = the tool schema; record `json.loads` ok/fail, schema-validation
ok/fail, tokens/s, and time-to-first-token. Ship iff syntax-failure rate drops
without latency regression. Repeat on `/v1` with `response_format` to confirm
parity.

## 2. Speculative decoding on CPU

### Mechanism

- Principle: draft cheap tokens, verify them with the target model "in a
  single batch"; "substantial speedups when the draft predictions are
  frequently correct" —
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Draft-model path: `--spec-draft-model, -md, --model-draft`; tokens per round
  `--spec-draft-n-max` (default 3); dedicated draft CPU thread/mask/priority
  flags (`--spec-draft-threads`, etc.) — same doc.
- Draft-free n-gram paths (no second model): `ngram-simple` ("looks for the
  last n-gram in history that matches the current n-gram… simplest
  self-speculative approach with minimal overhead",
  `--spec-type ngram-simple --spec-draft-n-max 64`), `ngram-map-k`,
  `ngram-map-k4v`, and `ngram-mod` ("Lightweight (~16 MB)", hash pool shared
  across slots; applications: iterating over code/text, reasoning models
  repeating thinking in the final answer, summarization). `--spec-default`
  enables ngram-mod — same doc.
- Ollama-native knob: Modelfile/request `draft_num_predict` = "Maximum number
  of speculative draft tokens to predict per step when a draft model is
  available. Separate draft models default to 4; embedded MTP tensors require
  setting this parameter. Set to 0 to disable" —
  https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx
- GGUF names the MTP sidecar convention (`mtp-` prefix = "speculative-decoding
  draft module… oftentimes the MTP weights can be distributed inside the base
  model, in which case there is no separate sidecar") —
  https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
- UNVERIFIED from primary sources: a Modelfile `DRAFT` instruction attaching a
  separate draft file (the Modelfile reference TOC lists only
  FROM/PARAMETER/TEMPLATE/SYSTEM/LICENSE/MESSAGE/REQUIRES/CAPABILITY; no
  `DRAFT` entry found). Treat "Ollama + separate draft model" as unconfirmed
  until tested on 0.40.16.
- n-gram flags do not appear in the Ollama docs/source read (FAQ, api.md,
  modelfile.mdx, envconfig/config.go) — they are a llama-server-only path as
  documented. `[INFERENCE from verified absence]`

### Expected gain on THIS box

- `[INFERENCE]` CPU-bound decode changes the tradeoff vs GPU lore: batch
  verification still costs a full target forward pass, so net win ≈
  acceptance-rate × draft-cheapness − verification overhead. High-acceptance
  workloads (code iteration, reasoning echo, summarization — exactly the
  ngram-mod application list) can win; low-acceptance chat drafting loses.
- `[INFERENCE]` ngram-simple/ngram-mod: small but nearly free speedup on
  repetitive workloads (voters re-emitting rubric text, coders echoing
  context), ~16 MB extra for ngram-mod, zero second model.
- `[INFERENCE]` Separate draft model: only if a much smaller same-vocab draft
  exists for the target family; doubles residency management on 8 GB.

### RAM math (8 GB, CPU-only)

- Anchor (primary): NobodyWho recommends Qwen3-4B-Q4_K_M as "a ~2GB chat
  model", and Qwen3-0.6B-Q4_K_M as "smaller and faster" —
  https://docs.nobodywho.ai/docs/model-selection/
- `[INFERENCE]` So: 4B target ≈ 2 GB weights + KV cache (grows with
  num_ctx × num_parallel — Ollama FAQ:
  https://docs.ollama.com/faq) + macOS/system ~2–3 GB.
  A 4B target + 0.6B draft (≈0.5 GB) + 2× KV cache fits in 8 GB at modest
  context; an 8B target (≈4–5 GB) + draft + cache is swap-adjacent and likely
  not worth it. Draft KV cache is the hidden second copy — size it, don't
  eyeball it.
- Cost / risk: second model load/unload churn (Ollama default keep-alive 5m —
  https://docs.ollama.com/faq and
  https://github.com/ollama/ollama/blob/main/envconfig/config.go); draft
  threads stealing the i5's 6 threads from the target `[INFERENCE]`; separate
  drafts unverified on Ollama 0.40.16 (see above).

### Fit verdict

llama-server n-gram path first (`--spec-default` / ngram-mod) on a sidecar for
the repetitive workloads; skip separate draft models on Ollama until the
`DRAFT` mechanism is confirmed on 0.40.16; embedded-MTP only if the chosen
model family ships MTP weights.

### How to test

Sidecar A/B on the Mini: llama-server with `--spec-type none` vs `ngram-mod`
vs `ngram-simple` (and, if confirmed, `-md` small draft) over a fixed
voter/coder prompt set; measure accepted-tokens/round (server metrics/slots),
tokens/s, and peak RSS. Promote only configs that are faster at equal-or-better
output (diff sampled outputs; n-gram drafting changes nothing structurally but
sampling interactions should be eyeballed).

## 3. Model-fit picker patterns

### Mechanism (what each project actually does — primary)

- NobodyWho `auto` mode: 'pass `auto` as the model path to select one based
  on available memory'; default suggestion Qwen3-4B-Q4_K_M (~2 GB); quant
  naming `Q4` = bits/param, `K_M` = middle-ground K-quant variant —
  https://docs.nobodywho.ai/docs/model-selection/
- LM Studio: `lms load --context-length --gpu --estimate-only`, where
  `--estimate-only` = "Print a resource (memory) estimate and exit without
  loading the model" —
  https://www.lmstudio.ai/docs/cli/local-models/load ; REST `POST
  /api/v1/models/load` with `context_length`, `eval_batch_size`,
  `offload_kv_cache_to_gpu` (KV in GPU vs CPU RAM), flash attention "can
  decrease memory usage" —
  https://www.lmstudio.ai/docs/developer/rest/load
- Unsloth: per-model run guides (e.g. Qwen3 how-to-run) linked from each GGUF
  model card, and Dynamic-quant docs framing the choice as accuracy-at-fixed-
  size across quants (works with llama.cpp) —
  https://huggingface.co/unsloth/Qwen3-4B-GGUF/raw/main/README.md and
  https://unsloth.ai/docs/basics/dynamic-3.0-ggufs.md . `[INFERENCE]` Unsloth
  ships no picker binary; the "picker" is per-quant files + sizing/quality
  guidance.
- Ollama sizing inputs (primary): default context 4096 (FAQ) with server
  default tiers "4k/32k/256k based on VRAM" (config.go comment — CPU-only Mini
  lands on 4k `[INFERENCE]`, override with `OLLAMA_CONTEXT_LENGTH` /
  `num_ctx`); "Required RAM will scale by OLLAMA_NUM_PARALLEL ×
  OLLAMA_CONTEXT_LENGTH"; `ollama ps` shows per-model SIZE and Processor
  (100% CPU vs GPU split); models stay loaded 5m by default, `keep_alive: -1`
  pins, `0` unloads —
  https://docs.ollama.com/faq and
  https://github.com/ollama/ollama/blob/main/envconfig/config.go

### Runs-or-swaps predictor (`[INFERENCE]` design from the above inputs)

`fits = weights(file bytes) + kv(num_ctx × num_parallel, per-model factor) +
os_headroom < free_ram`. Calibrate the KV factor empirically per model (load
once at a known ctx, read `ollama ps` SIZE delta). Picker semantics copied
from NobodyWho `auto`: largest allowlisted (model, quant, ctx) triple that
fits; LM-Studio `--estimate-only` UX: print the estimate and exit non-zero on
no-fit instead of loading into swap.

### Expected gain on THIS box

`[INFERENCE]` 8 GB is the binding constraint, so a preflight check converts
mystery slowdowns (swap death, load/unload churn) into explicit
pick-smaller-quant / shrink-ctx / serialize decisions. Gain is robustness and
debuggability, not tokens/s.

### Cost / risk

Small script + calibration table; risk is stale estimates after model/version
changes — re-calibrate on upgrade, and treat the predictor as advisory with a
runtime backstop (see §4 queue limits).

### Fit verdict

Build the preflight: check free RAM → pick triple → print estimate → refuse to
load on no-fit. Cheapest correct shape; no new runtime.

### How to test

Unit-test the predictor against observed `ollama ps` SIZE values across
ctx ∈ {2k, 4k, 8k}; then live-test: predicted-fit loads must reach first token
without memory-pressure warnings, predicted-no-fit must refuse. Re-run after
every Ollama/model upgrade.

## 4. Serial job queue + backpressure

### Mechanism (primary)

- Two concurrency levels: multiple models loaded at once "if memory allows",
  plus parallel requests per model; if a new model can't fit, "all new
  requests will be queued until the new model can be loaded"; "Queued requests
  will be processed in order"; parallel slots multiply context ("2K context
  with 4 parallel requests → 8K context and additional memory") —
  https://docs.ollama.com/faq
- Knobs (code + FAQ): `OLLAMA_NUM_PARALLEL` default 1 ("Maximum number of
  parallel requests"); `OLLAMA_MAX_LOADED_MODELS` default 3×GPUs, 3 on CPU
  ("Maximum number of loaded models per GPU"); `OLLAMA_MAX_QUEUE` default 512
  ("Maximum number of queued requests"); overload → HTTP 503 —
  https://github.com/ollama/ollama/blob/main/envconfig/config.go and
  https://docs.ollama.com/faq ("If too many requests are sent… it responds
  with a 503 overloaded error").
- llama-server equivalent: `-np/--parallel` slots (default auto), unified KV
  options, `/slots` monitoring, `?fail_on_no_slot=1` → 503 when no slot is
  free —
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

### Expected gain on THIS box

`[INFERENCE]` Load is already serial, so the win is enforcement + clarity:
pin the server to truly-one-at-a-time so a second model or parallel slot can
never halve RAM per job or trigger swap; map overload to explicit 503/backoff
instead of silent queueing behind a 512-deep FIFO.

### Cost / risk

Config-only: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`,
small `OLLAMA_MAX_QUEUE`, `keep_alive` pinning for the hot model. Risk: with
MAX_LOADED=1, alternating voter→coder models unload/reload each switch (~GBs
over seconds) — mitigate by batching same-model jobs. `[INFERENCE]`

### Fit verdict

Do both layers: server pins (above) AND a tiny client-side single-flight
guard (one in-flight request, bounded local queue, deadline + fail-fast).
The external queue still earns its keep for job priority/fairness/deadlines,
which Ollama's FIFO ("processed in order", no priority API documented)
cannot express. `[INFERENCE]`

### How to test

Concurrency probe: fire K simultaneous requests, assert server-side execution
is serial (non-overlapping active spans via request timings), memory flat
(`ollama ps`), and requests beyond the local bound fail fast locally while
requests beyond `OLLAMA_MAX_QUEUE` surface 503. Re-run with model alternation
to measure unload/reload cost and set batching policy.

## 5. Cascade / verifier patterns for code (cheapest correct local shape)

### Mechanism (primary pieces; composition is `[INFERENCE]`)

- Tests-as-gate: `pytest` exit code 0 = all passed, 1 = some failed (2/3/4/5 =
  interrupted/internal/usage/no-tests) —
  https://docs.pytest.org/en/stable/reference/exit-codes.html . Exit code is
  the machine-checkable verdict — no LLM needed.
- Syntax gate: `py_compile.compile()` byte-compiles a file, raises
  `PyCompileError` with `doraise`, CLI form `python -m py_compile` —
  https://docs.python.org/3/library/py_compile.html . Milliseconds, stdlib,
  catches the "doesn't even parse" class before any inference spend.
- Structured critic verdicts: Ollama `format` = schema (e.g.
  `{verdict: pass|fail, reasons: [...]}`) + temperature 0 —
  https://docs.ollama.com/capabilities/structured-outputs
- Critic separation substrate: Ollama loads multiple models concurrently "if
  memory allows" (https://docs.ollama.com/faq) — but on this 8 GB box,
  separation should be by fresh context (separate request, no solution
  history), not by second resident model. `[INFERENCE]`

### Cheapest correct local shape (`[INFERENCE]`)

L0 `py_compile` (drop unparseable instantly) → L1 targeted `pytest` slice,
exit code gates (drop red) → L2 same-small-model critic in a FRESH context
with a `format`-constrained verdict schema (drop on `fail`) → L3 escalate
only survivors-that-matter to a bigger/reasoning model or a human. Each stage
is cheaper than the next; nothing reaches paid/slow stages that a free stage
could have rejected.

### Expected gain on THIS box

`[INFERENCE]` L0+L1 are ~free CPU (ms–s, zero tokens) and catch the bulk of
mechanical breakage; L2 adds one small-model call only for code that already
parses and passes tests. Net: fewer wasted downstream calls, higher precision
on "correct" claims, ~zero RAM impact (no extra resident model).

### Cost / risk

`[INFERENCE]` Test-gate quality bounds everything: weak tests pass bad code
(gate recall = test recall). Critic-in-fresh-context still shares the small
model's blind spots — it is a second opinion, not an oracle. Keep L2 prompts
and verdict schema versioned so critic drift is detectable.

### How to test

Seed a labeled set (known-good + known-broken patches); measure per-stage
precision/recall, end-to-end escape rate, and cost (tokens + wall time) vs a
no-gate baseline. Promote thresholds (which pytest slice, critic schema)
only on measured escape-rate reduction.

## Ranking: expected Mini gain-per-effort

| Rank | Upgrade | Why (gain ÷ effort) |
|------|---------|---------------------|
| 1 | §1 Ollama-native `format` + temp 0 | One param; kills the JSON-syntax failure class on both `/api/chat` and `/v1`. Near-zero cost. |
| 2 | §4 Serial pins + client single-flight | Config + tiny guard; converts OOM/swap/queue mysteries into explicit, measurable behavior. |
| 3 | §5 L0/L1 local gates (py_compile + pytest) | Stdlib-only, zero tokens; mechanical breakage never reaches inference. |
| 4 | §3 Fit preflight (`auto`-like picker) | Small script + calibration; prevents swap death when models/ctx change. Pays off on every upgrade. |
| 5 | §2 Speculative decoding | Needs a llama-server sidecar (n-gram) or an unverified-on-Ollama draft path; extra RAM/thread contention on a 6-thread i5; wins only on high-acceptance workloads. Test last. |
| — | Outlines / llguidance / NobodyWho runtimes | Decline for now: each replaces Ollama serving or needs a custom build; revisit only if §1's native path proves insufficient. `[INFERENCE]` |

Caveat: Ollama primary docs were read at current main (Nov 2026) while the
box runs 0.40.16 — re-verify `draft_num_predict`/MTP and `/v1`
`response_format` behavior on the pinned version before building on them.
`[INFERENCE]`
