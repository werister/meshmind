#!/usr/bin/env python3
"""Stdlib contract-conformance harness for scripts/bakeoff.py — run directly.

bakeoff composes the FROZEN run_8q / run_ladder CLIs. We point it at the b9
stub scripts (fixtures) via BAKEOFF_RUN_8Q / BAKEOFF_RUN_LADDER so no network
and no real 8Q/ladder code are touched. Prints a PASS count on exit.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAKEOFF = ROOT / "scripts" / "bakeoff.py"
FIX = ROOT / "tests" / "fixtures" / "gateway"
STUB_8Q = FIX / "b9-run_8q-stub.py"
STUB_LADDER = FIX / "b9-run_ladder-stub.py"
STUB_SCREEN = FIX / "b9-screen-stub.py"


def run_bakeoff(models, out_dir, screen_cmd=None, questions=None):
    env = os.environ.copy()
    env["BAKEOFF_RUN_8Q"] = str(STUB_8Q)
    env["BAKEOFF_RUN_LADDER"] = str(STUB_LADDER)
    cmd = [sys.executable, str(BAKEOFF), "--models", models, "--out", str(out_dir)]
    if screen_cmd is not None:
        cmd += ["--screen-cmd", screen_cmd]
    if questions is not None:
        cmd += ["--questions", questions]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120)
    return proc


class BakeoffContract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="b9-bakeoff-")
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _findings(self):
        return json.loads((self.out / "findings.json").read_text())

    def test_happy_path_writes_both_artifacts_exit0(self):
        proc = run_bakeoff("alpha-PASS,beta-PASS", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertTrue((self.out / "findings.json").exists())
        self.assertTrue((self.out / "findings.md").exists())
        # stdout is a single JSON object (contract: JSON to stdout).
        payload = json.loads(proc.stdout.decode())
        self.assertEqual(payload["tool"], "bakeoff")
        self.assertEqual(set(payload["survivors"]), {"alpha-PASS", "beta-PASS"})

    def test_8q_fail_skips_ladder_marked_filtered(self):
        run_bakeoff("gamma-FILTER", self.out)
        rec = self._findings()["models"][0]
        self.assertEqual(rec["status"], "filtered")
        self.assertFalse(rec["passed_8q"])
        self.assertIsNone(rec["ladder"], "ladder must be skipped after 8Q fail")
        self.assertIn("filtered_by_8q", rec["notes"])
        self.assertIn("filtered", (self.out / "findings.md").read_text())

    def test_continue_past_failure(self):
        # Middle model's 8Q hits an infra error (exit 2); run continues.
        proc = run_bakeoff("one-PASS,two-INFRA,three-PASS", self.out)
        self.assertEqual(proc.returncode, 0)
        recs = {r["model"]: r for r in self._findings()["models"]}
        self.assertEqual(recs["one-PASS"]["status"], "ran")
        self.assertEqual(recs["two-INFRA"]["status"], "failed")
        self.assertEqual(recs["three-PASS"]["status"], "ran")
        self.assertEqual(set(self._findings()["survivors"]), {"one-PASS", "three-PASS"})

    def test_ladder_infra_marks_failed_not_fatal(self):
        proc = run_bakeoff("x-PASS-LADDERDOWN,y-PASS", self.out)
        self.assertEqual(proc.returncode, 0)
        recs = {r["model"]: r for r in self._findings()["models"]}
        self.assertEqual(recs["x-PASS-LADDERDOWN"]["status"], "failed")
        self.assertTrue(any("ladder" in n for n in recs["x-PASS-LADDERDOWN"]["notes"]))
        self.assertEqual(recs["y-PASS"]["status"], "ran")

    def test_ladder_verdict_false_still_ran_and_noted(self):
        run_bakeoff("z-PASS-LADDERFAIL", self.out)
        rec = self._findings()["models"][0]
        self.assertEqual(rec["status"], "ran")
        self.assertFalse(rec["ladder"]["verdict"])
        self.assertIn("ladder_verdict_false", rec["notes"])

    def test_screen_skip_when_no_cmd(self):
        run_bakeoff("s-PASS", self.out)  # no --screen-cmd
        rec = self._findings()["models"][0]
        self.assertIsNone(rec["screen"])
        self.assertIn("no_screen_cmd", rec["notes"])

    def test_screen_runs_when_cmd_present(self):
        tpl = "%s %s --model {model}" % (sys.executable, STUB_SCREEN)
        run_bakeoff("s2-PASS", self.out, screen_cmd=tpl)
        rec = self._findings()["models"][0]
        self.assertIsNotNone(rec["screen"])
        self.assertIn("auc", rec["screen"])

    def test_screen_unrunnable_is_null_not_crash(self):
        tpl = "%s %s --model {model}" % (sys.executable, STUB_SCREEN.parent / "does-not-exist.py")
        proc = run_bakeoff("s3-PASS", self.out, screen_cmd=tpl)
        self.assertEqual(proc.returncode, 0)
        rec = self._findings()["models"][0]
        self.assertIsNone(rec["screen"])
        self.assertTrue(any(n.startswith("screen_") for n in rec["notes"]))

    def test_zero_survivors_exit0_empty_models_and_no_survivors_text(self):
        proc = run_bakeoff("only-FILTER", self.out)
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout.decode())
        self.assertEqual(payload["survivors"], [])
        # findings.md says "no survivors"; findings.json still lists the models ran.
        self.assertIn("no survivors", (self.out / "findings.md").read_text())

    def test_findings_md_has_table_header(self):
        run_bakeoff("h-PASS", self.out)
        md = (self.out / "findings.md").read_text()
        self.assertIn("| model | status | 8Q pass | tok/s | mem_kb | screen | notes |", md)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\nPASS %d/%d (failures=%d errors=%d)"
          % (passed, result.testsRun, len(result.failures), len(result.errors)))
    sys.exit(0 if result.wasSuccessful() else 1)
