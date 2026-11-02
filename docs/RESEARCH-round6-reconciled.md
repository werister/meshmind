# Round-6 model research: reconciliation (coordinator review)

> Status 2026-11-02: historical snapshot, committed as written. Parts are
> superseded: Stage 3 (Granite 4.2 3B pulled, adopted for reasoning),
> tool-test ownership (T12 harness built), and the Ettin/T10 rerank work
> have all moved since. Open decisions partially resolved — see MODEL-FIT.md.

Sources: Gemini deep run + Perplexity R1/R2 (external, pasted 2026-10-29),
reconciled against local measured evidence (bake-off, ladders, metering)
and fresh registry checks (this doc, §4).

## Report cards

- **Gemini: WEAK.** Its "fresh discoveries" are our own inventory
  restated (phi4-mini, qwen3:1.7b, granite micro-h, smol, nomic) — zero
  genuinely new models, zero primary-source checks. Two reckless purges:
  `qwen2.5:0.5b` (the monitor probe model — removal breaks health checks
  unless reconfigured) and `bge-m3` (just pulled; lost one triple, not
  proven cruft). Unsourced assertions (e.g. "Granite beats functiongemma",
  "SmolLM3 premier micro-coder") with no executable evidence. RAM-envelope
  reasoning is directionally sound; the rest is inventory astrology.
- **Perplexity R1: SOLID discipline.** Correctly staged (record → remove
  failures → test installed → pull), honest about what registry pages do
  and don't prove (Qwen3.5 packaging warnings are gold), right call on
  conditional removals and "don't spend the 14 GB reserve."
- **Perplexity R2: THE FINDS.** Granite 4.2 3B, LFM2.5 2.6B/VL-3B, Ettin,
  Jina v3.5 (with the fork trap called out), EmbeddingGemma 2 — all with
  exact artifacts and honest publisher-vs-local caveats. This is the
  shortlist to work from.

## Claim reconciliation (external claim → local evidence → verdict)

| Claim | Local evidence | Verdict |
|---|---|---|
| Voter slot needs churn | granite 8/8 stable twice; 4/5 stable | REJECT churn — keepers stand (agree PPLX) |
| SmolLM3 is the coder pick | no code tests run here, ever | UNPROVEN — needs executable tests, not adjectives |
| Granite beats functiongemma at tools | neither tested locally | UNPROVEN — run PPLX's 6-point tool test first |
| LFM2.5-1.2B failure settles 2.6B | different model (2.69B, always-thinks) | FAIR — test 2.6B with eyes open on latency |
| Purge bge-m3 (lost mini-probe) | one triple, 0.48 vs 0.39 margin | CONDITIONAL — multilingual/index deps first (agree PPLX) |
| Purge qwen2.5:0.5b (superseded) | monitor probes target it; fastest smoke | REJECT — Gemini error |
| Granite 4.2 = granite refresh | different arch (dense 3B vs hybrid micro) | CHALLENGER, not refresh (agree PPLX) |
| Qwen3.5:2b is a 2B-Q4 pull | PPLX: page shows 2.7–3.1 GB artifacts | RESOLVE MANIFEST FIRST — name lies |
| Jina v3.5 ready to pull | needs llama.cpp fork + projector + torch, CC BY-NC | DEFER behind Ettin (agree PPLX) |
| Ettin 17M CPU-first reranker | Intel i7 benches, nomic pairings, Apache 2.0 | STRONGEST retrieval lead — verify Intel-macOS deps |

## Registry verifications (coordinator, 2026-10-29, from the Mini)

- `granite4.2:3b-q4_K_M` EXISTS: 2,244,023,965 B (2.244 GB). Our T9
  "no Ollama tag" note is stale — registry wins, tag verified.
- `LiquidAI/LFM2.5-VL-3B-GGUF`: Q4_K_M 1,674,455,072 B + mmproj
  855,763,424 B = ~2.53 GB on disk + runtime. Fits post-cleanup.
- `cross-encoder/ettin-reranker-17m-v1` EXISTS (sentence-transformers,
  onnx, openvino, safetensors tags — ONNX/OpenVINO = CPU-friendly paths).

## Proposed program (gated, disk-funded)

Disk math (listed sizes): 8b+14b (14.2 GB) + lfm2.5 (0.7) + gemma2 (1.6)
+ llama3.2 (2.0) + phi3 (2.2) + qwen3:4b (2.5) ≈ 23 GB reclaimable.
Spend verified-recovered space only; keep 15 GB floor.

- Stage 0: record manifests of removal candidates (no pulls).
- Stage 1: tag-verified removals — 14b, 8b (Phase 3), LFM2.5 bakeoff
  (measured DROP), gemma2:2b + llama3.2:3b (failing evals), phi3 (cruft),
  qwen3:4b (behavior evidence; preserve manifest first).
- Stage 2: test installed, no pulls — functiongemma 6-point tool test,
  gemma3:4b vision smoke.
- Stage 3: pull Granite 4.2 3B (2.244 GB) — coder executables + tool
  test + non-thinking voter check.
- Stage 4: Ettin 17M sidecar (ONNX path first; deps check pre-install).
- Stage 5: LFM2.5-VL 3B (~2.53 GB) — grounding/OCR vs gemma3:4b vision.
- Stage 6: EmbeddingGemma 2 text-only (304 MB) vs nomic, separate index.
- Parked: Jina v3.5 (fork+license), LFM2.5 2.6B (always-thinks latency
  risk — test only if a tool/extraction gap remains), Qwen3.5 (manifest
  ambiguity), Ministral/Falcon (watchlist).
- Holds (explicit): bge-m3 (multilingual), qwen2.5:0.5b (monitor),
  qwen2.5-coder:3b (only coder until G42 wins executables),
  qwen2.5:3b + phi3.5 (bounded eval or remove).

## Open owner decisions

1. Approve the Stage 1 removal list (irreversible without re-pull;
   manifests recorded first)?
2. Run this as a gated crew program (intake → plan-gate → builders),
   or coordinator-direct (removals + pulls are coordinator-only anyway)?
3. Tool-test ownership: 6-point harness as a built artifact (T10?) or
   coordinator hand-runs?
