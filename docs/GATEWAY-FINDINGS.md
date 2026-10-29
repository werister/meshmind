# Gateway bake-off findings (coordinator → gateway user)

Executed 2026-10-28 → 29 on the Mini (2018 i5, 8 GB, Ollama 0.32.1).
All inference traffic went through the metering proxy and is reflected
on the dashboard (calls 139 → 201, +62 exactly: 40 8Q + 15 ladder +
6 embed-probe + 1 verify chat; agents `run_8q` / `run_ladder` /
`embed-probe` attributed).

## Pinned environment (numbers are relative to this)

- KV cache: default (f16 — `OLLAMA_KV_CACHE_TYPE` unset in server env).
- Server parallelism: default (`OLLAMA_NUM_PARALLEL` unset).
- Ladder: `num_ctx=4096` window with a SHORT prompt (21–158 prompt
  tokens) — this measures 4k-window residency + short-gen speed, not
  4k of content. `tok_s` is aggregate (all clients' tokens ÷ wall).
- If Phase 5 adopts q8_0 KV, re-run ladders: headroom numbers are KV-relative.

## Pulls (all guards green, sizes byte-exact vs registry)

| Model | Spec | Bytes | Verdict |
|---|---|---|---|
| granite4:micro-h | tag | 1,942,583,381 | pulled, probed |
| lfm2.5-1.2b-…:bakeoff | LFM2.5 GGUF (supersedes LFM2) | 730,895,168 | pulled, probed |
| huggingfacetb-smollm3-3b-…:bakeoff | SmolLM3 GGUF (resolved) | 1,915,305,792 | pulled, probed |
| qwen3:1.7b | tag | 1,359,293,444 | pulled, probed |
| gemma3:4b | tag (incl. 851 MB vision layer) | 3,350,272,403 | pulled, probed |
| bge-m3:latest | tag (embeddings) | 1,157,672,605 | pulled, embedded |

Freshness re-check held: no same-class successor exists for the kept
slots (qwen3.5:2b, gemma4:e2b, LFM3-1.7B are larger/different class —
Tier-2 leads in PULLPACK).

## 8Q filter (mixed 4/4 ground truth, run twice: direct + proxy)

| Model | Direct | Via proxy | Notes |
|---|---|---|---|
| granite4:micro-h | 4/4 pass | 4/4 pass | 8/8 correct both runs, stable |
| smollm3-3b | 6/2 pass | 6/2 pass | stable; misses Q5+Q8 |
| qwen3:1.7b | 5/3 pass | 5/3 pass | stable; misses Q8 |
| gemma3:4b | 5/3 pass | 5/3 pass | stable; misses Q8 |
| lfm2.5-1.2b | 6/2 pass | **8/8 all-yes FAIL** | yes-unstable → FILTERED |

4/5 models perfectly stable across both runs; only LFM2.5 flipped
(6/2 → 8/8 always-yes). The filter worked as designed: LFM2.5 skips
ladders. Methodology gap for v2: runners send no temperature/seed,
so close calls can flip — pin `temperature=0` + seed next round.
Q8 (rename-as-data-loss) was missed by 4/5 — hardest discriminator;
consider rebalancing in a v2 set.

## Ladders (4 survivors, verdict true for all)

| Model | p1 tok/s | p2 tok/s (aggr.) | mem free in run |
|---|---|---|---|
| granite4:micro-h | 5.01 | 9.90 | 1816 MB (re-run; see anomaly) |
| smollm3-3b | 4.64 | 12.61 | 2310 MB |
| qwen3:1.7b | 3.16 | 20.36 | 2414 MB |
| gemma3:4b | 2.91 | 8.77 | 1826 MB |

Anomaly + resolution: granite's first ladder read mem_free 20 MB
(cold-start transient). Re-ran granite on an idle box: 1816 MB with
matching tok/s → transient confirmed, not granite-specific.
Parallel-2 never queued-failed: the deployed server served 2 concurrent
clients on every model (that IS the finding for this config).

## Embeddings mini-probe (sanity: similar > dissimilar)

| Model | Dim | Cos sim / dis | Margin | Speed |
|---|---|---|---|---|
| nomic-embed-text:v1.5 | 768 | 0.827 / 0.351 | 0.48 | ~50 ms |
| bge-m3 | 1024 | 0.861 / 0.470 | 0.39 | ~400 ms |

Both pass sanity. Nomic wins this mini-probe: better margin at
6–9× the CPU speed. One triple only — treat as directional.

## Bugs found live, fixed, tested, re-validated (T9.1)

1. `mini_pull` size lookup missed untagged specs (`bge-m3` vs
   `bge-m3:latest` in /api/tags) — now tries both.
2. `mini_pull` probe failed embedding-only models (/api/generate) —
   now falls back to /api/embeddings (model-agnostic, no heuristics).
Tests 16/16 → 22/22, then re-ran the bge-m3 pull live: ok:true.

## Not done here (gateway-user steps)

The logprob screen (`scripts/local_logprob_screen.py`) and the labelled
findings for gate agreement do not exist on this machine — they live in
your checkout. The Mini is ready; survivors + questions are deployed:

```
cd ~/local-ai-lab/gate2   # on the Mini (or via the gateway API)
# 8Q:  python3 scripts/run_8q.py --model <tag> --ollama http://127.0.0.1:8081 --questions questions-8q-v1.json
# lad:  python3 scripts/run_ladder.py --model <tag> --ollama http://127.0.0.1:8081 --status http://127.0.0.1:8081/status
# your screen against the 4 survivors, then gate agreement (kappa bar 0.7)
```

`bakeoff.py` itself was tested (10/10) but not run end-to-end live —
the pieces ran directly instead (a live run now would only re-spend
the tokens; its screen step would null without your script).

## Model verdicts (coordinator)

- KEEP: granite4:micro-h (most correct, stable, fast), SmolLM3-3B
  (fastest aggregate, stable), qwen3:1.7b (stable), gemma3:4b
  (stable, slowest gen, biggest disk).
- DROP: LFM2.5-1.2B (yes-unstable across runs — unreliable voter).

## State left behind

- Disk 15.2 GB free (floor: 15). Next pulls need Phase 3 removals
  (qwen2.5:14b 9 GB + deepseek-r1:8b 5.2 GB ≈ 14 GB reclaimable).
- T6 telemetry live: /status carries mem/swap top-level; health.log
  samples each tick with swap-delta alerts. Sidecar up since deploy.
- Cut, unchanged: magnitude (T7), ColBERT sidecar, 5-way embedding
  bake-off, keeper refresh.
