#!/usr/bin/env python3
"""Stdlib acceptance for the sidecar POST /fetch endpoint; run directly.

    python3 tests/test_fetch_endpoint.py

Spawns feedback-server.py as a subprocess (like test_metering_proxy.py)
with a temp METER_DIR. A local stub origin proves the ok path with
FETCH_ALLOWLOOPBACK=1; block tests never touch the network.
"""
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class OriginStub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/x")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = (b"<html><body><h1>Stub</h1>"
                b"<script>var x = 1;</script><p>Hello fetch</p></body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def post_json(port, path, payload, agent="fetch-test"):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), data=data,
        headers={"Content-Type": "application/json", "X-Agent": agent})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


import urllib.error  # noqa: E402  (kept with the helper that needs it)


class FetchEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.origin = ThreadingHTTPServer(("127.0.0.1", 0), OriginStub)
        threading.Thread(target=cls.origin.serve_forever,
                         daemon=True).start()
        cls.origin_port = cls.origin.server_address[1]
        cls.tmp = tempfile.TemporaryDirectory(prefix="fetch-test-")
        cls.port = free_port()
        env = dict(__import__("os").environ)
        env.update({"FEEDBACK_SERVER_PORT": str(cls.port),
                    "METER_DIR": cls.tmp.name,
                    "FETCH_ALLOWLOOPBACK": "1"})
        cls.stderr_path = str(
            __import__("pathlib").Path(cls.tmp.name) / "sidecar-stderr.log")
        cls.stderr_fh = open(cls.stderr_path, "wb")
        cls.sidecar = subprocess.Popen(
            [sys.executable, str(ROOT / "feedback-server.py")],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
            stderr=cls.stderr_fh)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(
                    "http://127.0.0.1:%d/status" % cls.port,
                    timeout=2).read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("sidecar did not start")

    @classmethod
    def tearDownClass(cls):
        cls.sidecar.terminate()
        try:
            cls.sidecar.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.sidecar.kill()
        cls.origin.shutdown()
        cls.stderr_fh.close()
        cls.tmp.cleanup()

    def test_fetch_ok_via_stub(self):
        code, out = post_json(
            self.port, "/fetch",
            {"op": "fetch",
             "url": "http://127.0.0.1:%d/page" % self.origin_port})
        self.assertEqual(code, 200)
        self.assertTrue(out["ok"])
        self.assertIn("Hello fetch", out["text"])
        self.assertNotIn("var x", out["text"])

    def test_fetch_blocked(self):
        # NOTE: 127.0.0.1 is intentionally open here (FETCH_ALLOWLOOPBACK=1
        # for the stub); loopback-allowed is proven by test_fetch_ok_via_stub.
        for url in ("http://169.254.169.254/latest/meta-data/",
                    "http://10.0.0.1/",
                    "http://100.100.100.100/",
                    "http://example.com:22/",
                    "file:///etc/passwd"):
            with self.subTest(url=url):
                code, out = post_json(
                    self.port, "/fetch", {"op": "fetch", "url": url},
                    agent="block-test")
                self.assertEqual(code, 200)
                self.assertFalse(out["ok"])
                self.assertTrue(
                    any(k in out["error"]
                        for k in ("blocked", "http(s)", "port")))

    def test_fetch_redirect_hop_blocked(self):
        code, out = post_json(
            self.port, "/fetch",
            {"op": "fetch",
             "url": "http://127.0.0.1:%d/redirect" % self.origin_port})
        self.assertEqual(code, 200)
        self.assertFalse(out["ok"])
        self.assertIn("blocked", out["error"])

    def test_fetch_bad_request(self):
        code, _ = post_json(self.port, "/fetch", {"op": "bogus"})
        self.assertEqual(code, 400)
        code, _ = post_json(self.port, "/fetch", {"op": "fetch"})
        self.assertEqual(code, 400)

    def test_fetch_zz_rate_limit_and_clean_stderr(self):
        # Runs last (zz): exhausts the shared per-IP budget, so nothing
        # may run after it. Rotating X-Agent must NOT dodge the limit
        # (the key is the peer IP); then the captured stderr must show
        # no handler traceback for the whole session.
        codes = []
        for i in range(32):
            code, _ = post_json(
                self.port, "/fetch",
                {"op": "fetch", "url": "http://169.254.169.254/"},
                agent="burst-test-%d" % i)
            codes.append(code)
        self.assertIn(429, codes)
        with open(self.stderr_path, "rb") as f:
            err = f.read().decode("utf-8", "replace")
        self.assertNotIn("Traceback", err)

    def test_fetch_metered(self):
        post_json(self.port, "/fetch",
                  {"op": "fetch",
                   "url": "http://127.0.0.1:%d/page" % self.origin_port},
                  agent="meter-test")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/calls?limit=50" % self.port)
        with urllib.request.urlopen(req, timeout=10) as resp:
            calls = json.loads(resp.read().decode())
        mine = [c for c in calls
                if c.get("agent") == "meter-test"
                and c.get("model") == "web_fetch"]
        self.assertTrue(mine)
        self.assertIsNone(mine[-1]["prompt_tokens"])
        self.assertIsNone(mine[-1]["eval_tokens"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FetchEndpointTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\nfetch_endpoint: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
