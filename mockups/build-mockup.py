#!/usr/bin/env python3
"""Builds mockups/dashboard-round4b.html (static, zero-JS, no external assets).

The template lives in feedback-server.py (render_dashboard); this script renders it in
mockup mode from tests/fixtures/status-metered.json. That fixture has metering totals but
no metering_breakdown, so the per-model, per-day and per-agent panels are the tagged
Sample split of the real totals (largest-remainder, sums exact).

Two inputs are not in that fixture and come from the recorded live snapshot
(tests/fixtures/status-live-2026-10-27.json) instead: the models over 8 GB (listed in the
memory panel) and the count of models too big for the box.

Run:  python3 mockups/build-mockup.py           (writes the file)
      python3 mockups/build-mockup.py --check   (exit 1 if the committed file differs)
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "dashboard-round4b.html")


def load_server():
    spec = importlib.util.spec_from_file_location("fbserver_mockup", os.path.join(ROOT, "feedback-server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name)) as f:
        return json.load(f)


def build():
    srv = load_server()
    st = fixture("status-metered.json")
    live_models = fixture("status-live-2026-10-27.json")["models"]
    have = {m["name"] for m in st["models"]}
    oversize = [m for m in live_models if m["size_mb"] > srv.RAM_MB and m["name"] not in have]
    return srv.render_dashboard(st, mockup=True, extra_models=oversize,
                                too_big_count=len(srv.too_big(live_models)))


def main():
    html = build()
    if "--check" in sys.argv:
        with open(OUT, encoding="utf-8") as f:
            same = f.read() == html
        print("mockup matches" if same else "mockup DIFFERS from %s" % OUT)
        sys.exit(0 if same else 1)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote mockups/dashboard-round4b.html")


if __name__ == "__main__":
    main()
