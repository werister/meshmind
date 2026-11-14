"""Lab bench 10: prompt-tuning — can few-shot/strict prompts fix the
format-failures (yi, opencoder) and biases (qwen3 yes-bias, minicpm no-bias)?
Same 8 items, frozen parser. Local only transcript."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
MODELS = ["yi-coder:1.5b", "opencoder:1.5b", "qwen3:1.7b",
          "openbmb/minicpm5-2b:latest"]
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
FEWSHOT = [
    {"role": "user", "content": "Question: Is ice cold?\nAnswer: YES or NO?"},
    {"role": "assistant", "content": "YES"},
    {"role": "user", "content": "Question: Do fish ride bicycles?\nAnswer: YES or NO?"},
    {"role": "assistant", "content": "NO"},
]
SYS = ("Reply with ONLY the word YES or the word NO. Nothing else. "
       "No punctuation, no explanation, no 'Answer:'.")
TR = open("/tmp/lab_bench10_transcript.jsonl", "w")


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


BASELINE = {"yi-coder:1.5b": 0, "opencoder:1.5b": 0, "qwen3:1.7b": 5,
            "openbmb/minicpm5-2b:latest": 5}
totals = {}
for model in MODELS:
    print(f"=== {model} (few-shot tuned) ===", flush=True)
    correct, lat, toks = 0, [], 0
    for i, (q, exp) in enumerate(ITEMS):
        try:
            body, wall = post("/api/chat", {
                "model": model, "stream": False, "think": False,
                "messages": [{"role": "system", "content": SYS}] + FEWSHOT + [
                    {"role": "user", "content": f"Question: {q}\nAnswer: YES or NO?"}],
                "options": {"temperature": 0, "num_predict": 8},
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i + 1}/8] ERROR {exc}", flush=True)
            continue
        text = (body.get("message") or {}).get("content", "")
        v = parse(text)
        correct += v == exp
        lat.append(wall)
        toks += body.get("eval_count", 0)
        TR.write(json.dumps({"model": model, "item": i, "vote": v,
                             "ok": v == exp, "raw": text[:80]}) + "\n")
        TR.flush()
        print(f"  [{i + 1}/8] {v:>4} exp={exp} raw={text[:30]!r}", flush=True)
    lat.sort()
    med = lat[len(lat) // 2] if lat else -1
    print(f"=> {model}: tuned {correct}/8 (baseline {BASELINE[model]}/8) med={med:.1f}s tok={toks}", flush=True)
    totals[model] = [correct, toks]
    unload(model)
TR.close()
print("TOTALS-TUNE:", json.dumps(totals), flush=True)
