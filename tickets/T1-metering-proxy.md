# T1 — Metering proxy

**Assignee:** Luna (codex CLI). **Needs:** SPEC.md Q1, repo checkout.
**No Mini SSH** — build and test against local Ollama only.

## Goal

Extend `feedback-server.py` per SPEC.md Q1: proxy inference paths,
tap token counts, serve `/calls`, extend `/status` with `metering{}`.

## Scope

- Caddyfile `handle /v1/* + /api/*` → :8081 (config change, coordinator deploys).
- Sidecar: metered POST paths, passthrough for the rest, Host rewrite
  on all forwarded paths, ring buffer, `calls.log` + rotation,
  `proxy-token-total` state file, C1/C2 throughout.
- Local test script exercising the SPEC acceptance list against a
  local Ollama (any tiny model) including: rotation monotonicity,
  byte-identical meter-on/off, streamed + non-streamed counts,
  backend-down 502, /v1 no-usage null handling.

## Pass/fail

- All SPEC acceptance checks pass locally; test script committed.
- No request/response bodies persisted; no new dependencies (stdlib only).
- The 4 KB `/feedback` guard untouched for `/feedback`, bypassed on proxy paths.

## Guardrails

Own worktree only, merge nothing, no secrets in code or logs,
tiny writes (disk is tight). Coordinator reviews, deploys to Mini,
runs Mini acceptance.
