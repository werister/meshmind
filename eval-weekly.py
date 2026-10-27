#!/usr/bin/env python3
"""Weekly smoke eval for the Local AI Lab.

A small weekly smoke eval (NOT the full context sweep): a few fast models run
a fixed prompt set, graded pass/fail with tok/s, appended to JSONL. The sidecar
tails the latest run summary into /status.

Design (stdlib only, 8 GB-safe):
- Fixed prompt set with deterministic, substring-checkable answers.
- Per-model wall-clock timeout (a hung model fails, never hangs the run).
- Models are unloaded between runs (keep_alive:0) so only one sits in RAM.
- Memory guard: before each model, if free memory % is below --mem-min we try
  one unload+settle, and if still pressured we SKIP the model (never OOM).
- A nonsense model name yields FAIL rows, not a crash (fail-safe grading).

JSONL records (one per line, newest appended):
  {"kind":"result", model, prompt_id, verdict, tok_s, ...}   per prompt
  {"kind":"model_summary", model, passed, total, ...}         per model
  {"kind":"run_summary", models, passed_models, ...}          once per run

Usage:
  eval-weekly.py                       # default model set, weekly set
  eval-weekly.py --models gemma-270m   # restrict to named models
  eval-weekly.py --mem-min 101         # force the memory-guard SKIP path
  eval-weekly.py --models nonesuch:9b  # force the FAIL path
  eval-weekly.py --out /tmp/eval.jsonl --timeout 120
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

DEFAULT_BASE = "http://127.0.0.1:11434"
DEFAULT_OUT = os.path.expanduser("~/local-ai-lab/eval-weekly.jsonl")

# Weekly smoke models: small, CPU-friendly, present on the box. The Mini runs a
# different tiny set than this dev MacBook; override with --models on the Mini.
DEFAULT_MODELS = [
    "qwen2.5:0.5b",
    "gemma2:2b",
    "llama3.2:3b",
]

# Fixed prompt set. Each answer is graded by lowercase substring match on at
# least one accepted token, so minor formatting/verbosity still passes.
PROMPTS = [
    {
        "id": "arith",
        "prompt": "What is 17 plus 26? Reply with only the number.",
        "accept": ["43"],
        "num_predict": 16,
    },
    {
        "id": "capital",
        "prompt": "What is the capital city of Japan? Reply with only the city name.",
        "accept": ["tokyo"],
        "num_predict": 16,
    },
    {
        "id": "reverse",
        "prompt": "Spell the word 'lab' backwards. Reply with only the letters.",
        "accept": ["bal"],
        "num_predict": 16,
    },
]


def ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def api(base, path, payload, timeout):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), time.time() - t0
    except Exception as e:
        return 0, {"_error": str(e)[:200]}, time.time() - t0


def mem_free_pct():
    """System-wide free memory %, or None if unavailable (guard disabled)."""
    try:
        out = subprocess.run(
            ["memory_pressure"], capture_output=True, text=True, timeout=10
        ).stdout
        m = re.search(r"free percentage:\s*(\d+)", out)
        if m:
            return int(m.group(1))
        # Fallback: last standalone integer in the output.
        for tok in out.replace("%", " ").split():
            if tok.isdigit():
                return int(tok)
    except Exception:
        pass
    return None


def unload(base, model):
    api(base, "/api/generate", {"model": model, "keep_alive": 0}, 30)


def grade(resp_text, accept):
    low = (resp_text or "").strip().lower()
    for a in accept:
        if a.lower() in low:
            return True
    return False


def tok_s(d):
    ec = d.get("eval_count", 0) or 0
    dur_ns = d.get("eval_duration", 0) or 0
    if ec and dur_ns:
        return round(ec / (dur_ns / 1e9), 1)
    return 0.0


def run_model(base, model, prompts, per_prompt_timeout, mem_min, out):
    """Run the fixed prompt set against one model. Returns the model_summary dict."""
    # --- memory guard ---
    free = mem_free_pct()
    if free is not None and free < mem_min:
        unload(base, model)
        time.sleep(5)
        free_after = mem_free_pct()
        if free_after is not None and free_after < mem_min:
            rec = {
                "kind": "model_summary",
                "ts": ts(),
                "model": model,
                "skipped": True,
                "verdict": "SKIP",
                "note": "memory guard: free %s%% < min %s%%" % (free_after, mem_min),
                "mem_free_pct": free_after,
                "passed": 0,
                "total": len(prompts),
            }
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(
                "MODEL=%s VERDICT=SKIP (mem free %s%% < %s%%)"
                % (model, free_after, mem_min),
                flush=True,
            )
            return rec
        free = free_after

    passed = 0
    speeds = []
    for p in prompts:
        status, d, wall = api(
            base,
            "/api/generate",
            {
                "model": model,
                "prompt": p["prompt"],
                "stream": False,
                "options": {"num_predict": p["num_predict"], "temperature": 0},
            },
            per_prompt_timeout,
        )
        ok_http = status == 200 and bool(d.get("done"))
        resp = d.get("response", "")
        correct = ok_http and grade(resp, p["accept"])
        verdict = "PASS" if correct else "FAIL"
        if correct:
            passed += 1
        spd = tok_s(d)
        if spd:
            speeds.append(spd)
        err = ""
        if not ok_http:
            err = str(d.get("error", d.get("_error", "done!=true")))[:160]
        rec = {
            "kind": "result",
            "ts": ts(),
            "model": model,
            "prompt_id": p["id"],
            "http": status,
            "done": bool(d.get("done")),
            "response": (resp or "").strip()[:120],
            "accept": p["accept"],
            "correct": correct,
            "verdict": verdict,
            "eval_count": d.get("eval_count", 0) or 0,
            "tok_s": spd,
            "wall_s": round(wall, 1),
            "mem_free_pct": free,
            "note": err,
        }
        out.write(json.dumps(rec) + "\n")
        out.flush()
        print(
            "MODEL=%s PROMPT=%s VERDICT=%s tok/s=%s wall=%.1fs %s"
            % (model, p["id"], verdict, spd, wall, err),
            flush=True,
        )

    avg_tok_s = round(sum(speeds) / len(speeds), 1) if speeds else 0.0
    summary = {
        "kind": "model_summary",
        "ts": ts(),
        "model": model,
        "skipped": False,
        "verdict": "PASS" if passed == len(prompts) else "FAIL",
        "passed": passed,
        "total": len(prompts),
        "avg_tok_s": avg_tok_s,
        "mem_free_pct": free,
    }
    out.write(json.dumps(summary) + "\n")
    out.flush()
    print(
        "MODEL=%s SUMMARY %d/%d avg_tok_s=%s"
        % (model, passed, len(prompts), avg_tok_s),
        flush=True,
    )
    # Always unload so the next model starts from a clean RAM slate.
    unload(base, model)
    time.sleep(2)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Weekly smoke eval (stdlib only).")
    ap.add_argument("--models", help="comma-separated model list override")
    ap.add_argument("--base", default=DEFAULT_BASE, help="Ollama base URL")
    ap.add_argument("--out", default=DEFAULT_OUT, help="JSONL output path")
    ap.add_argument("--timeout", type=int, default=120, help="per-prompt timeout (s)")
    ap.add_argument(
        "--mem-min",
        type=int,
        default=12,
        help="skip a model if free memory %% is below this (use 101 to force SKIP)",
    )
    args = ap.parse_args(argv)

    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else list(DEFAULT_MODELS)
    )

    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    print(
        "START eval-weekly models=%d timeout=%ds mem_min=%d%% out=%s"
        % (len(models), args.timeout, args.mem_min, args.out),
        flush=True,
    )
    summaries = []
    with open(args.out, "a") as out:
        for m in models:
            summaries.append(
                run_model(args.base, m, PROMPTS, args.timeout, args.mem_min, out)
            )
        passed_models = sum(1 for s in summaries if s["verdict"] == "PASS")
        skipped_models = sum(1 for s in summaries if s["verdict"] == "SKIP")
        run_summary = {
            "kind": "run_summary",
            "ts": ts(),
            "models": len(models),
            "prompts_each": len(PROMPTS),
            "passed_models": passed_models,
            "failed_models": sum(1 for s in summaries if s["verdict"] == "FAIL"),
            "skipped_models": skipped_models,
            "wall_s": round(time.time() - t0, 1),
        }
        out.write(json.dumps(run_summary) + "\n")
        out.flush()
    print(
        "DONE %d models, %d passed, %d skipped, %.1fs"
        % (len(models), passed_models, skipped_models, run_summary["wall_s"]),
        flush=True,
    )
    return run_summary


if __name__ == "__main__":
    main()
