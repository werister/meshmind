"""Hard coding bench for lab code models: 7 models x 5 tasks, exec-verified.

Tasks escalate: fib -> first-unique-char -> merge-intervals -> fix-binary-search
-> max-profit-once. Output executed locally (no-import code only, 10s cap).
Transcript -> /tmp/lab_codebench_transcript.jsonl (local only).
"""
import concurrent.futures
import json
import re
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
MODELS = ["qwen2.5-coder:1.5b", "qwen2.5-coder:3b", "yi-coder:1.5b",
          "opencoder:1.5b", "granite-code:3b", "openbmb/minicpm5-2b:latest",
          "granite3.1-moe:3b"]
TR = open("/tmp/lab_codebench_transcript.jsonl", "w")
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


def extract(text):
    fenced = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S | re.I)
    code = fenced[0] if fenced else text
    i = code.find("def ")
    return code[i:].strip() if i >= 0 else ""


def run_tests(code, fn, tests):
    if not code or POISON.search(code):
        return 0, len(tests), "rejected-or-empty"

    def attempt():
        ns = {}
        exec(compile(code, "<gen>", "exec"), {"__builtins__": __builtins__}, ns)  # noqa: S102
        f = ns.get(fn)
        if not callable(f):
            return 0, "no-fn"
        passed = sum(1 for args, exp in tests if f(*args) == exp)
        return passed, "ok"

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            return (*ex.submit(attempt).result(timeout=10), len(tests))
        except Exception as exc:  # noqa: BLE001
            return 0, f"{type(exc).__name__}", len(tests)


def unload(model):
    try:
        post({"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def main():
    totals = {}
    for model in MODELS:
        print(f"=== {model} ===", flush=True)
        passed_items, case_ok, case_n, toks = 0, 0, 0, 0
        for t in TASKS:
            try:
                body, wall = post({
                    "model": model, "stream": False, "think": False,
                    "messages": [{"role": "user", "content": t["prompt"]}],
                    "options": {"temperature": 0, "num_predict": 300},
                })
            except Exception as exc:  # noqa: BLE001
                print(f"  {t['id']}: ERROR {exc}", flush=True)
                continue
            text = (body.get("message") or {}).get("content", "")
            code = extract(text)
            p, note, n = run_tests(code, t["fn"], t["tests"])
            toks += body.get("eval_count", 0)
            case_ok += p if isinstance(p, int) else 0
            case_n += n
            ok_item = (p == n)
            passed_items += ok_item
            TR.write(json.dumps({"model": model, "task": t["id"], "cases": f"{p}/{n}",
                                 "note": note, "wall_s": round(wall, 2),
                                 "eval": body.get("eval_count")}) + "\n")
            TR.flush()
            print(f"  {t['id']}: {p}/{n} wall={wall:.0f}s ({note})", flush=True)
        print(f"=> {model}: {passed_items}/5 items, {case_ok}/{case_n} cases, {toks} tok", flush=True)
        totals[model] = [passed_items, case_ok, case_n, toks]
        # adherence: minicpm verbosity check uses its own transcript rows
        unload(model)
    TR.close()
    print("TOTALS-CODE:", json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
