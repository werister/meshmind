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
- No sidecar `/fetch` endpoint yet (the models call tools through an agent
  loop; serving fetch is a separate deploy with blast radius).
- No reader-mode quality (crude tag strip), no JS pages.

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
