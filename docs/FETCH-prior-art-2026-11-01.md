# Prior art for `/fetch` — how others designed it, + what to bake in from WTMW (2026-11-01)

Companion to `FETCH-endpoint-draft-2026-11-01.md`. Researched how real repos/tools design
SSRF-safe URL fetching and tool-serving endpoints, and mined the `what-the-market-wants` (WTMW)
project for patterns worth reusing. **Proposals only — no code changes.** External claims are
hypotheses to verify; the design *decisions* are what transfer.

---

## Part A — how others built SSRF-safe fetch (the consensus is strong and specific)

The literature and reference implementations converge on a **three-layer, defense-in-depth,
fail-CLOSED** design. This directly validates and sharpens the draft's SSRF section.

### The agreed three-layer pattern (reject independently at each layer)
1. **Parse layer** — scheme allowlist `http`/`https` only; **port allowlist 80/443**; URL-length
   cap. Do this *before* any DNS work. ([voxgig](https://voxgig.com/howto/defend-a-url-fetching-endpoint-against-ssrf),
   [takeaseatventure](https://dev.to/takeaseatventure/the-ssrf-check-that-passed-every-test-and-still-had-a-fail-open-branch-jj6))
2. **DNS layer** — resolve the hostname and **check EVERY returned address** (v4 and v6), not
   just the first. "A hostname can resolve to several, and an attacker controlling DNS can return
   one public and one private address hoping you check the wrong one."
   ([Rehanfaisal/ssrf-safe-fetch](https://github.com/Rehanfaisal/ssrf-safe-fetch),
   [itechguides](https://www.itechguides.com/how-to-stop-ssrf-validate-the-ip-your-api-actually-connects-to/))
3. **Redirect layer** — re-run layers 1–2 on **every redirect hop**; a public URL can 302 to
   `http://169.254.169.254/`. ([dev.to/jaryn](https://dev.to/jaryn_123/block-ssrf-redirect-chains-before-your-url-fetcher-reaches-private-networks-34ga))

### Blocklist (what "private/internal" must cover — more than the draft listed)
Loopback (`127/8`, `::1`), link-local + **cloud metadata** (`169.254/16` → `169.254.169.254`,
`fe80::/10`), RFC1918 private (`10/8`, `172.16/12`, `192.168/16`), **IPv4-mapped IPv6**
(`::ffff:169.254.169.254` — a classic bypass), **unspecified/`0.0.0.0`**, multicast, reserved
(RFC 6890 special-purpose), and **carrier-grade NAT `100.64/10`**. Block literal hostnames
`localhost`, `metadata.google.internal`.
([takeaseatventure](https://dev.to/takeaseatventure/the-ssrf-check-that-passed-every-test-and-still-had-a-fail-open-branch-jj6),
[standardbeagle/mastra](https://errors.standardbeagle.com/mastra-ai/mastra/url-resolves-to-a-private-or-reserved-address/))
→ **Adds to the draft:** IPv4-mapped IPv6, `0.0.0.0`, and CGN `100.64/10` were not in the draft's
list; add them.

### The two failure modes everyone warns about (and the draft must dodge)
- **Time-of-check/time-of-use (DNS rebinding):** checking the hostname, then letting the HTTP
  library resolve *independently*, leaves a TOCTOU gap — the name can rebind to an internal IP
  between check and connect. **Fix: pin the connection to an IP that already passed** (resolve →
  validate → connect to that literal IP with the original `Host` header), per
  [itechguides](https://www.itechguides.com/how-to-stop-ssrf-validate-the-ip-your-api-actually-connects-to/)
  and [pantheon-ssrf-guard](https://pypi.org/project/pantheon-ssrf-guard). The draft listed this
  as an optional follow-up — the prior art says **it's the core requirement, not optional**, if
  the endpoint is exposed beyond a trusted tailnet. For a tailnet-only single-user box the
  getaddrinfo pre-check is a reasonable v1, but **document the TOCTOU gap explicitly** and plan
  the pin.
- **Fail-OPEN branches:** "The SSRF check that passed every test and still had a fail-open
  branch" — an exception path (DNS error, unexpected family) that *allows* the fetch. **Fix:**
  the guard must `raise`/deny on *any* uncertainty; default-deny, never default-allow.
  ([takeaseatventure](https://dev.to/takeaseatventure/the-ssrf-check-that-passed-every-test-and-still-had-a-fail-open-branch-jj6))
  → This is the opposite of `_record_call`'s fail-OPEN metering: **metering fails open, the SSRF
  guard fails closed.** Worth stating in the code's docstring so no one "helpfully" makes the
  guard tolerant.

### Reference implementations to mirror (don't adopt a dep — copy the shape)
- **`Rehanfaisal/ssrf-safe-fetch`** — *one file, stdlib only, no deps*: a `fetch(url)` that
  raises `SafeFetchError`, resolves every address, blocks the full special-range set, caps size.
  **This is almost exactly the lab's constraint** (stdlib, no deps). Mirror its `fetch()` +
  typed-error shape in the lab's hardened `fetch_url`. ([repo](https://github.com/Rehanfaisal/ssrf-safe-fetch))
- **mastra's `assertAllowedUrl`** — normalizes hostname, rejects blocked names + private/reserved
  IPs *before* fetching; a clean "assert-then-fetch" seam. ([standardbeagle](https://errors.standardbeagle.com/mastra-ai/mastra/url-resolves-to-a-private-or-reserved-address/))
- **Cautionary tale — LangChain SSRF bypass:** a "resolve hostname, if public return URL as safe"
  check was bypassable — *returning the URL* re-opens the TOCTOU gap vs. *returning/connecting to
  the validated IP*. ([medium/rickidevs](https://medium.com/@rickidevs/i-found-an-ssrf-bypass-in-langchain-then-got-a-duplicate-dddbbfc873c0))
  → Lesson: validate-then-reuse-the-same-IP; don't validate a name and re-resolve.

**Net adjustment to the draft's §1:** keep the three-layer structure; (a) expand the blocklist
(IPv4-mapped IPv6, `0.0.0.0`, CGN); (b) promote connection-pinning from "follow-up" to "stated
requirement with a documented v1 gap"; (c) make fail-CLOSED explicit; (d) point the implementer
at `ssrf-safe-fetch` as the shape to copy.

---

## Part B — patterns to bake in from `what-the-market-wants` (WTMW)

WTMW (`~/dev/what-the-market-wants`, MIT, @werister) is a FastAPI "Order-to-ERP" agent workbench
built on the exact stack employers screen for: ingest → extract → hybrid-RRF match → **HITL
gate** → SSE pipeline streaming → idempotent approve/reject → eval harness. Several of its
patterns map cleanly onto the lab — some onto `/fetch`, some bigger.

### Directly reusable for the `/fetch` endpoint (and the sidecar generally)
1. **SSE streaming pattern** (`api.py` `stream_order_events` → `StreamingResponse(..., media_type=
   "text/event-stream")`, yielding `event: {stage}\ndata: {json}\n\n`). → If `/fetch` ever grows a
   long operation (e.g. multi-page crawl or search-then-fetch), this is the lab's reference for
   streaming progress over HTTP. Also a clean model for a future streaming `/status` feed instead
   of meta-refresh. *Note: WTMW uses `async` FastAPI; the lab sidecar is sync stdlib
   `ThreadingHTTPServer` — the SSE wire format ports, the async framework does not.*
2. **Status-code discipline** (`422` validation, `404` not-found, `409` HITL-blocked,
   `400` bad-override). → Matches and justifies the draft's endpoint-ran-vs-infra split; adopt
   the same explicit codes (`400` bad body, `413` oversize, `429` rate-limited, `200`+`ok:false`
   for a blocked/failed fetch).
3. **`/health` and `/metrics` endpoints** as first-class. → The lab has `/status`; WTMW's split of
   liveness (`/health`) vs. aggregate metrics (`/metrics`) is a cleaner convention if the sidecar
   grows. Low priority, but a good pattern to note.
4. **Measured-not-claimed eval harness** (`eval_harness.py`: "100% SKU resolution … latency & cost
   reported — measured, never claimed"). → Exactly the lab's verified-vs-estimated ethos; any
   `/fetch` or `/tools` acceptance should report measured numbers, not assertions.

### The bigger idea worth baking in — the HITL gate
WTMW's standout pattern is the **deterministic human-in-the-loop gate**: the pipeline *blocks ERP
dispatch with a `409` until every ambiguous line is human-resolved*, with idempotent
approve/reject and `sku_overrides`. The lab has no HITL concept today. **Where it could matter:**
a tool endpoint that can take a consequential action (a future `send_message`-style real tool, or
an agentic fetch-then-act loop) should gate the action behind an approve step rather than
auto-firing — the `409-until-approved` pattern is the clean, idempotent way to do it. For the
*read-only* `/fetch`/`/search` this is not needed (reads aren't consequential), but it's the
right design the moment a lab tool can *write* or *send*. Flag for the tool-registry roadmap.

### What does NOT transfer (be honest)
- **Postgres + pgvector + Alembic + SQLAlchemy ORM** — WTMW's persistence stack is a heavy
  Docker-compose footprint; the lab is a stdlib-only 8 GB CPU box. The **hybrid-RRF retrieval
  idea** (`retrieval.py`: BM25 + dense + Reciprocal Rank Fusion) is conceptually interesting for
  the lab's bge-m3 rerank lane (T10), but its pgvector implementation does not fit on-box — borrow
  the RRF *algorithm*, not the stack.
- **async FastAPI framework** — the sidecar is deliberately stdlib `ThreadingHTTPServer`; don't
  pull FastAPI in for one endpoint.

---

## Recommendations (merge into the `/fetch` build)
1. **SSRF guard = copy the `ssrf-safe-fetch` shape** (stdlib, one file, `fetch()`+typed error),
   with the expanded blocklist (IPv4-mapped IPv6, `0.0.0.0`, CGN `100.64/10`), three-layer checks,
   **fail-CLOSED**, and connection-pinning stated as the requirement (v1 getaddrinfo pre-check OK
   if the TOCTOU gap is documented). This is the one non-negotiable.
2. **Adopt WTMW's status-code discipline** (`400/413/429` + `200`/`ok:false`) and its
   **measured-not-claimed** eval stance for acceptance.
3. **Note the SSE wire format** (`event:/data:`) as the lab's reference for any future streaming
   endpoint — wire ports, async framework does not.
4. **Reserve the HITL `409-until-approved` gate** for the first lab tool that can *act* (write/
   send), not for read-only `/fetch`. Put it on the `/tools` registry roadmap.
5. **Borrow RRF (algorithm) for the rerank lane**, not WTMW's pgvector stack.

### Evidence / cross-ref
SSRF: ssrf-safe-fetch (stdlib ref), voxgig/itechguides/takeaseatventure/jaryn (3-layer +
fail-closed + redirect), pantheon-ssrf-guard (connection pinning), mastra assertAllowedUrl,
LangChain SSRF-bypass case (medium/rickidevs). WTMW: `~/dev/what-the-market-wants`
(`src/wtmw/api.py` SSE+HITL+status codes, `eval_harness.py`, `retrieval.py` RRF, `pyproject.toml`
stack). Lab: `FETCH-endpoint-draft-2026-11-01.md`, `feedback-server.py` (`_record_call` fail-open
contrast), `scripts/web_tools.py` (no guard today), T10 rerank. All external numbers hypotheses;
design decisions are the transferable part. *External content rephrased for licensing compliance.*
