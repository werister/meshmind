#!/usr/bin/env python3
"""Unit tests for the metering rollups (metering-aggregates.json). Stdlib only, no network.

Drives _record_call() directly against a temp METER_DIR, so the same code path the proxy
uses bumps the state file. Run:  python3 tests/test_metering_aggregates.py
"""
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_server(meter_dir):
    spec = importlib.util.spec_from_file_location("fbserver_agg", os.path.join(ROOT, "feedback-server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.METER_DIR = meter_dir
    mod.CALLS = os.path.join(meter_dir, "calls.log")
    mod.PROXY_TOTAL = os.path.join(meter_dir, "proxy-token-total")
    mod.METER_AGG = os.path.join(meter_dir, "metering-aggregates.json")
    mod.CALLS_RING.clear()
    return mod


def jload(path):
    with open(path) as f:
        return json.load(f)


def call(day, model="qwen3:4b", agent="kiro-spar", prompt=10, out=20, ok=True, status=200, **kw):
    c = {"ts": "%sT10:00:00+00:00" % day, "path": "/api/chat", "status": status, "agent": agent, "model": model,
         "prompt_tokens": prompt, "eval_tokens": out, "ok": ok, "stream": False, "partial": False, "truncated": False}
    c.update(kw)
    return c


class Aggregates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agg-test-")
        self.mod = load_server(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def bd(self, today="2026-10-27"):
        return self.mod.metering_breakdown(today=date.fromisoformat(today))

    def test_per_model_agent_daily_and_failures(self):
        rec = self.mod._record_call
        rec(call("2026-10-27"))
        rec(call("2026-10-27", model="llama3.2:3b", agent="codex-spar", prompt=5, out=7))
        rec(call("2026-10-27", out=None, no_usage=True))                                 # null: counted, not summed
        rec(call("2026-10-26", model="gemma2:2b", prompt=3, out=0, ok=False, status=502))
        rec(call("2026-10-26", ok=False, status=200, partial=True, out=4))                # client hang-up: not a failure
        b = self.bd()
        pm = {r["model"]: r for r in b["per_model"]}
        self.assertEqual(pm["qwen3:4b"], {"model": "qwen3:4b", "calls": 3, "prompt_tokens": 30,
                                          "eval_tokens": 24, "failed": 0, "no_usage": 1})
        self.assertEqual(pm["gemma2:2b"]["failed"], 1)
        self.assertEqual([r["model"] for r in b["per_model"]][0], "qwen3:4b")  # sorted by eval desc
        pa = {r["agent"]: r for r in b["per_agent"]}
        self.assertEqual((pa["kiro-spar"]["calls"], pa["codex-spar"]["eval_tokens"]), (4, 7))
        self.assertEqual(b["failures"], {"total": 1, "by_status": {"502": 1}})
        self.assertEqual(len(b["daily"]), 14)
        self.assertEqual((b["daily"][0]["date"], b["daily"][-1]["date"]), ("2026-10-14", "2026-10-27"))
        today, yday = b["daily"][-1], b["daily"][-2]
        self.assertEqual((today["calls"], today["eval_tokens"], today["no_usage"]), (3, 27, 1))
        self.assertEqual(today["by_model"], {"llama3.2:3b": 7, "qwen3:4b": 20})
        self.assertEqual((yday["failed"], yday["eval_tokens"]), (1, 4))
        self.assertTrue(all(d["calls"] == 0 for d in b["daily"][:-2]), "missing days are zero-filled")
        # the rollups agree with each other and with the cumulative total for this run
        total = jload((self.mod.PROXY_TOTAL))["eval_tokens_total"]
        self.assertEqual(sum(r["eval_tokens"] for r in b["per_model"]), total)
        self.assertEqual(sum(r["eval_tokens"] for r in b["per_agent"]), total)
        self.assertEqual(sum(d["eval_tokens"] for d in b["daily"]), total)
        self.assertEqual(b["since"], "2026-10-27T10:00:00+00:00")
        self.assertEqual(len(self.mod.CALLS_RING), 5)

    def test_daily_prunes_past_fourteen_days(self):
        for day in ("2026-10-01", "2026-10-13", "2026-10-14", "2026-10-27"):
            self.mod._record_call(call(day))
        stored = jload((self.mod.METER_AGG))["daily"]
        self.assertEqual(sorted(stored), ["2026-10-14", "2026-10-27"])
        b = self.bd()
        self.assertEqual(sum(d["calls"] for d in b["daily"]), 2)
        self.assertEqual({r["model"]: r["calls"] for r in b["per_model"]}["qwen3:4b"], 4, "totals keep pruned days")

    def test_caller_controlled_keys_are_capped(self):
        for i in range(self.mod.AGG_MAX_KEYS + 10):
            self.mod._record_call(call("2026-10-27", agent="agent-%03d" % i, model="model-%03d" % i))
        b = self.bd()
        self.assertEqual(len(b["per_agent"]), self.mod.AGG_MAX_KEYS + 1)
        self.assertEqual({r["agent"]: r["calls"] for r in b["per_agent"]}[self.mod.AGG_OTHER], 10)
        self.assertEqual(len(b["per_model"]), self.mod.AGG_MAX_KEYS + 1)

    def test_rotation_never_moves_rollups_backward(self):
        self.mod.CALLS_MAX = 300
        for _ in range(12):
            self.mod._record_call(call("2026-10-27"))
        self.assertTrue(os.path.exists(self.mod.CALLS + ".1"), "calls.log rotated")
        open(self.mod.CALLS, "w").close()  # even an emptied ledger does not touch the rollups
        self.mod._record_call(call("2026-10-27"))
        b = self.bd()
        self.assertEqual(b["per_model"][0]["calls"], 13)
        self.assertEqual(b["daily"][-1]["eval_tokens"], 13 * 20)

    def test_state_file_is_atomic_json_and_corruption_fails_open(self):
        self.mod._record_call(call("2026-10-27"))
        self.assertEqual(jload((self.mod.METER_AGG))["version"], 1)
        self.assertEqual([f for f in os.listdir(self.tmp.name) if f.startswith("metering-aggregates.json.")], [],
                         "no temp files left behind")
        with open(self.mod.METER_AGG, "w") as f:
            f.write("{not json")
        self.mod._record_call(call("2026-10-27"))  # must not raise, ring still grows
        self.assertEqual(len(self.mod.CALLS_RING), 2)
        self.assertEqual(self.bd()["per_model"][0]["calls"], 1, "corrupt file restarts the rollup, never crashes")

    def test_status_blocks_unchanged_and_breakdown_added(self):
        st = jload((os.path.join(ROOT, "tests", "fixtures", "status-breakdown.json")))
        base = jload((os.path.join(ROOT, "tests", "fixtures", "status-metered.json")))
        for key in base:
            self.assertEqual(st[key], base[key], "block %s identical" % key)
        self.assertEqual(set(st) - set(base), {"metering_breakdown"})
        self.assertEqual(set(st["metering_breakdown"]), set(self.bd()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
