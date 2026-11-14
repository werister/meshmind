"""Lab bench 8: hard near-miss set (10 items x top-4 voters)."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
MODELS = ["granite3.1-moe:3b", "voter-granite-moe:3b", "falcon3:3b",
          "nemotron-3-nano:4b"]
ITEMS = [
    ("The Eiffel Tower grows slightly taller in summer due to thermal expansion.", "yes"),
    ("Binary search on a sorted array runs in linear O(n) time.", "no"),
    ("Octopuses have three hearts.", "yes"),
    ("The human genome contains exactly 100,000 protein-coding genes.", "no"),
    ("Lightning never strikes the same place twice.", "no"),
    ("A group of flamingos is called a flamboyance.", "yes"),
    ("Venus spins in the opposite direction to Earth.", "yes"),
    ("The Titanic sank on its maiden voyage in 1912.", "yes"),
    ("Goldfish have a memory span of only three seconds.", "no"),
    ("Sound travels faster in water than in air.", "yes"),
]
SYS = "Answer with exactly one word: YES or NO."
TR = open("/tmp/lab_bench8_transcript.jsonl", "w")


def post(path, payload, timeout=600):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def parse(text):
    toks = "".join(ch if ch.isalnum() else " " for ch in text).upper().split()
    if not toks:
        return "?"
    return "yes" if toks[0] == "YES" else ("no" if toks[0] == "NO" else "?")


def unload(m):
    try:
        post("/api/generate", {"model": m, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


totals = {}
for model in MODELS:
    print(f"=== {model} ===", flush=True)
    correct, lat, toks, misses = 0, [], 0, []
    for i, (q, exp) in enumerate(ITEMS):
        try:
            body, wall = post("/api/chat", {
                "model": model, "stream": False, "think": False,
                "messages": [{"role": "system", "content": SYS},
                             {"role": "user", "content": f"Question: {q}\nAnswer with exactly one word (YES or NO):"}],
                "options": {"temperature": 0, "num_predict": 8},
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i + 1}/10] ERROR {exc}", flush=True)
            continue
        text = (body.get("message") or {}).get("content", "")
        v = parse(text)
        correct += v == exp
        lat.append(wall)
        toks += body.get("eval_count", 0)
        if v != exp:
            misses.append((q[:45], text[:45].replace("\n", " ")))
        TR.write(json.dumps({"model": model, "item": i, "vote": v,
                             "ok": v == exp, "wall_s": round(wall, 2)}) + "\n")
        TR.flush()
        print(f"  [{i + 1}/10] {v:>4} exp={exp} wall={wall:.1f}s", flush=True)
    lat.sort()
    med = lat[len(lat) // 2] if lat else -1
    print(f"=> {model}: {correct}/10 med={med:.1f}s tok={toks}", flush=True)
    for q, r in misses:
        print(f"   miss: {q!r} -> {r!r}", flush=True)
    totals[model] = [correct, round(med, 2), toks]
    unload(model)
TR.close()
print("TOTALS-HARD:", json.dumps(totals), flush=True)
