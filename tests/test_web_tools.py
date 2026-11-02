#!/usr/bin/env python3
"""Stdlib acceptance for scripts/web_tools.py; run directly.

    python3 tests/test_web_tools.py

Offline only: pure-function and validation tests. Live network stays
coordinator-run (like T12's --live).
"""
import json
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "web_tools.py"

sys.path.insert(0, str(ROOT / "scripts"))
import web_tools


class WebToolsTests(unittest.TestCase):

    def test_html_to_text(self):
        html = (b"<html><head><script>var x = 1;</script></head>"
                b"<body><h1>Hi</h1><p>A &amp; B</p><!-- c --></body></html>")
        text = web_tools.html_to_text(html)
        self.assertIn("Hi", text)
        self.assertIn("A & B", text)
        self.assertNotIn("var x", text)
        self.assertNotIn("<p>", text)
        self.assertEqual(web_tools.html_to_text(b""), "")

    def test_fetch_rejects_scheme(self):
        out = web_tools.fetch_url("ftp://example.com/x")
        self.assertFalse(out["ok"])
        self.assertIn("http", out["error"])

    def test_usage(self):
        proc = subprocess.run([sys.executable, str(SCRIPT)],
                              cwd=ROOT, capture_output=True, text=True,
                              timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", (proc.stdout + proc.stderr).lower())

    def test_search_shape_offline(self):
        # Shape contract only (no network): emulate by checking the
        # function returns the documented keys on failure path.
        out = web_tools.fetch_url("http://")
        self.assertEqual(set(out) >= {"ok", "url", "error"}, True)
        self.assertFalse(out["ok"])

    # --- SSRF blocklist: all offline (numeric IPs, no DNS) --------------
    def test_ssrf_blocklist(self):
        blocked = [
            "http://127.0.0.1/",
            "http://127.0.0.1:11434/api/tags",
            "http://[::1]/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://100.100.100.100/",  # CGN range = the tailnet itself
            "http://localhost:8080/",
            "http://metadata.google.internal/",
            "http://example.com:22/",
            "http://example.com:6379/",
            "file:///etc/passwd",
            "ftp://example.com/x",
            # Non-canonical IP literals: resolvers disagree on these, so they
            # die pre-DNS (offline-safe, no network touched).
            "http://0177.0.0.1/",
            "http://0x7f.0.0.1/",
            "http://2130706433/",
            "http://127.1/",
        ]
        for url in blocked:
            with self.subTest(url=url):
                out = web_tools.fetch_url(url)
                self.assertFalse(out["ok"])
                self.assertTrue(
                    any(k in out["error"]
                        for k in ("blocked", "http(s)", "port", "hostname")))

    def test_ssrf_redirect_hop(self):
        # Pre-check rejections (no DNS by design; IP answers are enforced
        # at connect time by _resolve_checked, covered below and live).
        handler = web_tools._GuardedRedirectHandler()
        req = urllib.request.Request("https://example.com/")
        for target in ("ftp://example.com/x",
                       "http://localhost:8080/x",
                       "http://user@example.com/"):
            with self.subTest(target=target):
                with self.assertRaises(web_tools._GuardBlock):
                    handler.redirect_request(req, None, 302, "Found", {},
                                             target)

    def test_ssrf_pct_host_and_userinfo(self):
        # urllib unquotes % at connect time: a %-host must die pre-DNS so
        # the checked string and the resolved string cannot differ.
        for url in ("http://a%2eb.example.com/",
                    "http://a%252e.example.com/",
                    "http://user@example.com/",
                    "http://user:pass@example.com/",
                    "http://exam\\ple.com/"):
            with self.subTest(url=url):
                out = web_tools.fetch_url(url)
                self.assertFalse(out["ok"])
                self.assertEqual(out["error"], "blocked")
                self.assertTrue(out["blocked"])

    def test_ssrf_gap_nets_connect_time(self):
        # Numeric literals: getaddrinfo parses offline, no network touched.
        gap = ["::7f00:1", "64:ff9b::7f00:1", "64:ff9b:1::1",
               "2002:7f00:1::", "2001::1", "fec0::1",
               "198.18.0.1", "192.0.0.170", "192.88.99.1",
               "169.254.169.254", "100.100.100.100", "127.0.0.1"]
        for host in gap:
            with self.subTest(host=host):
                with self.assertRaises(web_tools._GuardBlock):
                    web_tools._resolve_checked(host, 80)

    def test_rebind_pinned_single_lookup(self):
        # Hooked resolver answers public once, then loopback (rebinding):
        # exactly one lookup happens and the socket goes to the checked IP.
        import socket as _socket
        answers = iter(["93.184.216.34", "127.0.0.1", "127.0.0.1"])
        calls = []
        seen = []
        real_gai = _socket.getaddrinfo
        real_conn = _socket.create_connection

        def fake_gai(host, port, *a, **k):
            calls.append(host)
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "",
                     (next(answers), port))]

        def fake_conn(addr, *a, **k):
            seen.append(addr)
            raise OSError("stop")

        _socket.getaddrinfo = fake_gai
        _socket.create_connection = fake_conn
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                web_tools._GuardedRedirectHandler(),
                web_tools._PinHTTPHandler(), web_tools._PinHTTPSHandler())
            with self.assertRaises(OSError):
                opener.open("http://rebind.test/", timeout=2)
        finally:
            _socket.getaddrinfo = real_gai
            _socket.create_connection = real_conn
        self.assertEqual(len(calls), 1)
        self.assertEqual(seen, [("93.184.216.34", 80)])

    def test_oracle_normalized(self):
        # Host/IP decisions collapse to one string; malformed input keeps
        # its message (it reveals nothing about names).
        for url in ("http://169.254.169.254/",
                    "http://10.0.0.1/",
                    "http://0177.0.0.1/",
                    "http://",
                    "http://localhost:8080/"):
            with self.subTest(url=url):
                out = web_tools.fetch_url(url)
                self.assertFalse(out["ok"])
                self.assertEqual(out["error"], "blocked")
                self.assertTrue(out["blocked"])

    def test_html_pathological_fast(self):
        # Red-team round 2: unclosed openers went quadratic under the old
        # regex strip (1.6 s at 64 KB, ~4x per doubling). The parser is O(n).
        import time as _time
        bodies = (b"<script>" * 8192, b"<" * 65536, b"<!--" * 16384)
        for body in bodies:
            start = _time.monotonic()
            web_tools.html_to_text(body)
            self.assertLess(_time.monotonic() - start, 2.0,
                            "pathological HTML too slow")

    def test_http_exceptions_are_ok_false(self):
        # InvalidURL/BadStatusLine from the stack must surface as ok:false
        # with a fixed string, never escape and never leak socket text.
        import http.client as _hc
        real_get = web_tools._get
        for exc in (_hc.InvalidURL("bad"), _hc.BadStatusLine("garbage"),
                    OSError("boom"), ValueError("refusing non-text: x")):
            web_tools._get = lambda url, _e=exc: (_ for _ in ()).throw(_e)
            try:
                out = web_tools.fetch_url("http://example.com/")
            finally:
                web_tools._get = real_get
            self.assertFalse(out["ok"])
            self.assertNotIn("boom", out["error"])
            self.assertNotIn("garbage", out["error"])

    def test_total_deadline_slow_body(self):
        # A server dribbling 8 KB every 5 s never trips the 15 s per-op
        # timeout, but the total deadline (patched short here) must end
        # the fetch instead of pinning the slot indefinitely.
        import os
        import socket
        import threading
        import time as _time
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def serve():
            conn, _ = srv.accept()
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\n"
                         b"Content-Type: text/plain\r\n\r\n")
            try:
                for _ in range(12):
                    conn.sendall(b"x" * 8192)
                    _time.sleep(5)
            except OSError:
                pass
            finally:
                conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        old = os.environ.get("FETCH_ALLOWLOOPBACK")
        os.environ["FETCH_ALLOWLOOPBACK"] = "1"
        real_deadline = web_tools.TOTAL_DEADLINE
        web_tools.TOTAL_DEADLINE = 3.0
        try:
            start = _time.monotonic()
            out = web_tools.fetch_url("http://127.0.0.1:%d/" % port)
            elapsed = _time.monotonic() - start
        finally:
            web_tools.TOTAL_DEADLINE = real_deadline
            if old is None:
                del os.environ["FETCH_ALLOWLOOPBACK"]
            else:
                os.environ["FETCH_ALLOWLOOPBACK"] = old
            srv.close()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "fetch failed")
        self.assertLess(elapsed, 12.0)

    def test_garbage_status_is_ok_false(self):
        # A non-HTTP speaker must yield ok:false, never an escaped exception.
        import os
        import socket
        import threading
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def serve():
            conn, _ = srv.accept()
            conn.recv(4096)
            conn.sendall(b"THIS IS NOT HTTP\r\n\r\n")
            conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        old = os.environ.get("FETCH_ALLOWLOOPBACK")
        os.environ["FETCH_ALLOWLOOPBACK"] = "1"
        try:
            out = web_tools.fetch_url("http://127.0.0.1:%d/" % port)
        finally:
            if old is None:
                del os.environ["FETCH_ALLOWLOOPBACK"]
            else:
                os.environ["FETCH_ALLOWLOOPBACK"] = old
            srv.close()
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(WebToolsTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\nweb_tools: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
