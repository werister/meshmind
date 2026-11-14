#!/usr/bin/env python3
"""Minimal Ollama-native eval harness (stdlib only). Scratch for the local-voter eval; not product code.

Calls the lab Ollama via native /api/generate (native API gives load/eval timing splits the
OpenAI-compat path lacks; repo transport.py's host allowlist is the owner's opt-in and is not
widened here). Disciplines adopted from lane_qualify.py: --dry-run budget first, one attempt per
call for ANSWERED calls (transport errors may refill on resume; model behaviors stand), JSONL out.
"""
from __future__ import annotations

"""Provenance: built 2026-11-03/04 during the Nov 13-14 lab campaign (66-item voter harness (moved from eval-local-voters-2026-11-03 scratch));
landed in meshmind via feat/nov13-benchmarks. Lab: CPU-only Ollama Mini."""
import argparse, hashlib, json, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

LAB = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
SYSTEM = "Answer with exactly one word: YES or NO."
SEEDS = (11, 22, 33)

def post_json(url, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, json.loads(body), (time.time() - t0) * 1000.0, None
    except urllib.error.HTTPError as e:
        return e.code, {}, (time.time() - t0) * 1000.0, "http_%s" % e.code
    except Exception as e:  # timeout, connection reset, DNS: infrastructure, refillable on resume
        return -1, {}, (time.time() - t0) * 1000.0, "transport_%s" % type(e).__name__

def get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def model_identity(base, model):
    try:
        tags = get_json(base + "/api/tags")
        for m in tags.get("models", []):
            if m.get("name") == model or m.get("model") == model:
                d = m.get("details", {})
                return {"digest": m.get("digest"), "size": m.get("size"),
                        "parameter_size": d.get("parameter_size")}
    except Exception as e:
        return {"digest": None, "error": type(e).__name__}
    return {"digest": None, "error": "not_in_tags"}

def load_items(path, subset):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    if subset:
        want = set(s.strip() for s in subset.split(",") if s.strip())
        rows = [r for r in rows if r["id"] in want]
        assert len(rows) == len(want), "subset ids missing: %s" % want
    return rows

def completed_keys(path):
    done, refill = set(), set()
    try:
        for line in open(path):
            try: r = json.loads(line)
            except Exception: continue
            k = (r.get("item_id"), r.get("run"))
            if r.get("status") == "ok": done.add(k)
            elif r.get("status") == "transport_error": refill.add(k)
    except FileNotFoundError:
        pass
    return done - refill, refill

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True); p.add_argument("--items", required=True)
    p.add_argument("--out", required=True); p.add_argument("--runs", type=int, default=3)
    p.add_argument("--num-predict", type=int, default=64); p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--subset", default=""); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-unload", action="store_true"); p.add_argument("--base", default=LAB); p.add_argument("--endpoint", default="native", choices=("native","v1"))
    p.add_argument("--tag", default=""); p.add_argument("--think", action="store_true",
        help="allow model thinking (default off: voters run think=false)")
    a = p.parse_args()
    items = load_items(a.items, a.subset)
    budget = len(items) * a.runs
    ident = {"model": a.model}
    if a.dry_run:
        print("budget: model=%s items=%d runs=%d calls=%d num_predict=%d timeout=%s" % (
            a.model, len(items), a.runs, budget, a.num_predict, a.timeout)); return 0
    ident.update(model_identity(a.base, a.model))
    print("identity: %s" % json.dumps(ident), flush=True)
    if not a.no_unload:  # cold-start call #1: unload first so load time lands in one measured call
        post_json(a.base + "/api/generate", {"model": a.model, "prompt": "ok",
                  "stream": False, "keep_alive": 0, "options": {"num_predict": 1}}, 120)
        print("unload poke sent (call #1 below is cold)", flush=True)
    done, refill = completed_keys(a.out)
    n_new = 0
    with open(a.out, "a") as f:
        for run in range(1, a.runs + 1):
            seed = SEEDS[(run - 1) % len(SEEDS)]
            for it in items:
                if (it["id"], run) in done: continue
                prompt = "Question: %s\nAnswer with exactly one word (YES or NO):" % it["question"]
                if a.endpoint == "v1":
                    st, vbody, wall, err = post_json(a.base + "/v1/chat/completions", {
                        "model": a.model, "temperature": 0, "max_tokens": a.num_predict,
                        "messages": [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": prompt}]}, a.timeout)
                    ch = (vbody.get("choices") or [{}])[0] if isinstance(vbody, dict) else {}
                    body = {"response": (ch.get("message") or {}).get("content", ""),
                            "done": ch.get("finish_reason") == "stop",
                            "done_reason": ch.get("finish_reason") or "",
                            "eval_count": (vbody.get("usage") or {}).get("completion_tokens"),
                            "eval_duration": 0, "load_duration": 0,
                            "prompt_eval_count": (vbody.get("usage") or {}).get("prompt_tokens")}
                else:
                    st, body, wall, err = post_json(a.base + "/api/generate", {
                        "model": a.model, "prompt": prompt, "system": SYSTEM, "stream": False, "think": a.think,
                        "keep_alive": "10m",
                        "options": {"temperature": 0, "seed": seed, "num_predict": a.num_predict},
                    }, a.timeout)
                rec = {"ts": datetime.now(timezone.utc).isoformat(), "tag": a.tag, "endpoint": a.endpoint,
                       "item_id": it["id"], "tier": it["tier"], "label": it["label"],
                       "run": run, "seed": seed, "num_predict": a.num_predict, "temperature": 0,
                       "model": a.model, "model_digest": ident.get("digest"),
                       "http_status": st, "wall_ms": round(wall, 1),
                       "response_raw": body.get("response", "") if isinstance(body, dict) else "",
                       "done": bool(body.get("done")) if isinstance(body, dict) else False,
                       "done_reason": (body.get("done_reason") or "") if isinstance(body, dict) else "",
                       "thinking": body.get("thinking", "") if isinstance(body, dict) else "",
                       "eval_count": body.get("eval_count"), "eval_duration_ms":
                           round(body.get("eval_duration", 0) / 1e6, 1) if isinstance(body, dict) else None,
                       "load_duration_ms":
                           round(body.get("load_duration", 0) / 1e6, 1) if isinstance(body, dict) else None,
                       "prompt_eval_count": body.get("prompt_eval_count")}
                if err is None and isinstance(body, dict) and "response" in body:
                    rec["status"] = "ok"
                else:
                    rec["status"] = "transport_error"; rec["error"] = err or "no_response"
                f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
                n_new += 1
                print("[%s r%d] %s status=%s eval=%s wall=%.1fs %s" % (
                    a.model, run, it["id"], rec["status"], rec["eval_count"],
                    wall / 1000.0, (rec["response_raw"] or "")[:60].replace("\n", " ")), flush=True)
    print("wrote %d new records -> %s" % (n_new, a.out), flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
