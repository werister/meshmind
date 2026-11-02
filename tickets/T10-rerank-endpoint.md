# T10 — /rerank endpoint + Ettin worker (BUILD then coordinator deploy)

## Problem
Retrieval is first-stage-only (nomic dense). A CPU reranker over a
shortlist is the highest-leverage quality upgrade for language+coder —
but no served, metered rerank path exists.

## Goal
1. `POST /rerank` on the sidecar: `{query, passages: [{id, text}],
   top_k?}` → `{scores: [{id, score}], model, latency_s}`.
   Served + metered like the proxy paths (agent tag `rerank`).
2. `scripts/rerank_worker.py`: runs under the Mini's
   `~/local-ai-lab/.venv-rerank` (onnxruntime). Frozen interface:
   argv `--model-dir`, stdin JSON `{query, passages}`, stdout JSON
   `{scores: [{id, score}]}`. No hardcoded cache paths.
3. Endpoint shells out to the worker (subprocess list-args, no shell),
   timeout 60s; worker missing/unparseable → HTTP 503 + JSON error,
   never a crash.

## Non-goals
- No index rebuild, no embedder swap (nomic stays first stage).
- No Jina/ColBERT (parked behind this experiment).
- Builder never touches the Mini; coordinator deploys weights to
  `~/local-ai-lab/ettin-17m/` + restarts sidecar (backup kept).

## Behavior
- Input caps (security): ≤20 passages, ≤2000 chars each, top_k ≤ 20;
  over-cap → HTTP 400 with reason. Scores descending; stable sort.
- Latency budget: p95 single call < 5s on the Mini (measured live,
  not asserted here).
- Empty passages → `{scores: []}`, not an error.

## Failure modes
| Trigger | Visible result | Test |
|---|---|---|
| Over-cap input | 400 + reason | test_caps |
| Worker timeout/crash | 503 + JSON error, server alive | test_worker_down (stub worker) |
| Worker bad JSON | 503 + note | test_worker_garbage |
| Empty list | `{scores: []}` | test_empty |

## Tests (named, stdlib + stub worker — no onnx on the MacBook)
`tests/test_rerank_endpoint.py` (+ fixtures): caps, empty, stub-worker
scoring order, worker-down, worker-garbage. Worker itself tested
against a fake ONNX session object (injected), never real weights.

## Outcome (coordinator, 2026-11-02): LIVE
- Merged from `wt-lab-r10` (Kiro-crew build, coordinator review + Kiro
  merge-readiness review: approve-with-conditions). One coordinator change
  at merge: token columns stay null (passage counts ride `call["passages"]`).
- The builder's worker assumed ONNX `[n,1]` logits, but Ettin's
  `onnx/model.onnx` is the encoder only (`last_hidden_state [b,s,256]`).
  Coordinator recovered the head recipe live on the Mini: ST module stack
  Transformer -> CLS-Pooling -> Dense(256,GELU,no-bias) -> LayerNorm ->
  Dense(1,bias), weights from per-module `model.safetensors` (shapes
  asserted; LayerNorm eps=1e-5 = torch default, documented assumption).
  Implemented in numpy in `scripts/rerank_worker.py`.
- Live acceptance (Mini, real weights): Paris/quantum/Eiffel probe scores
  11.22/-1.30/8.03 (correct order), endpoint 200 + top_k in 2.2 s (inside
  the 5 s budget), 21-passage body -> 400 with reason, empty -> []. Tests:
  `test_rerank_endpoint.py` 16/16. Deployed: weights + tokenizer + head in
  `~/local-ai-lab/ettin-17m/`, `.venv-rerank` (onnxruntime 1.23.2), Caddy
  `/rerank` route, sidecar restarted.
- Qwen3-Reranker GGUF lane CLOSED: mradermacher Q8_0 under llama-server
  `--reranking` returned degenerate scores (one doc ~1.0, rest ~1e-12)
  with wrong, order-sensitive winners, insensitive to `--pooling rank`
  and query instruction — a bad conversion, and T10 no longer needs it.

## Ticket fields
- Door: build two-way; deploy is a sidecar restart (two-way, backup).
- Blast radius: small at build / medium at deploy (new endpoint).
- Acceptance: `python3 tests/test_rerank_endpoint.py` → exit 0, AND
  coordinator live-verifies one real rerank on the Mini post-deploy.
- May touch: `feedback-server.py` (additive route only),
  `scripts/rerank_worker.py`, `tests/test_rerank_endpoint.py`,
  `tests/fixtures/rerank/*`.
- Must not: `Caddyfile`, `.env`, `health-check.sh`, `tickets/`,
  anything on the Mini.
- Author: kiro crew R. Reviewer: coordinator + security lens at diff
  (new endpoint: caps, timeouts, no shell).
- Cost: $0. Disk note: MacBook tight — targeted tests, no installs.
