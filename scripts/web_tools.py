#!/usr/bin/env python3
"""web_tools.py -- real web backends for lab tool-calling (fetch + search).

Stdlib only. No API keys. Two tools the T12-style agent loop can call:

  fetch_url(url) -> {"ok": True, "url": ..., "text": ...}
  web_search(query) -> {"ok": True, "results": [{"title":..., "url":...}]}

Limits (safety): https/http only, 15 s timeout, 256 KB cap per fetch.
Search is Wikipedia-backed (keyless API; general web search would need a
Brave/Bing key). HTML -> text is a crude strip (scripts/styles/comments
removed); good enough for a model to read, not a reader-mode replacement.
"""
import html as _html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 15
MAX_BYTES = 256 * 1024
MAX_RESULTS = 5
USER_AGENT = "local-ai-lab/1.0 (tool-fetch)"

_STRIP_RE = re.compile(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]*>")
_WS_RE = re.compile(r"[ \t\xa0]+")
_BLANK_RE = re.compile(r"\n\s*\n+")
_DDG_RE = re.compile(
    r'(?is)<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>')


def _get(url):
    """GET a URL. Returns (final_url, body_bytes) or raises."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT,
                      "Accept": "text/html,*/*;q=0.8"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
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
    try:
        scheme = urllib.parse.urlsplit(url).scheme.lower()
        if scheme not in ("http", "https"):
            return {"ok": False, "url": url, "error": "http(s) only"}
        final, body = _get(url)
        if len(body) > MAX_BYTES:
            return {"ok": False, "url": url, "error": "page over size cap"}
        return {"ok": True, "url": final, "text": html_to_text(body)}
    except (urllib.error.URLError, OSError, ValueError) as exc:
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
    except (urllib.error.URLError, OSError, ValueError) as exc:
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
