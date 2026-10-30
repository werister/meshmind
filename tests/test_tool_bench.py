#!/usr/bin/env python3
"""Stdlib acceptance harness for scripts/tool_bench.py; run directly.

    python3 tests/test_tool_bench.py

No pytest on this box. Every test maps to a T12 contract behavior or a row of
the T12 failure table; no test without a regression it would catch. No LIVE
model calls: canned replies drive scoring, host-down uses a dead port, and the
endpoint-vs-reasoning split is exercised against an in-process stub HTTP server
(a local fake, never the Mini).

Also enforces the T12 acceptance schema check: all 12 shipped scenarios validate
against the fixed 4-tool catalog, cover 2-per-point, and pass with canned replies.
"""
import json
import socket
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tool_bench.py"
TB = ROOT / "tests" / "fixtures" / "toolbench"
SCENARIOS = TB / "scenarios"
SAMPLES = TB / "samples"
BAD_SCENARIOS = TB / "bad-scenarios"
CATALOG = TB / "catalog.json"

EXPECTED_TOOLS = ["calc", "file_read", "get_weather", "send_message"]


def run(args, timeout=60):
    """Invoke tool_bench.py. Returns (exit_code, parsed_stdout_or_None, stderr)."""
    proc = subprocess.run([sys.executable, str(SCRIPT)] + args,
                          cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    parsed = None
    out = proc.stdout.strip()
    if out:
        try:
            parsed = json.loads(out)
        except ValueError:
            parsed = None
    return proc.returncode, parsed, proc.stderr


def dead_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def scenarios_by_name(block):
    return {r["name"]: r for r in block["scenarios"]}


class _StubHandler(BaseHTTPRequestHandler):
    """Preflight /api/tags OK, but /api/chat 500 -> per-turn endpoint failure."""

    def log_message(self, *_a):  # silence the stub
        return

    def do_GET(self):
        if self.path.endswith("/api/tags"):
            body = b'{"models": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self.send_response(500)
        self.end_headers()


class ToolBenchTests(unittest.TestCase):

    # --- T12 acceptance: 12 scenarios validate + all canned replies pass
    def test_twelve_scenarios_validate_and_pass(self):
        code, out, _ = run(["--models", "canned"])
        self.assertEqual(code, 0)
        self.assertEqual(out["tool"], "tool_bench")
        self.assertEqual(out["scenarios_total"], 12)
        self.assertEqual(out["catalog"], EXPECTED_TOOLS)
        agg = out["models"][0]["aggregates"]
        self.assertEqual(agg["scenarios_passed"], 12)
        self.assertEqual(agg["reasoning_failures"], 0)
        self.assertEqual(agg["endpoint_failures"], 0)
        # 2 scenarios per point, all six points present, all passing.
        per_point = agg["per_point"]
        self.assertEqual(sorted(per_point), ["1", "2", "3", "4", "5", "6"])
        for point in per_point.values():
            self.assertEqual(point["total"], 2)
            self.assertEqual(point["passed"], 2)

    # --- findings schema shape ------------------------------------------
    def test_findings_shape(self):
        code, out, _ = run(["--models", "canned", "--scenarios", str(SAMPLES)])
        self.assertEqual(code, 0)
        block = out["models"][0]
        self.assertEqual(set(block), {"model", "scenarios", "aggregates"})
        for res in block["scenarios"]:
            self.assertEqual(set(res) >= {"name", "point", "pass", "note",
                                          "endpoint_error", "turns"}, True)
            self.assertIsInstance(res["pass"], bool)
            self.assertIsInstance(res["endpoint_error"], bool)

    # --- sample pass/fail/abstain (ticket-named fixtures) ---------------
    def test_sample_pass_fail_abstain(self):
        code, out, _ = run(["--models", "m", "--scenarios", str(SAMPLES)])
        self.assertEqual(code, 0)
        by = scenarios_by_name(out["models"][0])
        self.assertTrue(by["s1-pass-select"]["pass"])
        self.assertTrue(by["s3-abstain"]["pass"])
        self.assertFalse(by["s2-fail-wrongtool"]["pass"])
        self.assertEqual(by["s2-fail-wrongtool"]["note"], "wrong_tool")

    # --- T12 failure table: invalid tool-call JSON -> fail, note bad_json
    def test_bad_json(self):
        code, out, _ = run(["--models", "m", "--scenarios", str(SAMPLES)])
        self.assertEqual(code, 0)
        by = scenarios_by_name(out["models"][0])
        self.assertFalse(by["s4-badjson"]["pass"])
        self.assertEqual(by["s4-badjson"]["note"], "bad_json")
        # bad_json is a REASONING failure, not an endpoint failure.
        self.assertFalse(by["s4-badjson"]["endpoint_error"])

    # --- T12 failure table: tool-error recovery scored turn-2, not fatal
    def test_error_recovery(self):
        code, out, _ = run(["--models", "m", "--scenarios", str(SAMPLES)])
        self.assertEqual(code, 0)
        by = scenarios_by_name(out["models"][0])
        # recovered: turn-1 errored, turn-2 corrected retry -> pass
        rec = by["s5-recover"]
        self.assertTrue(rec["pass"])
        self.assertEqual(len(rec["turns"]), 2)
        self.assertTrue(rec["turns"][0]["pass"])  # the initial call was well-formed
        self.assertEqual(rec["turns"][1]["expect"], "recover")
        # gave up: turn-2 produced no retry -> fail note no_recovery (not fatal)
        bad = by["s6-recover-fail"]
        self.assertFalse(bad["pass"])
        self.assertEqual(bad["note"], "no_recovery")

    # --- exact-argument scoring: point 2 checks values AND types --------
    def test_exact_arguments_point2(self):
        code, out, _ = run(["--models", "canned"])
        by = scenarios_by_name(out["models"][0])
        self.assertTrue(by["p2a-args-weather-unit"]["pass"])
        self.assertTrue(by["p2b-args-file-maxbytes"]["pass"])

    # --- endpoint failures recorded SEPARATELY from reasoning failures --
    def test_endpoint_vs_reasoning_split(self):
        server = HTTPServer(("127.0.0.1", 0), _StubHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            code, out, _ = run(["--models", "m", "--live",
                               "--ollama", "http://127.0.0.1:%d" % port,
                               "--scenarios", str(SAMPLES), "--timeout", "5"])
        finally:
            server.shutdown()
            thread.join()
        # Preflight (/api/tags) succeeds, so we RAN (exit 0); every /api/chat
        # 500s, so every scenario is an endpoint failure, counted apart from
        # reasoning failures (which must be zero here -- nothing was judged).
        self.assertEqual(code, 0)
        agg = out["models"][0]["aggregates"]
        self.assertEqual(agg["scenarios_passed"], 0)
        self.assertEqual(agg["reasoning_failures"], 0)
        self.assertEqual(agg["endpoint_failures"], agg["scenarios_total"])
        for res in out["models"][0]["scenarios"]:
            self.assertTrue(res["endpoint_error"])
            self.assertEqual(res["note"], "endpoint_error")

    # --- T12 failure table: host down mid-suite -> exit 2 ---------------
    def test_host_down(self):
        port = dead_port()
        code, out, err = run(["--models", "m", "--live",
                             "--ollama", "http://127.0.0.1:%d" % port,
                             "--timeout", "2"])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("unreachable", err)

    # --- T12 failure table: scenario dir malformed -> exit 2 naming file
    def test_bad_scenarios(self):
        code, out, err = run(["--models", "m", "--scenarios", str(BAD_SCENARIOS)])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("malformed.json", err)

    # --- catalog is the fixed 4 tools; scenarios reference only those ---
    def test_catalog_fixed_four(self):
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        names = sorted(t["name"] for t in data["tools"])
        self.assertEqual(names, EXPECTED_TOOLS)
        # every expect.tool across all 12 scenarios is in the catalog
        for path in sorted(SCENARIOS.glob("*.json")):
            obj = json.loads(path.read_text(encoding="utf-8"))
            for turn in obj["turns"]:
                tool = turn["expect"].get("tool")
                if tool is not None:
                    self.assertIn(tool, names, "%s references %s" % (path.name, tool))

    # --- multi-model, independently scored ------------------------------
    def test_multi_model(self):
        code, out, _ = run(["--models", "a,b"])
        self.assertEqual(code, 0)
        self.assertEqual([b["model"] for b in out["models"]], ["a", "b"])
        for block in out["models"]:
            self.assertEqual(block["aggregates"]["scenarios_passed"], 12)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(ToolBenchTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\ntool_bench: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
