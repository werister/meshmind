#!/usr/bin/env python3
"""Fixture-based render tests for the round-4b dashboard. No live Ollama, no network.

Loads feedback-server.py by path (its name has a hyphen), renders build_dashboard()
against recorded /status fixtures, and asserts: zero-JS, no external assets, measured vs
self-reported never summed, Sample/Measured labeling honest, exact sums, graceful empty
and degraded states, escaping, and that the mockup builder still reproduces the committed
mockups/dashboard-round4b.html byte for byte.

Run:  python3 tests/test_dashboard_render.py
Exit 0 = all pass; non-zero = failure (prints the first failing assertion).
"""
import copy
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")


def load_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_server():
    return load_path("fbserver", os.path.join(ROOT, "feedback-server.py"))


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
    check(re.search(r"\son[a-z]+\s*=", low) is None, "no inline on* handlers")


def assert_no_external_assets(html):
    low = html.lower()
    check("http://" not in low and "https://" not in low, "no absolute http(s) urls")
    check("src=" not in low, "no src= (no external/embedded media)")
    check("@import" not in low, "no css @import")
    check("<link" not in low, "no <link> external stylesheet")


def assert_bars(html):
    """The taste / ui-ux-pro-max bars that must hold on every render."""
    check("tabular-nums" in html, "tabular numerals")
    check("prefers-reduced-motion:reduce" in html, "reduced motion respected")
    check("prefers-color-scheme:dark" in html, "dark mode tokens")
    check(":focus-visible" in html, "focus-visible styles")
    check('name="viewport"' in html, "viewport meta")
    check("gradient" not in html.lower(), "no gradients")
    for ch in "📈📊🔥✅❌🚀":
        check(ch not in html, "no emoji counter %r" % ch)


def chip_count(html, kind):
    return html.count('class="chip chip-%s"' % kind)


def test_mockup_regression(mod):
    builder = load_path("build_mockup", os.path.join(ROOT, "mockups", "build-mockup.py"))
    with open(os.path.join(ROOT, "mockups", "dashboard-round4b.html"), encoding="utf-8") as f:
        committed = f.read()
    check(builder.build() == committed, "fixture rebuilds byte-identical to mockups/dashboard-round4b.html")
    with open(os.path.join(ROOT, "mockups", "round4b.css"), encoding="utf-8") as f:
        check(f.read() == mod.CSS, "server CSS is the committed round4b.css, unchanged")
    print("  mockup regression (byte-identical): OK")


def test_metered_fixture(mod):
    st = load_fixture("status-metered.json")
    html = mod.build_dashboard(st)
    assert_zero_js(html)
    assert_no_external_assets(html)
    assert_bars(html)

    check("<title>Lab status · Local AI Lab</title>" in html, "live title")
    check('http-equiv="refresh" content="30"' in html, "auto refresh kept")
    check(">Lab status</h1>" in html, "page has an h1")
    check("Mockup from a recorded fixture" not in html, "no mockup notice on the live page")

    # headline numbers, each with its own provenance tag
    check("23,110" in html and "9,640" in html and ">128<" in html, "measured totals shown")
    check(chip_count(html, "measured") >= 1, "measured tag on the lead figure")
    check(chip_count(html, "declared") >= 2, "self-declared on agent reports and the X-Agent column")
    check(chip_count(html, "est") >= 2, "estimated tag on cost figures")
    check(">445<" in html and "7 reports" in html, "self-reported tokens shown on their own")

    # never summed: no cross-source total may appear anywhere in DATA-DRIVEN
    # content. The static SVG sprite (logo path coordinates) is excluded: it is
    # fixed art, not computed output, and digit runs in path data are not sums.
    page = re.sub(r'<svg width="0" height="0".*?</defs></svg>', "", html, flags=re.S)
    t, m = st["tokens"], st["metering"]
    for bad in (t["grand_total"], m["eval_tokens_total"] + t["feedback_total"],
                m["eval_tokens_total"] + t["probe_total"], m["eval_tokens_total"] + t["grand_total"]):
        check("{:,}".format(bad) not in page and ">%d<" % bad not in page, "no mixed-source sum %d on the page" % bad)

    # no breakdown in this snapshot -> the per-model panels are honest Samples
    check(chip_count(html, "sample") == 2, "both split panels tagged Sample")
    check("this snapshot has no per-model metering" in html, "sample provenance note")

    # failures and unmetered from data
    check("1 failed</span> · 4 without usage" in html, "KPI failure/unmetered counts from data")
    check("4 streams without usage · 1 failed (502) · not counted" in html, "flow leak line from data")
    check("Failed 502" in html and "No usage" in html, "call results labeled in words")
    check("kiro-spar" in html and "llama3.2:3b" in html, "call rows rendered")

    # activity, eval, memory
    check('class="hc num' in html and ">8</b>" in html, "activity grid and streak")
    check("Weekly eval" in html and "2/3" in html, "eval rows")
    check("379 MB" in html and "Loaded" in html, "memory ring from loaded models")
    print("  metered fixture (sample split): OK")


def test_sample_split_is_exact(mod):
    st = load_fixture("status-metered.json")
    for total in (0, 1, 7, 10007, 23110, 987654):
        s = copy.deepcopy(st)
        s["metering"]["eval_tokens_total"] = total
        mix = mod.token_mix(s)
        check(sum(x[2] for x in mix["models"]) == total, "sample models sum to %d" % total)
        check(sum(a[1] for a in mix["agents"]) == total, "sample agents sum to %d" % total)
        for (name, _, tok, _, _), row in zip(mix["models"], mix["rows"]):
            check(sum(row) == tok and min(row) >= 0, "sample day row of %s sums to its total (%d)" % (name, total))
    check(mod.largest_remainder(10, [1, 1, 1]) == [4, 3, 3], "largest remainder tie-break is stable")
    print("  sample split exact (largest remainder): OK")


def test_breakdown_fixture(mod):
    st = load_fixture("status-breakdown.json")
    bd = st["metering_breakdown"]
    html = mod.build_dashboard(st)
    assert_zero_js(html)
    assert_no_external_assets(html)
    assert_bars(html)

    check(chip_count(html, "sample") == 0, "no Sample tag once real rollups exist")
    check(chip_count(html, "measured") >= 3, "per-model and flow panels tagged Measured")
    total = sum(r["eval_tokens"] for r in bd["per_model"])
    check("Counted since 2026-10-21: %s of 23,110 generated tokens" % "{:,}".format(total) in html,
          "since-note when rollups cover less than the lifetime total")

    mix = mod.token_mix(st)
    check(mix["total"] == total, "mix total equals per-model sum")
    check(sum(a[1] for a in mix["agents"]) == total, "agent flow sums to the model flow")
    check([x[0] for x in mix["models"]][:4] == [r["model"] for r in bd["per_model"][:4]], "top four models in order")
    check(mix["models"][-1][0] == "phi4-mini:latest + 1 more", "tail bucketed as + N more")
    for (_, _, tok, _, _), row in zip(mix["models"], mix["rows"]):
        check(sum(row) == tok, "daily by_model columns sum to the model total")
    check(mix["agents"][-1][0] == "2 more", "agents past four bucketed")

    check("2 failed</span> · 4 without usage" in html, "KPI failures from the rollup")
    check("2 streams without usage · 2 failed (502, 503) · not counted" in html, "leak line from the rollup")
    check(">5,930<" in html or "5,930" in html, "real per-model figure shown")
    print("  breakdown fixture (real rollups): OK")


def test_live_fixture_graceful(mod):
    st = load_fixture("status-live-2026-10-27.json")  # no metering/calls/eval blocks
    html = mod.build_dashboard(st)
    assert_zero_js(html)
    assert_no_external_assets(html)
    check(">Lab status</h1>" in html, "live fixture renders a page")
    check("proxy metering not reporting" in html, "absent metering shown as not reporting, not zero")
    check(chip_count(html, "sample") == 0, "no Sample panels without a total to split")
    check("ring is empty" in html, "empty calls message")
    check("No weekly eval run recorded yet." in html, "empty eval state")
    check("No daily probe history" in html, "empty activity state")
    check("2 too big for this box" in html, "policy and oversize models counted from the model list")
    check("Too big" in html, "oversize model flagged in words")
    print("  live fixture (no metering): OK")


def test_degraded_and_escaping(mod):
    st = load_fixture("status-breakdown.json")
    st["health"]["serve"] = "FAIL"
    for mdl in st["models"]:
        mdl["loaded"] = False
    st["eval"] = None
    evil = '<script>alert("x")</script>'
    st["calls"][0]["agent"] = evil
    st["calls"][0]["model"] = evil
    st["metering_breakdown"]["per_agent"][0]["agent"] = evil
    st["metering_breakdown"]["per_model"][0]["model"] = evil
    html = mod.build_dashboard(st)
    assert_zero_js(html)
    check("Degraded" in html and "Operational" not in html, "degraded status in words")
    check("Nothing loaded" in html, "empty memory state")
    check("&lt;script&gt;" in html, "caller-controlled names are escaped")
    print("  degraded + escaping: OK")


def test_streak_edges(mod):
    check(mod.streaks([]) == (0, 0), "empty streak")
    check(mod.streaks([{"count": 0}]) == (0, 0), "single zero day")
    check(mod.streaks([{"count": 1}, {"count": 0}, {"count": 2}]) == (1, 1), "gap breaks current streak")
    check(mod.streaks([{"count": 1}, {"count": 1}, {"count": 1}]) == (3, 3), "all-active streak")
    cur, longest = mod.streaks(load_fixture("status-metered.json")["activity"]["daily"])
    check((cur, longest) == (8, 8), "fixture streaks 8/8")
    print("  streak edge cases: OK")


def main():
    mod = load_server()
    print("render tests:")
    test_mockup_regression(mod)
    test_metered_fixture(mod)
    test_sample_split_is_exact(mod)
    test_breakdown_fixture(mod)
    test_live_fixture_graceful(mod)
    test_degraded_and_escaping(mod)
    test_streak_edges(mod)
    print("ALL %d checks passed" % PASSED)


if __name__ == "__main__":
    main()
