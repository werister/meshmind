# Local AI Lab — Merged Spec (2026-10-27)

Panel: 3× Kiro (all report "Auto", kiro-cli 2.34.2). Round 1: unanimous
Q1=A, Q4=A. Round 2: cross-reviews (1→2, 2→3, 3→1), merged below.
Rule: majority per divergence, ties break toward 8 GB safety.

## Vote table

| # | Divergence | R1 | R2 | R3 | Merged |
|---|---|---|---|---|---|
| 1 | ledger filename | calls.log | metering.log | calls.log | **calls.log** |
| 2 | /status shape | separate calls:{} | separate metering:{} | fold into grand_total | **separate metering:{}, never fold** |
| 3 | X-Agent | forward | strip | strip | **strip, advisory-only** |
| 4 | ring buffer | yes/100 | yes/500 | yes/256 | **yes, deque(256)** |
| 5 | /calls/stream SSE | no | phase-2 | drop | **no this round** |
| 6 | cumulative total | state file | state file | state file | **state file (unanimous)** |
| 7 | /v1 no-usage streams | estimated flag | null+flag+count | null+flag | **null, excluded, counted** |
| 8 | GET /api/* | passthrough | passthrough | passthrough | **passthrough (unanimous)** |
| Q4 | deploy lane | A | A | A | **A (unanimous)** |

Key corrections the panel caught: (a) folding metered tokens into
`grand_total` double-counts agents that also POST /feedback — measured
and self-reported series stay separate; (b) recompute-from-tail goes
non-monotonic after the first log rotation — cumulative lives in a
state file; (c) `/v1` streams omit `usage` unless the client sends
`stream_options.include_usage` — absent usage records null, never 0.

## Q1 — Metering proxy (merged mini-spec)

Extend the :8081 sidecar to reverse-proxy inference paths with a
metering tap. Non-negotiable conditions: **C1 fail-open** (a meter
failure never withholds backend bytes) and **C2 tap-never-buffer**
(bounded tail scan, never whole bodies in RAM).

**Routing (Caddyfile, additive):** `handle /v1/*` and `handle /api/*`
→ :8081, above the catch-all. Showcase routes unchanged. The sidecar
sets `Host: 127.0.0.1:11434` upstream on ALL forwarded paths
(metered and passthrough alike — Ollama rejects anything else).

**Endpoints gained:** `POST /api/chat|/generate|/embeddings`,
`POST /v1/chat/completions|/completions|/embeddings` (metered);
everything else under `/api/*|/v1/*` is transparent passthrough
(GETs: 15 s timeout; generations: 300 s). `GET /calls?limit=N`
(default 50, max = ring size) serves newest-first from the ring.
`/status` gains `metering:{calls_total, prompt_tokens_total,
eval_tokens_total, ring_len, backend_up, unmetered_stream_calls}`;
the existing `tokens{}` block is byte-identical.

**Streaming:** relay every chunk immediately; scan a bounded tail
buffer for the totals frame (`done:true` on /api, terminal `usage`
on /v1). `/v1` streamed without usage → `eval_tokens:null`,
`no_usage:true`, excluded from sums, counted in
`unmetered_stream_calls`. Client disconnect mid-stream →
`partial:true`. Slow SSE subscribers N/A (no push feed this round).

**Storage:** `calls.log` JSONL (no bodies ever — numbers only),
rotate at 50 MB → `calls.log.1`; ring `deque(maxlen=256)` serves
reads, warmed from file tail at startup; cumulative headline in
`proxy-token-total` state file (atomic write, `monitor-state`
pattern), bumped per finalized call.

**Failure modes:** backend down → 502 + `ok:false` row; bodies over
cap → stream through, `truncated:true`; parse error → client still
gets bytes, row notes `meter_parse_failed`; missing X-Agent →
`"unknown"`; concurrency capped (~16 in-flight) so per-call bounds
imply an aggregate bound.

**Acceptance (Mini loopback):** non-streamed probe via :8080 →
`metering.calls_total` +1 with matching agent/model/eval_tokens;
streamed probe arrives token-by-token with exactly one row;
Ollama stopped → 502 inside timeout, client never hangs;
`ring_len` ≤ 256 under load; responses byte-identical meter-on vs
meter-off; rotation never moves the cumulative backward.

**Implementation traps:** (1) the existing 4 KB `do_POST` guard is
`/feedback`-only — proxy paths must bypass it or all chat breaks;
(2) Host rewrite on passthrough GETs too; (3) X-Agent is
self-declared — dashboard labels it so, never auth; (4) nulls never
enter sums.

## Q4 — Deploy lane: A

Coordinator deploys over existing SSH this round. No agent keys:
three standing credentials on a tailnet-exposed 8 GB box (each able
to load a banned 14B model, fill disk, or alter exposure) is a
security-posture change deserving its own decision, not deploy
convenience. Revisit only if coordinator latency becomes the
bottleneck, then least-privilege (forced/restricted command).

## Not verified (build crew must close)

- Ollama 0.32.1 `/v1` SSE framing/`usage` placement live.
- RAM/CPU blast radius under concurrent load (reasoned, not measured).
- Acceptance commands specified, not executed (no Mini access in panel).
