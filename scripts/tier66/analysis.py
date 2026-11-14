#!/usr/bin/env python3
"""Mechanical analysis for the local-voter eval (stdlib only). Re-derives every number from transcripts.

Parse rule (pre-registered, applied uniformly): strip; if '</think>' present keep text after the LAST one;
strip quotes/whitespace; first alphanumeric token uppercased: YES->yes, NO->no, else unparseable.
Empty response -> unparseable(empty). Unparseable (incl '?' and empty) counts WRONG, never skipped.
Transport errors (no answer) are excluded from accuracy n and reported separately.
Wilson intervals imported (not copied) from the repo: scripts/baseline_replay.py::wilson.
"""
from __future__ import annotations

"""Provenance: built 2026-11-03/04 during the Nov 13-14 lab campaign (66-item voter harness (moved from eval-local-voters-2026-11-03 scratch));
landed in meshmind via feat/nov13-benchmarks. Lab: CPU-only Ollama Mini."""
import glob, importlib.util, json, math, os, statistics, sys
from collections import Counter

EV = "/Volumes/AthenaSSD/dev/improvement-20261030/eval-local-voters-2026-11-03"
WT = "/Volumes/AthenaSSD/dev/improvement-20261030/mml-stack-eval-2ed44b7"
spec = importlib.util.spec_from_file_location("bl_replay", WT + "/scripts/baseline_replay.py")
bl = importlib.util.module_from_spec(spec); spec.loader.exec_module(bl)
wilson = bl.wilson  # noqa: F841 (repo function, imported not copied)
Z95, Z80 = 1.959963984540054, 0.8416212335729143

def parse_vote(raw):
    if raw and "</think>" in raw: raw = raw.rsplit("</think>", 1)[1]
    t = (raw or "").strip().strip("'\"").strip()
    if not t: return "unparseable", True
    tok = "".join(ch for ch in t.split()[0] if ch.isalnum()).upper()
    if tok == "YES": return "yes", False
    if tok == "NO": return "no", False
    return "unparseable", False

def load(path):
    recs = []
    for line in open(path):
        line = line.strip()
        if line: recs.append(json.loads(line))
    return recs

def pct(c, n): return 100.0 * c / n if n else 0.0

def wils(c, n):
    w = wilson(c, n)
    return (w[0] * 100, w[1] * 100) if w else (0.0, 0.0)

def maj_label(votes):  # votes: parsed labels incl unparseable; strict majority of decided, else abstain
    c = Counter(v for v in votes if v in ("yes", "no"))
    if not c: return "abstain"
    top = c.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]: return "abstain"
    return top[0][0]

def summarize(name, recs):
    oks = [r for r in recs if r.get("status") == "ok"]
    terr = [r for r in recs if r.get("status") == "transport_error"]
    for r in oks:
        v, empty = parse_vote(r.get("response_raw", ""))
        r["_vote"], r["_empty"] = v, empty
        r["_correct"] = v == r.get("label")
    n = len(oks); c = sum(1 for r in oks if r["_correct"])
    unp = sum(1 for r in oks if r["_vote"] == "unparseable")
    emp = sum(1 for r in oks if r["_empty"])
    by_item = {}
    for r in oks: by_item.setdefault(r["item_id"], []).append(r)
    agree = sum(1 for v in by_item.values()
                if len(v) == 3 and len({x["_vote"] for x in v}) == 1)
    agree_n = sum(1 for v in by_item.values() if len(v) == 3)
    toks = sorted(r["eval_count"] for r in oks if isinstance(r.get("eval_count"), int))
    walls = sorted(r["wall_ms"] / 1000.0 for r in oks if r.get("wall_ms") is not None)
    first_wall = oks[0]["wall_ms"] / 1000.0 if oks and oks[0].get("wall_ms") else None
    rest = walls[1:] if len(walls) > 1 else []
    tiers = {}
    for t in (1, 2, 3):
        tr = [r for r in oks if r.get("tier") == t]
        cc = sum(1 for r in tr if r["_correct"])
        tiers[t] = (cc, len(tr))
    return {"name": name, "n_ok": n, "n_terr": len(terr), "correct": c,
            "acc": pct(c, n), "wilson": wils(c, n), "unparseable": unp,
            "empty": emp, "agree": agree, "agree_n": agree_n,
            "tok_mean": statistics.mean(toks) if toks else 0,
            "tok_p50": statistics.median(toks) if toks else 0,
            "tok_p90": toks[int(0.9 * (len(toks) - 1))] if toks else 0,
            "wall_first": first_wall, "wall_med_rest": statistics.median(rest) if rest else 0,
            "wall_med": statistics.median(walls) if walls else 0,
            "wall_p90": walls[int(0.9 * (len(walls) - 1))] if walls else 0,
            "tiers": tiers, "by_item": by_item, "oks": oks}

def diff_ci(c1, n1, c2, n2):
    if not n1 or not n2: return (0, 0, 0)
    p1, p2 = c1 / n1, c2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return (p1 - p2, p1 - p2 - Z95 * se, p1 - p2 + Z95 * se)

def power_n(p1, p2, alpha=0.05, power=0.8):
    if abs(p1 - p2) < 1e-9: return float("inf")
    za, zb = Z95, Z80
    pb = (p1 + p2) / 2
    return ((za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / ((p1 - p2) ** 2)

def main():
    cfgs = {}
    for path in sorted(glob.glob(EV + "/transcripts/voters-*.jsonl") + glob.glob(EV + "/transcripts/retest-*.jsonl")
                       + glob.glob(EV + "/transcripts/think*.jsonl") + glob.glob(EV + "/transcripts/xcheck-*.jsonl")):
        slug = os.path.basename(path)[:-len(".jsonl")]
        cfgs[slug] = summarize(slug, load(path))
    out = {"configs": {}}
    print("=" * 100); print("PER-CONFIG ACCURACY (unparseable incl '?' and empty count WRONG)")
    print("slug  n_ok terr  acc%  wilson95  unp emp agree3  tokmean|p50|p90  wall_first|med|p90(s)")
    for slug, s in cfgs.items():
        lo, hi = s["wilson"]
        print("%-28s %3d %4d %5.1f [%5.1f,%5.1f] %3d %3d %3d/%-3d %6.1f|%4.0f|%4.0f  %6.1f|%5.1f|%6.1f" % (
            slug, s["n_ok"], s["n_terr"], s["acc"], lo, hi, s["unparseable"], s["empty"],
            s["agree"], s["agree_n"], s["tok_mean"], s["tok_p50"], s["tok_p90"],
            s["wall_first"] or -1, s["wall_med"], s["wall_p90"]))
        out["configs"][slug] = {k: s[k] for k in ("n_ok", "n_terr", "correct", "acc", "wilson",
            "unparseable", "empty", "agree", "agree_n", "tok_mean", "tok_p50", "tok_p90",
            "wall_first", "wall_med_rest", "wall_med", "wall_p90") if k in s}
        out["configs"][slug]["tiers"] = {str(t): {"c": v[0], "n": v[1], "wilson": wils(v[0], v[1])}
                                         for t, v in s["tiers"].items()}
    # baselines + ensembles on voter majority labels
    voters = [cfgs[k] for k in cfgs if k.startswith("voters-")]
    items = sorted({i for s in voters for i in s["by_item"]})
    mlabels = {s["name"]: {i: maj_label([r["_vote"] for r in s["by_item"].get(i, [])]) for i in items} for s in voters}
    truth = {}
    for s in voters:
        for i, rs in s["by_item"].items(): truth[i] = rs[0]["label"]
    def ens_acc(mnames):
        cc, n = 0, 0
        for i in items:
            vv = [mlabels[m][i] for m in mnames if mlabels[m][i] in ("yes", "no")]
            if not vv: continue
            n += 1
            c = Counter(vv).most_common()
            lab = c[0][0] if not (len(c) > 1 and c[0][1] == c[1][1]) else "abstain"
            if lab == truth[i]: cc += 1
        return cc, n
    print("=" * 100); print("BASELINES + ENSEMBLES (per-item majority labels, n=%d items)" % len(items))
    print("always-yes: 33/66 = 50.0%% wilson=%s" % (wils(33, 66),))
    pre = ["voters-gemma3-4b", "voters-phi4mini", "voters-qwen25-3b"]
    pre = [m for m in pre if m in mlabels]
    cc, n = ens_acc(pre)
    print("prereg-ensemble %s: %d/%d = %.1f%% wilson=[%.1f,%.1f]" % (pre, cc, n, pct(cc, n), *wils(cc, n)))
    top3 = sorted([s["name"] for s in voters], key=lambda m: cfgs[m]["acc"], reverse=True)[:3]
    cc3, n3 = ens_acc(top3)
    print("exploratory top3 %s: %d/%d = %.1f%% wilson=[%.1f,%.1f]" % (top3, cc3, n3, pct(cc3, n3), *wils(cc3, n3)))
    out["ensembles"] = {"prereg": {"models": pre, "c": cc, "n": n},
                        "top3": {"models": top3, "c": cc3, "n": n3}}
    # pairwise disagreement
    print("=" * 100); print("PAIRWISE DISAGREEMENT (voter majority labels)")
    pairs = []
    names = sorted(mlabels)
    for x in range(len(names)):
        for y in range(x + 1, len(names)):
            a, b = names[x], names[y]
            comp = [i for i in items if mlabels[a][i] in ("yes", "no") and mlabels[b][i] in ("yes", "no")]
            dis = [i for i in comp if mlabels[a][i] != mlabels[b][i]]
            a_right = sum(1 for i in dis if mlabels[a][i] == truth[i])
            yes_given = sum(1 for i in dis if truth[i] == "yes")
            print("%-22s vs %-22s dis=%d/%d=%.1f%% A-right=%d/%d P(yes|dis)=%d/%d=%.2f" % (
                a, b, len(dis), len(comp), pct(len(dis), len(comp)), a_right, len(dis) or 1,
                yes_given, len(dis) or 1, yes_given / (len(dis) or 1)))
            pairs.append({"a": a, "b": b, "dis": len(dis), "comp": len(comp),
                          "a_right": a_right, "yes_given_dis": yes_given})
    out["pairs"] = pairs
    # retest diffs
    print("=" * 100); print("RETEST PAIR DIFFS (new - old, 95% CI)")
    for new, old, pname in [("retest-qwen3-instruct2507", "voters-qwen25-3b", "qwen2.5:3b->qwen3-2507-instruct"),
                            ("retest-phi35", "voters-phi4mini", "phi3.5->phi4-mini"),
                            ("retest-granite-microh", "voters-granite42", "granite-micro-h->granite4.2:3b")]:
        if new in cfgs and old in cfgs:
            A, B = cfgs[new], cfgs[old]
            d, lo, hi = diff_ci(A["correct"], A["n_ok"], B["correct"], B["n_ok"])
            print("%s: %.1f%% - %.1f%% = %+.1fpp CI [%+.1f,%+.1f] %s" % (
                pname, A["acc"], B["acc"], d * 100, lo * 100, hi * 100,
                "SIGNIFICANT" if (lo > 0 or hi < 0) else "not significant"))
    # v1 agreement
    print("=" * 100); print("V1-vs-NATIVE AGREEMENT (xcheck, parsed votes)")
    for m in ("gemma", "qwen25"):
        na = "xcheck-%s-native" % m
        v1 = "xcheck-%s-v1" % m
        if na in cfgs and v1 in cfgs:
            A = {(r["item_id"], r["run"]): r["_vote"] for r in cfgs[na]["oks"]}
            B = {(r["item_id"], r["run"]): r["_vote"] for r in cfgs[v1]["oks"]}
            keys = sorted(set(A) & set(B))
            ag = sum(1 for k in keys if A[k] == B[k])
            print("%s: agree %d/%d = %.1f%% wilson=[%.1f,%.1f]" % (m, ag, len(keys), pct(ag, len(keys)), *wils(ag, len(keys))))
    json.dump(out, open(EV + "/derived.json", "w"), indent=1)
    print("=" * 100); print("wrote", EV + "/derived.json")

if __name__ == "__main__":
    main()
