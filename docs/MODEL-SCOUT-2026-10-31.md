# Model scout — candidates per lane (2026-10-31)

Proposals only. No pulls, no live changes, no edits to `AGENTS.md` / `MODEL-FIT.md`.
The coordinator pulls and benches winners.

**Box envelope (from `docs/MODEL-FIT.md`, `THINKING-small-models-2026-10-31.md`, T7):**
8 GB 2018 Intel Mac mini, i5-8500B, **CPU-only**, ~3.8–4.4 GB real model budget, 4k ctx,
Ollama 0.32.1. Install path = `ollama.com` tag **or** `hf.co/<repo>:<quant>` GGUF
passthrough. A 4B at Q4_K_M (~2.5 GB weights + KV) is the comfortable ceiling.

**Framing rule (the Artemis lesson).** Every number below is a **vendor/published
benchmark = a hypothesis pending our own T11/T12 + weekly-eval harness.** Artemis 0.8B
had a real BFCL 163/258 on the card and still scored 4/12 live because it never emitted
our instructed JSON fence. So two things are weighted heavily here beyond the headline
score: (a) a **standard, documented tool-call template** (Hermes/Qwen `<tool_call>` or
native tool tokens), and (b) a **non-thinking mode** for the tool lane (thinking small
models stall — qwen3:1.7b returned empty answers; see THINKING doc). Harmony-style /
exotic output formats are treated as a red flag for our fence protocol until proven.

---

## Lane 1 — tool-calling small model (replace/augment the weak artemis 4/12 & phi4-mini 5/12)

Target: a strong instruction-follower with a **standard chat template**, published BFCL
(or TAU), a **non-thinking** path, and ≤~3 GB so it co-resides.

### #1 — `qwen3:4b-instruct-2507` (Q4_K_M)  ★ top pick
- **Pull:** `ollama pull qwen3:4b-instruct-2507-q4_K_M` (official Ollama *library* tag).
- **Size/quant:** **2.5 GB**, Q4_K_M (registry manifest: 2497.3 MB model layer). 4.0B params,
  262K ctx native, Apache-2.0.
- **Published (official HF card):** **BFCL-v3 61.9** (vs 57.6 old Qwen3-4B non-thinking, vs
  53.0 GPT-4.1-nano), TAU1-Retail 48.7, TAU1-Airline 32.0, TAU2-Retail 40.4, **IFEval 83.4**,
  Arena-Hard v2 43.4, MMLU-Pro 69.6.
  [card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
  [blog](https://qwenlm.github.io/blog/qwen3/).
- **Independent cross-check (non-vendor):** Apple's PROOF-Gen paper cites Qwen3-4B-Instruct-2507
  on BFCL-v4 multi-turn (base Pass^1 0.132), confirming it's a real BFCL subject, not
  marketing-only. [Apple ML](https://machinelearning.apple.com/research/proof-gen-optimized-distillation).
- **Why it fits our failure mode:** **non-thinking by design** (card: "does not generate
  `<think>` blocks") → no stall risk; uses the **standard Qwen/Hermes `<tool_call>` template**
  that Ollama's native tool parser understands → directly the thing artemis lacked.
- **Caveats (honest):** all card numbers are GPU/reference-framework; **CPU tok/s on
  i5-8500B unmeasured** — at 4B expect ~9–10 tok/s like gemma3:4b (measured earlier), so
  latency ≈ our current 4B lane, not faster. 262K ctx is irrelevant at our 4k cap. Qwen
  recommends 16K output for best IFEval — we clamp to 4k, so re-bench IFEval at our ctx.
  BFCL-v3, not v4.

### #2 — `LiquidAI/lfm2.5-1.2b` → really **LFM3-1.7B** (dual-mode, tiny, agent-trained)
- **Pull:** `ollama pull hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M` (verify exact GGUF repo/tag
  before pull; Liquid ships official GGUFs). LFM2.5-2.6B is **deprecated by Liquid in favour
  of LFM3-1.7B** ([Liquid docs](https://docs.liquid.ai/lfm/models/lfm25-2.6b)), so scout the
  successor, not the 2.6B.
- **Size/quant:** **~1 GB at 4-bit** (Liquid: "~1 GB of memory" at 4-bit), 1.73B params,
  256K ctx, LFM Open License v1.0. Tri-hybrid (conv + sliding-window + global attn) → fast on CPU.
- **Published:** Liquid positions it for **"local agents, tool calling, structured outputs"**,
  post-trained for Hermes Agent / Pi / OpenClaw harnesses (→ standard tool-call format).
  [card](https://docs.liquid.ai/lfm/models/lfm3-1.7b). No single clean BFCL number on the doc
  page — **treat tool quality as unverified until our harness**; the signal here is
  architecture (tiny + hybrid = fast CPU) + harness-grade tool formatting, not a score.
- **Why list it:** at ~1 GB it is a **fast specialist** that leaves huge headroom; dual-mode
  (`enable_thinking=False` for direct answers) so the tool path can be non-thinking. The lab
  already runs LFM2 (athena-slm), so the runtime is proven.
- **Caveats (honest):** card **explicitly says "not recommended for agentic coding or complex
  multi-step reasoning due to its small size"** — tool/structured-output lane only. No
  published BFCL on the doc → lower-confidence than #1; its whole case rests on our bench.
  Confirm the GGUF has a current LFM3 chat template (older llama.cpp needs `--chat-template-file`).

### #3 — `phi4-mini` is the incumbent; the honest alt is **grammar-constrained decoding**, not a new model
- No clearly-better *small* dedicated tool model with a credible public BFCL beat over Qwen3-4B
  surfaced. The d-central BFCL survey names Phi-4-mini "the safest single pick ... always paired
  with **grammar-constrained decoding**" ([d-central](https://d-central.tech/local-llm-agent-capability/)).
- **Proposal, not a model:** before adding a third model, test whether the *existing* phi4-mini /
  qwen3-4b-instruct-2507 clear the fence reliably when we **constrain output with a JSON grammar**
  (Ollama `format: json` / GBNF), which removes the "model forgot the fence" failure mode entirely.
  This may be a higher-leverage fix than any new weight. If a dedicated model is still wanted,
  `fauxpaslife/nanbeige4.1` (3B, claims reasoning+tools) is the only on-Ollama candidate found —
  but **low confidence**: ~1.9k downloads, a community tag, no published BFCL I could source. List
  it only as a long-shot to bench, not a recommendation.

**Lane-1 ranking:** 1) qwen3:4b-instruct-2507 (strong score + standard template + non-thinking),
2) LFM3-1.7B (fast/tiny, agent-trained, but unverified score + no-coding caveat),
3) grammar-constrained decoding on the models we already have (likely bigger win than a 3rd model;
nanbeige4.1 only as a low-confidence long-shot).

---

## Lane 2 — faster reliable thinker (granite4.2:3b is correct but 75–95 s; qwen3:1.7b unreliable)

Target: a **real Ollama `think` channel** (not family-inferred — verify with a `think:true`
probe), ideally finishing faster/more reliably than granite4.2:3b on the THINKING-doc probes.

### #1 — `qwen3:4b-thinking-2507` (Q4_K_M)  ★ top pick
- **Pull:** `ollama pull qwen3:4b-thinking-2507-q4_K_M` (official Ollama library tag).
- **Size/quant:** **2.5 GB**, Q4_K_M (manifest: 2497.3 MB), 4.0B, 262K ctx, Apache-2.0.
- **Published (official HF card):** **BFCL-v3 71.2** (best agent score in this scout),
  **AIME25 81.3**, HMMT25 55.5, IFEval 87.4, MMLU-Pro 74.0, LiveCodeBench v6 55.2, TAU2-Retail 53.5.
  [card](https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507). Substantially stronger reasoning than
  granite4.2:3b at a similar size.
- **Real thinking channel:** chat template auto-opens `<think>`; Ollama exposes it as a dual-mode
  thinking model (confirm live with `think:true`, watch for the "does not support thinking" error
  as we did for granite4:micro-h).
- **Caveats (honest, important for our box):** the card **recommends 32K output and warns of
  "increased thinking length."** On an 8 GB CPU box this is the *opposite* of what we want — it may
  think **longer** than granite4.2:3b (which already costs 75–95 s and sometimes stalled). It is
  likely **more accurate but not faster**; the "faster" half of the lane goal may be unmet. Bench
  wall-clock at a **capped** output budget (e.g. `num_predict 900–1200`) and watch for the empty-
  answer stall the THINKING doc found on qwen3:1.7b. If it stalls at a 4k ctx cap, reject for this box.

### #2 — `granite4:micro` (the *non-h* micro tag) — scout whether a thinking micro exists
- **Pull (to investigate):** `ollama pull granite4:micro` then probe `think:true`. We proved
  `granite4:micro-h` has **no** thinking channel (THINKING doc). IBM's Granite 4 line documents a
  thinking toggle at the family level ([granite4.1 lib](https://ollama.com/library/granite4.1)); it
  is unknown which *micro* tag (if any) exposes it under Ollama. **This is a probe task, not a
  recommendation** — its value is a possibly-faster small thinker than granite4.2:3b if a
  thinking-capable micro variant exists (micro is smaller: ~3.2B vs 3.7B).
- **Caveat:** may also be instruct-only like micro-h; verify before counting on it. No separate
  published thinking benchmark distinct from the 3b.

### #3 — `smollm3-3b` with think-on — already on the box, re-rank as the *middle* option
- Not a new pull (`huggingfacetb-smollm3-3b-q4-k-m:bakeoff` is installed). Listed for completeness:
  the THINKING doc measured it **correct on P1 / didn't converge on P2** with think-on, ~52–73 s.
  It is the existing dual-mode fallback; a new thinker only earns a pull if it beats smollm3's
  reliability *and* granite4.2's correctness. Keep as the baseline to beat, don't re-pull.

**Lane-2 ranking:** 1) qwen3:4b-thinking-2507 (clearly strongest reasoning + real think channel —
but prove it doesn't over-think/stall at our ctx cap; "faster" is at risk), 2) granite4:micro
probe (only if a thinking-capable micro tag turns out to exist), 3) smollm3-3b incumbent as the
reliability floor. **Phi-reasoning tags** (from the earlier close-out) remain an unpulled lead worth
a probe if the Qwen3-thinking latency disappoints.

---

## Lane 3 — coder upgrade over `qwen2.5-coder:3b`

Honest finding first: **there is no clearly-better *dedicated* small (≤4B) coder with a credible
public beat over qwen2.5-coder:3b that fits the budget.** The Qwen3-Coder family floor is
**30B-A3B (~19 GB)** — far over budget; no sub-30B Qwen3-Coder exists
([codersera](https://codersera.com/blog/qwen-3-5-complete-guide-2026/),
[localaimaster](https://localaimaster.com/models/best-local-ai-coding-models)). opencoder (1.5B/8B)
and granite-code (3b) are older and not a clear step up. So Lane 3 is **"hold" with one credible
sideways option**, not a dedicated-coder upgrade.

### #1 — `qwen3:4b-instruct-2507` as a **coding-capable generalist** (not a dedicated coder)
- Same 2.5 GB pull as Lane 1. Card coding numbers: **LiveCodeBench v6 35.1, MultiPL-E 76.8**
  (both above old Qwen3-4B non-thinking: 26.4 / 66.6), though **Aider-Polyglot 12.9 is weak**.
  [card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).
- **Why list it:** if we pull it for Lane 1 anyway, it doubles as a *generalist that also codes
  reasonably* — one model covering tools + light code, saving a model slot on an 8 GB box. It is
  **not** a replacement for a dedicated coder on hard code tasks (Aider score says so).
- **Caveat:** dedicated qwen2.5-coder:3b may still win on pure code-completion/FIM; only our T11
  coder bench settles it. Treat as "coding-capable generalist to A/B," not "coder upgrade."

### #2 — keep `qwen2.5-coder:3b` (incumbent) — license note
- No pull. Flag only: Qwen2.5-Coder-3B-Instruct is **`qwen-research` (non-commercial) license**
  ([card](https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct)), unlike the Apache-2.0 Qwen3-4B
  tags. If licensing ever matters for the lab, the Apache-2.0 generalist above is the cleaner base.

### #3 — none worth a dedicated pull
- Deliberately empty. opencoder-1.5b / granite-code:3b exist on Ollama but show no credible public
  beat over qwen2.5-coder:3b at our size; adding one would spend a slot for no measured gain. Revisit
  only if/when a sub-8B Qwen3-Coder (or similar) ships.

**Lane-3 ranking:** 1) qwen3:4b-instruct-2507 *if already pulled for tools* (generalist that codes,
not a dedicated upgrade), 2) hold qwen2.5-coder:3b (note its non-commercial license), 3) no new
dedicated coder is justified at ≤4B today.

---

## One-look summary (all proposals, pending our harness)

| Lane | Pick | Tag | Size/quant | Headline (source) | Biggest caveat |
|---|---|---|---|---|---|
| Tools | qwen3-4b-instruct-2507 | `qwen3:4b-instruct-2507-q4_K_M` | 2.5 GB Q4_K_M | BFCL-v3 61.9, IFEval 83.4 (HF card) | CPU tok/s unmeasured (~4B speed); re-bench fence live |
| Tools | LFM3-1.7B | `hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M` | ~1 GB 4-bit | agent/tool-trained (Liquid docs) | no public BFCL; "no coding/complex reasoning" |
| Tools | (fix) grammar-constrained decode | — | — | removes fence-miss failure | not a model; test on existing weights first |
| Thinker | qwen3-4b-thinking-2507 | `qwen3:4b-thinking-2507-q4_K_M` | 2.5 GB Q4_K_M | BFCL 71.2, AIME25 81.3 (HF card) | "increased thinking length" → may be slower, stall risk |
| Thinker | granite4:micro (probe) | `granite4:micro` | ~2 GB | family has thinking toggle | may be instruct-only like micro-h |
| Coder | qwen3-4b-instruct-2507 (generalist) | (same as tools) | 2.5 GB | LiveCodeBench v6 35.1 (HF card) | Aider 12.9 weak; not a dedicated coder |

### Suggested bench order for the coordinator
1. **qwen3:4b-instruct-2507** — one pull serves Lane 1 (tools) + Lane 3 (generalist code); highest
   expected value, official tag, standard template. Run the T12 fence bench first.
2. In parallel, **test grammar-constrained / `format:json` decoding** on phi4-mini and the new
   instruct model — this may fix the fence problem without a new model at all.
3. **qwen3:4b-thinking-2507** — only after confirming the instruct model's footprint; bench with a
   **capped** output budget and reject if it stalls/over-thinks at 4k like qwen3:1.7b did.
4. **LFM3-1.7B** and the **granite4:micro** thinking-probe — cheap, tiny pulls; quick capability
   checks (does the fence hold? does `think:true` work?) before any full bench.

### Sources
Official HF cards: Qwen3-4B-Instruct-2507, Qwen3-4B-Thinking-2507, Qwen2.5-Coder-3B-Instruct.
Ollama registry manifests (sizes). Liquid AI docs (LFM3-1.7B, LFM2.5-2.6B deprecation). Apple
PROOF-Gen (independent BFCL cross-ref). d-central / codersera / localaimaster (landscape, 2026).
Cross-ref lab: `MODEL-FIT.md`, `THINKING-small-models-2026-10-31.md`,
`tickets/T7-magnitude-runtime-eval.md`. All vendor numbers are hypotheses pending T11/T12 + weekly
eval. *External content rephrased for licensing compliance.*
