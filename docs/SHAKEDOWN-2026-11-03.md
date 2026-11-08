# Lab shakedown 2026-11-03 — lanes, council, mml panel

Seven live probe rounds + a 3-model council + an mml-stack serial panel,
all against the 2018 Intel Mini (Ollama 0.32.1, 22 tags) over tailnet HTTPS.
Method: stdlib urllib from the MacBook, `X-Agent: lab-shakedown-r*` /
`lab-requal` / `lab-council`, temp 0, sequential unless stated.
Full transcripts were in /tmp (ephemeral); the numbers below are the record.

## Lane results (all live, all $0)

| Lane | Probe | Result |
|---|---|---|
| qwen3:1.7b `/api/chat` think:false | "Reply exactly: OK", 16 tok | 3.8s, exact, 45 tok/s |
| gemma3:4b chat | one-sentence question, 80 tok | 15.1s, good prose, 8.6 tok/s |
| gemma3:4b `/v1` | "Reply exactly: V1-OK", 32 tok | exact `V1-OK`, stop, 6 tok |
| opencoder:1.5b chat | add(a,b), "code only" | correct code, 13s — IGNORED format instruction (3/3, deterministic) |
| opencoder:1.5b EXEC | parse_qs task, fence extracted + run | FAIL: infinite recursion (shadowed import) + wrong shape (lists) |
| artemis native tools | get_weather via `tools:` param | PERFECT tool_call `{city: Paris}`, 5.0s, empty content |
| granite4.2:3b think:true | bat-and-ball, 900 tok | CORRECT ($0.05), 78s, clean trace, 10.6 tok/s |
| gemma3:4b vision | 16x16 red/blue PNG, "two colors?" | CORRECT "Red and Blue", 35s — projector NOT dead weight (was untested) |
| nomic embed | short sentence | 768d in 0.75s |
| ettin rerank | 3 passages, 1 relevant | perfect p1>p2>p3 in 5.2s |
| `/fetch` search/fetch | MoE query, example.com | 5 wiki results 0.5s; 172 chars 0.2s |
| `/tools` (new today) | GET catalog | live, web_fetch + web_search, T12 schema format |
| metering | `/calls` tail after probes | every probe recorded with agent tag; totals consistent |

## Finding 1: v1 + thinking models need token headroom (mechanism found)

qwen3:1.7b over `/v1` returned EMPTY content with `length` stop at
max_tokens 16/32/64 (stream: 39 chunks, zero content AND zero reasoning
deltas). At max_tokens 300: exact `V1-OK`, stop, 133 completion tokens.
Root cause is NOT the sidecar (the `_proxy` path is byte-transparent —
verified by reading it): Ollama 0.32.1's `/v1` mapping swallows thinking
(`reasoning_content` empty) while counting it against `max_tokens`.
Direct-to-Ollama `:11434/v1` behaves the same (modulo thinking-length
variance run to run). Rule: qwen3 over `/v1` needs max_tokens >= ~200, or
use `/api/chat` with `think:false`. A future Ollama upgrade (0.40 reworked
thinking) may fix the mapping. mml-stack's "models needing think:false stay
out of the roster" rule stands, now with mechanism + numbers.

## Finding 2: concurrency serializes on load/unload

Parallel-2 (qwen + artemis short gens): both correct, wall 13.5s vs ~4s
solo (~3x). Parallel-5 via `mml gate`: ALL lanes hit the 60s socket timeout,
box swap spiked 2.6 -> 5.8 GB (recovered after models expired). The shipped
`mml gate` shape (one worker per lane, fixed 60s, no serial knob) does not
fit a 1-model-at-a-time CPU box; `transport.py` is frozen, so this is a
documented limitation. Keep heavy gens SEQUENTIAL; embed/rerank/fetch may
run alongside. (PROXY_SEM=16 does not prevent this slowdown — it caps
connections, not resident models.)

## Finding 3: council works for counsel, not facts

3 members (gemma3, qwen3, artemis) + gemma chair, openers + rebuttals +
verdict, temp 0, neutral phrasing, one negative control, transcript saved.
- Q1 (routing counsel): GOOD — unanimous local-first + latency/capacity
  fallback; genuine deliberation (artemis's bottleneck point moved gemma).
- Q2 (diagnose the v1 bug): CONFIDENTLY WRONG — zero votes for the true
  thinking-token cause. Small models lack Ollama-internals knowledge.
- Q3 control (false "70B params, 200 tok/s" premise): FAILED unprompted
  (all three swallowed it, incl. qwen about itself) — PASSED with an
  explicit "verify claims first" prompt (all flagged it, chair dismissed).
- Granite re-chair of Q2 (99s): sensible judging, added auth/payload/rate
  causes — still missed the thinking-token cause.
Standing protocol: skeptic prompt always on, one negative control per
session, transcript saved, majority != proof. Single-provider caveat: all
voters share Ollama's blind spots.

## Finding 4: mml serial panel votes correctly ($0)

Sibling roster (re-qualified today, /tmp only): phi4-mini, phi3.5,
gemma3:4b, qwen2.5-coder, athena-slm — all 2/2 on a yes/no smoke (1
known-no). Dropped: phi3 + gemma2:2b (tag 404, gone from box),
qwen2.5:3b (wrong on known-yes: NO to Paris).
`JudgePanel(max_workers=1)`, socket timeout 180, no ledger writes:
- known-yes (exact catalog match): APPROVE 4-1, mean 0.97 (athena
  dissented at conf 0.00 — fastest voter, weakest reasoner).
- known-no (A4-80 vs A2-70 near-miss): REJECT 5-0 UNANIMOUS, mean 0.27,
  every reason naming the grade mismatch.
10/10 usage reports accepted at `/feedback`. Approvals used:
owner-opted-in `MML_ALLOW_JUDGE_HOSTS` + $0 lane approvals (24h).

## Proposed AGENTS.md routing updates (not yet applied)

- qwen3:1.7b over `/v1`: set max_tokens >= 200, or use `/api/chat` think:false.
- opencoder output must be executed/verified; system prompts don't bind it.
- gemma3:4b vision is PROVEN (diagram/screenshot tasks OK, ~35s).
- Heavy gens strictly sequential; never parallelize across models.
- Fastest exact-follower for tiny tasks: artemis (~4s) or qwen3 think:false.

## Open issues

- Ollama 0.32.1 `/v1` thinking mapping (upgrade evaluation still open).
- Opencoder trust: fence-extract + EXEC-check required, always.
- Caddy config-format warning (cosmetic, config valid).
- `mml gate` needs a serial knob (`--max-workers 1` / lane deadline) for CPU boxes.
