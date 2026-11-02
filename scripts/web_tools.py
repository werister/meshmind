#!/usr/bin/env python3
"""web_tools.py -- real web backends for lab tool-calling (fetch + search).

Stdlib only. No API keys. Two tools the T12-style agent loop can call:

  fetch_url(url) -> {"ok": True, "url": ..., "text": ...}
  web_search(query) -> {"ok": True, "results": [{"title":..., "url":...}]}

Limits (safety): https/http only, 15 s timeout, 256 KB cap per fetch,
SSRF guard (scheme + port allowlist, canonical-literal check, resolved-IP
blocklist incl. the 100.64/10 CGN range that carries Tailscale,
per-redirect-hop re-check). Search is Wikipedia-backed (keyless API;
general web search would need a Brave/Bing key). HTML -> text is a crude
strip (scripts/styles/comments removed); good enough for a model to read,
not a reader-mode replacement.
"""
import html as _html
import http.client
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 15
MAX_BYTES = 256 * 1024
MAX_RESULTS = 5
MAX_HOPS = 5
USER_AGENT = "local-ai-lab/1.0 (tool-fetch)"

_STRIP_RE = re.compile(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]*>")
_WS_RE = re.compile(r"[ \t\xa0]+")
_BLANK_RE = re.compile(r"\n\s*\n+")
_IPISH_RE = re.compile(r"^[0-9a-fA-F.:]+$")

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


def check_url(url):
    """SSRF pre-check. Returns an error string, or None when fetchable.

    FETCH_ALLOWLOOPBACK=1 relaxes loopback only (for offline stub tests);
    metadata, private ranges, the CGN/tailnet range and odd ports stay blocked.
    """
    allow_loopback = os.environ.get("FETCH_ALLOWLOOPBACK") == "1"
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "bad url"
    if parts.scheme.lower() not in ("http", "https"):
        return "http(s) only"
    host = (parts.hostname or "").lower().rstrip(".")
    if (not host or host in _BLOCKED_HOSTS
            or host.endswith(_BLOCKED_SUFFIXES)):
        return "blocked: local hostname"
    if _IPISH_RE.match(host):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # Looks like an IP but isn't canonical (0177.0.0.1, 0x7f...,
            # 2130706433, 127.1): resolvers disagree on these, so refuse
            # before any resolver gets a vote. No public DNS name matches.
            return "blocked: non-canonical IP literal"
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        return "bad port"
    if port not in (80, 443):
        if not (allow_loopback and _is_loopback_literal(host)):
            return "blocked: port not allowed"
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "dns failed"
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_blocked_ip(addr):
            if allow_loopback and addr.is_loopback:
                continue
            return "blocked: private address"
    return None


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect follower that re-runs the SSRF guard on every hop."""

    def __init__(self):
        super().__init__()
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > MAX_HOPS:
            raise ValueError("too many redirects")
        err = check_url(newurl)
        if err is not None:
            raise ValueError("blocked redirect: %s" % err)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url):
    """GET a URL through the guarded opener. Returns (final_url, body)."""
    opener = urllib.request.build_opener(_GuardedRedirectHandler())
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT,
                      "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=TIMEOUT) as response:
        final = response.geturl()
        ctype = response.headers.get("Content-Type", "")
        if "text" not in ctype and "json" not in ctype and "xml" not in ctype:
            raise ValueError("refusing non-text content: %s" % ctype)
        return final, response.read(MAX_BYTES + 1)


def html_to_text(body):
    """Crude HTML -> text. Never raises on bad input."""
    try:
        text = body.decode("utf-8", "replace")
    except (AttributeError, UnicodeError):
        return ""
    text = _STRIP_RE.sub("\n", text)
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    text = _TAG_RE.sub("\n", text)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text)
    return text.strip()[:8000]


def fetch_url(url):
    """Fetch a page and return its text. Always returns a dict."""
    err = check_url(url)
    if err is not None:
        return {"ok": False, "url": url, "error": err}
    try:
        final, body = _get(url)
        if len(body) > MAX_BYTES:
            return {"ok": False, "url": url, "error": "page over size cap"}
        return {"ok": True, "url": final, "text": html_to_text(body)}
    except _NET_ERRORS as exc:
        return {"ok": False, "url": url, "error": str(exc)[:160]}


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
    except _NET_ERRORS as exc:
        return {"ok": False, "query": query, "error": str(exc)[:160]}


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
