#!/usr/bin/env python3
"""web_tools.py -- real web backends for lab tool-calling (fetch + search).

Stdlib only. No API keys. Two tools the T12-style agent loop can call:

  fetch_url(url) -> {"ok": True, "url": ..., "text": ...}
  web_search(query) -> {"ok": True, "results": [{"title":..., "url":...}]}

Limits (safety): https/http only, 15 s per-op socket timeout plus a
30 s total deadline per fetch, 256 KB cap per fetch, SSRF guard (scheme +
port allowlist, canonical-literal check, host hygiene, resolve-once pin-IP
connect where the checked IP is the connected IP, per-redirect-hop
re-check; blocklist incl. the 100.64/10 CGN range that carries Tailscale).
Search is Wikipedia-backed (keyless API; general web search would need a
Brave/Bing key). HTML -> text is a linear html.parser strip
(scripts/styles/comments removed); good enough for a model to read,
not a reader-mode replacement.
"""
import html.parser
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 15
TOTAL_DEADLINE = 30.0
DNS_TIMEOUT = 10.0
MAX_BYTES = 256 * 1024
MAX_RESULTS = 5
MAX_HOPS = 5
USER_AGENT = "local-ai-lab/1.0 (tool-fetch)"

_WS_RE = re.compile(r"[ \t\xa0]+")
_BLANK_RE = re.compile(r"\n\s*\n+")
_IPISH_RE = re.compile(r"^[0-9a-fA-F.:]+$")

# Per-thread fetch deadline (monotonic); set by _get so the pinned
# connect step and the redirect follower share one budget.
_TLS = threading.local()

# Explicit blocklist (checked with `in`, never is_private/is_global, so the
# CGN range that carries Tailscale cannot slip through on any interpreter).
_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    # Red-team round 2: transition/reserved ranges whose endpoints must
    # never be fetch targets (blocked wholesale; no per-address unwrap).
    ipaddress.ip_network("::/96"),              # v4-compatible (deprecated)
    ipaddress.ip_network("64:ff9b::/96"),       # NAT64 well-known prefix
    ipaddress.ip_network("64:ff9b:1::/48"),     # NAT64 local-use
    ipaddress.ip_network("2002::/16"),          # 6to4
    ipaddress.ip_network("2001::/32"),          # Teredo
    ipaddress.ip_network("fec0::/10"),          # site-local (deprecated)
    ipaddress.ip_network("198.18.0.0/15"),      # benchmarking
    ipaddress.ip_network("192.0.0.0/24"),       # IETF protocol assignments
    ipaddress.ip_network("192.88.99.0/24"),     # 6to4 relay (deprecated)
]
_BLOCKED_HOSTS = ("localhost", "metadata.google.internal")
_BLOCKED_SUFFIXES = (".localhost", ".internal", ".local")

# Network-layer failures that become ok:false (never escape to the caller).
_NET_ERRORS = (urllib.error.URLError, OSError, ValueError,
               http.client.HTTPException)


def _is_blocked_ip(addr):
    addrs = [addr]
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addrs.append(mapped)
    return any(any(a in net for net in _BLOCKED_NETS) for a in addrs)


def _is_loopback_literal(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _GuardBlock(ValueError):
    """A guard decision (host, IP, redirect target). Never carries detail
    to the caller: every block normalizes to one 'blocked' string so the
    error text cannot oracle internal-name existence."""


def check_url(url):
    """SSRF pre-check. Returns an error string, or None when fetchable.

    Cheap and DNS-free on purpose: the authoritative check is the
    resolve-once pin at connect time (_resolve_checked), so there is no
    check/lookup vs connect/lookup pair to rebind. This pre-check only
    rejects malformed, non-HTTP, or obviously local targets early.

    FETCH_ALLOWLOOPBACK=1 relaxes loopback only (for offline stub tests);
    metadata, private ranges, the CGN/tailnet range and odd ports stay blocked.
    """
    allow_loopback = os.environ.get("FETCH_ALLOWLOOPBACK") == "1"
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        return "bad url"
    if parts.scheme.lower() not in ("http", "https"):
        return "http(s) only"
    # Host hygiene: the string we pre-check must be the string that gets
    # resolved. urllib unquotes % at connect time, so any %, userinfo,
    # backslash or control character is a check/connect mismatch vector.
    if "@" in parts.netloc:
        return "blocked: userinfo not allowed"
    if not host or "%" in host or "\\" in host:
        return "blocked: bad hostname"
    if any(ord(c) < 33 or ord(c) == 127 for c in host):
        return "blocked: bad hostname"
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return "blocked: local hostname"
    if _IPISH_RE.match(host):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # Looks like an IP but isn't canonical (0177.0.0.1, 0x7f...,
            # 2130706433, 127.1): resolvers disagree on these, so refuse
            # before any resolver gets a vote. No public DNS name matches.
            return "blocked: non-canonical IP literal"
    if port not in (80, 443):
        if not (allow_loopback and _is_loopback_literal(host)):
            return "blocked: port not allowed"
    return None


def _deadline():
    return getattr(_TLS, "deadline", None)


def _resolve_checked(host, port):
    """Resolve once, check every answer, return the IP to connect to.

    Single lookup per connection: the checked IP is the connected IP, so
    DNS rebinding and %-encoded check/connect mismatches cannot redirect
    the socket. Fail-closed on timeout, DNS error, or any blocked answer.
    """
    allow_loopback = os.environ.get("FETCH_ALLOWLOOPBACK") == "1"
    budget = DNS_TIMEOUT
    dl = _deadline()
    if dl is not None:
        budget = max(1.0, min(DNS_TIMEOUT, dl - time.monotonic()))
    box = {}

    def run():
        try:
            box["infos"] = socket.getaddrinfo(host, port,
                                              type=socket.SOCK_STREAM)
        except Exception as exc:  # gaierror and friends: fail closed
            box["err"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(budget)
    if worker.is_alive() or "infos" not in box:
        raise _GuardBlock("dns failed")
    for info in box["infos"]:
        try:
            addr = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            continue
        if _is_blocked_ip(addr):
            if allow_loopback and addr.is_loopback:
                continue
            raise _GuardBlock("blocked: private address")
    return box["infos"][0][4][0]


_TLS_CTX = ssl.create_default_context()


class _PinHTTP(http.client.HTTPConnection):
    """HTTP connection pinned to the checked IP (hostname kept for Host)."""

    def connect(self):
        ip = _resolve_checked(self.host, self.port)
        self.sock = socket.create_connection((ip, self.port), self.timeout)


class _PinHTTPS(http.client.HTTPSConnection):
    """HTTPS connection pinned to the checked IP (SNI/certs keep the name)."""

    def connect(self):
        ip = _resolve_checked(self.host, self.port)
        raw = socket.create_connection((ip, self.port), self.timeout)
        self.sock = _TLS_CTX.wrap_socket(raw, server_hostname=self.host)


class _PinHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinHTTP, req)


class _PinHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinHTTPS, req, context=_TLS_CTX)


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect follower that re-runs the SSRF guard on every hop and
    shares the fetch's total deadline across hops."""

    def __init__(self):
        super().__init__()
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > MAX_HOPS:
            raise ValueError("too many redirects")
        dl = _deadline()
        if dl is not None and time.monotonic() > dl:
            raise TimeoutError("fetch deadline exceeded")
        err = check_url(newurl)
        if err is not None:
            raise _GuardBlock("blocked redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url):
    """GET a URL through the guarded opener. Returns (final_url, body)."""
    _TLS.deadline = time.monotonic() + TOTAL_DEADLINE
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # env proxies would bypass the pin
            _GuardedRedirectHandler(), _PinHTTPHandler(), _PinHTTPSHandler())
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT,
                          "Accept": "text/html,*/*;q=0.8"})
        with opener.open(request, timeout=TIMEOUT) as response:
            final = response.geturl()
            ctype = response.headers.get("Content-Type", "")
            if ("text" not in ctype and "json" not in ctype
                    and "xml" not in ctype):
                raise ValueError("refusing non-text content: %s" % ctype)
            body = bytearray()
            while len(body) <= MAX_BYTES:
                if time.monotonic() > _TLS.deadline:
                    raise TimeoutError("fetch deadline exceeded")
                chunk = response.read(8192)
                if not chunk:
                    break
                body += chunk
            return final, bytes(body)
    finally:
        _TLS.deadline = None


class _TextExtractor(html.parser.HTMLParser):
    """Linear HTML -> text. Skips script/style/noscript/template content;
    comments are ignored by default. No regexes: pathological nesting or
    unclosed tags cost O(n), never quadratic time with the GIL held."""

    _SKIP = ("script", "style", "noscript", "template")
    _BLOCK = ("p", "div", "section", "article", "header", "footer", "main",
              "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "tr",
              "table", "blockquote", "pre", "br", "hr", "title")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(body):
    """Crude HTML -> text. Never raises on bad input."""
    try:
        text = body.decode("utf-8", "replace")
    except (AttributeError, UnicodeError):
        return ""
    try:
        parser = _TextExtractor()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        return ""
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text)
    return text.strip()[:8000]


def _blocked(url, err):
    """One 'blocked' string for every host/IP decision (no oracle);
    malformed-input errors keep their message (they reveal nothing)."""
    if err in ("http(s) only", "bad url", "bad port"):
        return {"ok": False, "url": url, "error": err}
    return {"ok": False, "url": url, "blocked": True, "error": "blocked"}


def fetch_url(url):
    """Fetch a page and return its text. Always returns a dict."""
    err = check_url(url)
    if err is not None:
        return _blocked(url, err)
    try:
        final, body = _get(url)
        if len(body) > MAX_BYTES:
            return {"ok": False, "url": url, "error": "page over size cap"}
        return {"ok": True, "url": final, "text": html_to_text(body)}
    except _GuardBlock as exc:
        return _blocked(url, str(exc))
    except _NET_ERRORS:
        # Fixed string: raw socket/HTTP errors can oracle port state on
        # allowed hosts, and callers must not parse exception text.
        return {"ok": False, "url": url, "error": "fetch failed"}


def web_search(query):
    """Wikipedia search (keyless API). Up to MAX_RESULTS title/url pairs."""
    try:
        target = ("https://en.wikipedia.org/w/api.php?action=query"
                  "&list=search&format=json&srlimit=%d&srsearch=%s"
                  % (MAX_RESULTS, urllib.parse.quote_plus(query)))
        _, body = _get(target)
        data = json.loads(body.decode("utf-8", "replace"))
        out = []
        for hit in (data.get("query") or {}).get("search", []):
            title = hit.get("title", "")
            if title:
                link = ("https://en.wikipedia.org/wiki/"
                        + urllib.parse.quote(title.replace(" ", "_")))
                out.append({"title": title[:160], "url": link[:300]})
        return {"ok": True, "query": query, "source": "wikipedia",
                "results": out}
    except _GuardBlock:
        return {"ok": False, "query": query, "blocked": True,
                "error": "blocked"}
    except _NET_ERRORS:
        return {"ok": False, "query": query, "error": "fetch failed"}


def main(argv):
    if len(argv) != 3 or argv[1] not in ("fetch", "search"):
        print("usage: web_tools.py fetch <url> | search <query>")
        return 2
    if argv[1] == "fetch":
        print(json.dumps(fetch_url(argv[2])))
    else:
        print(json.dumps(web_search(argv[2])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
