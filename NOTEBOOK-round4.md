# NOTEBOOK — Round 4: NotebookLM (agent-dev) grounded follow-ups

Captured 2026-10-28 in worktree `wt-lab-research` (branch `research/assist`), agent `kiro-nlm`.
Tool: `nlmx` (NotebookLM wrapper), always `--profile langchain`, one-shot queries only.
Notebook: **agent-dev** — id `a887fc7b-4102-4a4a-8c7f-a6e06fe51c53`,
title *"Entwicklung autonomer KI-Agenten"*, **22 sources**, updated 2026-10-27.

Access verified via `nlmx notebook list --profile langchain` (3 notebooks returned; agent-dev
present with 22 sources) and a describe/summary call. The notebook's own summary describes its
scope plainly: the **LangChain ecosystem** — LangGraph, Deep Agents, Managed Deep Agents (MDA),
built-in tools (virtual filesystem, planning, sub-agent delegation), durable execution, custom
HTTP/messaging channels (e.g. Slack), and automated evals via **Harbor** + **LangSmith**.

> **Scope caveat that shapes every verdict below:** this notebook is about *building agents on
> LangChain/LangGraph*, **not** about CPU/hardware inference tuning. So the agent-framework
> questions (RAG orchestration, eval harnesses, token metering) land squarely in-scope and come
> back richly grounded; the hardware question (CPU tuning) is explicitly **out of scope** and the
> notebook says so rather than hallucinating. That honesty is itself a useful grounding signal.

Lab context carried in from the 4 prior files (read, not modified): 2018 Intel Mac mini,
i5-8500B (6c/6t, AVX2+FMA, no AVX-512), 8 GB RAM (~5.9 GB usable, ~3.8–4.4 GB real model budget),
CPU-only Ollama, 4k context, no 8B+. q8_0 KV tuning is *pending* adoption; `bge-m3` embeddings
*not yet pulled*; every UI/RAG/memory stack was downgraded to **off-box** (point at the Mini over
the tailnet) in STRESSTEST/SPARRING.

---

## Query A — CPU-only tuning beyond keep_alive / num_ctx / KV-quant

**Q:** For CPU-only llama.cpp or Ollama inference on an 8GB machine, what tuning levers matter
BEYOND keep_alive, num_ctx, and KV-cache quant? (threads/batch, mmap vs mlock, prefix KV reuse,
CPU flash attention, NUMA, memory-bandwidth limits).

**A (verbatim gist):** The notebook **does not cover** low-level llama.cpp/Ollama CPU tuning —
no thread/batch, mmap/mlock, prefix KV reuse, CPU flash-attention, NUMA, or memory-bandwidth
content. Its only local-inference mention is that Ollama/local models can be plugged into
`create_deep_agent` as a custom model instance. The notebook offered to do web research instead.

**Sources used:** `683115ac…` (1 source) — a Deep Agents walkthrough transcript about
`create_deep_agent`, **not** a CPU-tuning source.

**Verdict:**
- **Ran:** The query executed and returned a grounded, in-notebook answer. `sources_used` was
  non-empty (1), citing the create_deep_agent source — so this is a *grounded "we don't have it"*,
  not a model-knowledge guess.
- **Inferred:** Nothing new on CPU tuning from this notebook. The authoritative CPU-tuning answer
  for the lab already lives in **SPARRING-round2.md §3** (verified llama.cpp flags: `-t 5`,
  `-tb 6`, `-c 4096`, `-np 1`, `--cache-reuse 256`, `-ctk/-ctv q8_0`, `-fa on`, `--mlock`, keep
  mmap on, skip `--numa`) and **STRESSTEST-cpu-ram.md** (source #21136 `--mlock` + swappiness).
  The notebook does not add to or contradict those.
- **Not-verified:** Any CPU-tuning claim from *this notebook* — because it has none. **LOW
  CONFIDENCE** for CPU specifics here; rely on the prior two files instead.

---

## Query B — Thin-client RAG over a tailnet (LLM + embeddings on a remote CPU box)

**Q:** How should a thin client build a RAG pipeline over a tailnet when both the LLM and the
embedding model live on a single remote CPU box? (retriever/orchestration patterns, where
embeddings run, keeping the client stateless, relevant LangChain/LangGraph blocks).

**A (grounded gist):**
- **Where things run / stateless client:** Server hosts the full LangGraph/LangChain runtime
  (LangGraph Server or LangSmith Deployments); it generates query embeddings, queries the vector
  index, and runs the LLM loop. The thin client (web UI, terminal, Slack/HTTP webhook) holds **no
  history and no weights** — it sends JSON/HTTP and receives token streams. Server-side state via
  LangGraph **checkpointers** (`AgentState`/`DeepAgentState`); long-term memory via `memory.py` +
  Context Hub; client tracks only a lightweight **thread ID**.
- **RAG/orchestration patterns:** (A) tool-based retrieval via `@tool(parse_docstring=True)`;
  (B) parallel multi-query RAG (LangGraph nodes fan out, aggregator merges); (C) router-based
  retrieval via structured-output (Pydantic) router → conditional edges; (D) **evaluator-optimizer**
  generate→grade→regenerate loop for grounding/hallucination control; (E) orchestrator-worker RAG
  using the `Send` API / `task` subagent tool so each worker retrieves in isolation and returns
  only a summary (keeps the main context clean).
- **Building blocks:** `create_react_agent`/`create_deep_agent`; state schemas; custom **HTTP
  channel** handlers (`verify`/`parse`/`post`); `before_model` / `wrap_tool_call` middleware for
  compaction, prompt-cache headers, and guardrails.
- **Notebook's own caveat:** it does **not** cover Tailscale/tailnet networking setup or
  CPU-specific embedding runtimes (ONNX / llama.cpp embeddings / thread allocation).

**Sources used:** 11 sources (`83441375…`, `9c099c97…`, `d9644cd1…`, `00e54fc0…`, `4993bfc3…`,
`a636067a…`, `3c2eb808…`, `683115ac…`, `f11d5683…`, `fef5bd84…`, `2cca7881…`); 60 citations.

**Verdict:**
- **Ran:** Executed; **richly grounded** (11 sources / 60 citations). HIGH CONFIDENCE on the
  *orchestration/agent-architecture* half of the question.
- **Inferred:** This maps cleanly onto the lab's STRESSTEST conclusion ("runtime fits on-box;
  UI/RAG stacks belong off-box"). The notebook supplies the **client-side architecture** for that
  split: keep the Mini as the stateless-agent host *or* run the LangGraph runtime off-box and let
  the Mini be purely the Ollama LLM+embedder endpoint. The evaluator-optimizer pattern (D) is the
  concrete grounding-check mechanism the lab's probes have been wanting.
- **Not-verified:** The **tailnet transport** and **CPU embedding runtime** specifics — the
  notebook explicitly disclaims both. Those remain owned by AGENTS.md (tailnet URL) and TRIALS /
  MODEL-FIT (`bge-m3` pull still pending). Treat the networking/embedding-perf layer as
  **NOT grounded by this notebook**.

---

## Query C — CPU-runnable eval harnesses for small models at weekly-smoke scale

**Q:** What eval harnesses/frameworks suit automated quality evals for small LLM agents at a
lightweight weekly-smoke scale? (LangSmith, Harbor, dataset/LLM-as-judge, keeping runs cheap &
reproducible).

**A (grounded gist):**
- **Harbor** (bundled in Managed Deep Agents): sandboxed benchmark runner for tool-calling/stateful
  agents. Each task folder = `Dockerfile` (fresh container) + `instruction.md` (prompt) +
  `task.md` (spec) + `test.sh` (verifier). **Binary reward** written to a `reward` file (1.0/0.0).
- **LangSmith**: Harbor results + traces log to **Data Sets** / **Experiments**; track pass-rate,
  latency, and token cost side-by-side across revisions. **Online LLM-as-a-judge** grades live
  threads against a rubric and attaches a score + reasoning to the trace.
- **Cheap & reproducible:** (1) prefer **deterministic `pytest` verifiers** in `test.sh` (assert
  cited IDs exist, fallback text used, required blocks present) to avoid judge API calls;
  (2) **lower LLM-judge sampling** (e.g. 100%→50%) to halve judge cost; (3) **container isolation**
  for reproducibility; (4) run suites on a **scheduled weekly/nightly** CI cadence, not per-edit.
- **Scaffolding:** `mda evals init -i` hands off to a coding agent (via the
  `langchain-eval-engineering` skill) to generate `task.md`, `Dockerfile`, and `pytest` verifiers.

**Sources used:** 6 sources (`ec02002a…`, `d9644cd1…`, `2cca7881…`, `fef5bd84…`, `1a132856…`,
`9c099c97…`); 19 citations.

**Verdict:**
- **Ran:** Executed; **well grounded** (6 sources / 19 citations), directly on-target. HIGH
  CONFIDENCE.
- **Inferred:** The **deterministic-pytest-verifier** pattern is the single most lab-relevant
  takeaway: it needs **zero judge-model calls**, so a weekly smoke suite can run with only cheap
  deterministic checks against the Mini's own output — ideal for an 8 GB CPU box where every token
  is slow. This fits the existing `eval-weekly.py` + launchd weekly job. The Docker-container
  requirement in Harbor is a **caveat** for the lab (Docker is a disk/RAM blocker per TRIALS) —
  but the *pattern* (fresh workspace + verifier script + binary reward + scheduled cadence) is
  reproducible without Harbor-the-tool.
- **Not-verified:** Whether Harbor's Docker-per-task model runs acceptably on the lab hardware —
  the notebook doesn't address CPU/RAM/disk cost of the harness itself. **Verify locally** before
  adopting Harbor; the deterministic-verifier *pattern* is adoptable regardless.

---

## Query D — Token metering proxies for self-hosted OSS stacks

**Q:** How can token usage/cost be metered for a self-hosted OSS LLM stack? (proxy/gateway token
counting, per-request/per-agent accounting, tracing/observability, where it hooks into an agent
framework).

**A (grounded gist):**
- **Gateway/proxy layer:** a centralized **LLM gateway ("Lang Gateway")** sits in front of
  providers and local endpoints, intercepting requests/responses to authenticate, rate-limit, and
  centrally count raw input/output tokens before calls hit the backend.
- **Tracing/observability:** **LangSmith** auto-logs input tokens, output tokens, latency, and
  computed cost per step/model-call/tool-call; step-by-step trace trees locate token spikes (big
  system prompts, large tool returns, long histories); Experiments benchmark total tokens + avg
  cost/run alongside accuracy.
- **Framework hooks:** `before_model`/`after_model` **middleware** — summarization/compaction when
  history exceeds a token threshold, and **prompt-caching** headers to reuse static system prompts;
  **subagent context isolation** via the `task` tool (heavy subtasks run in a fresh window, return
  one summary); explicit **tool-call budgets** to stop runaway loops.
- **Per-request/per-agent accounting:** tag requests with **thread IDs / user IDs / hashed client
  IDs**, aggregate per user/thread/tenant; **model right-sizing** (cheap model for routine work,
  frontier only for heavy reasoning); **evaluator sampling** to cut judge cost.

**Sources used:** 11 sources (`9c099c97…`, `222f8cc0…`, `00e54fc0…`, `ec02002a…`, `fef5bd84…`,
`99a215f0…`, `2cca7881…`, `683115ac…`, `83441375…`, `a636067a…`, `1a132856…`); 25 citations.

**Verdict:**
- **Ran:** Executed; **well grounded** (11 sources / 25 citations). HIGH CONFIDENCE on the pattern.
- **Inferred:** The lab already has the two load-bearing pieces this describes — **Caddy** (the
  proxy/gateway front door) and the **feedback sidecar** (per-agent token accounting via
  `prompt_eval_count`/`eval_count` per AGENTS.md). The notebook's gateway-token-counting pattern
  validates the lab's existing architecture and suggests the natural next increment: have the
  proxy/sidecar tag every request with a **per-agent/per-thread ID** and roll per-agent token
  totals (it already keeps `total_feedback_tokens`). SPARRING already argued **litellm is a
  redundant hop** here; this notebook's "central gateway" role is satisfied by Caddy+sidecar, so
  no new gateway is needed — only richer tagging.
- **Not-verified:** The notebook's framing assumes paid-token cost accounting; the lab's local
  calls cost $0, so "cost" = **token-budget / latency control**, not dollars. The
  compaction/prompt-cache **middleware** is a client-side (agent-framework) concern, not something
  the Mini enforces — **not verified** as runnable on the current Caddy+sidecar stack without
  adding a LangGraph runtime somewhere.

---

## Grounding scorecard (did the answer come from the notebook's sources?)

| Query | sources_used | citations | Grounded? | Confidence for the lab |
|---|---|---|---|---|
| A — CPU tuning | 1 (off-topic) | 1 | Grounded "not covered" | **LOW** for CPU specifics — use SPARRING §3 / STRESSTEST instead |
| B — thin-client RAG | 11 | 60 | Yes (orchestration) | **HIGH** for agent architecture; tailnet+CPU-embed NOT covered |
| C — eval harnesses | 6 | 19 | Yes | **HIGH** — pattern adoptable; Harbor's Docker is a lab caveat |
| D — token metering | 11 | 25 | Yes | **HIGH** — validates Caddy+sidecar; no new gateway needed |

Every query returned non-empty `sources_used`, so none of the four answers are pure
model-knowledge. Query A is a *grounded refusal* (the notebook genuinely lacks CPU content), which
is the correct, honest outcome — not a hallucinated CPU recipe.

---

## Concrete next lab actions

1. **Keep CPU tuning sourced from SPARRING-round2.md §3, not this notebook.** The notebook has no
   CPU-tuning content; do not cite it for q8_0/thread/mlock decisions. Proceed with the pending
   q8_0 KV adoption (`OLLAMA_KV_CACHE_TYPE=q8_0`) and benchmark via `llama-bench` as already planned.
2. **Adopt the deterministic-`pytest`-verifier eval pattern for `eval-weekly.py`.** Model the
   weekly smoke suite on Harbor's `instruction.md` + `test.sh` + binary-reward shape, but implement
   verifiers as plain deterministic Python asserts (cited-ID exists, fallback used, required blocks
   present) so it needs **zero judge-model calls** — cheap enough for the CPU box. Skip Harbor's
   Docker-per-task on-box (disk/RAM blocker); keep the scheduled-weekly cadence via the existing
   launchd job.
3. **Extend the feedback sidecar with per-agent/per-thread token tagging.** The notebook's
   gateway-metering pattern maps onto Caddy+sidecar, which already captures `eval_count`. Add a
   request tag (agent + thread ID) so `total_feedback_tokens` can break down per agent — closes the
   "per-request accounting" gap without adding litellm (confirmed redundant in SPARRING).
4. **If/when RAG moves off-box, use the evaluator-optimizer (generate→grade→regenerate) RAG loop**
   from Query B for grounding checks, and keep the Mini as the stateless LLM+embedder endpoint with
   the LangGraph runtime (checkpointers, thread-ID client) hosted off-box — consistent with the
   STRESSTEST "UI/RAG belongs off-box" verdict. Still gated on the `bge-m3` pull (disk) from TRIALS.
5. **Do a separate, non-notebook pass for the two gaps the notebook disclaimed**: (a) Tailscale
   transport specifics for the RAG client, and (b) CPU embedding runtime perf (`bge-m3` vs
   `nomic-embed-text` t/s on the Mini). These are hardware/networking questions this notebook
   cannot ground — collect them via the lab's existing web-recon path, not nlmx.

---

NLM-DONE queries=4
