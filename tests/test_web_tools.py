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


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(WebToolsTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\nweb_tools: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
