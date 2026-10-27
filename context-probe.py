#!/usr/bin/env python3
"""Measure max handlable context per installed model, smallest first. JSONL results. Skips 8B/14B per lab policy."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:11434"
MODELS = ["functiongemma", "qwen2.5:0.5b", "athena-slm", "gemma2:2b", "qwen2.5:3b", "qwen2.5-coder:3b", "llama3.2:3b", "phi3", "phi3.5:3.8b", "phi4-mini", "qwen3:4b"]
BANNED = ["deepseek-r1:8b", "qwen2.5:14b"]
SENT = "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. How vexingly quick daft zebras jump. "

def ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def api(path, payload, timeout):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), time.time() - t0
    except Exception as e:
        return 0, {"_error": str(e)[:200]}, time.time() - t0

def mem_free_pct():
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        for tok in out.replace("%", " ").split():
            if tok.isdigit():
                return int(tok)
    except Exception:
        pass
    return None

def unload(model):
    api("/api/generate", {"model": model, "keep_alive": 0}, 30)

def filler(target):
    n = max(1, int(target * 4.3 / len(SENT)) + 1)
    return (SENT * n)[:int(target * 4.3)]

def run_model(model, steps, per_step_timeout, out):
    for target in steps:
        prompt = filler(target)
        free_before = mem_free_pct()
        if free_before is not None and free_before < 10:
            unload(model)
            time.sleep(20)
            free_before = mem_free_pct()
            if free_before is not None and free_before < 10:
                out.write(json.dumps({"ts": ts(), "model": model, "target_ctx": target, "verdict": "SKIP", "note": "low memory even after unload"}) + "\n")
                out.flush()
                return
        status, d, wall = api("/api/generate", {"model": model, "prompt": prompt, "stream": False, "options": {"num_ctx": target + 256, "num_predict": 5, "temperature": 0}}, per_step_timeout)
        pe = d.get("prompt_eval_count", 0) or 0
        verdict = "PASS" if status == 200 and d.get("done") else "FAIL"
        note = "" if verdict == "PASS" else str(d.get("error", d.get("_error", "done!=true")))[:160]
        rec = {"ts": ts(), "model": model, "target_ctx": target, "num_ctx": target + 256, "prompt_chars": len(prompt), "http": status, "done": bool(d.get("done")), "prompt_eval_count": pe, "prompt_eval_ms": round((d.get("prompt_eval_duration", 0) or 0) / 1e6), "eval_count": d.get("eval_count", 0) or 0, "wall_s": round(wall, 1), "mem_free_pct": free_before, "verdict": verdict, "note": note}
        out.write(json.dumps(rec) + "\n")
        out.flush()
        print("MODEL=%s TARGET=%d ACTUAL_TOKENS=%d WALL_S=%.1f VERDICT=%s %s" % (model, target, pe, wall, verdict, note), flush=True)
        if verdict != "PASS":
            unload(model)
            return
        time.sleep(10)
    unload(model)

def main():
    only = None
    steps = [4096, 8192, 16384, 32768]
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--only" and i + 1 < len(args):
            only = args[i + 1]
            i += 2
        elif args[i] == "--steps" and i + 1 < len(args):
            steps = [int(x) for x in args[i + 1].split(",")]
            i += 2
        else:
            i += 1
    models = [m for m in MODELS if only is None or m == only]
    if only is not None and only not in MODELS:
        print("UNKNOWN MODEL (available: %s; banned: %s)" % (",".join(MODELS), ",".join(BANNED)))
        return
    fh = open(os.path.expanduser("~/local-ai-lab/context-results.jsonl"), "a")
    print("START models=%d steps=%s" % (len(models), steps), flush=True)
    for m in models:
        run_model(m, steps, 600, fh)
    fh.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
