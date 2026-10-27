# Local AI Lab

Small-model inference lab on an 8 GB Intel Mac Mini (CPU-only Ollama),
served tailnet-only over Tailscale with monitoring, agent feedback,
and a showcase dashboard.

Base URL: `https://mac-mini-von-hugo-1.taild73e38.ts.net`

## Layout

| Path | What |
|---|---|
| `feedback-server.py` | Sidecar service (:8081): `POST /feedback`, `GET /status`, `GET /dashboard`, `GET /agents.md` |
| `Caddyfile` | Localhost Caddy (:8080): rewrites `Host` for Ollama, routes sidecar paths |
| `health-check.sh` | 5-minute monitor: availability, model snapshot, token probe, cumulative totals → `health.log` |
| `context-probe.py` | Max-context sweep harness (11 models × 4k–32k, skips 8B/14B per policy) |
| `AGENTS.md` | Agent quickstart (also served live at `/agents.md`) |
| `launchd/` | macOS service plists (Ollama, Caddy, monitor, sidecar) |
| `docs/` | Evidence and fit notes |

Live state (`*.log`, `monitor-state`, results) is git-ignored on purpose.

## Run it (fresh Mini)

1. Install Ollama, Caddy, Tailscale; `ollama pull` the models in `docs/MODEL-FIT.md`.
2. Copy this repo to `~/local-ai-lab`; copy `launchd/*.plist` to `~/Library/LaunchAgents/`.
3. Approve Tailscale Serve for the node, then `tailscale serve --bg http://127.0.0.1:8080`.
4. `launchctl load` each plist; check `GET /status` and the `/dashboard`.

## Operate it

- Health: `tail ~/local-ai-lab/health.log` (columns: local/serve, installed, loaded, probe tok/s, cumulative totals, feedback).
- Feedback: agents POST `{agent, model, ok, note, tokens}` to `/feedback`.
- Evals: `python3 context-probe.py [--only MODEL] [--steps 4096,8192]` (background it; watch `context-probe.log`).
- Never run `qwen2.5:14b` / `deepseek-r1:8b` interactively; never `tailscale funnel`; never `OLLAMA_HOST=0.0.0.0`.

## Deploy flow

Agents build against local Ollama in their own worktrees. The coordinator
reviews and ships to the Mini over SSH (agents have no Mini SSH access),
then verifies via `/status` and the section-3 HTTPS tests.
