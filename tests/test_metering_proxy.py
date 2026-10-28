#!/usr/bin/env python3
"""Small stdlib acceptance harness for feedback-server.py; run directly."""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLOW_LOCK = threading.Lock()
SLOW_COUNT = 0
SLOW_EVENT = threading.Event()


class Backend(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *_):
        pass
    def do_GET(self):
        if self.headers.get("Host") != "127.0.0.1:11434":
            self.send_error(400, "Host was not rewritten")
            return
        body = b'{"version":"test"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        global SLOW_COUNT
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        if self.headers.get("Host") != "127.0.0.1:11434":
            self.send_error(400, "Host was not rewritten")
            return
        if b'"slow":true' in body:
            with SLOW_LOCK:
                SLOW_COUNT += 1
                if SLOW_COUNT >= 16:
                    SLOW_EVENT.set()
            time.sleep(3)
        if self.path == "/api/chat" and b'"stream":true' in body:
            frames = [b'{"message":{"content":"one"},"done":false}\n',
                      b'{"message":{"content":"two"},"done":false}\n',
                      b'{"done":true,"prompt_eval_count":3,"eval_count":7}\n']
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            for frame in frames:
                self.wfile.write(frame)
                self.wfile.flush()
                time.sleep(0.12)
            self.close_connection = True
            return
        if self.path == "/v1/chat/completions" and b'"stream":true' in body:
            frames = [b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n',
                      b'data: {"choices":[{"delta":{"content":"b"}}]}\n\n', b'data: [DONE]\n\n']
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for frame in frames:
                self.wfile.write(frame)
                self.wfile.flush()
                time.sleep(0.12)
            self.close_connection = True
            return
        if self.path == "/api/echo":
            result = body
        elif self.path.startswith("/v1/"):
            result = b'{"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":6}}'
        elif self.path == "/api/chat":
            result = b'{"done":true,"prompt_eval_count":3,"eval_count":7}'
        else:
            result = b'{"done":true,"prompt_eval_count":1,"eval_count":2}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)
    do_PUT = do_POST


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MeterAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="meter-test-")
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        cls.backend_port = cls.backend.server_address[1]
        cls.backend_thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.backend_thread.start()
        cls.port = free_port()
        env = os.environ.copy()
        env.update({"FEEDBACK_SERVER_PORT": str(cls.port), "METER_DIR": cls.tmp.name,
                    "CALLS_MAX_BYTES": "500", "OLLAMA_URL": f"http://127.0.0.1:{cls.backend_port}"})
        cls.proxy = subprocess.Popen([sys.executable, str(ROOT / "feedback-server.py")],
                                     cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = ("127.0.0.1", cls.port)
        for _ in range(100):
            try:
                cls.request("GET", "/status")
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("proxy did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proxy.terminate()
        cls.proxy.wait(timeout=5)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.tmp.cleanup()

    @classmethod
    def request(cls, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection(*(host or cls.base), timeout=15)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        payload = response.read()
        result = (response.status, payload, response.getheaders())
        conn.close()
        return result

    def calls(self):
        return json.loads(self.request("GET", "/calls?limit=256")[1])

    def status_when(self, predicate, timeout=3):
        """The meter records after relaying the response (fail-open), so poll briefly."""
        deadline = time.monotonic() + timeout
        while True:
            status = json.loads(self.request("GET", "/status")[1])
            if predicate(status) or time.monotonic() > deadline:
                return status
            time.sleep(0.02)

    def test_nonstream_counts_and_caller_agent(self):
        before = json.loads(self.request("GET", "/status")[1])["metering"]["calls_total"]
        body = json.dumps({"model": "probe", "messages": [{"role": "user", "content": "hi"}]}).encode()
        status, _, _ = self.request("POST", "/api/chat", body,
                                    {"Content-Type": "application/json", "X-Agent": "self-declared"})
        self.assertEqual(status, 200)
        self.status_when(lambda st: st["metering"]["calls_total"] >= before + 1)
        row = self.calls()[0]
        self.assertEqual(row["agent"], "self-declared")
        self.assertEqual((row["model"], row["prompt_tokens"], row["eval_tokens"]), ("probe", 3, 7))
        self.assertEqual((row["path"], row["status"]), ("/api/chat", 200))
        self.assertEqual(json.loads(self.request("GET", "/status")[1])["metering"]["calls_total"], before + 1)

    def test_status_carries_rollups_and_keeps_metering_block(self):
        body = json.dumps({"model": "rollup", "messages": []}).encode()
        self.request("POST", "/api/chat", body, {"Content-Type": "application/json", "X-Agent": "rollup-agent"})
        status = self.status_when(lambda st: any(r["model"] == "rollup" for r in st["metering_breakdown"]["per_model"]))
        self.assertEqual(set(status["metering"]), {"calls_total", "prompt_tokens_total", "eval_tokens_total",
                                                   "ring_len", "backend_up", "unmetered_stream_calls"})
        bd = status["metering_breakdown"]
        model = next(r for r in bd["per_model"] if r["model"] == "rollup")
        self.assertEqual((model["calls"], model["prompt_tokens"], model["eval_tokens"]), (1, 3, 7))
        self.assertIn("rollup-agent", [r["agent"] for r in bd["per_agent"]])
        self.assertEqual(len(bd["daily"]), 14)
        self.assertGreaterEqual(bd["daily"][-1]["by_model"].get("rollup", 0), 7)
        self.assertTrue((Path(self.tmp.name) / "metering-aggregates.json").exists())

    def test_stream_relay_is_incremental_and_one_row(self):
        body = b'{"model":"stream","stream":true}'
        conn = http.client.HTTPConnection(*self.base, timeout=5)
        conn.request("POST", "/api/chat", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        started = time.monotonic()
        first = response.read1(1)
        first_latency = time.monotonic() - started
        self.assertTrue(first)
        self.assertLess(first_latency, 0.3)
        self.assertIn(b"one", first + response.read())
        conn.close()
        rows = self.calls()
        self.assertEqual(sum(r["model"] == "stream" for r in rows), 1)
        row = next(r for r in rows if r["model"] == "stream")
        self.assertEqual(row["eval_tokens"], 7)

    def test_v1_stream_missing_usage_is_null_not_summed(self):
        before_status = json.loads(self.request("GET", "/status")[1])["metering"]
        before = before_status["eval_tokens_total"]
        body = b'{"model":"v1","stream":true}'
        self.assertEqual(self.request("POST", "/v1/chat/completions", body)[0], 200)
        row = self.calls()[0]
        self.assertTrue(row.get("no_usage"))
        self.assertIsNone(row["eval_tokens"])
        after = json.loads(self.request("GET", "/status")[1])["metering"]["eval_tokens_total"]
        self.assertEqual(after, before)
        self.assertEqual(json.loads(self.request("GET", "/status")[1])["metering"]["unmetered_stream_calls"],
                         before_status["unmetered_stream_calls"] + 1)

    def test_large_proxy_body_bypasses_feedback_guard(self):
        body = b'{"model":"large","data":"' + (b"x" * 5000) + b'"}'
        status, result, _ = self.request("POST", "/api/echo", body, {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(result, body)

    def test_passthrough_host_rewrite_and_metered_body_equality(self):
        body = b'{"model":"same","messages":[]}'
        direct = self.request("POST", "/api/chat", body,
                              {"Content-Type": "application/json", "Host": "127.0.0.1:11434"},
                              ("127.0.0.1", self.backend_port))[1]
        proxied = self.request("POST", "/api/chat", body, {"Content-Type": "application/json"})[1]
        self.assertEqual(proxied, direct)
        self.assertEqual(self.request("GET", "/api/version")[1], b'{"version":"test"}')
        status, echoed, _ = self.request("PUT", "/api/echo", body,
                                         {"Content-Type": "application/json"})
        self.assertEqual((status, echoed), (200, body))

    def test_rotation_keeps_cumulative_total_monotonic(self):
        before = json.loads(self.request("GET", "/status")[1])["metering"]["calls_total"]
        for _ in range(4):
            self.request("POST", "/api/chat", b'{"model":"rotate"}', {"Content-Type": "application/json"})
        after = self.status_when(lambda st: st["metering"]["calls_total"] >= before + 4)["metering"]["calls_total"]
        self.assertEqual(after, before + 4)
        self.assertTrue((Path(self.tmp.name) / "calls.log.1").exists())

    def test_ring_stays_bounded(self):
        body = b'{"model":"ring"}'
        for _ in range(260):
            self.request("POST", "/api/chat", body, {"Content-Type": "application/json"})
        status = json.loads(self.request("GET", "/status")[1])
        self.assertLessEqual(status["metering"]["ring_len"], 256)
        self.assertEqual(len(self.calls()), 256)

    def test_busy_proxy_records_503_status(self):
        global SLOW_COUNT
        with SLOW_LOCK:
            SLOW_COUNT = 0
        SLOW_EVENT.clear()
        body = b'{"model":"slow","slow":true}'
        workers = [threading.Thread(target=self.request,
                                    args=("POST", "/api/chat", body, {"Content-Type": "application/json"}))
                   for _ in range(16)]
        for worker in workers:
            worker.start()
        try:
            self.assertTrue(SLOW_EVENT.wait(timeout=5), "16 slow requests did not reach backend")
            status, _, _ = self.request("POST", "/api/chat", b'{"model":"busy"}',
                                        {"Content-Type": "application/json"})
            self.assertEqual(status, 503)
            row = next(r for r in self.calls() if r["status"] == 503)
            self.assertEqual((row["path"], row["status"]), ("/api/chat", 503))
        finally:
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

    def test_backend_down_returns_502_and_records_failed_call(self):
        dead_port = free_port()
        env = os.environ.copy()
        env.update({"FEEDBACK_SERVER_PORT": str(free_port()), "METER_DIR": str(Path(self.tmp.name) / "down"),
                    "OLLAMA_URL": f"http://127.0.0.1:{dead_port}"})
        process = subprocess.Popen([sys.executable, str(ROOT / "feedback-server.py")], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port = int(env["FEEDBACK_SERVER_PORT"])
            for _ in range(100):
                try:
                    ready = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    ready.request("GET", "/status")
                    ready.getresponse().read()
                    ready.close()
                    break
                except OSError:
                    time.sleep(.05)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/api/chat", b'{"model":"down"}')
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 502)
            conn.close()
            data = (Path(env["METER_DIR"]) / "calls.log").read_text().strip().splitlines()
            row = json.loads(data[-1])
            self.assertFalse(row["ok"])
            self.assertEqual((row["path"], row["status"]), ("/api/chat", 502))
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_installed_smallest_ollama_model_probe(self):
        # End-to-end local Ollama inference. No model is pulled; caller may override the tag.
        model = os.environ.get("METER_TEST_MODEL", "qwen2.5:0.5b")
        try:
            conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=3)
            conn.request("GET", "/api/tags")
            response = conn.getresponse()
            tags = json.loads(response.read())
            conn.close()
        except Exception as exc:
            self.fail(f"local Ollama unavailable: {exc}")
        self.assertIn(model, [m.get("name") for m in tags.get("models", [])])
        port = free_port()
        data_dir = str(Path(self.tmp.name) / "real-ollama")
        env = os.environ.copy()
        env.update({"FEEDBACK_SERVER_PORT": str(port), "METER_DIR": data_dir,
                    "OLLAMA_URL": "http://127.0.0.1:11434"})
        stderr_path = str(Path(self.tmp.name) / "real-ollama-stderr.log")
        stderr_file = open(stderr_path, "wb")
        process = subprocess.Popen([sys.executable, str(ROOT / "feedback-server.py")], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=stderr_file)
        try:
            for _ in range(100):
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    conn.request("GET", "/status")
                    conn.getresponse().read()
                    conn.close()
                    break
                except OSError:
                    time.sleep(.05)
            body = json.dumps({"model": model, "messages": [{"role": "user", "content": "Reply with one word: OK."}],
                               "stream": False}).encode()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
            conn.request("POST", "/api/chat", body, {"Content-Type": "application/json", "X-Agent": "luna-build-test"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200, response.read().decode("utf-8", "replace"))
            response.read()
            conn.close()
            ledger = Path(data_dir) / "calls.log"
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not (ledger.exists() and ledger.stat().st_size):
                time.sleep(.01)
            self.assertTrue(ledger.exists(), f"no ledger written; sidecar stderr: {Path(stderr_path).read_text(errors='replace')}")
            rows = [json.loads(line) for line in ledger.read_text().splitlines()]
            row = rows[-1]
            self.assertEqual((row["agent"], row["model"]), ("luna-build-test", model))
            self.assertIsInstance(row["eval_tokens"], int)
        finally:
            process.terminate()
            process.wait(timeout=5)
            stderr_file.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
