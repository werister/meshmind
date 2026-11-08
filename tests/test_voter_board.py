#!/usr/bin/env python3
"""Fixture-based tests for the dashboard model-comparison section. No live Ollama.

Figure definitions (one sentence each):
- Easy/Hard render the snapshot lane's "p/t" pass counts verbatim (no computation).
- Pairs W-L-T counts opponents beaten head-to-head: a pair is won with more
  questions right (wa>wb as a, wb>wa as b), tied when equal; models with no
  pairs render an unscored dash, never 0-0-0.
- ms/q and tok/q are the snapshot's means per question over the lane's scored
  questions, rounded to int with round().
- Lanes render in snapshot order (the writer's order, never re-sorted).

Forbidden combinations (never rendered): cross-lane averages or totals (lanes
have different n), and comparison figures added to live metering totals.

Run:  python3 tests/test_voter_board.py
Exit 0 = all pass; non-zero = failure (prints the first failing assertion).
"""
import importlib.util
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")


def load_server():
    spec = importlib.util.spec_from_file_location(
        "fbserver", os.path.join(ROOT, "feedback-server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


PASSED = 0


def check(cond, msg):
    global PASSED
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    PASSED += 1


def st_with(name, filt=None):
    mod = load_server()
    st = load_fixture("status-metered.json")
    st["comparisons"] = mod.read_comparisons(os.path.join(FIX, name))
    st["cmp_filter"] = filt if filt is not None else {"family": None, "lane": None}
    return mod, st


def test_read_comparisons(mod):
    check(mod.read_comparisons(os.path.join(FIX, "voter-board-nope.json")) is None,
          "missing snapshot file -> None")
    c = mod.read_comparisons(os.path.join(FIX, "voter-board-present.json"))
    check(c["version"] == 1 and c["date"] == "2026-11-05", "snapshot version/date kept")
    check(c["easy_n"] == 20 and c["hard_n"] == 10, "lane sizes kept")
    check(len(c["lanes"]) == 8, "8 lanes loaded")
    first = c["lanes"][0]
    check(first["model"] == "qwen3:4b", "first lane model")
    check(first["easy"] == (17, 20) and first["hard"] == (6, 10), "first lane scores")
    check(first["ms"] == 18432.6 and first["tok"] == 312.4, "first lane means")
    check(len(c["pairs"]) == 28, "all 28 pairs loaded")
    check(c["note"].startswith("SYNTHETIC fixture"), "snapshot note kept")

    m = mod.read_comparisons(os.path.join(FIX, "voter-board-mismatch.json"))
    check(m.get("mismatch") is True and m.get("version") == 99 and m.get("expected") == 1,
          "schema mismatch flagged with both versions")

    p = mod.read_comparisons(os.path.join(FIX, "voter-board-partial.json"))
    by_model = {lane["model"]: lane for lane in p["lanes"]}
    check(by_model["llama3.2:3b"]["hard"] is None, "missing hard block -> None")
    check(by_model["llama3.2:3b"]["ms"] is None and by_model["llama3.2:3b"]["tok"] is None,
          "missing means -> None")
    check(by_model["llama3.2:3b"]["easy"] == (15, 20), "present easy block kept")
    check(by_model["gemma2:2b"]["ms"] is None and by_model["gemma2:2b"]["tok"] == 141.7,
          "partial means kept independently")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write("{nope")
        tmp = f.name
    try:
        bad = mod.read_comparisons(tmp)
        check(bad.get("unparseable") is True, "corrupt snapshot -> unparseable, not a crash")
    finally:
        os.unlink(tmp)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"version": 1, "lanes": "nope", "pairs": {}}, f)
        tmp = f.name
    try:
        wrong = mod.read_comparisons(tmp)
        check(wrong["lanes"] == [] and wrong["pairs"] == [], "wrong-typed blocks -> empty, not a crash")
    finally:
        os.unlink(tmp)
    print("  read_comparisons: OK")


def test_parse_cmp_filter(mod):
    check(mod.parse_cmp_filter({}) == {"family": None, "lane": None}, "empty query -> no filter")
    check(mod.parse_cmp_filter({"family": ["QWEN "], "lane": ["easy"]}) == {"family": "qwen", "lane": "easy"},
          "family lowercased/trimmed, lane easy kept")
    check(mod.parse_cmp_filter({"lane": ["bogus"]}) == {"family": None, "lane": None},
          "unknown lane ignored")
    check(mod.parse_cmp_filter({"family": [""]}) == {"family": None, "lane": None},
          "empty family ignored")
    print("  parse_cmp_filter: OK")


def test_section_absent_without_snapshot(mod):
    st = load_fixture("status-metered.json")
    html = mod.build_dashboard(st)
    check('id="h-cmp"' not in html, "no comparison section without a snapshot")
    check(html.count('class="chip chip-sample"') == 2, "old chip counts unchanged")
    print("  absent without snapshot: OK")


def test_present_renders(mod):
    mod, st = st_with("voter-board-present.json")
    html = mod.build_dashboard(st)
    low = html.lower()
    check("<script" not in low and "javascript:" not in low, "comparison render is zero-JS")
    check("http://" not in low and "https://" not in low, "no absolute urls from comparison render")
    check("tabular-nums" in html and "prefers-color-scheme:dark" in html, "taste bars hold")
    check('id="h-cmp"' in html and "Model comparisons" in html, "comparison heading")
    check("Recorded 2026-11-05" in html, "staleness date shown")
    check("Snapshot note: SYNTHETIC fixture" in html, "snapshot note rendered")
    check("n=30 (easy 20 + hard 10)" in html, "staleness n shown")
    check("qwen3:4b" in html and "17/20" in html and "6/10" in html, "lane pass counts verbatim")
    check("18,433" in html, "ms/q mean rounded to int")
    check(">312<" in html, "tok/q mean rounded to int")
    check("6&ndash;0&ndash;1" in html or "6–0–1" in html, "qwen3 pair record 6-0-1")
    sec = html.split('id="h-cmp"')[1]
    check(sec.index("qwen3:4b") < sec.index("llama3.2:3b"), "snapshot order kept, never re-sorted")
    print("  present snapshot renders: OK")


def test_forbidden_combos(mod):
    mod, st = st_with("voter-board-present.json")
    html = mod.build_dashboard(st)
    check(">Average<" not in html and ">Total<" not in html, "no summary row over lanes")
    check("24,071" not in html and "24070" not in html, "no cross-lane mean of ms/q")
    check("23,217" not in html, "comparison passes never added to metering totals")
    print("  forbidden combinations absent: OK")


def test_states(mod):
    st = load_fixture("status-metered.json")
    st["comparisons"] = None
    st["cmp_filter"] = {"family": None, "lane": None}
    html = mod.build_dashboard(st)
    check('id="h-cmp"' in html, "missing snapshot still renders the heading")
    check("No comparison snapshot yet" in html, "missing snapshot says so")

    mod2, stm = st_with("voter-board-mismatch.json")
    html = mod2.build_dashboard(stm)
    check("snapshot v99" in html and "reader expects v1" in html, "mismatch names both versions")

    mod3, stp = st_with("voter-board-partial.json")
    html = mod3.build_dashboard(stp)
    check("15/20" in html, "partial snapshot keeps present cells")
    check("0/10" not in html, "missing cells never render as losses")
    check("—" in html, "missing cells render as unscored dashes")
    print("  missing/mismatch/partial states: OK")


def test_escaping(mod):
    mod, st = st_with("voter-board-evil.json")
    html = mod.build_dashboard(st)
    low = html.lower()
    check("<script" not in low, "evil snapshot strings escaped")
    check("&lt;script&gt;" in html, "evil content visible-escaped, not dropped")
    print("  evil snapshot escaped: OK")


def test_family_filter(mod):
    mod, st = st_with("voter-board-present.json", {"family": "qwen", "lane": None})
    html = mod.build_dashboard(st)
    sec = html.split('id="h-cmp"')[1]  # other panels name models too; scope to ours
    for keep in ("qwen3:4b", "qwen2.5:0.5b", "qwen2.5-coder:3b"):
        check(keep in sec, "qwen filter keeps %s" % keep)
    for drop in ("llama3.2:3b", "gemma2:2b", "phi4-mini:latest", "gemma3:4b", "granite4.2:3b"):
        check(drop not in sec, "qwen filter drops %s" % drop)
    check("family=qwen" in html and "lane=easy" in html, "filter links offered")
    m = re.search(r'href="([^"]*lane=easy[^"]*)"', html)
    check(m and "family=qwen" in m.group(1), "lane link preserves the family filter")

    mod, st = st_with("voter-board-present.json", {"family": "nvidia", "lane": None})
    html = mod.build_dashboard(st)
    check("No lanes match family=nvidia" in html, "known-but-absent family says so")
    check('href="/dashboard"' in html, "zero-match offers a clear-filters link")

    mod, st = st_with("voter-board-present.json", {"family": "zz9", "lane": None})
    html = mod.build_dashboard(st)
    check("llama3.2:3b" in html and "gemma3:4b" in html, "unknown family ignored, all lanes render")
    check('Unknown family "zz9"' in html, "unknown family named in a note")
    print("  family filter: OK")


def test_lane_filter(mod):
    mod, st = st_with("voter-board-present.json", {"family": None, "lane": "easy"})
    html = mod.build_dashboard(st)
    sec = html.split('id="h-cmp"')[1]
    check(">Easy</th>" in sec and ">Hard</th>" not in sec, "lane=easy shows only the Easy column")
    check("17/20" in sec and "ms/q" in sec, "lane-level means stay with a lane filter")

    mod, st = st_with("voter-board-present.json", {"family": None, "lane": "hard"})
    html = mod.build_dashboard(st)
    sec = html.split('id="h-cmp"')[1]
    check(">Hard</th>" in sec and ">Easy</th>" not in sec, "lane=hard shows only the Hard column")
    print("  lane filter: OK")


def main():
    mod = load_server()
    print("voter-board tests:")
    test_read_comparisons(mod)
    test_parse_cmp_filter(mod)
    test_section_absent_without_snapshot(mod)
    test_present_renders(mod)
    test_forbidden_combos(mod)
    test_states(mod)
    test_escaping(mod)
    test_family_filter(mod)
    test_lane_filter(mod)
    print("ALL %d checks passed" % PASSED)


if __name__ == "__main__":
    main()
