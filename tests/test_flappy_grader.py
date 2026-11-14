#!/usr/bin/env python3
"""Stdlib acceptance for scripts/flappy/grade.cjs; run directly.

    python3 tests/test_flappy_grader.py

No pytest on this box. No live calls: grades the two shipped fixtures.
Skips (exit 0, reason on stderr) when node or the playwright browsers
are unavailable.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADER = ROOT / "scripts" / "flappy" / "grade.cjs"
GOOD = ROOT / "tests" / "fixtures" / "flappy" / "ref-good.html"
BAD = ROOT / "tests" / "fixtures" / "flappy" / "ref-bad.html"


def grade(path):
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                   os.path.expanduser("~/.cache/ms-playwright"))
    p = subprocess.run(["node", str(GRADER), str(path)], capture_output=True,
                       text=True, timeout=240, cwd=str(GRADER.parent), env=env)
    return json.loads(p.stdout.strip().splitlines()[-1])


class GraderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node not installed")
        if not GRADER.exists():
            raise unittest.SkipTest("grader missing")

    def test_reference_game_scores_90(self):
        try:
            out = grade(GOOD)
        except Exception as e:  # noqa: BLE001 - e.g. browsers not installed
            raise unittest.SkipTest(f"browser unavailable: {e}")
        self.assertTrue(all(out["checks"].values()), out["checks"])
        self.assertEqual(out["score"], 90)

    def test_broken_file_scores_10(self):
        try:
            out = grade(BAD)
        except Exception as e:  # noqa: BLE001
            raise unittest.SkipTest(f"browser unavailable: {e}")
        self.assertEqual(out["score"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
