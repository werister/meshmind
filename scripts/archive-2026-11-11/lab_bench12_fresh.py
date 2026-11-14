"""Lab bench 12: FRESH 12-item benchmark, 15 models, pre-registered.
New items (6 yes / 6 no), frozen parser, temp 0, raws kept for all votes.
Transcript -> /tmp/lab_bench12_transcript.jsonl (local only)."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
MODELS = ["huggingfacetb-smollm3-3b-q4-k-m:bakeoff", "falcon3:3b",
          "granite3.1-moe:3b", "voter-granite-moe:3b", "nemotron-3-nano:4b",
          "phi4-mini:latest", "gemma3:4b", "gemma3:1b-it-q4_K_M",
          "granite3.3:2b", "granite4:micro-h", "qwen2.5-coder:3b",
          "yi-coder:1.5b", "openbmb/minicpm5-2b:latest", "qwen2.5:3b",
          "llama3.2:3b-instruct-q4_K_M"]
ITEMS = [
    ("Honey never spoils; edible honey was found in ancient Egyptian tombs.", "yes"),
    ("The human body has 206 bones at birth.", "no"),
    ("Sharks existed before Saturn got its rings.", "yes"),
    ("Napoleon was shorter than the average Frenchman of his time.", "no"),
    ("Humans and giraffes have the same number of neck vertebrae.", "yes"),
    ("The Dead Sea is the deepest lake in the world.", "no"),
    ("Bananas are berries, but strawberries are not.", "yes"),
    ("The speed of light is exactly 300,000 km/s.", "no"),
    ("Cleopatra lived closer in time to the Moon landing than to the pyramids.", "yes"),
    ("Vikings wore horned helmets into battle.", "no"),
    ("Lightning is hotter than the surface of the Sun.", "yes"),
    ("The Eiffel Tower stands in Berlin.", "no"),
]
SYS = "Answer with exactly one word: YES or NO."
TR = open("/tmp/lab_bench12_transcript.jsonl", "w")


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
            print(f"  [{i + 1}/12] ERROR {exc}", flush=True)
            continue
        text = (body.get("message") or {}).get("content", "")
        v = parse(text)
        correct += v == exp
        lat.append(wall)
        toks += body.get("eval_count", 0)
        if v != exp:
            misses.append((q[:42], text[:42].replace("\n", " ")))
        TR.write(json.dumps({"model": model, "item": i, "vote": v,
                             "expected": exp, "ok": v == exp,
                             "wall_s": round(wall, 2),
                             "raw": text[:120]}) + "\n")
        TR.flush()
        print(f"  [{i + 1}/12] {v:>4} exp={exp} wall={wall:.1f}s", flush=True)
    lat.sort()
    med = lat[len(lat) // 2] if lat else -1
    print(f"=> {model}: {correct}/12 med={med:.1f}s tok={toks}", flush=True)
    for q, r in misses:
        print(f"   miss: {q!r} -> {r!r}", flush=True)
    totals[model] = [correct, round(med, 2), toks]
    unload(model)
TR.close()
print("TOTALS-FRESH12:", json.dumps(totals), flush=True)
