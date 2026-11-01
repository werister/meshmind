# Ecosystem scout — 50-link dump, 5 clusters, lab-grounded (2026-11-01)

Brainstorm pass over a large link dump across five themes: token/agent monitors,
memory systems, agent/model routers, LLM observability, and the Jev decision-model
ecosystem. Read from primary sources via five parallel subagents. **Nothing installed.**
All vendor numbers are hypotheses pending our own harness (the Artemis lesson).

**The one-line finding:** almost nothing here is worth *running* on (or off) the box —
the lab already owns the data layer (metering proxy + `/status` + `/dashboard` + `/calls`
+ weekly eval) and the front door (Caddy + sidecar). The payoff is **(1) a short list of
cheap presentation/observability features to fold into the existing stdlib
`feedback-server.py`**, and **(2) exactly one genuinely new capability lead — a local,
CPU-only, no-GPU "decision/judge" endpoint** that fits the box and the lab's existing
smollm2-as-judge use. Everything else is fleet/cloud/Claude-cost tooling that a
single-user, single-Ollama, tailnet-only CPU box has no use for.

---

## Cluster verdicts (one line each, full detail below)

| Cluster | Verdict for the box | Keep |
|---|---|---|
| Token/agent monitors | Borrow UX only; all are Claude-cost/quota tools, irrelevant for no-cost local Ollama | 3 dashboard ideas |
| Memory systems | Mostly skip; 1 lightweight file-based memory *iff* agents are Claude Code | append-log pattern |
| Agent/model routers | Skip; fleet tools, nothing beats Caddy+proxy for one node | 1 idea (prompt caching) |
| LLM observability | All heavy (ClickHouse/Docker) → off-box only; don't adopt | 5 stdlib features |
| Jev decision models | 7 requested repos all no-fit (need paid hosted key/GPU); BUT open-weights fringe has real CPU leads | **a new lane** |

---

## 1. Token/agent monitors — borrow UX, adopt nothing

Every tool (Claude-Code-Usage-Monitor, token-monitor, CCAM, agent-dashboard, codestatus,
herdr-portal, dsh-traffic-light, tmuxpad, frieren-pet, agents-cli) is built for **Claude
Code / cloud-subscription cost + quota tracking**. On CPU-only Ollama there is **no
per-token cost and no plan limit**, so the entire cost/quota/reset-window feature class is
dead weight. Raw token counting is also not a gap — the metering proxy already has exact
per-model/per-agent counts.

**Three UX ideas worth lifting into `/dashboard` (stdlib HTML, no deps):**
1. **Traffic-light health dot** (green/yellow/red; blink-rate = urgency: slow-pulse =
   running, fast-blink = needs-attention) for the 5-min health monitor — the single
   cleanest glanceable pattern in the set. (dsh-traffic-light, MIT)
2. **Burn-rate / velocity in tok/s and tok/min** — genuinely meaningful here because
   throughput *is* the CPU box's constraint; computable from existing `eval_count` +
   `*_duration` in the ring buffer, rendered as a sparkline/live counter. (token-monitor;
   pace math from Claude-Code-Usage-Monitor)
3. **Per-agent leaderboard as horizontal volume bars with stable per-agent accent colors**
   so parallel agents stay trackable across reorders — straight from the per-agent
   rollups. (bars: agent-dashboard; stable colors: herdr-portal)

Honorable mentions: a one-line **"N idle / N busy / N needs-you"** summary `/status` could
emit for a tmux statusline (codestatus, MIT); **provenance/confidence labels on every
number** (official vs local_estimate), which match the lab's verified-vs-estimated ethos
(Claude-Code-Usage-Monitor). **Run-as-is verdict: none** — all would duplicate metering we
own; borrow layout, not code. Verify LICENSE before copying code from non-MIT repos
(token-monitor, agent-dashboard, herdr-portal licenses unconfirmed).

## 2. Memory systems — mostly skip

- **carbonbasednerd/claude-memory-system** (MIT, pure-Python, JSON+markdown on disk, no DB,
  no embedder) — lightweight and local-first, but it is **Claude-Code-coupled** and does
  **keyword** recall, not semantic (it never calls an LLM or `/api/embed`, so "point it at
  Ollama embeddings" doesn't apply). On-box-safe *iff* the lab's agents are Claude Code;
  otherwise skip. **Steal the pattern** regardless (see §Cross-cutting).
- **erinra memory-dashboard** (MCP skill) — a GUI launcher for a memory engine the lab
  doesn't have; Claude-coupled. **Skip.**
- The LangChain "compare LLM outputs" reddit thread was **unreadable (403)** — the subagent
  correctly refused to invent its contents, and instead surfaced real local output-diff
  tools (e.g. CaptainMcCrank/LLM_Output_Comparison) as *leads* needing a base_url check.
  Relevant only as a nudge: a tiny local output-diff viewer would help bake-offs, but the
  lab's own harness already produces the data.
- **Skip, irrelevant:** open-codesign (Electron design app), MuseBot (messaging chatbot),
  k-dense-byok (heavy desktop research app), treg (paid-tool billing relay), deepwiki-open
  (repo-wiki generator), opencodex (Ollama-aware API gateway, adjacent-only).

## 3. Agent/model routers — skip, keep Caddy + proxy

dabit3/agent-router (in-process TS lib), nidhi-singh02/agent-router (mandatory TypeSafe
cloud call + Herdr), theagentrouter/Envoy-AI-Gateway (Kubernetes/Envoy fleet control
plane), EasyCLIProxyAPI (Tauri desktop GUI over CLIProxyAPI), all-api-hub (browser
extension for cloud relay accounts), ccs (Docker/Bun multi-account switcher),
Tetrate ARS (hosted SaaS), and the four GitHub topic pages — **every one is a
multi-provider cloud-fleet tool.** With a single local Ollama, routing / failover /
budgets / OAuth aggregation are inert, and each carries that weight as resident RAM/disk
the box can't spare (Docker is out). **Nothing beats the existing Caddy + metering proxy
for one node.** The single transferable idea: **agentgateway.dev's semantic/prompt
caching** in front of a slow CPU model — but cheaper to bolt a tiny exact-match
prompt→response cache onto the existing proxy than to adopt a gateway. Consistent with the
earlier antirion verdict (off-box by nature).

## 4. LLM observability — all heavy, off-box only; mine the ideas

- **Langfuse** — ClickHouse + Postgres + object store + Docker/compose. **Non-starter
  on-box.** Off-box node only.
- **Helicone** (Apache-2.0) — OpenAI-compatible proxy (closest fit to our proxy, has an
  Ollama integration) but self-host = **6 services incl. ClickHouse + Supabase + Minio**.
  **Non-starter on-box;** off-box if ever.
- **OpenLLMetry** (Apache-2.0) — the light one: `pip install traceloop-sdk`, emits OTLP,
  native Ollama instrumentation. The **SDK half is on-box-safe**, but it only has value
  with an OTLP backend (heavy, off-box). Lightest *standards-based* option if we ever
  outgrow our own JSON.

**5 stdlib features to build into `feedback-server.py` (no deps), strongest-first:**
1. **Self-coverage counter on `/status`:** `calls_seen_by_proxy` vs `calls_logged`, expose
   the gap — makes a silent metering/delivery failure visible ("observability measures
   itself"). (kevinastuhuaman/llm-observability)
2. **Per-model rolling latency (p50/p95) + up/down flag on `/dashboard`** from the ring
   buffer via stdlib `statistics`. (JFrog panels)
3. **Cheap drift signal:** stamp each call with a prompt/model-version id, chart rolling
   mean prompt/eval token length per version — surfaces "behavior changed after a
   prompt/model swap." (Confident-AI, NVIDIA)
4. **Async severity-tagging (off critical path):** stdlib regex/heuristic checks (PII-like
   patterns, "ignore previous instructions"/restriction-bypass phrasing) tag each buffered
   call with a severity; dashboard lists only anomalies. (OpenAI misalignment post, used as
   design reference only)
5. **Token threshold flags in `/calls`** per model/agent (not cost — just volume ceilings)
   that flip a `/status` flag. (github llm-observability topic pattern)

## 5. Jev decision-model ecosystem — the one new capability lead

**All 7 requested repos are no-fit as-is** — hermes-jev-skills, jev-router, jev-gateway,
jev-eval-agent every one needs a **paid hosted TypeSafe key and/or OpenRouter/subscription
remotes**, breaking the tailnet-only/no-external-dependency posture; and they're
routers/clients, not local judges. (This matches the earlier mode-io/vllm-jev no-fit:
GPU/CUDA + arm64-only Mac wheels.)

**But** the open-weights fringe of the CC0 `hellogumbo/awesome-jev` list has real CPU-first
leads that fit the box (all **unvisited leads pending per-repo verification**, per that
list's own "treat as leads" disclaimer):
- **gut** — one-line-Python judge wrapper (`likely/classify/rate → YES/NO/UNSURE`) over
  **any small model incl. local Ollama**. Thinnest possible fit; pairs with the existing
  smollm2 judge. **Top pick to spike.**
- **edgejev** — ONNX + INT8, **no torch at runtime**, ~15.6 ms/question on a 4-core CPU;
  x86_64-friendly (unlike MLX/Metal options). Best technical fit if a real decision model
  is wanted.
- **Verdict / Open-jev** — 151M ModernBERT, ~35.6 ms CPU, self-reports its failure modes
  (option-order flips) — tiny and honest.
- **jevalt** (three 4B models, ~3 GB CPU RAM) / **Kev** (Apache-2.0, Ollama-or-OpenAI-compat
  serving shell) — if the lab wants to *own* a `/v1/systemone` endpoint inside the 3–4B
  memory ceiling.
- Explicitly **not** for this Intel box: system-one (MLX), openjev-multimodal (Metal).

**The most valuable transferable artifact:** `jev-eval-agent`'s **design** — a typed-decision
trace (choice / confidence / done-gate / top-5 / latency as JSONL) that diffs two modes
(LLM-picks-tool vs decision-model-picks-tool). The *methodology and trace format* port
directly onto the lab's PASS/FAIL judge; only its wiring (OpenRouter + hosted Jev) is
unusable.

**Recommendation — modest yes to a thin `/v1/systemone` judge shim (spike, not a product):**
the protocol is now first-class (vLLM mainline + LiteLLM), so the surface is a stable
contract, not a bet; and the lab already does decision work (smollm2-as-judge, PASS/FAIL
grading) that maps 1:1 onto Noul (PASS/FAIL) and Score (rubric). Putting **gut (or Kev) in
front of the existing Ollama** would let the eval harness call one typed endpoint and read a
calibrated-ish probability instead of parsing judge prose — a real flakiness reduction.
**Do not stand up vLLM** (the known no-fit) and treat the probability as a lab-internal
signal verified against held-out PASS/FAIL. Worth a weekend spike with gut+Ollama; a
dedicated decision model (edgejev/Verdict) only if that proves out.

---

## Cross-cutting synthesis (what actually matters for the lab)

Three themes recur across all five clusters and point at cheap, high-value moves:

1. **The lab's instinct is right: own the data layer, borrow only ideas.** Four of five
   clusters (monitors, routers, observability, and the Jev *clients*) resolve to "don't
   adopt — you already have the proxy/sidecar/front-door." The dashboard/observability
   features in §1 and §4 are the real harvest, and they're all stdlib additions to
   `feedback-server.py`, not new processes.

2. **One genuinely new capability exists:** a **local CPU decision/judge endpoint**
   (§5) — the only item in 50 links that adds something the lab can't already do and that
   fits the box. It also closes a loop from earlier scouts (the `/v1/systemone` → vLLM-merge
   convergence). This is the single thing worth a hands-on spike.

3. **Append-only run history** (stolen from claude-memory-system's manifest+append-log
   pattern, §2): store each bake-off/eval run as JSONL with a tiny top-level manifest
   (model, prompt-set, timestamp, scores) → cheap, concurrent-safe, greppable history with
   no DB, and later feedable into the existing embeddings lane for "find similar past runs."
   Complements the jev-eval-agent trace format in §5.

### Proposed, prioritized (all optional; nothing applied)
- **P1 (new capability):** weekend spike — `gut` (or `Kev`) in front of the Mini's Ollama
  as a thin `/v1/systemone` judge shim; A/B its PASS/FAIL against the current
  smollm2-prose judge on held-out items. If it reduces grader flakiness, keep.
- **P2 (cheap, high-signal dashboard):** add the traffic-light health dot + tok/s burn-rate
  + per-agent leaderboard bars to `/dashboard` (stdlib HTML only).
- **P3 (self-monitoring):** add the self-coverage counter, p50/p95 latency panel, and
  async severity-tagging to the sidecar (stdlib only).
- **P4 (housekeeping):** adopt the append-only JSONL run-history + manifest pattern for
  bake-off/eval outputs.

### Sources
Five subagent primary-source reads (2026-11-01) across the listed URLs. Key MIT/Apache
repos: dsh-traffic-light, codestatus, claude-memory-system (MIT); helicone, openllmetry,
Kev (Apache-2.0); hellogumbo/awesome-jev (CC0). Reddit threads (1lexe92, mlops r7fp91,
LangChain 16pd7p7) were 403-blocked — not used as sources. vLLM `/v1/systemone` merge:
vllm-project/vllm#59299 (established in prior scout). All vendor latency/accuracy numbers
are hypotheses pending the lab's T11/T12 + weekly-eval harness. Cross-ref:
`RESEARCH-runtime-scout-2026-10-30.md`, `THINKING-small-models-2026-10-31.md`,
`MODEL-SCOUT-2026-10-31.md`. *External content rephrased for licensing compliance.*
