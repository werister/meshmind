# Build brief for muse — Local AI Lab (handoff 2026-11-01)

You are building for the **Local AI Lab**: an 8 GB Intel Mac mini (i5-8500B, CPU-only Ollama
0.32.1 behind Tailscale), served via a **stdlib-only Python** sidecar (`feedback-server.py`) +
Caddy. Hard constraints: **stdlib only, no new deps, no Docker, no heavy frameworks**; one
generative model resident at a time; ~3.8–4.4 GB model budget; 4k context typical.

## Read first (committed research — the grounding)
- `docs/GAPS-whats-left-2026-11-01.md` — the prioritized "what's left" list (start here).
- `docs/FETCH-endpoint-draft-2026-11-01.md` + `FETCH-prior-art-2026-11-01.md` +
  `FETCH-infra-protection-2026-11-01.md` — the `/fetch` endpoint design + SSRF/egress guard.
- `docs/EVAL-from-behavior-2026-11-01.md` — mining `calls.log` for regression/drift.
- `docs/CONTEXT-MAX-2026-11-01.md` — KV q8_0 lever, context≠reasoning.
- `docs/SCOUT-benchmarks-quants-providers-2026-11-01.md` — benches, quants, providers.
- `scripts/web_tools.py` (fetch/search backends, **no SSRF guard**), `feedback-server.py`
  (`_record_call`, `send_json`, `do_POST`/`do_GET` dispatch, `PROXY_SEM`, call-entry schema),
  `tests/test_tool_bench.py` (the in-process stub-server test pattern to copy).

## Rules of engagement
- **Work in a git worktree** (you were launched with `--worktree create`), never on the main
  working tree. Small, reviewable commits.
- **Stdlib only.** If a task seems to need a dep, stop and note it instead.
- **Proposals already exist** — implement to the committed design docs; don't redesign.
- **The SSRF guard is P0 and fail-CLOSED** — it protects localhost services (Ollama :11434,
  the sidecar :8081, collectors) AND the whole tailnet (block CGN `100.64.0.0/10`). Copy the
  one-file stdlib shape from `Rehanfaisal/ssrf-safe-fetch`: resolve every IP, block
  loopback/link-local/metadata/RFC1918/CGN/IPv4-mapped-IPv6/0.0.0.0, re-check every redirect hop,
  scheme+port allowlist (80/443 only), connect to the validated IP. Add the test that proves
  `127.0.0.1:11434`, `169.254.169.254`, a `100.64.x.x` tailnet address, and `file://` are all
  blocked pre-connection.
- **Tests, stdlib `unittest`, no live network** — mirror `tests/test_tool_bench.py`'s in-process
  `_StubHandler`. Every new endpoint ships with a test.
- **Metering consistency:** log new endpoints through the same `_record_call` path (e.g.
  `model:"web_fetch"`, token fields `None`, a `bytes` extra) so they show on `/calls` + dashboard.

## Build targets (highest ROI first — do as many as cleanly fit)
1. **SSRF guard module** (`scripts/ssrf_guard.py`, stdlib): `assert_allowed_url(url)` /
   `safe_get(url)` per the fetch docs. Fail-closed. Full blocklist incl. CGN `100.64/10`. Ship
   with `tests/test_ssrf_guard.py` (blocklist + redirect-hop + fail-closed cases).
2. **`POST /fetch` + `/search`** on the sidecar, wired through the SSRF guard and `_record_call`;
   8 KB body cap, `FETCH_SEM` concurrency, per-agent rate limit → 429; `200`+`ok:false` for a
   blocked/failed fetch. Ship `tests/test_fetch_endpoint.py` (stub-server pattern).
3. **`GET /tools` catalog** — machine-readable tool registry (T12 schema *format*, NOT the T12
   fixture file) so agents can discover `/fetch`, `/search`. Add an `AGENTS.md` "Web tools"
   section. Ship a test asserting the catalog validates.
4. **`replay.py`** (stdlib) — EVAL-from-behavior: read `calls.log`, re-issue sampled past prompts
   to a chosen model, diff answer/tok-s/done_reason vs the recorded run. Body-gated/opt-in. Ship a
   test over a fixture `calls.log`.
5. **Weekly-eval fix** — per DASHBOARD-CHECK: change the PASS bar from 3/3-binary to a score/ratio
   and update the model list to the current installed set. Keep the existing output schema; extend
   tests.

## The model/reasoning angle (for whoever runs the benches, not a build task)
The lab has coding/reasoning candidates **installed but unbenched** — note these in a short
`docs/MODELS-to-bench.md` if useful, don't bench them yourself (that needs the live box):
- `qwen3:4b-thinking-2507` — reasoning lane (real `<think>` channel; watch for over-thinking/stall
  at 4k).
- `qwen3:4b-instruct-2507` — codes reasonably (LiveCodeBench v6 35.1, MultiPL-E 76.8) + strong
  tools (BFCL 61.9); non-thinking so no stall.
- `granite4.2:3b` — most reliable small reasoner measured (Mamba-hybrid, low KV).
- `LFM3-1.7B` — tiny dual-mode, installed, unbenched.
- Open leads (not pulled): **Nemotron-3-Nano-4B** (agentic 4B competitor to qwen3-2507); a
  **Mamba/SSM or RWKV** small model (linear-attention prefill — the one arch that could move the
  CPU context wall); **IQ4_XS** PPL A/B vs Q4_K_M (needs raw llama.cpp). No sub-4B dedicated coder
  beats qwen2.5-coder:3b today (Qwen3-Coder floor is 30B).

## Definition of done
Each target = working stdlib code in the worktree + a passing stdlib `unittest` + a one-line note
in the relevant doc. Nothing deployed to the Mini (coordinator deploys). If a target needs the
live box or a non-stdlib dep, stop and record it rather than forcing it.
