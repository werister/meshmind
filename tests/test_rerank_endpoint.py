#!/usr/bin/env python3
"""Stdlib acceptance harness for the T10 /rerank endpoint + worker. Run directly.

No onnxruntime exists on the build MacBook: the endpoint is tested against STUB
workers (tests/fixtures/rerank/stub_worker_*.py) and the worker module is tested
against a FAKE ONNX session object injected in-process. Never real weights.

    python3 tests/test_rerank_endpoint.py   ->   exit 0 with PASS counts
"""
import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "rerank"
SCORING = str(FIX / "stub_worker_scoring.py")
CRASH = str(FIX / "stub_worker_crash.py")
GARBAGE = str(FIX / "stub_worker_garbage.py")
HANG = str(FIX / "stub_worker_hang.py")


def _load_worker_module():
    """Import scripts/rerank_worker.py directly (stdlib-only at import time)."""
    path = ROOT / "scripts" / "rerank_worker.py"
    spec = importlib.util.spec_from_file_location("rerank_worker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ======================================================================= worker unit tests
class FakeOnnxSession:
    """Fake ONNX session: records feeds and returns caller-chosen logits.

    Mimics onnxruntime.InferenceSession.run(output_names, feeds) -> [logits],
    where logits is a per-passage array of 1-element rows (a cross-encoder's
    single relevance logit per pair). Never loads real weights.
    """

    def __init__(self, logits):
        self._logits = logits
        self.last_feeds = None

    def run(self, output_names, feeds):
        self.last_feeds = feeds
        return [self._logits]


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.worker = _load_worker_module()

    def test_worker_scores_in_input_order_from_fake_session(self):
        passages = [{"id": "a", "text": "alpha"}, {"id": "b", "text": "beta"}]
        session = FakeOnnxSession([[0.2], [0.9]])
        reranker = self.worker._OnnxReranker(session)
        out = self.worker.run(reranker, "q", passages)
        self.assertEqual(out, {"scores": [{"id": "a", "score": 0.2}, {"id": "b", "score": 0.9}]})
        # The fake session saw the query + passage texts (no real tokenizer).
        self.assertEqual(session.last_feeds["passages"], ["alpha", "beta"])

    def test_worker_empty_passages_short_circuits(self):
        rc = self.worker.main(
            argv=["--model-dir", "/nonexistent"],
            stdin=_StringIO('{"query":"q","passages":[]}'),
            stdout=(out := _StringIO()),
            reranker=self.worker._OnnxReranker(FakeOnnxSession([])),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), {"scores": []})

    def test_worker_bad_json_exits_nonzero_with_error(self):
        rc = self.worker.main(
            argv=["--model-dir", "/nonexistent"],
            stdin=_StringIO("not json"),
            stdout=(out := _StringIO()),
            reranker=self.worker._OnnxReranker(FakeOnnxSession([])),
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("error", json.loads(out.getvalue()))

    def test_worker_session_count_mismatch_is_reported(self):
        rc = self.worker.main(
            argv=["--model-dir", "/nonexistent"],
            stdin=_StringIO('{"query":"q","passages":[{"id":1,"text":"x"},{"id":2,"text":"y"}]}'),
            stdout=(out := _StringIO()),
            reranker=self.worker._OnnxReranker(FakeOnnxSession([[0.5]])),  # 1 score, 2 passages
        )
        self.assertEqual(rc, 1)
        self.assertIn("error", json.loads(out.getvalue()))


class _StringIO:
    """Minimal stdin/stdout stand-in so the worker's main() needs no real pipes."""
    def __init__(self, data=""):
        self._in = data
        self._out = []

    def read(self):
        return self._in

    def write(self, s):
        self._out.append(s)

    def getvalue(self):
        return "".join(self._out)


# ======================================================================= endpoint acceptance
class RerankEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="rerank-test-")
        cls.port = free_port()
        dead = free_port()  # Ollama upstream need not exist; /rerank never touches it.
        env = os.environ.copy()
        env.update({
            "FEEDBACK_SERVER_PORT": str(cls.port),
            "METER_DIR": cls.tmp.name,
            "OLLAMA_URL": f"http://127.0.0.1:{dead}",
            "RERANK_WORKER": SCORING,
            "RERANK_PYTHON": sys.executable,
            "RERANK_MODEL_DIR": str(Path(cls.tmp.name) / "fake-model"),
        })
        cls.env = env
        cls.proxy = subprocess.Popen(
            [sys.executable, str(ROOT / "feedback-server.py")],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                cls.request("GET", "/status")
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proxy.terminate()
        cls.proxy.wait(timeout=5)
        cls.tmp.cleanup()

    @classmethod
    def request(cls, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=30)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        payload = response.read()
        result = (response.status, payload)
        conn.close()
        return result

    def post(self, obj, headers=None):
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        return self.request("POST", "/rerank", json.dumps(obj).encode(), h)

    def calls(self):
        return json.loads(self.request("GET", "/calls?limit=256")[1])

    # ---- test_empty
    def test_empty_passages_returns_empty_scores_not_error(self):
        status, body = self.post({"query": "q", "passages": []})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["scores"], [])
        self.assertEqual(data["model"], "ettin-17m")
        self.assertIn("latency_s", data)

    # ---- stub-worker scoring order (descending, stable)
    def test_scoring_order_is_descending_and_stable(self):
        passages = [
            {"id": "short", "text": "ab"},       # len 2
            {"id": "longest", "text": "abcdef"},  # len 6
            {"id": "mid", "text": "abcd"},        # len 4
            {"id": "tie1", "text": "xy"},         # len 2 (ties with short, after it)
        ]
        status, body = self.post({"query": "q", "passages": passages})
        self.assertEqual(status, 200)
        data = json.loads(body)
        ids = [r["id"] for r in data["scores"]]
        # Descending by score (= text length); equal scores keep input order.
        self.assertEqual(ids, ["longest", "mid", "short", "tie1"])
        self.assertEqual([r["score"] for r in data["scores"]], [6.0, 4.0, 2.0, 2.0])

    def test_top_k_truncates_after_sort(self):
        passages = [{"id": i, "text": "x" * (i + 1)} for i in range(5)]
        status, body = self.post({"query": "q", "passages": passages, "top_k": 2})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual([r["id"] for r in data["scores"]], [4, 3])

    def test_rerank_call_is_metered_with_rerank_agent(self):
        self.post({"query": "q", "passages": [{"id": "x", "text": "hello"}]})
        row = next(r for r in self.calls() if r["path"] == "/rerank" and r["ok"])
        self.assertEqual(row["agent"], "rerank")
        self.assertEqual(row["model"], "ettin-17m")
        self.assertEqual(row["status"], 200)

    # ---- test_caps
    def test_too_many_passages_is_400(self):
        passages = [{"id": i, "text": "x"} for i in range(21)]
        status, body = self.post({"query": "q", "passages": passages})
        self.assertEqual(status, 400)
        self.assertIn("too many passages", json.loads(body)["error"])

    def test_passage_too_long_is_400(self):
        status, body = self.post({"query": "q", "passages": [{"id": 1, "text": "x" * 2001}]})
        self.assertEqual(status, 400)
        self.assertIn("too long", json.loads(body)["error"])

    def test_top_k_over_cap_is_400(self):
        status, body = self.post({"query": "q", "passages": [{"id": 1, "text": "x"}], "top_k": 21})
        self.assertEqual(status, 400)
        self.assertIn("top_k too large", json.loads(body)["error"])

    def test_passages_at_exact_cap_pass(self):
        passages = [{"id": i, "text": "x" * 2000} for i in range(20)]
        status, body = self.post({"query": "q", "passages": passages, "top_k": 20})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["scores"]), 20)

    def test_bad_json_body_is_400(self):
        status, body = self.request("POST", "/rerank", b"{not json",
                                    {"Content-Type": "application/json"})
        self.assertEqual(status, 400)

    # ---- test_worker_down / test_worker_garbage / timeout: each via a dedicated server
    def _server_with_worker(self, worker_path, extra_env=None):
        tmp = tempfile.TemporaryDirectory(prefix="rerank-wk-")
        port = free_port()
        env = os.environ.copy()
        env.update({
            "FEEDBACK_SERVER_PORT": str(port),
            "METER_DIR": tmp.name,
            "OLLAMA_URL": f"http://127.0.0.1:{free_port()}",
            "RERANK_WORKER": worker_path,
            "RERANK_PYTHON": sys.executable,
            "RERANK_MODEL_DIR": str(Path(tmp.name) / "fake-model"),
        })
        if extra_env:
            env.update(extra_env)
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "feedback-server.py")],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", "/status")
                c.getresponse().read()
                c.close()
                break
            except OSError:
                time.sleep(0.05)
        return proc, port, tmp

    def _post_to(self, port, obj):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request("POST", "/rerank", json.dumps(obj).encode(), {"Content-Type": "application/json"})
        r = c.getresponse()
        out = (r.status, r.read())
        c.close()
        return out

    def test_worker_down_is_503_and_server_alive(self):
        proc, port, tmp = self._server_with_worker(CRASH)
        try:
            status, body = self._post_to(port, {"query": "q", "passages": [{"id": 1, "text": "x"}]})
            self.assertEqual(status, 503)
            self.assertIn("error", json.loads(body))
            # Server still answers after a worker failure (never crashed).
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/status")
            self.assertEqual(c.getresponse().status, 200)
            c.close()
            row = next(r for r in json.loads(self._get(port, "/calls?limit=10")) if r["path"] == "/rerank")
            self.assertEqual(row["status"], 503)
            self.assertFalse(row["ok"])
        finally:
            proc.terminate(); proc.wait(timeout=5); tmp.cleanup()

    def test_worker_garbage_is_503(self):
        proc, port, tmp = self._server_with_worker(GARBAGE)
        try:
            status, body = self._post_to(port, {"query": "q", "passages": [{"id": 1, "text": "x"}]})
            self.assertEqual(status, 503)
            self.assertIn("error", json.loads(body))
        finally:
            proc.terminate(); proc.wait(timeout=5); tmp.cleanup()

    def test_worker_timeout_is_503(self):
        # Inject a 1s worker timeout so the hang stub trips it fast.
        proc, port, tmp = self._server_with_worker(HANG, {"RERANK_TIMEOUT_S": "1"})
        try:
            status, body = self._post_to(port, {"query": "q", "passages": [{"id": 1, "text": "x"}]})
            self.assertEqual(status, 503)
        finally:
            proc.terminate(); proc.wait(timeout=5); tmp.cleanup()

    @staticmethod
    def _get(port, path):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", path)
        out = c.getresponse().read()
        c.close()
        return out


if __name__ == "__main__":
    unittest.main(verbosity=2)
