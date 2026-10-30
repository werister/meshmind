#!/usr/bin/env python3
"""Stdlib acceptance harness for scripts/code_bench.py; run directly.

    python3 tests/test_code_bench.py

No pytest on this box. Every test maps to a T11 contract behavior or a row of
the T11 failure table; no test without a regression it would catch. No live
calls: model replies come from canned fixtures, host-down uses a dead port.

Also enforces the T11 acceptance self-test: all 10 shipped task files validate
and their reference solutions pass their own hidden asserts.
"""
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "code_bench.py"
CB = ROOT / "tests" / "fixtures" / "codebench"
TASKS = CB / "tasks"
SAMPLE = CB / "sample-tasks"
SAMPLE_MED = CB / "sample-tasks-median"
REPLIES = CB / "replies" / "sample-replies.json"
TIMEOUT_REPLY = CB / "replies" / "timeout-reply.json"
BAD_TASKS = CB / "bad-tasks"

# The fixed task mix the ticket froze: 4 pure, 2 stdlib, 2 bugfix, 1 edge, 1 refactor.
EXPECTED_TASK_STEMS = {
    "01-median", "02-dedup", "03-anagrams", "04-brackets",
    "05-stdlib-json-pathlib", "06-stdlib-datetime",
    "07-bugfix-average", "08-bugfix-fizzbuzz",
    "09-edge-trap", "10-refactor",
}


def run(args, timeout=90):
    """Invoke code_bench.py. Returns (exit_code, parsed_stdout_or_None, stderr)."""
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


def tasks_of(parsed, model_index=0):
    return parsed["models"][model_index]["tasks"]


class CodeBenchTests(unittest.TestCase):

    # --- T11 acceptance: the 10 shipped tasks self-test green -----------
    def test_self_test_all_tasks_green(self):
        code, out, _ = run(["--self-test"])
        self.assertEqual(code, 0)
        self.assertEqual(out["mode"], "self_test")
        self.assertEqual(out["tasks_total"], 10)
        self.assertTrue(out["all_green"], "reference solutions must pass own asserts")
        stems = {r["task"] for r in out["results"]}
        self.assertEqual(stems, EXPECTED_TASK_STEMS)
        for row in out["results"]:
            self.assertTrue(row["ok"], "%s reference failed: %s" % (row["task"], row["note"]))

    # --- schema/shape of the findings object ----------------------------
    def test_findings_shape(self):
        code, out, _ = run(["--models", "good-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES)])
        self.assertEqual(code, 0)
        self.assertEqual(out["tool"], "code_bench")
        self.assertEqual(out["tasks_total"], 2)
        self.assertEqual(len(out["models"]), 1)
        block = out["models"][0]
        self.assertEqual(block["model"], "good-model")
        for row in tasks_of(out):
            self.assertEqual(set(row), {"task", "pass", "note",
                                        "prompt_tokens", "eval_tokens"})
            self.assertIsInstance(row["pass"], bool)

    # --- happy path: a correct solution passes, tokens recorded ---------
    def test_passing_solution(self):
        code, out, _ = run(["--models", "good-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES)])
        self.assertEqual(code, 0)
        rows = tasks_of(out)
        self.assertTrue(all(r["pass"] for r in rows))
        self.assertEqual(rows[0]["eval_tokens"], 58)
        self.assertEqual(rows[0]["prompt_tokens"], 64)

    # --- a wrong (but fenced) solution fails via the hidden asserts -----
    #     (01-median has a skewed case so a mean-impostor cannot sneak by)
    def test_failing_solution(self):
        code, out, _ = run(["--models", "wrong-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES)])
        self.assertEqual(code, 0)
        rows = tasks_of(out)
        self.assertFalse(any(r["pass"] for r in rows))
        for row in rows:
            self.assertTrue(row["note"].startswith("assert_or_error"))

    # --- T11 failure table: no code fence -> task fail, run continues ---
    def test_no_fence(self):
        code, out, _ = run(["--models", "chatty-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES)])
        self.assertEqual(code, 0)  # run continues, not fatal
        rows = tasks_of(out)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertFalse(row["pass"])
            self.assertEqual(row["note"], "no_fence")

    # --- T11 failure table: assert subprocess timeout -> fail + note ----
    def test_task_timeout(self):
        code, out, _ = run(["--models", "hang-model",
                            "--tasks", str(SAMPLE_MED),
                            "--fixture", str(TIMEOUT_REPLY), "--timeout", "2"])
        self.assertEqual(code, 0)
        row = tasks_of(out)[0]
        self.assertFalse(row["pass"])
        self.assertEqual(row["note"], "timeout")

    # --- T11 failure table: host down -> exit 2, stderr reason ----------
    def test_host_down(self):
        port = dead_port()
        code, out, err = run(["--models", "probe",
                             "--tasks", str(SAMPLE),
                             "--ollama", "http://127.0.0.1:%d" % port,
                             "--timeout", "2"])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("unreachable", err)

    # --- T11 failure table: task dir malformed -> exit 2 naming the file
    def test_bad_tasks(self):
        code, out, err = run(["--models", "good-model",
                             "--tasks", str(BAD_TASKS), "--fixture", str(REPLIES)])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("broken.md", err)

    # --- missing fixture file is an infra error (exit 2) ----------------
    def test_missing_fixture_file(self):
        code, out, err = run(["--models", "good-model",
                             "--tasks", str(SAMPLE),
                             "--fixture", str(CB / "replies" / "nope.json")])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("not found", err)

    # --- missing --models (and no --self-test) is an infra error --------
    def test_models_required(self):
        code, out, err = run(["--tasks", str(SAMPLE), "--fixture", str(REPLIES)])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("--models", err)

    # --- multiple models in one run, independently scored ---------------
    def test_multi_model(self):
        code, out, _ = run(["--models", "good-model,wrong-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES)])
        self.assertEqual(code, 0)
        self.assertEqual([b["model"] for b in out["models"]],
                         ["good-model", "wrong-model"])
        self.assertTrue(all(r["pass"] for r in tasks_of(out, 0)))
        self.assertFalse(any(r["pass"] for r in tasks_of(out, 1)))


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(CodeBenchTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\ncode_bench: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
