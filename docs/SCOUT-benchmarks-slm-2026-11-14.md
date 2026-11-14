# Scout: external benchmarks for small/local models (2026-11-14)

Question: what do other people use to benchmark SLMs and agents, and what
should this lab adopt? Sources: agent-reach web+github batch 2026-11-14
(`/tmp/reach8/`, 7/8 ok), host web search. Verdicts marked [fit] are judged
against this box (8 GB Intel, CPU-only Ollama, serial load).

Already covered in-lab (do not duplicate): GSM8K-20, MMLU-20
(`scripts/gsm8k.py`, `scripts/mmlu_lite.py`), voter-18, code 5×26, T1
reasoning, T2 tier-66, T3 bank-100, Flappy end-to-end app bench, T12 tool
bench (Artemis track).

## SLM-specific suites and leaderboards

- **IIfSLM** (Zenodo 21753924): contamination-resistant intelligence index
  for SLMs. [fit: track as reference frame; compare our numbers.]
- **Smol AI WorldCup** (HF blog, FINAL-Bench): 5-axis SLM benchmark.
  [fit: track; axes may map onto our voter/code/reason/tools/app lanes.]
- **emi-dm/slm-bench** (GitHub): SLM bench harness. [fit: read before
  building anything new — may subsume our sweep runners.]
- **smaLLMs** (smallms.com): SLM benchmarking platform. [fit: reference.]
- **Awesome Agents SLM leaderboard** (<10B) + **udgamlabs board-scores**
  dataset. [fit: external comparison points.]
- **aicassindra SLM evaluation guide**: what each public bench measures.
  [fit: read once, keep as glossary.]

## Code

- **LiveCodeBench** (+ `code_generation_lite` HF set, v5 leaderboard):
  holistic, contamination-free by design (fresh contest problems).
  [fit: ADOPT lite slice — our exec harness (poison-filter + timeout-loop
  killer) already implements the hard parts.]
- HumanEval/MBPP: classic, largely saturated + contamination-suspect for
  current models. [fit: skip except tiny sanity slices.]

## Agents

- **Terminal-Bench** (harbor-framework, + v2/science): terminal-agent tasks.
  **tbench-local**, **terminal-bench-mini** (Core-19 results page), and a
  Qwen-local trace dataset show people DO run it small/local.
  [fit: SPIKE terminal-bench-mini — IF Docker is viable on this Mini
  (unverified; Docker Desktop on 8 GB Intel is the risk). Else skip with reason.]
- **SWE-bench / SWE-bench-Live / SWE-bench-Pro-v2**: real-repo tasks.
  [fit: SKIP — needs big models, long contexts, containers; out of weight class.]
- Qwen Code / Pi / Crush / SmallCode trial (separate track): our own
  harness comparison doubles as the agent eval until Terminal-Bench lands.

## Tool calling

- **BFCL V4 leaderboard** (+ SUPPORTED_MODELS): the standard.
  [fit: full harness heavy; consider a mini slice later.]
- **Manojb/small-llm-tool-use-bench** (HF dataset): small-model tool bench.
  [fit: ADOPT — extends the T12 tools lane directly.]
- **TinyLLM** (arxiv 2511.22138): SLM eval+optimization for agentic edge tasks.
  [fit: read; methods may transfer.]
- **The Local Bench** System-1 ranking: fast-model tool ranking.
  [fit: reference.]

## Instruction following / general

- **IFEval**: verifiable instructions (the strongest match for our
  strict-parse discipline). [fit: ADOPT a mini slice — fills the biggest
  unmeasured gap: following instructions exactly.]
- MMLU full / HellaSwag / ARC / BBH: [fit: skip full runs; our -20 lites +
  voter hard-10 cover the signal cheaply.]

## Proposal (ranked, cheapest first)

1. IFEval-mini runner (new, voter-style harness) — fills instruction-following gap.
2. Manojb tool-use-bench slice (extends T12).
3. LiveCodeBench-lite slice (reuse exec harness).
4. Terminal-Bench-mini spike (gated on Docker viability check).
5. Track IIfSLM + Smol WorldCup as external frames; no builds.
