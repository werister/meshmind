"""Smoke bench for the 2 new pulls: 8 yes/no votes each + 1 code probe."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
ITEMS = [
    ("Water boils at 100 degrees Celsius at sea level.", "yes"),
    ("Paris is the capital of France.", "yes"),
    ("The human heart has four chambers.", "yes"),
    ("Light travels faster than sound in air.", "yes"),
    ("The Great Wall of China is visible from the Moon with the naked eye.", "no"),
    ("Humans normally use only 10 percent of their brains.", "no"),
    ("Bats are completely blind and navigate only by echolocation.", "no"),
    ("The Pacific is the smallest of the world's oceans.", "no"),
]
MODELS = ["openbmb/minicpm5-2b:latest", "qwen2.5-coder:1.5b"]
SYS = "Answer with exactly one word: YES or NO."
TR = open("/tmp/lab_bench3_transcript.jsonl", "w")


def post(path, payload, timeout=600):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def parse_vote(text):
    toks = "".join(ch if ch.isalnum() else " " for ch in text).upper().split()
    if not toks:
        return "unparseable"
    return "yes" if toks[0] == "YES" else ("no" if toks[0] == "NO" else "unparseable")


def unload(model):
    try:
        post("/api/generate", {"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"  unload note: {exc}", flush=True)


totals = {}
for model in MODELS:
    print(f"=== {model} ===", flush=True)
    correct, lat, toks, misses = 0, [], 0, []
    for i, (q, exp) in enumerate(ITEMS):
        try:
            body, wall = post("/api/chat", {
                "model": model, "stream": False, "think": False,
                "messages": [
                    {"role": "system", "content": SYS},
                    {"role": "user", "content": f"Question: {q}\nAnswer with exactly one word (YES or NO):"},
                ],
                "options": {"temperature": 0, "num_predict": 8},
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i + 1}/8] ERROR {exc}", flush=True)
            misses.append((q[:50], "ERROR", str(exc)[:60]))
            continue
        text = (body.get("message") or {}).get("content", "")
        v = parse_vote(text)
        correct += v == exp
        lat.append(wall)
        toks += body.get("eval_count", 0)
        if v != exp:
            misses.append((q[:50], v, text[:50].replace("\n", " ")))
        TR.write(json.dumps({"model": model, "item": i, "vote": v, "ok": v == exp,
                             "wall_s": round(wall, 2)}) + "\n")
        TR.flush()
        print(f"  [{i + 1}/8] {v:>11} exp={exp} wall={wall:.1f}s", flush=True)
    lat.sort()
    med = lat[len(lat) // 2] if lat else -1
    print(f"=> {model}: {correct}/8, median {med:.1f}s, eval tokens {toks}", flush=True)
    for q, v, raw in misses:
        print(f"   miss: {q!r} -> {v} ({raw!r})", flush=True)
    totals[model] = [correct, round(med, 2), toks]
    unload(model)

print("== code probe (qwen2.5-coder:1.5b) ==", flush=True)
body, wall = post("/api/chat", {
    "model": "qwen2.5-coder:1.5b", "stream": False, "think": False,
    "messages": [{"role": "user", "content": (
        "Complete this Python function (reply with code only, no explanation):\n"
        "def is_even(n):\n")}],
    "options": {"temperature": 0, "num_predict": 60},
})
code = (body.get("message") or {}).get("content", "")
print(f"wall={wall:.1f}s eval={body.get('eval_count')}\n{code[:400]}", flush=True)
TR.write(json.dumps({"probe": "code", "wall_s": round(wall, 2),
                     "eval_count": body.get("eval_count"), "raw": code[:400]}) + "\n")
unload("qwen2.5-coder:1.5b")
TR.close()
print("TOTALS3:", json.dumps(totals), flush=True)
