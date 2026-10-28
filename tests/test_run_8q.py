#!/usr/bin/env python3
"""Stdlib acceptance harness for scripts/run_8q.py; run directly.

    python3 tests/test_run_8q.py

No pytest on this box. Every test maps to a contract behavior or a row of
the T8 failure table; no test without a regression it would catch.
"""
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_8q.py"
FIX = ROOT / "tests" / "fixtures" / "gateway"


def run(args):
    """Invoke run_8q.py. Returns (exit_code, parsed_stdout_or_None, stderr)."""
    proc = subprocess.run([sys.executable, str(SCRIPT)] + args,
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
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


class Run8qTests(unittest.TestCase):

    # --- happy path: mixed answers pass the filter ----------------------
    def test_mixed_answers_pass(self):
        code, out, _ = run(["--model", "probe",
                            "--questions", str(FIX / "a8-questions-placeholder.json"),
                            "--fixture", str(FIX / "a8-answers-mixed.json")])
        self.assertEqual(code, 0)
        self.assertEqual(out["tool"], "run_8q")
        self.assertEqual(out["model"], "probe")
        self.assertEqual(len(out["answers"]), 8)
        self.assertTrue(out["pass"])
        self.assertEqual([a["answer"] for a in out["answers"]],
                         ["yes", "yes", "yes", "yes", "no", "no", "no", "no"])
        for row in out["answers"]:
            self.assertIn("latency_s", row)
            self.assertIsInstance(row["latency_s"], float)

    # --- placeholder set ships, is clearly marked, and is 4/4 -----------
    def test_placeholder_questions_default_and_balanced(self):
        # No --questions => the shipped PLACEHOLDER set is used.
        code, out, _ = run(["--model", "probe",
                            "--fixture", str(FIX / "a8-answers-mixed.json")])
        self.assertEqual(code, 0)
        self.assertEqual(len(out["answers"]), 8)
        self.assertTrue(out["pass"])
        # The shipped placeholder file is explicitly marked and 4/4.
        data = json.loads((FIX / "a8-questions-placeholder.json").read_text())
        self.assertIn("PLACEHOLDER", json.dumps(data).upper())
        qs = data["questions"]
        self.assertEqual(sum(1 for q in qs if q["expect_yes"]), 4)
        self.assertEqual(sum(1 for q in qs if not q["expect_yes"]), 4)

    # --- T8 failure table: Question timeout -> null, completes, pass=false
    def test_probe_timeout(self):
        code, out, _ = run(["--model", "probe",
                            "--questions", str(FIX / "a8-questions-placeholder.json"),
                            "--fixture", str(FIX / "a8-answers-timeout.json")])
        self.assertEqual(code, 0)  # run still completes
        self.assertEqual(len(out["answers"]), 8)
        self.assertIsNone(out["answers"][2]["answer"])  # q3 timed out -> null
        self.assertFalse(out["pass"])

    # --- T8 failure table: Always-yes on mixed set -> pass=false --------
    def test_always_yes(self):
        code, out, _ = run(["--model", "lazy",
                            "--questions", str(FIX / "a8-questions-placeholder.json"),
                            "--fixture", str(FIX / "a8-answers-always-yes.json")])
        self.assertEqual(code, 0)
        self.assertTrue(all(a["answer"] == "yes" for a in out["answers"]))
        self.assertFalse(out["pass"])
        self.assertIn("agree", out["notes"])

    # --- contract: non-yes/no answer -> null -> pass=false --------------
    def test_non_yesno_is_null_and_fails(self):
        code, out, _ = run(["--model", "probe",
                            "--questions", str(FIX / "a8-questions-placeholder.json"),
                            "--fixture", str(FIX / "a8-answers-garbled.json")])
        self.assertEqual(code, 0)
        self.assertIsNone(out["answers"][3]["answer"])  # q4 prose -> null
        self.assertFalse(out["pass"])

    # --- contract guard: non-4/4 question set is an infra error (exit 2)
    def test_unbalanced_question_set_rejected(self):
        code, out, err = run(["--model", "probe",
                             "--questions", str(FIX / "a8-questions-unbalanced.json"),
                             "--fixture", str(FIX / "a8-answers-mixed.json")])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("4 yes", err)

    # --- T8 failure table: Ollama host down -> exit 2, stderr reason ----
    def test_host_down(self):
        port = dead_port()
        code, out, err = run(["--model", "probe",
                             "--ollama", "http://127.0.0.1:%d" % port,
                             "--timeout", "2"])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("unreachable", err)

    # --- missing fixture file is an infra error (exit 2) ----------------
    def test_missing_fixture_file(self):
        code, out, err = run(["--model", "probe",
                             "--fixture", str(FIX / "does-not-exist.json")])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("not found", err)


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(Run8qTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\nrun_8q: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
