"""Lab bench 6: voter census of 14 untested small models (8 items each).
Frozen first-alnum parser, temp 0, think:false. Local only transcript."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
MODELS = ["falcon3:3b", "sam860/falcon-h1:1.5b",
          "huggingfacetb-smollm3-3b-q4-k-m:bakeoff",
          "hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M",
          "granite4:1b-h", "granite4:micro-h", "granite3.3:2b",
          "qwen3:0.6b", "llama3.2:3b-instruct-q4_K_M",
          "yi-coder:1.5b", "opencoder:1.5b", "granite-code:3b",
          "nemotron-3-nano:4b",
          "hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M"]
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
SYS = "Answer with exactly one word: YES or NO."
TR = open("/tmp/lab_bench6_transcript.jsonl", "w")


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
            print(f"  [{i + 1}/8] ERROR {exc}", flush=True)
            misses.append((q[:40], "ERROR"))
            continue
        text = (body.get("message") or {}).get("content", "")
        v = parse(text)
        correct += v == exp
        lat.append(wall)
        toks += body.get("eval_count", 0)
        if v != exp:
            misses.append((q[:40], text[:40].replace("\n", " ")))
        TR.write(json.dumps({"model": model, "item": i, "vote": v,
                             "ok": v == exp, "wall_s": round(wall, 2)}) + "\n")
        TR.flush()
        print(f"  [{i + 1}/8] {v:>4} exp={exp} wall={wall:.1f}s", flush=True)
    lat.sort()
    med = lat[len(lat) // 2] if lat else -1
    print(f"=> {model}: {correct}/8 med={med:.1f}s tok={toks} miss={len(misses)}", flush=True)
    for q, r in misses:
        print(f"   miss: {q!r} -> {r!r}", flush=True)
    totals[model] = [correct, round(med, 2), toks]
    unload(model)
TR.close()
print("TOTALS-CENSUS:", json.dumps(totals), flush=True)
