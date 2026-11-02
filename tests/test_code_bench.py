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

    # --- paired mode: interleaved reps + task-level sign test --------
    def test_paired_interleave(self):
        code, out, err = run(["--models", "good-model,wrong-model",
                              "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                              "--order", "interleave", "--reps", "2",
                              "--seed", "7", "--temp", "0.8"])
        self.assertEqual(code, 0)
        self.assertEqual(out["mode"], "paired")
        self.assertEqual(out["reps"], 2)
        self.assertEqual(out["seed"], 7)
        self.assertTrue(out["fixture_duplicates"])  # non-list entries repeat
        p = out["paired"]
        self.assertEqual(p["cells"], 4)  # 2 tasks x 2 reps
        self.assertEqual((p["wins_a"], p["wins_b"], p["ties"]), (4, 0, 0))
        self.assertEqual(p["cell_p_two_sided_descriptive_only"], 0.125)
        self.assertEqual((p["favor_a"], p["favor_b"], p["favor_tie"]), (2, 0, 0))
        self.assertEqual(p["task_p_two_sided"], 0.5)  # 2*(1/4)
        self.assertFalse(p["parity_veto"])
        self.assertIn("task p (two-sided)", err)

    def test_paired_all_ties(self):
        code, out, _ = run(["--models", "good-model,good-model-2",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                            "--order", "interleave", "--reps", "2",
                            "--seed", "7", "--temp", "0.8"])
        self.assertEqual(code, 0)
        p = out["paired"]
        self.assertEqual((p["decisive"], p["ties"]), (0, 4))
        self.assertEqual(p["task_p_two_sided"], 1.0)

    def test_paired_order_alternates_per_rep(self):
        # (task_index + rep) counterbalancing: every task sees both orders.
        code, out, _ = run(["--models", "good-model,wrong-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                            "--order", "interleave", "--reps", "2",
                            "--seed", "7", "--temp", "0.8"])
        self.assertEqual(code, 0)
        got = [(r["rep"], r["task"], r["first"]) for r in out["rows"]]
        self.assertEqual(got, [
            (0, "01-median", "good-model"), (0, "01-median", "good-model"),
            (0, "02-dedup", "wrong-model"), (0, "02-dedup", "wrong-model"),
            (1, "01-median", "wrong-model"), (1, "01-median", "wrong-model"),
            (1, "02-dedup", "good-model"), (1, "02-dedup", "good-model"),
        ])
        self.assertEqual([r["turn"] for r in out["rows"]], list(range(8)))

    def test_paired_per_rep_fixture_lists(self):
        # list-model passes 01-median on rep 0, fails it on rep 1.
        code, out, _ = run(["--models", "list-model,wrong-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                            "--order", "interleave", "--reps", "2",
                            "--seed", "7", "--temp", "0.8"])
        self.assertEqual(code, 0)
        # wrong-model's entries are non-lists, so reps still duplicate there.
        self.assertTrue(out["fixture_duplicates"])
        t = out["paired"]["per_task"]["01-median"]
        self.assertEqual((t["list-model"], t["wrong-model"], t["ties"]),
                         (1, 0, 1))

    def test_paired_requires_two_models(self):
        for models in ("good-model", "good-model,wrong-model,chatty-model"):
            code, out, err = run(["--models", models,
                                  "--tasks", str(SAMPLE),
                                  "--fixture", str(REPLIES),
                                  "--order", "interleave",
                                  "--seed", "7", "--temp", "0.8"])
            self.assertEqual(code, 2)
            self.assertIsNone(out)
            self.assertIn("exactly two", err)

    def test_paired_models_must_differ(self):
        code, out, err = run(["--models", "good-model,good-model",
                              "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                              "--order", "interleave",
                              "--seed", "7", "--temp", "0.8"])
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertIn("must differ", err)

    def test_paired_requires_seed_and_temp(self):
        base = ["--models", "good-model,wrong-model",
                "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                "--order", "interleave"]
        code, _, err = run(base + ["--seed", "7"])
        self.assertEqual(code, 2)
        self.assertIn("explicit --seed and --temp", err)
        code, _, err = run(base + ["--temp", "0.8"])
        self.assertEqual(code, 2)
        self.assertIn("explicit --seed and --temp", err)

    def test_temp0_reps_refused(self):
        code, _, err = run(["--models", "good-model,wrong-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                            "--order", "interleave", "--reps", "2",
                            "--seed", "7", "--temp", "0"])
        self.assertEqual(code, 2)
        self.assertIn("greedy", err)

    def test_reps_sequential_refused(self):
        code, _, err = run(["--models", "good-model,wrong-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                            "--reps", "2"])
        self.assertEqual(code, 2)
        self.assertIn("--order interleave", err)

    def test_unload_fixture_skips_with_note(self):
        code, out, err = run(["--models", "good-model,wrong-model",
                              "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                              "--order", "interleave", "--reps", "1",
                              "--seed", "7", "--temp", "0.8", "--unload"])
        self.assertEqual(code, 0)
        self.assertFalse(out["unload"])
        self.assertIn("--unload skipped (fixture mode performs no loads)", err)

    def test_journal_survives_rows(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            journal = str(Path(tmp) / "run.jsonl")
            code, out, _ = run(["--models", "good-model,wrong-model",
                                "--tasks", str(SAMPLE),
                                "--fixture", str(REPLIES),
                                "--order", "interleave", "--reps", "1",
                                "--seed", "7", "--temp", "0.8",
                                "--journal", journal])
            self.assertEqual(code, 0)
            lines = Path(journal).read_text().strip().split("\n")
            self.assertEqual(len(lines), len(out["rows"]))
            self.assertEqual(json.loads(lines[0])["turn"], 0)

    def test_provenance_recorded(self):
        code, out, _ = run(["--models", "good-model,wrong-model",
                            "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                            "--order", "interleave", "--reps", "1",
                            "--seed", "7", "--temp", "0.8"])
        self.assertEqual(code, 0)
        prov = out["provenance"]
        self.assertEqual(prov["fixture"], str(REPLIES))
        self.assertIsNone(prov["ollama"])
        self.assertEqual(len(prov["tasks_hash"]), 16)
        self.assertIn("--seed", prov["argv"])
        code2, out2, _ = run(["--models", "good-model,wrong-model",
                              "--tasks", str(SAMPLE), "--fixture", str(REPLIES),
                              "--order", "interleave", "--reps", "1",
                              "--seed", "7", "--temp", "0.8"])
        self.assertEqual(code2, 0)
        self.assertEqual(out2["provenance"]["tasks_hash"],
                         prov["tasks_hash"])

    def test_seed_threading_stubbed(self):
        # bench_paired passes identical seed+rep options to both models.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "code_bench_under_test", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        seen = []

        def fake_ask(url, model, prompt, timeout, options=None):
            seen.append((model, dict(options or {})))
            return ("```python\ndef f():\n    pass\n```", 1, 1)

        real = mod.ask_ollama
        mod.ask_ollama = fake_ask
        try:
            tasks = mod.load_tasks(SAMPLE_MED)
            rows = mod.bench_paired(["m-a", "m-b"], tasks, 30, None,
                                    "http://127.0.0.1:9", 2, 41, 0.8, False)
        finally:
            mod.ask_ollama = real
        self.assertEqual(len(rows), 4)  # 1 task x 2 models x 2 reps
        by_rep = {}
        for model, options in seen:
            by_rep.setdefault(options["seed"], {})[model] = options
        self.assertEqual(sorted(by_rep), [41, 42])
        for seed, pair in by_rep.items():
            self.assertEqual(pair["m-a"], pair["m-b"])
            self.assertEqual(pair["m-a"]["temperature"], 0.8)

    def test_bad_server_json_is_infra_not_traceback(self):
        # A garbage-speaking Ollama must yield exit 2, never exit 1.
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Garbage(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                body = b"THIS IS NOT JSON"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Garbage)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            code, out, err = run(["--models", "m-a,m-b",
                                  "--tasks", str(SAMPLE_MED),
                                  "--ollama", "http://127.0.0.1:%d" % port,
                                  "--order", "interleave", "--reps", "1",
                                  "--seed", "7", "--temp", "0.8"])
        finally:
            server.shutdown()
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertNotIn("Traceback", err)

    # --- paired_summary unit tests (pure function, synthetic rows) -----
    def _summary_mod(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "code_bench_under_test", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _row(rep, task, model, passed, note="ok", first="m-a"):
        return {"rep": rep, "task": task, "model": model, "pass": passed,
                "note": note, "first": first}

    def test_summary_task_level_sign(self):
        mod = self._summary_mod()
        rows = []
        # 3 tasks favor m-a, 1 favors m-b (reps would double-count cells).
        for task, winner in (("t1", "m-a"), ("t2", "m-a"), ("t3", "m-a"),
                             ("t4", "m-b")):
            for rep in (0, 1):
                rows.append(self._row(rep, task, "m-a", winner == "m-a"))
                rows.append(self._row(rep, task, "m-b", winner == "m-b"))
        out = mod.paired_summary(rows, ["m-a", "m-b"])
        self.assertEqual((out["favor_a"], out["favor_b"]), (3, 1))
        self.assertEqual(out["task_p_two_sided"], 0.625)  # 2*(1+4)/16
        self.assertEqual(out["breadth_leader"], 3)

    def test_summary_artifacts_excluded(self):
        mod = self._summary_mod()
        rows = [self._row(0, "t1", "m-a", True),
                self._row(0, "t1", "m-b", False, note="no_fence"),
                self._row(0, "t2", "m-a", True),
                self._row(0, "t2", "m-b", True)]
        out = mod.paired_summary(rows, ["m-a", "m-b"])
        self.assertEqual(out["decisive"], 0)  # artifact cell is not evidence
        self.assertEqual(out["artifacts_b"], 1)
        self.assertEqual(out["task_p_two_sided"], 1.0)

    def test_summary_parity_veto(self):
        mod = self._summary_mod()
        rows = []
        # m-a leads 4-2 overall, but m-b leads the b-first subset by 2.
        wins = [(0, "t1", "m-a", "m-a"), (0, "t2", "m-a", "m-a"),
                (0, "t3", "m-a", "m-a"), (0, "t4", "m-a", "m-a"),
                (0, "t5", "m-b", "m-b"), (0, "t6", "m-b", "m-b")]
        for rep, task, winner, first in wins:
            rows.append(self._row(rep, task, "m-a", winner == "m-a",
                                  first=first))
            rows.append(self._row(rep, task, "m-b", winner == "m-b",
                                  first=first))
        out = mod.paired_summary(rows, ["m-a", "m-b"])
        self.assertEqual(out["leader"], "m-a")
        self.assertTrue(out["parity_veto"])

    def test_summary_incomplete_and_validation(self):
        mod = self._summary_mod()
        rows = [self._row(0, "t1", "m-a", True)]  # m-b missing
        out = mod.paired_summary(rows, ["m-a", "m-b"])
        self.assertEqual((out["cells"], out["incomplete"]), (1, 1))
        self.assertEqual(out["task_p_two_sided"], 1.0)
        with self.assertRaises(ValueError):
            mod.paired_summary(rows, ["m-a"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(CodeBenchTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\ncode_bench: PASS %d/%d" % (passed, result.testsRun))
    sys.exit(0 if result.wasSuccessful() else 1)
