#!/usr/bin/env python3
"""Stdlib acceptance harness for scripts/gsm8k.py; run directly.

    python3 tests/test_gsm8k.py

Offline only: scoring unit tests (exact/whitespace/comma/negative cases),
dry-run plan tests, and live-against-stub tests (an in-process fake Ollama
on 127.0.0.1:0 -- never the Mini, never the HF datasets-server: the
committed fixture rows cover every requested offset). No test in this file
touches the network beyond localhost.
"""
import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gsm8k.py"
FIXTURES = ROOT / "tests" / "fixtures" / "gsm8k" / "rows.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("gsm8k", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(args, timeout=60):
    """Invoke gsm8k.py. Returns (exit_code, stdout, stderr)."""
    proc = subprocess.run([sys.executable, str(SCRIPT)] + args,
                          cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def dead_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fixture_rows():
    with open(FIXTURES, encoding="utf-8") as fh:
        return json.load(fh)["rows"]


class ScoringTests(unittest.TestCase):
    """Trailing #### number scoring: exact/whitespace/comma/negative."""

    @classmethod
    def setUpClass(cls):
        cls.g = load_mod()

    def test_exact(self):
        ok, note = self.g.score_reply("some work\n#### 18", "gold\n#### 18")
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_whitespace(self):
        ok, note = self.g.score_reply("####   42  \n", "gold\n#### 42")
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_comma(self):
        ok, note = self.g.score_reply("total\n#### 1,000", "gold\n#### 1000")
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_negative(self):
        ok, note = self.g.score_reply("#### -5", "gold\n#### -5")
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_decimal(self):
        ok, note = self.g.score_reply("#### 2.5", "gold\n#### 2.50")
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_wrong_answer(self):
        ok, note = self.g.score_reply("#### 19", "gold\n#### 18")
        self.assertFalse(ok)
        self.assertEqual(note, "wrong_answer")

    def test_no_number(self):
        ok, note = self.g.score_reply("The answer is eighteen.", "gold\n#### 18")
        self.assertFalse(ok)
        self.assertEqual(note, "no_number")

    def test_last_marker_wins(self):
        ok, note = self.g.score_reply("#### 7\nrecheck...\n#### 18",
                                      "gold\n#### 18")
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_none_reply(self):
        ok, note = self.g.score_reply(None, "gold\n#### 18")
        self.assertFalse(ok)
        self.assertEqual(note, "no_number")

    def test_prompt_shape(self):
        prompt = self.g.build_prompt("What is 1+1?")
        self.assertIn("What is 1+1?", prompt)
        self.assertIn("Solve step by step. End with exactly: #### <number>",
                      prompt)


class FixtureTests(unittest.TestCase):
    def test_five_committed_rows(self):
        rows = fixture_rows()
        self.assertEqual(len(rows), 5)
        golds = load_mod()
        for row in rows:
            self.assertTrue(row["question"])
            self.assertTrue(row["answer"])
            self.assertIsNotNone(
                golds.gold_number(row["answer"]),
                "fixture row %s gold has no #### number" % row.get("offset"))


class DryRunTests(unittest.TestCase):
    def test_plan_only_by_default(self):
        code, out, _ = run(["--models", "m", "--n", "2"])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)
        self.assertIn("Solve step by step. End with exactly: #### <number>",
                      out)
        self.assertIn("m", out)

    def test_plan_is_offline(self):
        # A dry-run never touches the network: a dead --base-url still plans.
        code, out, _ = run(["--models", "m", "--n", "2",
                            "--base-url",
                            "http://127.0.0.1:%d" % dead_port()])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)


class LiveStubTests(unittest.TestCase):
    """--live against a fake Ollama; fixture rows cover offset 0, so no API."""

    def test_live_scores_and_meters(self):
        gold = load_mod().gold_number(fixture_rows()[0]["answer"])
        seen = []

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                return

            def _ok(self, body):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._ok(b'{"models": []}')

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                if self.path.endswith("/api/chat"):
                    seen.append({
                        "payload": json.loads(raw.decode("utf-8", "replace")),
                        "x_agent": self.headers.get("X-Agent"),
                    })
                    body = json.dumps(
                        {"message": {"content": "work\n#### %s" % gold},
                         "prompt_eval_count": 10,
                         "eval_count": 5}).encode()
                    self._ok(body)
                else:  # unload ping (/api/generate): accept, ignore
                    self._ok(b'{"done": true}')

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            with tempfile.TemporaryDirectory(prefix="gsm8k-test-") as tmp:
                out_path = str(Path(tmp) / "gsm8k.jsonl")
                code, out, err = run(
                    ["--models", "stub-m", "--live", "--n", "1",
                     "--base-url", "http://127.0.0.1:%d" % port,
                     "--out", out_path, "--timeout", "10",
                     "--cache-dir", tmp])
                self.assertEqual(code, 0, err)
                findings = json.loads(out)
                lines = Path(out_path).read_text(encoding="utf-8").strip()
        finally:
            server.shutdown()
            thread.join()
        self.assertEqual(findings["tool"], "gsm8k")
        self.assertEqual(findings["n"], 1)
        block = findings["models"][0]
        self.assertEqual(block["model"], "stub-m")
        self.assertEqual(block["aggregates"]["passed"], 1)
        self.assertEqual(block["aggregates"]["total"], 1)
        self.assertEqual(block["results"][0]["gold"], gold)
        # Sidecar-to-dashboard wiring (mirrors tool_bench): one serial lane
        # call, X-Agent metered, temp 0, think:false.
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["x_agent"], "gsm8k")
        self.assertIs(seen[0]["payload"].get("think"), False)
        self.assertEqual(
            seen[0]["payload"].get("options", {}).get("temperature"), 0)
        # --out appends one JSONL line carrying the findings.
        self.assertEqual(len(lines.split("\n")), 1)
        self.assertEqual(json.loads(lines)["tool"], "gsm8k")

    def test_host_down(self):
        code, out, err = run(["--models", "m", "--live",
                              "--base-url",
                              "http://127.0.0.1:%d" % dead_port(),
                              "--timeout", "2"])
        self.assertEqual(code, 2)
        self.assertIn("unreachable", err)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromModule(
        sys.modules[__name__]))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\ngsm8k: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
