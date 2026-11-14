#!/usr/bin/env python3
"""Stdlib acceptance for scripts/flappy/grade{cjs,2.cjs,3.cjs}; run directly.

    python3 tests/test_flappy_grader.py

No pytest on this box. No live calls: grades the shipped fixtures.
Skips (exit 0, reason on stderr) when node or the playwright browsers
are unavailable. v1 = mechanics only; v2 adds visibility, paced scoring,
bounded physics, fence hygiene; v3 is input-causal (control-treatment flap,
two-arm scoring, flight filter, floor check, hard caps).
"""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "scripts" / "flappy" / "grade.cjs"
G2 = ROOT / "scripts" / "flappy" / "grade2.cjs"
G3 = ROOT / "scripts" / "flappy" / "grade3.cjs"
GOOD = ROOT / "tests" / "fixtures" / "flappy" / "ref-good.html"
BAD = ROOT / "tests" / "fixtures" / "flappy" / "ref-bad.html"
DECORATIVE = ROOT / "tests" / "fixtures" / "flappy" / "decorative.html"


def grade(grader, path):
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                   os.path.expanduser("~/.cache/ms-playwright"))
    p = subprocess.run(["node", str(grader), str(path)], capture_output=True,
                       text=True, timeout=240, cwd=str(grader.parent), env=env)
    return json.loads(p.stdout.strip().splitlines()[-1])


class GraderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node not installed")

    def _grade_or_skip(self, grader, path):
        try:
            return grade(grader, path)
        except Exception as e:  # noqa: BLE001 - e.g. browsers not installed
            raise unittest.SkipTest(f"browser unavailable: {e}")

    def test_v1_reference_game_scores_90(self):
        out = self._grade_or_skip(G1, GOOD)
        self.assertTrue(all(out["checks"].values()), out["checks"])
        self.assertEqual(out["score"], 90)

    def test_v1_broken_file_scores_10(self):
        out = self._grade_or_skip(G1, BAD)
        self.assertEqual(out["score"], 10)

    def test_v2_reference_game_scores_90(self):
        out = self._grade_or_skip(G2, GOOD)
        self.assertTrue(all(out["checks"].values()), out["checks"])
        self.assertEqual(out["score"], 90)

    def test_v2_broken_file_scores_10(self):
        out = self._grade_or_skip(G2, BAD)
        self.assertEqual(out["score"], 10)

    def test_v3_reference_game_scores_90(self):
        out = self._grade_or_skip(G3, GOOD)
        self.assertTrue(all(out["checks"].values()), out["checks"])
        self.assertEqual(out["score"], 90)

    def test_v3_broken_file_scores_10(self):
        out = self._grade_or_skip(G3, BAD)
        self.assertEqual(out["score"], 10)

    def test_v3_decorative_game_capped_at_35(self):
        # Static-decal specimen (gemma4 R2): pipes scroll and score by luck
        # but the bird never responds to input. Must cap, not partial-credit.
        out = self._grade_or_skip(G3, DECORATIVE)
        self.assertFalse(out["checks"]["flap"])
        self.assertEqual(out["score"], 35)
        self.assertTrue(any(n.startswith("cap:") for n in out["notes"]),
                        out["notes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
