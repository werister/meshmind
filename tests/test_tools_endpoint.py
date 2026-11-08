#!/usr/bin/env python3
"""Stdlib acceptance for the sidecar GET /tools catalog; run directly.

    python3 tests/test_tools_endpoint.py

Spawns feedback-server.py as a subprocess with a temp METER_DIR (like
test_fetch_endpoint.py). Asserts the catalog serves over GET and that every
entry validates against the T12 {name, description, parameters} schema
format (registry content, not the T12 fixture file).
"""
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class ToolsEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="tools-test-")
        cls.port = free_port()
        env = dict(__import__("os").environ)
        env.update({"FEEDBACK_SERVER_PORT": str(cls.port),
                    "METER_DIR": cls.tmp.name})
        cls.sidecar = subprocess.Popen(
            [sys.executable, str(ROOT / "feedback-server.py")],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
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
        cls.tmp.cleanup()

    def test_tools_catalog_validates(self):
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/tools" % self.port,
                timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode())
        tools = body["tools"]
        self.assertTrue(len(tools) >= 2)
        names = {t["name"] for t in tools}
        self.assertTrue({"web_fetch", "web_search"} <= names)
        for entry in tools:
            with self.subTest(tool=entry.get("name")):
                self.assertTrue(entry["description"])
                params = entry["parameters"]
                self.assertIsInstance(params, dict)
                self.assertTrue(params)
                for pname, pspec in params.items():
                    self.assertIn(pspec["type"], ("string", "integer",
                                                  "number", "boolean"))
                    self.assertIsInstance(pspec["required"], bool)
                self.assertEqual(entry["method"], "POST")
                self.assertTrue(entry["endpoint"].startswith("/"))

    def test_unknown_path_still_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(
                "http://127.0.0.1:%d/toolz" % self.port, timeout=10)
        self.assertEqual(ctx.exception.code, 404)


import urllib.error  # noqa: E402  (kept with the helper that needs it)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ToolsEndpointTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\ntools_endpoint: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
