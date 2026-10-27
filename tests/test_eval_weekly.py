#!/usr/bin/env python3
"""Offline harness tests for eval-weekly.py (T3). No live Ollama needed.

Spins a tiny mock Ollama HTTP server on a loopback port that returns canned
/api/generate responses keyed by model name, then drives eval-weekly.main()
against it. Proves, deterministically and fast:

  - all-correct model -> model_summary verdict PASS, tok/s computed
  - wrong-answer model -> FAIL (grader is not a rubber stamp)
  - 404 model name    -> FAIL rows, no crash (fail-safe)
  - memory guard      -> --mem-min 101 yields verdict SKIP
  - timeout           -> slow model exceeds per-prompt timeout -> FAIL, no hang
  - JSONL is well formed and the run_summary tallies match

Run:  python3 tests/test_eval_weekly.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Canned answers per model. "arith"->43, "capital"->tokyo, "reverse"->bal.
GOOD = {"43": "43", "tokyo": "Tokyo", "bal": "bal"}


def load_eval():
    path = os.path.join(ROOT, "eval-weekly.py")
    spec = importlib.util.spec_from_file_location("evalweekly", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MockOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(body or b"{}")
        except Exception:
            req = {}
        model = req.get("model", "")
        prompt = (req.get("prompt", "") or "").lower()

        # unload call (keep_alive:0, no prompt) -> trivial ok
        if "keep_alive" in req and not req.get("prompt"):
            return self._json({"done": True})

        # 404 for a nonsense model name
        if model == "ghost:9b":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"model not found"}')
            return

        # slow model: sleep past the client timeout so urlopen raises
        if model == "slowpoke":
            time.sleep(3)
            try:
                return self._json({"done": True, "response": "late"})
            except Exception:
                return  # client already gave up (expected); don't spam stderr

        # pick the right answer by prompt content
        if "17 plus 26" in prompt:
            ans = "43" if model == "good" else "0"
        elif "capital city of japan" in prompt:
            ans = "Tokyo" if model == "good" else "Paris"
        elif "backwards" in prompt:
            ans = "bal" if model == "good" else "xyz"
        else:
            ans = "?"

        self._json(
            {
                "done": True,
                "response": ans,
                "eval_count": 7,
                "eval_duration": 100_000_000,  # 0.1s -> 70 tok/s
                "prompt_eval_count": 5,
            }
        )

    def _json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockOllama)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d" % port


PASSED = 0


def check(cond, msg):
    global PASSED
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    PASSED += 1


def read_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def summaries_by_model(records):
    return {
        r["model"]: r for r in records if r.get("kind") == "model_summary"
    }


def main():
    mod = load_eval()
    srv, base = start_server()
    print("eval-weekly tests (mock Ollama at %s):" % base)
    try:
        tmp = tempfile.mkdtemp(prefix="evaltest-")

        # --- PASS + FAIL + 404 in one run ---
        out1 = os.path.join(tmp, "run1.jsonl")
        rs = mod.main(
            [
                "--models", "good,bad,ghost:9b",
                "--base", base,
                "--out", out1,
                "--timeout", "5",
            ]
        )
        recs = read_jsonl(out1)
        sm = summaries_by_model(recs)
        check(sm["good"]["verdict"] == "PASS", "good model PASS")
        check(sm["good"]["passed"] == 3, "good model 3/3")
        check(sm["good"]["avg_tok_s"] == 70.0, "tok/s computed (70.0)")
        check(sm["bad"]["verdict"] == "FAIL", "bad model FAIL (grader not rubber-stamp)")
        check(sm["bad"]["passed"] == 0, "bad model 0/3")
        check(sm["ghost:9b"]["verdict"] == "FAIL", "404 model FAIL not crash")
        ghost_rows = [r for r in recs if r.get("model") == "ghost:9b" and r.get("kind") == "result"]
        check(len(ghost_rows) == 3, "404 model still produced 3 result rows")
        check(all("404" in (r.get("note") or "") for r in ghost_rows), "404 recorded in row note")
        check(rs["passed_models"] == 1 and rs["failed_models"] == 2, "run tally 1 pass / 2 fail")
        print("  PASS/FAIL/404 run: OK")

        # --- memory guard SKIP (forced high threshold) ---
        out2 = os.path.join(tmp, "run2.jsonl")
        rs2 = mod.main(
            ["--models", "good", "--base", base, "--out", out2, "--mem-min", "101"]
        )
        recs2 = read_jsonl(out2)
        sm2 = summaries_by_model(recs2)
        # guard only fires if memory_pressure is readable; on this macOS box it is.
        if mod.mem_free_pct() is not None:
            check(sm2["good"]["verdict"] == "SKIP", "memory guard SKIP")
            check(rs2["skipped_models"] == 1, "run tally 1 skipped")
            check(not any(r.get("kind") == "result" for r in recs2), "no prompts run when skipped")
            print("  memory guard SKIP: OK")
        else:
            print("  memory guard SKIP: SKIPPED (no memory_pressure on this host)")

        # --- timeout: slow model exceeds per-prompt timeout -> FAIL, no hang ---
        out3 = os.path.join(tmp, "run3.jsonl")
        t0 = time.time()
        mod.main(["--models", "slowpoke", "--base", base, "--out", out3, "--timeout", "1"])
        elapsed = time.time() - t0
        recs3 = read_jsonl(out3)
        sm3 = summaries_by_model(recs3)
        check(sm3["slowpoke"]["verdict"] == "FAIL", "timeout -> FAIL")
        slow_rows = [r for r in recs3 if r.get("kind") == "result"]
        check(all(not r["done"] for r in slow_rows), "timed-out rows not done")
        # 3 prompts x ~1s timeout, plus small overhead; must not hang near the 3s sleep*3
        check(elapsed < 8, "run bounded by timeout (%.1fs)" % elapsed)
        print("  timeout path: OK (%.1fs)" % elapsed)

        # --- run_summary is always the last line and self-consistent ---
        check(recs[-1]["kind"] == "run_summary", "run_summary is last line")
        total = rs["passed_models"] + rs["failed_models"] + rs["skipped_models"]
        check(total == rs["models"], "summary tallies sum to model count")
        print("  jsonl shape: OK")

    finally:
        srv.shutdown()

    print("ALL %d checks passed" % PASSED)


if __name__ == "__main__":
    main()
