# Red team: sidecar POST /fetch + SSRF guard

Target: main a915e23 (detached worktree). Read-only review. Scope: `feedback-server.py` (`_fetch`, `_fetch_allowed`, `do_POST`), `scripts/web_tools.py`, `tests/test_fetch_endpoint.py`, `tests/test_web_tools.py`, `tickets/T13-web-tools.md`.
Environment for PoCs: Python 3.14.7, arm64 macOS.

## Findings (severity-ranked)

### 1. HIGH: SSRF bypass via percent-encoded hostname (check/connect mismatch)
- Where: `scripts/web_tools.py:91,103` (check) vs `:135-141` (connect).
- Cause: `check_url` resolves the raw `urlsplit().hostname`. urllib connects to `unquote(Request.host)`. The two sides resolve different strings.
- Input: `http://a%2eb.attacker.test/`. With `socket.getaddrinfo` hooked, check resolved `a%2eb.attacker.test`; connect resolved `a.b.attacker.test`.
- Exploit: attacker DNS answers a public IP for `a%2eb.evil.com` and `127.0.0.1` or a LAN IP for `a.b.evil.com`. Deterministic, no timing race. Reaches ports 80/443 of loopback/LAN/tailnet; body is returned.
- Fix: pin at connect (see sketch); the check then runs on the exact string connected. Also reject `%`, `\`, `@`, userinfo and control characters in the host.

### 2. HIGH: DNS rebinding (resolve twice)
- Where: `scripts/web_tools.py:103` vs `:141`; same on every redirect hop (`:129`).
- Input: TTL-0 host answering public to the check and private to the connect.
- Fix: resolve once, check the IP, connect to that IP (sketch below).

### 3. HIGH: O(n^2) regex DoS in `html_to_text`; stalls the whole sidecar
- Where: `scripts/web_tools.py:33-34,155-157`.
- PoC inputs, fed straight to `html_to_text` (seconds):

| Input | 32 KB | 64 KB | 200,000 bytes |
|---|---|---|---|
| `b"<script>" * (n//8)` | 0.36 | 1.42 | 13.7 |
| `b"<" * n` | 0.41 | 1.62 | 15.2 |
| `b"<!--" * (n//4)` | 0.96 | 3.81 | 35.6 |
| `b"<style>" * (n//7)` | 0.41 | 1.69 | 16.0 |

- Time quadruples when size doubles. The regexes go quadratic only when an opener has no closer; balanced tags stay fast. At the 256 KB cap expect roughly 23-58 s (scaled, not run).
- GIL stall measured: a 10 ms ticker thread stalled 1.67 s while `html_to_text(b"<" * 65536)` ran (1.66 s). `re` holds the GIL, so the Ollama proxy, `/status`, `/calls` and `/feedback` in the same process freeze too.
- Fix: replace the regexes with `html.parser.HTMLParser`, skipping `script`/`style`/`noscript`/`template` content (linear). Add a wall-clock kill (worker subprocess).

### 4. HIGH: `http.client` exceptions escape `fetch_url`; handler dies with no JSON reply
- Where: `scripts/web_tools.py:174` catches only `URLError`, `OSError`, `ValueError`.
- Inputs:
  - `https://example.com/a b` (or `\x01` in the path) raises `InvalidURL`.
  - A server returning a garbage status line raises `BadStatusLine`.
  - Live: `{"op":"fetch","url":"https://example.com/a b"}` returned HTTP 502.
- Not claimed: truncated bodies. A short-body stub returned `{'ok': True, 'text': 'abc'}`.
- Impact: no response, no metering row, rate slot already spent. Contradicts T13 "never tracebacks".
- Fix: catch `http.client.HTTPException` in `fetch_url`. In `_fetch`, wrap the `fetch_url`/`web_search` call in `except Exception` and return `{"ok":false,"error":"internal"}`.

### 5. HIGH: hang vectors pin the 4 fetch slots
- Where: `scripts/web_tools.py:103,141,146`; `FETCH_SEM(4)`.
- Inputs:
  - A server sending 1 byte/s: `timeout=15` is per socket op, so the fetch was still running after 40 s.
  - A nameserver that never answers: `getaddrinfo` has no timeout.
- Impact: four such requests make all other `/fetch` calls return 429 `busy`. A 5-hop redirect chain multiplies this (each hop gets its own timeouts).
- Fix: total deadline in a chunked read loop (check `time.monotonic()` per 8 KB); DNS in a thread with `join(timeout)`; share one deadline across redirect hops.

### 6. MEDIUM: rate limit keyed on a caller-controlled header
- Where: `feedback-server.py:1637-1648,1651`.
- Inputs: rotate `X-Agent` (unlimited rate); send a victim's name (locks them out for the window); 257 distinct names evict the oldest bucket and reset its counter. A `busy` 429 still spends a slot.
- Fix: global limit plus per-client-IP key (trust `X-Forwarded-For` only from 127.0.0.1); evict by expiry; count a slot only after the semaphore is acquired.

### 7. MEDIUM: no socket timeout on the handler
- Where: `feedback-server.py:1487` (`class H`), `rfile.read(n)` in `_fetch`.
- Input: `Content-Length: 8000` and no body. The thread hangs forever; `ThreadingHTTPServer` has no thread cap; the read happens before the rate check.
- Fix: `timeout = 30` on `H`; read the body after the rate check.

### 8. MEDIUM: metering pollution
- Where: `_record_call` / `_bump_aggregates` in `feedback-server.py`.
- Inputs: rotated `X-Agent` fills `AGG_MAX_KEYS=64` so real agents fold into `(other)`; fetch rows push LLM rows out of the 256-entry ring; blocked SSRF is `ok:false` so it counts as backend failure; `status:"fetch-failed"` is a string among ints; crashed calls (#4) leave no row.
- Fix: separate fetch ring and aggregate; `blocked:true` instead of `ok:false`; numeric status.

### 9. MEDIUM: blocklist gaps
- Where: `scripts/web_tools.py:40-58`.
- Inputs that `check_url` allowed: `[::7f00:1]`, `[64:ff9b::7f00:1]`, `[2002:7f00:1::]`, `198.18.0.1`, `192.0.0.170`, `192.88.99.1`. Reachability from the Mini not tested.
- Fix: allow only `ip.is_global`, plus the explicit CGN block; add `::/96`, `64:ff9b::/96`, `64:ff9b:1::/48`, `2002::/16`, `2001::/32`, `fec0::/10`, `198.18.0.0/15`, `192.0.0.0/24`, `192.88.99.0/24`.

### 10. LOW: error-text oracle
- Where: `scripts/web_tools.py:175` and `check_url` return strings.
- Input: an internal name. `dns failed` vs `blocked: private address` shows whether the name exists (for example MagicDNS or LAN names the Mini resolves). `str(exc)` leaks raw socket errors for allowed hosts.
- Fix: one `blocked` string and fixed error codes.

### 11. LOW: redirect chain amplifies hangs
- Where: `scripts/web_tools.py:125-132`. Hop count and scheme checks are correct; the issue is per-hop timeouts (see #5).
- Fix: shared total deadline.

### 12. LOW: test gaps
- No tests for percent-encoded hosts, userinfo, rebinding, `InvalidURL`/`BadStatusLine`, slow bodies, pathological HTML, rotating `X-Agent`, semaphore exhaustion.
- `tests/test_fetch_endpoint.py` runs the sidecar with `stderr=DEVNULL`, hiding tracebacks.
- Add: `test_ssrf_pct_host`, `test_rebind_pinned`, `test_invalidurl_json`, `test_html_pathological_fast`, `test_total_deadline`.

## Resolve-once, pin-IP sketch (stdlib)

Replaces the connection step in `_get`. `check_url` stays as a cheap pre-check; the connect-time check is authoritative. The connection keeps the original hostname, so the Host header, SNI and certificate verification use the name. Each redirect hop opens a new connection and is re-resolved and re-checked.

```python
import http.client

def _resolve_checked(host, port):
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)  # one lookup
    for i in infos:
        a = ipaddress.ip_address(i[4][0].split("%")[0])
        if _is_blocked_ip(a) and not (ALLOW_LOOPBACK and a.is_loopback):
            raise ValueError("blocked: private address")
    return infos[0][4][0]          # connect to exactly an IP that was checked

class _PinHTTP(http.client.HTTPConnection):
    def connect(self):
        ip = _resolve_checked(self.host, self.port)
        self.sock = socket.create_connection((ip, self.port), self.timeout)

class _PinHTTPS(http.client.HTTPSConnection):
    def connect(self):
        ip = _resolve_checked(self.host, self.port)
        s = socket.create_connection((ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(s, server_hostname=self.host)

class _HTTP(urllib.request.HTTPHandler):
    def http_open(self, req): return self.do_open(_PinHTTP, req)

class _HTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req): return self.do_open(_PinHTTPS, req, context=self._context)

# in _get:
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),      # env proxies would bypass the pin
    _GuardedRedirectHandler(), _HTTP(), _HTTPS())
```

Caveats: `_context` is private on `HTTPSHandler` (pass `ssl.create_default_context()` instead if preferred). `getaddrinfo` still has no timeout (#5).

Test that proves rebinding is closed: the resolver answers public once, then loopback; assert one resolve and a connect to the checked IP.

```python
answers = iter(["93.184.216.34", "127.0.0.1", "127.0.0.1"]); n = [0]; seen = []
socket.getaddrinfo = lambda h, p, *a, **k: (n.__setitem__(0, n[0]+1) or
    [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), p))])
socket.create_connection = lambda addr, *a, **k: (seen.append(addr), (_ for _ in ()).throw(OSError("stop")))[0]
try: opener.open("http://rebind.test/", timeout=2)
except Exception: pass
assert n[0] == 1 and seen == [("93.184.216.34", 80)]
```

Observed: `resolves: 1 connected to: [('93.184.216.34', 80)]`. Second case: resolver returns `127.0.0.1` on the first call; it raised `ValueError: blocked: private address` and no connect was attempted.

## Ran and saw
- `check_url` on about 25 URL forms offline. Blocked: `2130706433`, `0x7f.1`, `127.1`, `0`, `[::ffff:7f00:1]`, `[::ffff:100.64.0.1]`, `100.100.100.100`, `fd7a:…`, `169.254.169.254`, `localhost.`, `*.localhost`, fullwidth-dot `127。0。0。1`. Allowed: the six gap forms in #9. `0177.0.0.1` resolved to `177.0.0.1` on macOS (not an octal bypass here).
- Parser differential between `urlsplit` and `Request.host` for backslash, `@`, newline and `%`. Only `%` led to a different DNS lookup (#1); the others fail to connect.
- `getaddrinfo` hook: check vs connect strings differ for `a%2eb.attacker.test` (#1).
- Local stubs: `InvalidURL` and `BadStatusLine` escape `fetch_url`; a 1 byte/s server was still running after 40 s; a short-body response returned `ok:true`.
- Regex timings and the GIL ticker stall (#3).
- Live probes, 3 requests total: `http://169.254.169.254/` returned `blocked: private address` at 0 ms; `https://example.com/a b` returned HTTP 502. No bursts; no plain `example.com` ok-path request.
- Pin sketch and rebinding test ran in-process with a hooked resolver.

## Inferred
- The 502 is the sidecar handler dying and Caddy reporting no upstream reply; Mini logs not visible.
- #1 and #2 need attacker-controlled DNS; simulated with a mocked resolver.
- The 256 KB regex times are scaled from measured runs up to 200 KB.
- The Mini's macOS libc resolves numeric forms like this Mac.

## Not verified
- Whether the #9 IPv6/NAT64/6to4 targets are routable from the Mini.
- The Mini's Python version (tested on 3.14.7); older versions may allow `\n` header injection via hostnames.
- Real DNS rebinding timing and the Mini's resolver cache/TTL behavior.
- Caddy read/idle timeouts, which may soften #7.
- Whether the Mini's launchd environment sets `FETCH_ALLOWLOOPBACK` (repo grep: only tests and `web_tools.py`).
- Mini firewall rules on outbound LAN traffic.

## Top-3 must-fix
1. Pin the connection to the checked IP, which also closes the `%` mismatch (#1, #2).
2. Replace the HTML regexes with `html.parser` and add a total wall-clock deadline (#3, #5).
3. Catch `HTTPException` in `fetch_url` and add a catch-all in `_fetch` (#4).
