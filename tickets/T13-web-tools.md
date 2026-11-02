# T13 — Real web backends for tool-calling (fetch + search)

## Problem
T12 scores tool-calling against fake backends. The models themselves cannot
reach the web: no fetch, no search anywhere in Ollama/Caddy/sidecar. Any agent
needing fresh information must paste it in by hand.

## Goal
`scripts/web_tools.py` (stdlib only, no keys): `fetch_url(url)` (page -> text,
256 KB cap, http(s) only, 15 s timeout) + `web_search(query)` (Wikipedia API,
5 results). CLI: `web_tools.py fetch|search`.

## Live proof (coordinator, 2026-11-01)
artemis-0.8B emitted the exact call shape (with a one-shot example),
fetched the live lab `/status`, and answered the installed count (`18`) —
data no weights could hold. DDG HTML/API were tried first and are bot-walled
from here; Wikipedia search is the honest keyless scope. General web search
needs a Brave/Bing key (open follow-up, not built).

## Non-goals
- No reader-mode quality (crude tag strip), no JS pages.

## Outcome (coordinator, 2026-11-01): sidecar endpoint LIVE
- `POST /fetch` (`fetch`/`search` ops) deployed on the Mini + Caddy route;
  SSRF guard (incl. CGN/tailnet 100.64/10 + redirect re-check + port allowlist),
  30/min rate limit, FETCH_SEM(4), metering as `model:"web_fetch"` with
  null tokens. Tests: `test_fetch_endpoint.py` 6/6, `test_web_tools.py` 14/14.
- Live acceptance passed: example.com ok:true; metadata + loopback blocked at
  0 ms; search ok; 30x200 then 429s; `/calls` shows fetch rows, token totals
  unpolluted. One finding during deploy: Caddy needed an explicit `/fetch`
  route (fallback goes to Ollama) — added.

## Hardening round 2 (red-team driven, 2026-11-01/02)
Independent Claude red-team (report: `docs/REDTEAM-fetch-2026-11-01.md`,
12 findings, all PoC'd) + coordinator verification of every claim. Fixes:
- Resolve-once pin-IP connect (checked IP = connected IP; Host/SNI/certs keep
  the name): closes DNS rebinding AND the %-encoded check/connect mismatch.
- Linear `html.parser` text extraction: the old regex strip was verified
  quadratic on unclosed tags (0.40 s -> 1.59 s per doubling at 32/64 KB).
- 30 s total deadline shared across hops + chunked reads + DNS worker thread
  with timeout: slow-drip servers can't pin the 4 fetch slots.
- Host hygiene (`%`, userinfo, backslash, controls rejected pre-DNS),
  9 more blocked nets (NAT64/6to4/Teredo/site-local/benchmark/IANA-special),
  env proxies ignored, one `blocked` error string (no existence oracle).
- Sidecar: `timeout=30` on handlers, rate key = peer IP + global 120/min
  (X-Agent was rotatable/spoofable), sem->rate->body order (busy 429s don't
  spend budget), numeric status + `blocked` flag excluded from failure rollups.
- Already-fixed-in-repo at review time (verified, not re-fixed): HTTPException
  catch + sidecar safety net (ab0fb0d); the live 502 the red-team saw was a
  stale deployed sidecar, fixed by redeploying.
- Accepted as designed: fetch rows share the 256-entry calls ring; global
  burst cap 120/min; Wikipedia-only search (Brave/Bing key still open).

## Behavior
JSON to stdout, exit 0 = ran (per-call ok/error lives in the JSON),
exit 2 = usage error. Failures are `{"ok": false, ...}`, never tracebacks.

## Tests (named, stdlib only, offline)
`tests/test_web_tools.py`: `test_html_to_text`, `test_fetch_rejects_scheme`,
`test_usage`. Live network stays coordinator-run (like T12).

## Ticket fields
- Door: two-way (new files only). Blast radius: small.
- Acceptance: `python3 tests/test_web_tools.py` -> exit 0, AND one live
  model loop demonstrated (emit -> execute -> answer from fetch).
- May touch: `scripts/web_tools.py`, `tests/test_web_tools.py`.
- Must not: bench catalog/fixtures, sidecar, anything on the Mini.
- Author: coordinator. Cost: $0.
