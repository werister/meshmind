# Model scout 2026-11-03 — better versions for the 8 GB Intel box

Builds on round6 + MODEL-FIT (no repeats). All tags below verified against
primary sources (ollama.com/library pages fetched live, or named origin).
Box rules still hold: CPU-only, Ollama 0.32.1 (old — arch support is the #1
risk for 2026 models; LFM3 precedent), ~4k ctx (8k proven on <=1.7B only),
disk at floor (every pull must name its funding removal).

## Pull candidates (ranked)

### 1. `nemotron-3-nano:4b` (2.8 GB Q4_K_M) — voter/agentic challenger
- Source: [ollama.com/library/nemotron-3-nano/tags](https://ollama.com/library/nemotron-3-nano/tags)
  (979K pulls, tag updated 2 weeks ago; 256K ctx rated).
- Why: 2026 agentic 4B; independent 8 GB measurements 7/7 + 6/6
  (secondhand: kimono-oyaji Oct-2026 roundup — treat as lead, not proof).
- Lane fit: yes/no voter vs gemma3:4b/phi4-mini; possible agent-loop model.
- Risks: 2026-new arch on Ollama 0.32.1 (MEDIUM — test load first);
  NVIDIA Open Model License, not Apache (verify terms before reliance).
- Funded by: REMOVE `qwen3:8b` (5.2 GB, flagged do-not-run, drowns box).
  Net disk: -2.4 GB. Test: 2-probe smoke, then 10Q mini-bench.

### 2. `ministral-3:3b` (3.0 GB Q4_K_M) — multimodal voter + tools
- Source: [ollama.com/library/ministral-3/tags](https://ollama.com/library/ministral-3/tags)
  (1.6M pulls; tags 10 months old = better 0.32.1 odds). Apache-2.0
  (secondhand: vdf.ai Oct-2026 license check; jetson-ai-lab notes the
  `:3b` tag = Instruct 2512, tools+vision).
- Why: 3B Mistral instruct with tools AND vision in one tag; edge-designed.
- Lane fit: voter; vision second opinion vs gemma3:4b; tools fallback.
- Risks: LOW-MED arch risk (mistral family, old support; 2512 tweaks untested
  on 0.32.1). 256K rated ctx is fantasy here — test at 4k.
- Funded by: phase AFTER nemotron measures out; needs ~3 GB from a second
  removal decision (owner call — no voter should go without a bench loss).
- Test: vision smoke (red/blue), T12-lite tools, 10Q votes.

### 3. `qwen2.5:1.5b` (~1 GB) — coder-lane lottery ticket
- Source: secondhand (specpicks 2026 Pi-server roundup: 8-12 tok/s,
  "for code and JSON" at q5_K_M). Tag assumed from qwen2.5 family
  convention — VERIFY on library page before pull.
- Why: coder lane is 0/3 EXEC (opencoder, qwen2.5-coder:3b, 2507-instruct
  all failed parse_qs). Cheapest new coder experiment (~1 GB).
- Test FIRST (free, installed): EXEC-test `smollm3-3b` on parse_qs —
  bakeoff KEEP for votes, coder UNPROVEN. Pull 1.5b only if smollm3 fails.

## Ruled OUT (with reason)

- Qwen3-Coder small: DOES NOT EXIST. Library ships 30b/480b only
  (localaimaster 2026 tools list; flexion registry scrape 2026-09-15;
  hermes skill explicitly warns `qwen3-coder:8b` is a mistake). One
  conflicting aggregator row (llmconfigurator 8B) is single-source —
  unconfirmed, do not plan on it.
- Llama 3.2 3B: widely recommended for 8 GB (HumanEval 52.8% secondhand),
  but LOCALLY removed Oct-28 for failing our evals. No re-pull without
  new evidence.
- Gemma 4 E2B (`gemma4:e2b-it-qat` 4.3 GB QAT; Q4 ~3.2 GB): best-CPU-tradeoff
  claim (aitoollabs, 18/20) is tempting and google/gemma-4-e2b-gguf exists —
  but 2026-new arch = HIGH 0.32.1 risk (LFM3 precedent) and 4.3 GB strains
  RAM. Watchlist until Ollama upgrade. Note: TurinTech (our tools winner)
  ships `turintech/gemma-4-e2b-it-artemis` (2.3 GB) — the future variant.

## Pre-pull protocol (each candidate)
1. `ollama show <tag>` load check FIRST (arch compat, like RWKV proved).
2. 2-probe yes/no smoke (temp 0, think:false where applicable).
3. Lane bench (votes: 10Q; tools: T12-lite; coder: EXEC parse_qs; vision: colors).
4. Funded swap only: name the removal, keep 15 GB floor, record manifest.
