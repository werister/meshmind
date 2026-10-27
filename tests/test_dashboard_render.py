#!/usr/bin/env python3
"""Fixture-based render tests for the dashboard (T4). No live Ollama needed.

Loads feedback-server.py by path (its name has a hyphen), renders
build_dashboard() against recorded /status fixtures, and asserts the
round-3 guarantees: zero-JS, no external assets, measured-vs-self-reported
kept distinct and never summed, calls feed + heatmap + streaks + eval present.

Run:  python3 tests/test_dashboard_render.py
Exit 0 = all pass; non-zero = failure (prints the first failing assertion).
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")


def load_server():
    path = os.path.join(ROOT, "feedback-server.py")
    spec = importlib.util.spec_from_file_location("fbserver", path)
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


def assert_zero_js(html):
    low = html.lower()
    check("<script" not in low, "no <script> tags")
    check("javascript:" not in low, "no javascript: urls")
    # inline event handlers like onclick=, onload=
    check(re.search(r"\son[a-z]+\s*=", low) is None, "no inline on* handlers")


def assert_no_external_assets(html):
    low = html.lower()
    check("http://" not in low and "https://" not in low, "no absolute http(s) asset urls")
    check("src=" not in low, "no src= (no external/embedded media)")
    check("@import" not in low, "no css @import")
    check("<link" not in low, "no <link> external stylesheet")


def test_metered_fixture(mod):
    st = load_fixture("status-metered.json")
    html = mod.build_dashboard(st)

    assert_zero_js(html)
    assert_no_external_assets(html)

    # Metering section present and badged measured
    check("Metered traffic" in html, "metering section heading present")
    check("badge measured" in html, "measured badge rendered")
    check("23110" in html, "metering eval_tokens_total shown")
    check("128" in html, "metering calls_total shown")

    # Self-reported clearly labeled
    check("self-declared" in html, "feedback labeled self-declared")
    check(html.count("badge declared") >= 2, "self-declared badge on reports + feedback")

    # Measured and self-reported NEVER summed into the headline.
    gt = st["tokens"]["grand_total"]
    check(gt == st["tokens"]["probe_total"] + st["tokens"]["feedback_total"],
          "grand_total is probe+feedback only (fixture invariant)")
    # The metering eval total must not have been folded into grand_total.
    check(gt != st["tokens"]["grand_total"] + st["metering"]["eval_tokens_total"],
          "metering not added to grand_total")
    check(st["metering"]["eval_tokens_total"] not in
          (gt, gt + st["metering"]["eval_tokens_total"]),
          "no accidental metering+headline sum equals headline")

    # Calls feed: rows, no-usage flag, 502 error row
    check("Recent calls" in html, "calls feed heading")
    check("kiro-spar" in html, "call row agent shown")
    check("/v1/chat/completions" in html, "call row path shown")
    check("no-usage" in html, "no_usage stream flagged in feed")
    check("502" in html, "failed call shows 502")
    check("feed" in html, "feed container class present")

    # Activity heatmap + streaks
    check("class=\"heat\"" in html, "heatmap grid present")
    check("current streak" in html, "current streak label")
    check("longest streak" in html, "longest streak label")
    # 8-day current streak from the fixture (14 days, trailing active run)
    cur, longest = mod.streaks(st["activity"]["daily"])
    check(cur == 8, "computed current streak == 8 (got %s)" % cur)
    check(longest == 8, "computed longest streak == 8 (got %s)" % longest)

    # Weekly eval summary
    check("Weekly eval" in html, "eval section heading")
    check("llama3.2:3b" in html, "eval per-model row present")
    check("2/3" in html, "eval partial-pass shown")

    # tabular numerals / no emoji-counter slop
    check("tabular-nums" in html, "tabular numerals in CSS (anti-slop)")
    for ch in "📈📊🔥✅❌🚀":
        check(ch not in html, "no emoji counter %r" % ch)

    print("  metered fixture: OK")


def test_live_fixture_graceful(mod):
    # The raw live snapshot has NO metering/calls/eval blocks -> must still render.
    st = load_fixture("status-live-2026-10-27.json")
    html = mod.build_dashboard(st)
    assert_zero_js(html)
    assert_no_external_assets(html)
    check("Lab status" in html, "live fixture renders a page")
    # metering absent -> section omitted, not crashed
    check("<h2>Metered traffic" not in html, "no metering section when block absent")
    # calls absent -> empty-feed message
    check("Recent calls" in html, "calls section still renders header")
    check("ring is empty" in html, "empty calls feed message")
    print("  live fixture (no metering): OK")


def test_streak_edges(mod):
    check(mod.streaks([]) == (0, 0), "empty streak")
    check(mod.streaks([{"count": 0}]) == (0, 0), "single zero day")
    check(mod.streaks([{"count": 1}, {"count": 0}, {"count": 2}]) == (1, 1),
          "gap breaks current streak")
    check(mod.streaks([{"count": 1}, {"count": 1}, {"count": 1}]) == (3, 3),
          "all-active streak")
    print("  streak edge cases: OK")


def main():
    mod = load_server()
    print("render tests:")
    test_metered_fixture(mod)
    test_live_fixture_graceful(mod)
    test_streak_edges(mod)
    print("ALL %d checks passed" % PASSED)


if __name__ == "__main__":
    main()
