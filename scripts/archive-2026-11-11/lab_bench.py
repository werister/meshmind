"""Small voter benchmark on the mini lab: 4 models x 8 yes/no items.

Native /api/chat (exact eval_count/eval_duration), temp 0, think off,
strict first-token parse, keep_alive:0 unload between models.
Transcript -> /tmp/lab_bench_transcript.jsonl (local only, nothing on the mini).
"""
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

MODELS = [
    "qwen2.5:0.5b",
    "gemma3:1b-it-q4_K_M",
    "granite3.1-moe:3b",
    "phi4-mini:latest",
]

SYS = "Answer with exactly one word: YES or NO."


def post(path, payload, timeout=300):
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
    except Exception as exc:  # noqa: BLE001 - best effort
        print(f"  unload note: {exc}")


def main():
    transcript = open("/tmp/lab_bench_transcript.jsonl", "w")
    totals = {}
    for model in MODELS:
        print(f"=== {model} ===", flush=True)
        correct, lat, toks, misses = 0, [], 0, []
        for i, (q, exp) in enumerate(ITEMS):
            body, wall = post("/api/chat", {
                "model": model, "stream": False, "think": False,
                "messages": [
                    {"role": "system", "content": SYS},
                    {"role": "user", "content": f"Question: {q}\nAnswer with exactly one word (YES or NO):"},
                ],
                "options": {"temperature": 0, "num_predict": 8},
            })
            text = (body.get("message") or {}).get("content", "")
            vote = parse_vote(text)
            ok = vote == exp
            correct += ok
            lat.append(wall)
            toks += body.get("eval_count", 0)
            if not ok:
                misses.append((q[:60], vote, text[:60].replace("\n", " ")))
            transcript.write(json.dumps({
                "model": model, "item": i, "expected": exp, "vote": vote,
                "ok": ok, "wall_s": round(wall, 2),
                "eval_count": body.get("eval_count"),
                "eval_duration_ns": body.get("eval_duration"),
                "raw": text[:200],
            }) + "\n")
            transcript.flush()
            print(f"  [{i + 1}/8] {vote:>11} exp={exp} wall={wall:.1f}s", flush=True)
        lat.sort()
        med = lat[len(lat) // 2]
        print(f"=> {model}: {correct}/8, median vote {med:.1f}s, eval tokens {toks}", flush=True)
        for q, v, raw in misses:
            print(f"   miss: {q!r} -> {v} ({raw!r})", flush=True)
        totals[model] = (correct, med, toks)
        unload(model)
    transcript.close()
    print("TOTALS:", json.dumps(totals))


if __name__ == "__main__":
    main()
