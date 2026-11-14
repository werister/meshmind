"""Extended lab bench + stress probes. Think off everywhere, unload between
models, transcript -> /tmp/lab_bench2_transcript.jsonl (local only)."""
import concurrent.futures
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
    "voter-granite-moe:3b",
    "phi3.5:3.8b",
    "granite3.1-moe:1b",
    "qwen2.5:3b",
    "qwen2.5:1.5b",
    "qwen3:1.7b",
    "llama3.2:1b-instruct-q4_K_M",
    "gemma3:4b",
]

SYS = "Answer with exactly one word: YES or NO."
TR = open("/tmp/lab_bench2_transcript.jsonl", "w")


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


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


def vote(model, q):
    body, wall = post("/api/chat", {
        "model": model, "stream": False, "think": False,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": f"Question: {q}\nAnswer with exactly one word (YES or NO):"},
        ],
        "options": {"temperature": 0, "num_predict": 8},
    })
    text = (body.get("message") or {}).get("content", "")
    return text, wall, body.get("eval_count", 0)


def unload(model):
    try:
        post("/api/generate", {"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"  unload note: {exc}", flush=True)


def ps_snapshot(tag):
    try:
        ps = get("/api/ps")
        loaded = [(m.get("name"), round(m.get("size", 0) / 1e9, 2)) for m in ps.get("models", [])]
        print(f"  [ps {tag}] loaded={loaded}", flush=True)
        return loaded
    except Exception as exc:  # noqa: BLE001
        print(f"  [ps {tag}] error: {exc}", flush=True)
        return None


def main():
    print("== memory before ==", flush=True)
    ps_snapshot("before")
    totals = {}
    for model in MODELS:
        print(f"=== {model} ===", flush=True)
        correct, lat, toks, misses = 0, [], 0, []
        for i, (q, exp) in enumerate(ITEMS):
            try:
                text, wall, ec = vote(model, q)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i + 1}/8] ERROR {exc}", flush=True)
                TR.write(json.dumps({"model": model, "item": i, "error": str(exc)}) + "\n")
                misses.append((q[:50], "ERROR", str(exc)[:60]))
                continue
            v = parse_vote(text)
            correct += v == exp
            lat.append(wall)
            toks += ec
            if v != exp:
                misses.append((q[:50], v, text[:50].replace("\n", " ")))
            TR.write(json.dumps({"model": model, "item": i, "expected": exp,
                                 "vote": v, "ok": v == exp, "wall_s": round(wall, 2),
                                 "eval_count": ec, "raw": text[:150]}) + "\n")
            TR.flush()
            print(f"  [{i + 1}/8] {v:>11} exp={exp} wall={wall:.1f}s", flush=True)
        lat.sort()
        med = lat[len(lat) // 2] if lat else -1
        print(f"=> {model}: {correct}/8, median vote {med:.1f}s, eval tokens {toks}", flush=True)
        for q, v, raw in misses:
            print(f"   miss: {q!r} -> {v} ({raw!r})", flush=True)
        totals[model] = [correct, round(med, 2), toks]
        unload(model)
    ps_snapshot("after-unloads")

    # --- stress 1: 4 concurrent votes, one loaded model ---
    warm, _, _ = vote("granite3.1-moe:3b", ITEMS[0][0])
    print(f"== parallel x4 (granite3.1-moe:3b, warm={warm[:20]!r}) ==", flush=True)
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(vote, "granite3.1-moe:3b", ITEMS[i][0]) for i in range(1, 5)]
        walls = []
        for f in concurrent.futures.as_completed(futs):
            try:
                _, wall, _ = f.result()
                walls.append(round(wall, 2))
            except Exception as exc:  # noqa: BLE001
                walls.append(f"ERROR {exc}")
    print(f"   walls={walls} makespan={time.time() - t0:.1f}s", flush=True)
    TR.write(json.dumps({"probe": "parallel-x4", "walls": walls}) + "\n")
    unload("granite3.1-moe:3b")

    # --- stress 2: near-limit context (~3k tokens) ---
    print("== long-context ~3k tokens (granite3.1-moe:3b) ==", flush=True)
    para = ("The local AI lab serves small models on an 8 GB Intel Mac Mini over "
            "the tailnet. Each request names its model explicitly. Think-off is the "
            "default; the granite reasoning lane is the only opt-in thinker. ")
    big = para * 55  # ~3k tokens
    body, wall = post("/api/chat", {
        "model": "granite3.1-moe:3b", "stream": False, "think": False,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": f"Text: {big}\nQuestion: Does the text say each request names its model?\nAnswer with exactly one word (YES or NO):"},
        ],
        "options": {"temperature": 0, "num_predict": 8},
    })
    text = (body.get("message") or {}).get("content", "")
    print(f"   vote={parse_vote(text)} wall={wall:.1f}s "
          f"prompt_eval={body.get('prompt_eval_count')} tok in "
          f"{(body.get('prompt_eval_duration') or 0) / 1e9:.1f}s", flush=True)
    TR.write(json.dumps({"probe": "long-context", "vote": parse_vote(text),
                         "wall_s": round(wall, 2),
                         "prompt_eval_count": body.get("prompt_eval_count")}) + "\n")
    unload("granite3.1-moe:3b")
    ps_snapshot("final")
    TR.close()
    print("TOTALS2:", json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
