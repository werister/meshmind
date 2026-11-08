#!/usr/bin/env python3
"""Stdlib acceptance harness for scripts/mmlu_lite.py; run directly.

    python3 tests/test_mmlu_lite.py

Offline only: first-A-D scoring unit tests, letter-only prompt tests, fixed
dry-run plan tests, and live-against-stub tests (an in-process fake Ollama
on 127.0.0.1:0 -- never the Mini, never the HF datasets-server: the
committed fixture rows sit on the strided offsets the stub run requests).
No test in this file touches the network beyond localhost.
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
SCRIPT = ROOT / "scripts" / "mmlu_lite.py"
FIXTURES = ROOT / "tests" / "fixtures" / "mmlu_lite" / "rows.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("mmlu_lite", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(args, timeout=60):
    """Invoke mmlu_lite.py. Returns (exit_code, stdout, stderr)."""
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
    """First-A-D scoring against gold index 0-3."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_mod()

    def test_exact(self):
        ok, note = self.m.score_reply("C", 2)
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_lowercase(self):
        ok, note = self.m.score_reply("c", 2)
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_whitespace(self):
        ok, note = self.m.score_reply("  B\n", 1)
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_punctuated(self):
        ok, note = self.m.score_reply("(D)", 3)
        self.assertTrue(ok)
        self.assertEqual(note, "ok")

    def test_wrong_answer(self):
        ok, note = self.m.score_reply("A", 2)
        self.assertFalse(ok)
        self.assertEqual(note, "wrong_answer")

    def test_no_letter(self):
        ok, note = self.m.score_reply("E", 0)
        self.assertFalse(ok)
        self.assertEqual(note, "no_letter")

    def test_none_reply(self):
        ok, note = self.m.score_reply(None, 0)
        self.assertFalse(ok)
        self.assertEqual(note, "no_letter")

    def test_first_letter_wins(self):
        # Literal first-A-D: the first A-D char decides, wherever it sits.
        self.assertEqual(self.m.first_letter("B or C?"), "B")
        ok, _ = self.m.score_reply("B or C?", 1)
        self.assertTrue(ok)

    def test_prompt_shape(self):
        prompt = self.m.build_prompt("2+2?", ["1", "2", "4", "8"])
        for tag, choice in zip("ABCD", ["1", "2", "4", "8"]):
            self.assertIn("%s. %s" % (tag, choice), prompt)
        self.assertIn("only the letter", prompt)


class SampleTests(unittest.TestCase):
    def test_fixed_offsets(self):
        m = load_mod()
        self.assertEqual(m.offsets_for_n(3), [0, 700, 1400])
        self.assertEqual(m.offsets_for_n(20)[-1], 19 * 700)
        self.assertEqual(len(m.offsets_for_n(20)), 20)


class FixtureTests(unittest.TestCase):
    def test_five_committed_rows(self):
        rows = fixture_rows()
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertTrue(row["question"])
            self.assertEqual(len(row["choices"]), 4)
            self.assertIn(row["answer"], (0, 1, 2, 3))


class DryRunTests(unittest.TestCase):
    def test_plan_only_by_default(self):
        code, out, _ = run(["--models", "m", "--n", "2"])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)
        self.assertIn("fixed offsets", out)
        self.assertIn("only the letter", out)
        self.assertIn("m", out)

    def test_plan_is_offline(self):
        # A dry-run never touches the network: a dead --base-url still plans.
        code, out, _ = run(["--models", "m", "--n", "2",
                            "--base-url",
                            "http://127.0.0.1:%d" % dead_port()])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)


class LiveStubTests(unittest.TestCase):
    """--live against a fake Ollama; fixtures sit on offsets 0, 700, ...."""

    def test_live_scores_and_meters(self):
        row = fixture_rows()[0]
        gold = "ABCD"[row["answer"]]
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
                        {"message": {"content": gold},
                         "prompt_eval_count": 10,
                         "eval_count": 2}).encode()
                    self._ok(body)
                else:  # unload ping (/api/generate): accept, ignore
                    self._ok(b'{"done": true}')

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            with tempfile.TemporaryDirectory(prefix="mmlu-test-") as tmp:
                out_path = str(Path(tmp) / "mmlu.jsonl")
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
        self.assertEqual(findings["tool"], "mmlu_lite")
        self.assertEqual(findings["n"], 1)
        block = findings["models"][0]
        self.assertEqual(block["model"], "stub-m")
        self.assertEqual(block["aggregates"]["passed"], 1)
        self.assertEqual(block["aggregates"]["total"], 1)
        self.assertEqual(block["results"][0]["gold"], gold)
        # Sidecar-to-dashboard wiring (mirrors tool_bench): one serial lane
        # call, X-Agent metered, temp 0, think:false.
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["x_agent"], "mmlu_lite")
        self.assertIs(seen[0]["payload"].get("think"), False)
        self.assertEqual(
            seen[0]["payload"].get("options", {}).get("temperature"), 0)
        # --out appends one JSONL line carrying the findings.
        self.assertEqual(len(lines.split("\n")), 1)
        self.assertEqual(json.loads(lines)["tool"], "mmlu_lite")

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
    print("\nmmlu_lite: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
