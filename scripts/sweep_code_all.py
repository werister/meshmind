"""All-model coding sweep: 41 chat models x 5 tasks (26 exec-verified cases).

Same tasks/tests/exec contract as lab_codebench.py (no-import filter, 10s cap,
exact-name + exact-output, temp 0, think:false, num_predict 300) plus:
resume-safe (skips completed (model,task) pairs), raws kept.
Transcript -> /tmp/sweep_code_transcript.jsonl (local only).
"""
"""Provenance: built 2026-11-13 during the Nov 13-14 lab campaign (41-model sweeps);
landed in meshmind via feat/nov13-benchmarks. Lab: CPU-only Ollama Mini."""

import concurrent.futures
import json
import os
import re
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TR_PATH = "/tmp/sweep_code_transcript.jsonl"

MODELS = [
    "qwen3:0.6b",
    "hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M",
    "qwen2.5:0.5b",
    "functiongemma:latest",
    "granite3.1-moe:1b",
    "granite4:micro-h",
    "granite4:1b-h",
    "llama3.2:1b-instruct-q4_K_M",
    "qwen2.5:1.5b",
    "qwen2.5-coder:1.5b",
    "yi-coder:1.5b",
    "opencoder:1.5b",
    "sam860/falcon-h1:1.5b",
    "openbmb/minicpm5-2b:latest",
    "granite3.3:2b",
    "qwen3:1.7b",
    "hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M",
    "qwen2.5:3b",
    "qwen2.5:3b-instruct-q2_K",
    "qwen2.5:3b-instruct-q3_K_M",
    "qwen2.5-coder:3b",
    "granite3.1-moe:3b",
    "voter-granite-moe:3b",
    "granite-code:3b",
    "granite4.2:3b-q4_K_M",
    "falcon3:3b",
    "huggingfacetb-smollm3-3b-q4-k-m:bakeoff",
    "llama3.2:3b-instruct-q4_K_M",
    "phi3.5:3.8b",
    "gemma3:1b-it-q4_K_M",
    "gemma4:e2b",
    "gemma3:4b",
    "gemma3:4b-it-q4_K_M",
    "qwen3:4b-instruct-2507-q4_K_M",
    "qwen3:4b-thinking-2507-q4_K_M",
    "nemotron-3-nano:4b",
    "phi4-mini:latest",
    "athena-slm:latest",
    "nuextract:latest",
    "rwkv7-g1g-proof:latest",
    "qwen3:8b",
]

POISON = re.compile(r"\b(import\s+(os|sys|subprocess|shutil|pathlib|socket)|open\s*\(|eval\s*\(|exec\s*\()", re.I)

TASKS = [
    {"id": "fib", "fn": "fib",
     "prompt": "Reply with Python code only, no explanation, no markdown. Define fib(n): 0-indexed Fibonacci, fib(0)=0, fib(1)=1.",
     "tests": [((0,), 0), ((1,), 1), ((2,), 1), ((7,), 13), ((10,), 55), ((15,), 610)]},
    {"id": "unique", "fn": "first_unique",
     "prompt": "Reply with Python code only, no explanation, no markdown. Define first_unique(s): index of first non-repeating character in string s, or -1 if none.",
     "tests": [(("leetcode",), 0), (("loveleetcode",), 2), (("aabb",), -1), (("",), -1), (("z",), 0)]},
    {"id": "merge", "fn": "merge",
     "prompt": "Reply with Python code only, no explanation, no markdown. Define merge(iv): merge overlapping [start,end] interval lists, return sorted merged list.",
     "tests": [(([[1, 3], [2, 6], [8, 10], [15, 18]],), [[1, 6], [8, 10], [15, 18]]),
               (([[1, 4], [4, 5]],), [[1, 5]]), (([],), []), (([[5, 5]],), [[5, 5]])]},
    {"id": "bisect-fix", "fn": "bsearch",
     "prompt": ("Reply with Python code only, no explanation, no markdown. This binary search has a bug; define a FIXED bsearch(a, x) returning the index of x in sorted list a or -1:\n"
                "def bsearch(a, x):\n    lo, hi = 0, len(a)\n    while lo < hi:\n        mid = (lo + hi) // 2\n        if a[mid] < x: lo = mid\n        else: hi = mid\n    return lo if lo < len(a) and a[lo] == x else -1"),
     "tests": [(([], 3), -1), (([1], 1), 0), (([1, 3, 5, 7], 5), 2),
               (([1, 3, 5, 7], 4), -1), (([1, 2, 3, 4, 5], 5), 4), (([2, 2, 2], 2), 0)]},
    {"id": "profit", "fn": "max_profit",
     "prompt": "Reply with Python code only, no explanation, no markdown. Define max_profit(p): max profit from one buy then sell in price list p (single pass); 0 if no profit possible.",
     "tests": [(([7, 1, 5, 3, 6, 4],), 5), (([7, 6, 4, 3, 1],), 0), (([],), 0),
               (([2, 4, 1],), 2), (([3, 3, 3],), 0)]},
]


def post(payload, timeout=600):
    req = urllib.request.Request(
        BASE + "/api/chat", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def post_hard(payload, timeout=600, deadline=660):
    """post() with an overall wall-clock deadline (trickle-proof).

    urlopen's timeout only fires on 600s with zero bytes; a trickling
    connection hangs forever (observed: 2.5h). Daemon thread: the abandoned
    call leaks but neither the sweep nor process exit blocks on it.
    (ThreadPoolExecutor.__exit__ waits for workers -- must NOT be used here.)
    """
    import threading
    box = {}

    def target():
        try:
            box["res"] = post(payload, timeout)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(deadline)
    if t.is_alive():
        raise TimeoutError(f"call exceeded hard deadline {deadline}s")
    if "err" in box:
        raise box["err"]
    return box["res"]


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def extract(text):
    fenced = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S | re.I)
    code = fenced[0] if fenced else text
    i = code.find("def ")
    return code[i:].strip() if i >= 0 else ""


def run_tests(code, fn, tests):
    """Exec model code with a hard 10s cap. Daemon thread: looping model
    output (e.g. an unfixed lo=mid bsearch) must time out, never hang the
    sweep. (ThreadPoolExecutor.__exit__ waits for workers -- must NOT be
    used here; observed: 3 wedges on one looping row.) Returns (p, note, n).
    """
    import threading
    if not code or POISON.search(code):
        return 0, "rejected-or-empty", len(tests)

    box = {}

    def attempt():
        try:
            ns = {}
            exec(compile(code, "<gen>", "exec"), {"__builtins__": __builtins__}, ns)  # noqa: S102
            f = ns.get(fn)
            if not callable(f):
                box["res"] = (0, "no-fn")
                return
            box["res"] = (sum(1 for args, exp in tests if f(*args) == exp), "ok")
        except Exception as exc:  # noqa: BLE001
            box["res"] = (0, type(exc).__name__)

    t = threading.Thread(target=attempt, daemon=True)
    t.start()
    t.join(10)
    if t.is_alive():
        return 0, "timeout-loop", len(tests)
    p, note = box.get("res", (0, "no-result"))
    return p, note, len(tests)


def unload(model):
    try:
        post_hard({"model": model, "prompt": "", "keep_alive": 0}, timeout=60, deadline=90)
    except Exception:  # noqa: BLE001
        pass


def done_pairs():
    done = set()
    if os.path.exists(TR_PATH):
        for ln in open(TR_PATH, encoding="utf-8"):
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if row.get("model") and row.get("task"):
                done.add((row["model"], row["task"]))
    return done


def main():
    st = get("/status")
    print(f"preflight: mem_free={st.get('mem_free_mb')}MB swap={st.get('swap_used_mb')}MB "
          f"metering_calls={st['metering']['calls_total']}", flush=True)
    print(f"preflight ps: {[m['name'] for m in get('/api/ps').get('models', [])]}", flush=True)
    skip = done_pairs()
    print(f"resume: {len(skip)} (model,task) pairs already complete", flush=True)
    tr = open(TR_PATH, "a", encoding="utf-8")
    totals = {}
    for model in MODELS:
        print(f"=== {model} ===", flush=True)
        passed_items, case_ok, case_n, toks = 0, 0, 0, 0
        for t in TASKS:
            if (model, t["id"]) in skip:
                print(f"  {t['id']}: skipped (done)", flush=True)
                continue
            try:
                body, wall = post_hard({
                    "model": model, "stream": False, "think": False,
                    "messages": [{"role": "user", "content": t["prompt"]}],
                    "options": {"temperature": 0, "num_predict": 300},
                })
            except Exception as exc:  # noqa: BLE001
                tr.write(json.dumps({"model": model, "task": t["id"],
                                     "error": str(exc)[:200]}) + "\n")
                tr.flush()
                print(f"  {t['id']}: ERROR {str(exc)[:100]}", flush=True)
                continue
            text = (body.get("message") or {}).get("content", "")
            code = extract(text)
            p, note, n = run_tests(code, t["fn"], t["tests"])
            toks += body.get("eval_count", 0)
            case_ok += p if isinstance(p, int) else 0
            case_n += n
            ok_item = (p == n)
            passed_items += ok_item
            tr.write(json.dumps({"model": model, "task": t["id"], "cases": f"{p}/{n}",
                                 "note": note, "wall_s": round(wall, 2),
                                 "eval": body.get("eval_count"),
                                 "raw": text[:4000]}) + "\n")
            tr.flush()
            print(f"  {t['id']}: {p}/{n} wall={wall:.0f}s ({note})", flush=True)
        print(f"=> {model}: {passed_items}/5 items, {case_ok}/{case_n} cases, {toks} tok", flush=True)
        totals[model] = [passed_items, case_ok, case_n, toks]
        unload(model)
    tr.close()
    print("TOTALS-CODE-ALL: " + json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
