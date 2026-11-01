# Sidecar `/fetch` endpoint — design proposal (T13 follow-up, 2026-11-01)

**Proposals only — no code changes.** Goal: serve web-fetch (and search) from the lab sidecar
so **any tailnet caller** gets it, not just `scripts/web_tools.py`. Grounded in the actual
`feedback-server.py` conventions and the existing `scripts/web_tools.py` backends.

## What already exists (reuse, don't reinvent)
- **Backends** (`scripts/web_tools.py`): `fetch_url(url)` and `web_search(query)` — stdlib,
  http(s)-only, 15 s timeout, 256 KB cap, crude HTML→text (≤8000 chars), Wikipedia-backed
  search. **Gap: no SSRF guard** — it will fetch `http://localhost`, `169.254.169.254`, etc.
- **Sidecar routing** (`feedback-server.py`): `do_POST` dispatches `PROXY_PATHS` → `/api/*`
  `/v1/*` proxy → `/feedback`; `do_GET` serves `/calls`, `/status`, `/dashboard`, `/agents.md`.
  Helpers to reuse: `send_json(obj, code)`, `PROXY_SEM` (`BoundedSemaphore(16)`), the 4096-byte
  `Content-Length` guard on `/feedback`, the `X-Agent` header convention, and `_record_call(call)`
  (rotates `CALLS`, updates `proxy-token-total`, `_bump_aggregates`, appends `CALLS_RING` — all
  fail-open under `METER_LOCK`).
- **Call-entry shape** (what `/calls` and the ring expect): `{ts, path, status, agent, model,
  prompt_tokens, eval_tokens, ok, stream, partial, truncated, duration_ms}`.

---

## (1) Placement, shape, timeouts, SSRF guards

**Placement.** A new branch in `do_POST`, *before* the proxy/`/feedback` checks, matching the
existing dispatch style:
```
if urlsplit(self.path).path.rstrip("/") == "/fetch":
    self._fetch()      # new handler method on H, next to _proxy
    return
```
Keep the `web_tools` logic importable: move `fetch_url`/`web_search` into (or import them into)
the sidecar so there is one implementation; the CLI (`web_tools.py main`) and the endpoint share
it. **Do not** have the sidecar shell out to the script (fork cost + harder to guard).

**Request (POST /fetch), JSON body, mirror the `/feedback` length-guard (small cap, e.g. 8 KB):**
```json
{"op": "fetch", "url": "https://example.com/page"}          // op=fetch  (default)
{"op": "search", "query": "..."}                            // op=search
```
`X-Agent` header identifies the caller (same as the proxy). Reject bodies > 8192 bytes with 400.

**Response (JSON, 200 on a ran-request; the backend's own ok/error rides inside):**
```json
{"ok": true,  "op":"fetch", "url":"<final>", "text":"...", "bytes":12345, "truncated":false, "elapsed_ms":812}
{"ok": false, "op":"fetch", "url":"<req>",   "error":"blocked: private address"}
```
Convention to match the sidecar: **HTTP 200 = "the endpoint ran"**, with `ok:false` + `error`
for a fetch that failed or was blocked (same split the proxy/tool-bench use: endpoint-ran vs
content-failed). Reserve non-200 for malformed request (400) and infra/guard trips you want
loud (e.g. 413 over-size body, 429 rate-limited — see §2).

**Timeouts.** Reuse `web_tools` `TIMEOUT=15` for the upstream GET; add a **total handler
deadline** (e.g. 20 s) so a slow DNS + redirect chain can't pin a worker. Cap redirects
(urllib follows by default — see SSRF note on re-checking each hop).

**SSRF guards (the real work — `web_tools.py` has none today).** Before *and after* resolving:
1. **Scheme allowlist:** `http`/`https` only (already in `fetch_url`). Reject `file:`, `ftp:`,
   `gopher:`, `data:`.
2. **Resolve the host to IPs and block non-public ranges** (stdlib `socket.getaddrinfo` +
   `ipaddress`): reject loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`,
   `fe80::/10`) — **this blocks cloud metadata `169.254.169.254`** — private (`10/8`,
   `172.16/12`, `192.168/16`, `fc00::/7`), unspecified (`0.0.0.0`), and multicast/reserved.
   Also block the literal hostnames `localhost`, `metadata.google.internal`.
3. **Re-check on every redirect hop.** urllib's default opener follows redirects *without*
   re-applying the guard — a public URL can 302 to `http://169.254.169.254/`. Options:
   (a) install a custom `HTTPRedirectHandler` that re-runs the IP guard on each `Location`, or
   (b) disable auto-redirect and loop manually (≤3 hops), guarding each. **(a) or (b) is
   mandatory** — without it the guard is bypassable.
4. **DNS-rebinding note:** guard the *resolved IP actually connected to*, not just the hostname.
   Simplest robust form: resolve, pick an allowed IP, and connect to that IP with the original
   `Host` header — documented as a hardening follow-up if the simpler getaddrinfo pre-check is
   shipped first. Flag it; don't silently assume the pre-check is airtight.
5. **Port allowlist:** 80/443 only (block 22, 25, 6379, 11434-the-local-Ollama, etc.).
6. **Content-type + size:** keep `web_tools`' text/json/xml-only and `MAX_BYTES=256 KB` caps.

> The port + localhost guard specifically must block the box's own `11434` (Ollama) and `8081`
> (this sidecar) so `/fetch` can't be used to loop back into the lab's own services.

---

## (2) Abuse design: rate limits, size caps, logging/metering

**Rate limit.** Reuse the `PROXY_SEM` concurrency pattern with a *separate, smaller* semaphore
for fetches (e.g. `FETCH_SEM = BoundedSemaphore(4)`) so a burst of fetches can't starve the
model proxy's 16 slots. Add a simple **token-bucket per `X-Agent`** (in-memory dict under a
lock; e.g. 30 fetches/min/agent) → `429 {"ok":false,"error":"rate_limited","retry_after_s":N}`.
Keep it in-memory (stdlib, no store) consistent with the lab's "no heavy deps" rule; a restart
resets it, which is acceptable for a single-user tailnet box.

**Size caps.** Request body ≤ 8 KB (400 over). Upstream fetch ≤ 256 KB (`MAX_BYTES`, already).
Response text ≤ 8000 chars (already in `html_to_text`) — set `truncated:true` when clipped.

**Logging / metering — consistent with `calls.log` + the ring.** Record every `/fetch` through
the **same `_record_call(call)`** path so it lands in `CALLS`/`CALLS_RING`/aggregates and shows
on `/calls` and the dashboard. Shape a fetch call to the existing schema, using the
token fields to carry fetch-relevant metrics without breaking consumers:
```python
call = {"ts":..., "path":"/fetch", "status": http_or_backend_status,
        "agent": X-Agent, "model": "web_fetch",     # model slot = the "tool" name
        "prompt_tokens": None, "eval_tokens": None,  # keep None (not token work)
        "ok": backend_ok, "stream": False, "partial": False,
        "truncated": truncated, "duration_ms": elapsed_ms,
        "bytes": len(body)}                          # extra field; ring tolerates extras
```
- `model:"web_fetch"` / `"web_search"` makes fetches show up as their own "model" row in the
  metering breakdown — clean per-tool visibility, no schema change for existing readers.
- Leave `prompt_tokens`/`eval_tokens` as `None` so they don't pollute token totals (the
  dashboard's token counters sum those; fetches aren't token generation). Add `bytes` as an
  extra field — `_record_call` and `/calls` pass dicts through, so extra keys are safe.
- **Never log the fetched body or full query** to `calls.log` (privacy + size); log the URL
  (truncated) and a byte count only. Mirror the `[:64]`/`[:160]` truncation discipline already
  in the sidecar.
- Fail-open like `_record_call` already is: a metering failure must never break the fetch
  response.

---

## (3) Agent discovery: how models learn the tool

Do **all three**, smallest-friction first — they serve different consumers:
1. **`AGENTS.md` section (primary, human + agent-readable, already served at `/agents.md`).** Add
   a "Web tools" block: `POST /fetch {"op":"fetch","url":...}` / `{"op":"search","query":...}`,
   with the response shape, the SSRF/ratelimit caveats, and a curl example — exactly like the
   existing `/feedback` block. This is the lowest-friction path; agents already read `/agents.md`.
2. **A machine-readable tool-schema catalog file** (`tools/web-tools.catalog.json`) in the
   **same shape as the T12 `catalog.json`** (`{name, description, parameters:{...}}`), served at
   a new `GET /tools` endpoint. This lets an agent harness auto-wire the tool and lets the lab
   grow a single discovery surface for all lab-provided tools.
3. **Do NOT merge into the T12 bench catalog.** T12's `tests/fixtures/toolbench/catalog.json` is
   a *fixed, fake-backend* 4-tool set that the bench's acceptance tests pin (exactly 4 tools);
   adding a real tool there would break `test_catalog_fixed_four` and conflate a *test fixture*
   with a *production tool registry*. Keep them separate: T12 = bench fixture; `GET /tools` =
   live registry. (They can share the *schema format*, not the file.)

Recommended: ship (1) immediately, (2) as the durable discovery surface, skip (3).

---

## (4) Offline test strategy + live acceptance

**Offline (stub-server pattern, mirroring T12's `_StubHandler`).** A network endpoint is tested
without the network by pointing the fetch backend at a **local in-process stub HTTP server**
(stdlib `http.server`, bound to `127.0.0.1:0`), exactly as `test_tool_bench.py` does for the
endpoint-vs-reasoning split. Tests (stdlib `unittest`, no pytest, no live net):
- `test_fetch_ok` — stub returns HTML; assert `ok:true`, text stripped, `bytes` set.
- `test_fetch_non_text_refused` — stub returns `image/png`; assert `ok:false`,
  `error` mentions content-type.
- `test_fetch_over_size` — stub returns > 256 KB; assert `ok:false` / `truncated`.
- **`test_ssrf_blocklist`** (the critical one) — assert `http://127.0.0.1/`,
  `http://169.254.169.254/`, `http://10.0.0.1/`, `http://[::1]/`, `file:///etc/passwd`, and a
  non-80/443 port are all `ok:false` with a `blocked` error — **without the stub even being
  hit** (guard rejects pre-connection). Parametrize the address list so new ranges are easy to add.
- **`test_ssrf_redirect_hop`** — stub 302-redirects to `http://169.254.169.254/`; assert the
  hop is caught and blocked (guards the redirect-bypass from §1.3).
- `test_rate_limit` — fire N+1 fetches as one `X-Agent`; assert the last returns 429 with
  `retry_after_s`.
- `test_metering_records_fetch` — after a fetch, assert a `/fetch` entry with `model:"web_fetch"`
  is in the ring and `prompt/eval_tokens` are `None` (didn't pollute token totals).
- `test_search_wikipedia_stub` — stub serves a canned Wikipedia API JSON; assert parsed
  title/url pairs.
- `test_bad_request` — body > 8 KB → 400; non-JSON → 400.

**Live acceptance (coordinator, on the box, over tailnet):**
- `curl -s $BASE/fetch -H 'X-Agent: accept' -d '{"op":"fetch","url":"https://example.com"}'`
  returns `ok:true` with non-empty `text`.
- `curl ... -d '{"op":"fetch","url":"http://169.254.169.254/latest/meta-data/"}'` returns
  `ok:false`, `blocked` — **the metadata guard proven live.**
- `curl ... -d '{"op":"fetch","url":"http://127.0.0.1:11434/api/tags"}'` is blocked (no loopback
  into the lab's own Ollama).
- A fetch appears in `/calls` as `model:"web_fetch"` and on the dashboard; token totals unchanged.
- Rate limit: a scripted burst trips 429. Endpoint-ran (200/ok:false) vs infra (400/429) split
  behaves as designed.

---

## (5) Search upgrade path: Brave/Bing key via env, Wikipedia fallback

Keyless Wikipedia search stays the **default and the fallback**. Layer optional real web search
behind env vars, read once at startup (mirror `FEEDBACK_SERVER_PORT`/`METER_DIR` env style):
```
BRAVE_SEARCH_KEY=...   # if set -> Brave Web Search API (https://api.search.brave.com/...)
BING_SEARCH_KEY=...    # else if set -> Bing Web Search v7
# else -> Wikipedia (current keyless behavior)
```
- `web_search(query)` picks the backend by key presence; the response keeps the same
  `{ok, query, source, results:[{title,url}]}` shape so callers don't branch — only `source`
  changes (`"brave"`/`"bing"`/`"wikipedia"`). Add an optional `snippet` field when the provider
  returns one.
- **Key hygiene:** keys come from env only (never a request field, never logged); the sidecar
  already follows this for nothing-secret today, so document it explicitly. If a keyed call
  fails (quota/network), **fall back to Wikipedia** and set `"source":"wikipedia","degraded":true`
  so the caller knows it wasn't the premium path — matches the lab's verified-vs-estimated ethos.
- SSRF/caps apply to the search *result fetch* path too if `/fetch` is later chained after a
  search; the search API endpoints themselves are fixed, allowlisted hosts.

---

## Summary of recommendations
- `POST /fetch` + `POST /fetch {"op":"search"}` as a new `do_POST` branch sharing
  `web_tools` backends in-process; `GET /tools` for a machine-readable catalog.
- **Mandatory SSRF guard** (scheme/port allowlist + resolved-IP private/link-local/loopback
  block + per-redirect-hop re-check) — the single most important addition, absent today.
- Abuse: separate `FETCH_SEM(4)` + in-memory per-agent token bucket → 429; reuse size caps;
  log via `_record_call` as `model:"web_fetch"` with `None` token fields + a `bytes` extra.
- Discovery: `/agents.md` section now + `GET /tools` catalog; keep T12's fixture separate.
- Tests: T12-style in-process stub server; SSRF blocklist + redirect-hop are the must-have tests;
  live acceptance proves the metadata/loopback blocks on the box.
- Search: env-keyed Brave→Bing→Wikipedia with identical response shape and graceful
  `degraded:true` fallback.

### Evidence / cross-ref
`feedback-server.py` (`do_POST`/`do_GET` dispatch, `_record_call` L187, `send_json` L1477,
`_proxy` L1484, `PROXY_SEM`, `CALLS_RING`, `PROXY_PATHS`, call-entry schema),
`scripts/web_tools.py` (fetch/search backends + current caps, **no SSRF guard**),
`tests/test_tool_bench.py` (`_StubHandler` in-process stub pattern, endpoint-vs-reasoning split,
`test_catalog_fixed_four` fixed-4-tools assertion), `tickets/T13` (web fetch+search tools),
`README.md`/`AGENTS.md` (`/feedback` block style, endpoint list). All a design proposal; no
code written.
