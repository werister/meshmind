"""Lab bench 13: 100-item intertwined coding benchmark (seed-frozen).

8 families x 12-13 instances. Ground truth from reference implementations,
NOT by hand. Items frozen (seed 12345) before any model call; sha256 of the
item bank is printed first. Exec-verified, raws kept.
Transcript -> /tmp/lab_bench13_transcript.jsonl (local only).
"""
"""Provenance: built 2026-11-11/12 during the Nov 13-14 lab campaign (100-item code bank (recovered from session log));
landed in meshmind via feat/nov13-benchmarks. Lab: CPU-only Ollama Mini."""

import ast
import concurrent.futures
import hashlib
import json
import random
import re
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
MODELS = ["qwen2.5-coder:3b", "qwen2.5-coder:1.5b", "yi-coder:1.5b",
          "granite-code:3b", "opencoder:1.5b", "openbmb/minicpm5-2b:latest"]
POISON = re.compile(r"\b(import\s+(os|sys|subprocess|shutil|pathlib|socket)|open\s*\(|eval\s*\(|exec\s*\()", re.I)
TR = open("/tmp/lab_bench13_transcript.jsonl", "a")


def post(path, payload, timeout=600):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def post_hard(path, payload, timeout=600, deadline=660):
    """post() with an overall wall-clock deadline (trickle-proof).

    urlopen's timeout only fires on 600s with zero bytes; a trickling
    connection hangs forever (observed: 5.5h). Daemon thread: abandoned
    calls leak but never block the sweep or process exit.
    (ThreadPoolExecutor.__exit__ waits -- must NOT be used here.)
    """
    import threading
    box = {}

    def target():
        try:
            box["res"] = post(path, payload, timeout)
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


def run_fn(code, fn, tests):
    """Exec model code with a hard 10s cap. Daemon thread: looping model
    output must time out, never hang the sweep (ThreadPoolExecutor.__exit__
    waits for workers -- must NOT be used here). Returns (p, n, note)."""
    import threading
    if not code or POISON.search(code):
        return 0, len(tests), "rejected"

    box = {}

    def attempt():
        try:
            ns = {}
            exec(compile(code, "<gen>", "exec"), {"__builtins__": __builtins__}, ns)  # noqa: S102
            f = ns.get(fn)
            if not callable(f):
                box["res"] = (0, "no-fn")
                return
            box["res"] = (sum(1 for a, e in tests if f(*a) == e), "ok")
        except Exception as exc:  # noqa: BLE001
            box["res"] = (0, type(exc).__name__)

    t = threading.Thread(target=attempt, daemon=True)
    t.start()
    t.join(10)
    if t.is_alive():
        return 0, len(tests), "timeout-loop"
    p, note = box.get("res", (0, "no-result"))
    return p, len(tests), note


def extract(text):
    fenced = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S | re.I)
    code = fenced[0] if fenced else text
    i = code.find("def ")
    return code[i:].strip() if i >= 0 else ""


# ---------------- item bank (seed 12345, frozen) ----------------
def gen_bank():
    rng = random.Random(12345)
    items = []

    def add(fam, prompt, kind, ref=None, fn=None, tests=None, expect=None,
            no_loops=False):
        items.append({"fam": fam, "prompt": prompt, "kind": kind, "ref": ref,
                      "fn": fn, "tests": tests, "expect": expect,
                      "no_loops": no_loops})

    # 1. recurrences x12: f(n)=a*f(n-1)+b*f(n-2), varied bases
    for k in range(12):
        a, b = rng.choice([(1, 1), (2, 1), (1, 2), (3, -1), (2, -1), (1, 3)]), None
        a, b = (a if isinstance(a, tuple) else (a, b))
        f0, f1 = rng.randint(0, 3), rng.randint(0, 3)
        n = rng.randint(8, 14)
        seq = [f0, f1]
        for _ in range(n):
            seq.append(a * seq[-1] + b * seq[-2])
        add("recur", f"Reply with Python code only. Define f(n) with f(0)={f0}, f(1)={f1}, f(n)={a}*f(n-1){b:+}*f(n-2) for n>=2.",
            "fn", fn="f", tests=[((n,), seq[n]), ((5,), seq[5]), ((0,), f0)])
    # 2. string transforms x13
    for k in range(13):
        op = ["rot13alpha", "toggle", "dedup", "revwords"][k % 4]
        words = ["alpha", "bravo", "code", "delta", "echo", "gate"]
        s = " ".join(rng.sample(words, rng.randint(2, 4)))
        if op == "rot13alpha":
            exp = "".join(chr((ord(c) - 97 + 13) % 26 + 97) if "a" <= c <= "z" else c for c in s)
            add("str", f"Reply with Python code only. Define t(s): ROT13 each lowercase letter, keep other chars. Example: t('ab z')=='no m'.",
                "fn", fn="t", tests=[((s,), exp), (("ab z",), "no m")])
        elif op == "toggle":
            add("str", "Reply with Python code only. Define t(s): swap case of each letter.",
                "fn", fn="t", tests=[((s,), s.swapcase()), (("Ab1",), "aB1")])
        elif op == "dedup":
            exp = "".join(dict.fromkeys(s))
            add("str", "Reply with Python code only. Define t(s): remove duplicate characters, keep first occurrence order.",
                "fn", fn="t", tests=[((s,), exp), (("abba",), "ab")])
        else:
            add("str", "Reply with Python code only. Define t(s): reverse the order of whitespace-separated words.",
                "fn", fn="t", tests=[((s,), " ".join(s.split()[::-1])), (("a b",), "b a")])
    # 3. interval logic x12
    for k in range(12):
        n = rng.randint(2, 4)
        ivs = sorted([[rng.randint(0, 8), 0] for _ in range(n)])
        for iv in ivs:
            iv[1] = iv[0] + rng.randint(1, 4)
        if k % 3 == 0:  # total covered length
            pts = set()
            for a, b in ivs:
                pts.update(range(a, b))
            add("ivl", "Reply with Python code only. Define total(iv): total integer points covered by [start,end) intervals.",
                "fn", fn="total", tests=[((ivs,), len(pts)), (([[0, 2], [1, 3]],), 3)])
        elif k % 3 == 1:  # max overlap depth
            best = 0
            for x in range(0, 14):
                best = max(best, sum(1 for a, b in ivs if a <= x < b))
            add("ivl", "Reply with Python code only. Define depth(iv): max number of [start,end) intervals covering any integer.",
                "fn", fn="depth", tests=[((ivs,), best), (([[0, 5], [2, 3]],), 2)])
        else:  # gaps
            lo, hi = min(a for a, _ in ivs), max(b for _, b in ivs)
            gaps = [x for x in range(lo, hi) if not any(a <= x < b for a, b in ivs)]
            add("ivl", "Reply with Python code only. Define gaps(iv): sorted integers in [min start, max end) covered by NO [start,end) interval.",
                "fn", fn="gaps", tests=[((ivs,), gaps), (([[0, 1], [3, 4]],), [1, 2])])
    # 4. stack machines x12
    for k in range(12):
        if k % 2 == 0:
            ops = [rng.choice(["push", "pop", "peek"]) for _ in range(rng.randint(4, 7))]
            vals = [rng.randint(1, 9) for _ in ops]
            prog, st, out = [], [], []
            for op, v in zip(ops, vals):
                if op == "push":
                    prog.append(f"push {v}")
                    st.append(v)
                elif op == "pop":
                    prog.append("pop")
                    out.append(st.pop() if st else -1)
                else:
                    prog.append("peek")
                    out.append(st[-1] if st else -1)
            add("stack", f"Reply with the result only: comma-separated outputs (pop/peek, -1 if empty) for: {'; '.join(prog)}. Start: empty stack.",
                "value", expect=",".join(map(str, out)))
        else:
            opens = rng.choice(["()", "[]", "()[]"])
            s = "".join(rng.choice(opens) for _ in range(rng.randint(4, 8)))
            bal, depth, ok = 0, 0, True
            mp = {")": "(", "]": "["}
            st = []
            for ch in s:
                if ch in "([":
                    st.append(ch)
                elif not st or st.pop() != mp[ch]:
                    ok = False
                    break
            ok = ok and not st
            add("stack", f"Reply with the result only: YES if balanced brackets else NO: {s}",
                "value", expect="YES" if ok else "NO")
    # 5. debug-fix x13: fix the planted bug, keep name/signature
    bugs = [
        ("sum_range", "def sum_range(a, b):\n    return sum(range(a, b))",
         "should include BOTH ends", [((1, 5), 15), ((3, 3), 3), ((0, 0), 0)]),
        ("count_even", "def count_even(xs):\n    return sum(1 for x in xs if x % 2 == 1)",
         "counts the wrong parity", [(([1, 2, 3, 4],), 2), (([],), 0), (([1, 3],), 0)]),
        ("max3", "def max3(a, b, c):\n    m = a\n    if b > m: m = b\n    return m",
         "ignores the third argument", [((1, 2, 3), 3), ((9, 1, 1), 9), ((1, 1, 1), 1)]),
        ("clamp", "def clamp(x, lo, hi):\n    if x < lo: return hi\n    if x > hi: return lo\n    return x",
         "returns the wrong bound on both sides", [((5, 0, 10), 5), ((-3, 0, 10), 0), ((99, 0, 10), 10)]),
    ]
    for k in range(13):
        name, code, hint, tests = bugs[k % 4]
        add("debug", f"Reply with Python code only. This function has a bug ({hint}); define the FIXED {name} with the same signature:\n{code}",
            "fn", fn=name, tests=tests)
    # 6. multi-fn intertwined x13: implement f AND g (g must call f)
    for k in range(13):
        kind = k % 4
        if kind == 0:
            add("multi", "Reply with Python code only. Define is_prime(n) (n<2 False, trial division) AND nth_prime(n) (1-indexed, must call is_prime).",
                "multi", fn=("is_prime", "nth_prime"),
                tests=[("is_prime", (7,), True), ("is_prime", (1,), False),
                       ("nth_prime", (1,), 2), ("nth_prime", (6,), 13)])
        elif kind == 1:
            add("multi", "Reply with Python code only. Define gcd(a,b) (Euclid) AND lcm(a,b) (must call gcd).",
                "multi", fn=("gcd", "lcm"),
                tests=[("gcd", (12, 8), 4), ("gcd", (7, 5), 1),
                       ("lcm", (4, 6), 12), ("lcm", (7, 5), 35)])
        elif kind == 2:
            add("multi", "Reply with Python code only. Define depth(x) (0 for non-list, 1+max of elements) AND flatten(x) (depth-first leaves, must call depth only if needed — both must exist).",
                "multi", fn=("depth", "flatten"),
                tests=[("depth", ([1, [2, [3]]],), 3), ("depth", (5,), 0),
                       ("flatten", ([1, [2, [3]]],), [1, 2, 3]), ("flatten", ([],), [])])
        else:
            add("multi", "Reply with Python code only. Define uniq_sorted(xs) (sorted unique list) AND median_of(xs) (median of uniq_sorted(xs), must call it; average middle two if even).",
                "multi", fn=("uniq_sorted", "median_of"),
                tests=[("uniq_sorted", ([3, 1, 3],), [1, 3]),
                       ("median_of", ([3, 1, 2],), 2), ("median_of", ([4, 1, 3, 2],), 2.5)])
    # 7. constrained code x12: correct AND no for/while statements
    for k in range(12):
        kind = k % 3
        if kind == 0:
            add("constr", "Reply with Python code only, no for/while statements. Define sum_sq(n): sum of i*i for i in 1..n.",
                "constr", fn="sum_sq", no_loops=True,
                tests=[((5,), 55), ((1,), 1), ((10,), 385)])
        elif kind == 1:
            add("constr", "Reply with Python code only, no for/while statements. Define dot(a,b): dot product of equal-length lists.",
                "constr", fn="dot", no_loops=True,
                tests=[(([1, 2], [3, 4]), 11), (([], []), 0)])
        else:
            add("constr", "Reply with Python code only, no for/while statements. Define count_ch(s,c): occurrences of c in s.",
                "constr", fn="count_ch", no_loops=True,
                tests=[(("hello", "l"), 2), (("abc", "z"), 0)])
    # 8. output prediction x13: reply the value only
    preds = []
    for k in range(13):
        a, b = rng.randint(2, 12), rng.randint(2, 12)
        style = k % 3
        if style == 0:
            code = f"x = {a}\ny = {b}\nfor i in range(3):\n    x, y = y, x + y"
            x, y = a, b
            for _ in range(3):
                x, y = y, x + y
            preds.append((code, f"{x},{y}"))
        elif style == 1:
            s = "".join(rng.choice("ab") for _ in range(6))
            code = f"s = {s!r}\nprint(s[::2] + s[1::2])"
            preds.append((code, s[::2] + s[1::2]))
        else:
            n = rng.randint(10, 30)
            code = f"n = {n}\nc = 0\nwhile n > 1:\n    n = n // 2 if n % 2 == 0 else 3 * n + 1\n    c += 1"
            m, c = n, 0
            while m > 1:
                m = m // 2 if m % 2 == 0 else 3 * m + 1
                c += 1
            preds.append((code, str(c)))
    for code, exp in preds:
        add("pred", f"Reply with the result only, no explanation. What does this print?\n{code}",
            "value", expect=exp)
    return items


BANK = gen_bank()
print("BANK:", len(BANK), "sha256:",
      hashlib.sha256(json.dumps(
          [(b['fam'], b['prompt']) for b in BANK]).encode()).hexdigest()[:16])
assert len(BANK) == 100, len(BANK)


def grade(item, text):
    if item["kind"] == "value":
        got = " ".join(text.strip().split())
        exp = " ".join(item["expect"].split())
        return (1 if got == exp else 0), 1, f"got={got[:40]!r}"
    code = extract(text)
    if not code or POISON.search(code):
        return (0, 0, "rejected")
    if item["no_loops"]:
        try:
            tree = ast.parse(code)
            if any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree)):
                return (0, 0, "has-loops")
        except SyntaxError:
            return (0, 0, "syntax")
    if item["kind"] == "multi":
        names, tests = item["fn"], item["tests"]

        def attempt():
            ns = {}
            exec(compile(code, "<gen>", "exec"), {"__builtins__": __builtins__}, ns)  # noqa: S102
            ok, n = 0, 0
            for fn, args, exp in tests:
                f = ns.get(fn)
                n += 1
                if callable(f) and f(*args) == exp:
                    ok += 1
            src = code
            uses = ("is_prime(" in src and src.count("is_prime(") > 1) or \
                   ("gcd(" in src and src.count("gcd(") > 1) or \
                   ("uniq_sorted(" in src and src.count("uniq_sorted(") > 1)
            return ok, n, ("ok" if uses else "no-reuse")

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            try:
                return (*ex.submit(attempt).result(timeout=10),)
            except Exception as exc:  # noqa: BLE001
                return (0, 0, type(exc).__name__)
    p, n, note = run_fn(code, item["fn"], item["tests"])
    return (p == n, 1 if p == n else 0, note) if False else (p, n, note)


def main():
    totals = {}
    done = set()
    try:
        for line in open("/tmp/lab_bench13_transcript.jsonl"):
            r = json.loads(line)
            done.add((r["model"], r["item"]))
            p, nn = r["score"].split("/")
            t = totals.setdefault(r["model"], [0, 0, 0])
            t[0] += int(p) == int(nn)
            t[1] += 1
    except FileNotFoundError:
        pass
    print(f"RESUME: {len(done)} rows already scored", flush=True)
    for model in MODELS:
        print(f"=== {model} ===", flush=True)
        passed, n, toks = totals.get(model, [0, 0, 0])
        for i, item in enumerate(BANK):
            if (model, i) in done:
                continue
            try:
                body, wall = post_hard("/api/chat", {
                    "model": model, "stream": False, "think": False,
                    "messages": [{"role": "user", "content": item["prompt"]}],
                    "options": {"temperature": 0, "num_predict": 400},
                })
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i + 1}/100] ERROR {exc}", flush=True)
                continue
            text = (body.get("message") or {}).get("content", "")
            toks += body.get("eval_count", 0)
            p, nn, note = grade(item, text)
            if isinstance(p, bool):
                p = 1 if p else 0
                nn = 1
            passed += p == nn
            n += 1
            TR.write(json.dumps({"model": model, "item": i, "fam": item["fam"],
                                 "score": f"{p}/{nn}", "note": note,
                                 "wall_s": round(wall, 1),
                                 "raw": text[:400]}) + "\n")
            TR.flush()
            if (i + 1) % 10 == 0:
                print(f"  [{i + 1}/100] {model}: {passed}/{n} so far", flush=True)
        print(f"=> {model}: {passed}/{n} items tok={toks}", flush=True)
        totals[model] = [passed, n, toks]
        try:
            post_hard("/api/generate", {"model": model, "prompt": "", "keep_alive": 0},
                      timeout=60, deadline=90)
        except Exception:  # noqa: BLE001
            pass
    TR.close()
    print("TOTALS-100:", json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()

