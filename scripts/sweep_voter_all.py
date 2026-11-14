"""All-model voter sweep: 41 chat models x 18 yes/no items (8 standard + 10 hard).

Same contract as lab_bench.py/lab_bench8_hard.py (native /api/chat, temp 0,
think:false, num_predict 8, strict first-token parse, keep_alive:0 unload
between models) plus: resume-safe (skips models with 18 transcript rows),
per-item error rows, raws kept.
Transcript -> /tmp/sweep_voter_transcript.jsonl (local only).
"""
"""Provenance: built 2026-11-13 during the Nov 13-14 lab campaign (41-model sweeps);
landed in meshmind via feat/nov13-benchmarks. Lab: CPU-only Ollama Mini."""

import json
import os
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TR_PATH = "/tmp/sweep_voter_transcript.jsonl"

STD = [
    ("Water boils at 100 degrees Celsius at sea level.", "yes"),
    ("Paris is the capital of France.", "yes"),
    ("The human heart has four chambers.", "yes"),
    ("Light travels faster than sound in air.", "yes"),
    ("The Great Wall of China is visible from the Moon with the naked eye.", "no"),
    ("Humans normally use only 10 percent of their brains.", "no"),
    ("Bats are completely blind and navigate only by echolocation.", "no"),
    ("The Pacific is the smallest of the world's oceans.", "no"),
]
HARD = [
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
ITEMS = [("std%d" % i, q, e) for i, (q, e) in enumerate(STD)]
ITEMS += [("hard%d" % i, q, e) for i, (q, e) in enumerate(HARD)]

# All chat-capable tags on the box 2026-11-13 (embed-only excluded:
# qwen3-embedding:0.6b, bge-m3:latest, nomic-embed-text:v1.5). Small-first.
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

SYS = "Answer with exactly one word: YES or NO."


def post(path, payload, timeout=300):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


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


def done_models():
    done = {}
    if os.path.exists(TR_PATH):
        for ln in open(TR_PATH, encoding="utf-8"):
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            done[row.get("model")] = done.get(row.get("model"), 0) + 1
    return {m for m, n in done.items() if n >= len(ITEMS)}


def main():
    st = get("/status")
    print(f"preflight: mem_free={st.get('mem_free_mb')}MB swap={st.get('swap_used_mb')}MB "
          f"metering_calls={st['metering']['calls_total']}", flush=True)
    print(f"preflight ps: {[m['name'] for m in get('/api/ps').get('models', [])]}", flush=True)
    skip = done_models()
    print(f"resume: {len(skip)} models already complete", flush=True)
    tr = open(TR_PATH, "a", encoding="utf-8")
    totals = {}
    for model in MODELS:
        if model in skip:
            print(f"=== {model} (skipped, done) ===", flush=True)
            continue
        print(f"=== {model} ===", flush=True)
        correct, lat, toks, misses, errs = 0, [], 0, [], 0
        for iid, q, exp in ITEMS:
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
                errs += 1
                tr.write(json.dumps({"model": model, "item": iid, "error": str(exc)[:200]}) + "\n")
                tr.flush()
                print(f"  [{iid}] ERROR {str(exc)[:100]}", flush=True)
                continue
            text = (body.get("message") or {}).get("content", "")
            v = parse(text)
            ok = v == exp
            correct += ok
            lat.append(wall)
            toks += body.get("eval_count", 0)
            if not ok:
                misses.append((iid, v, text[:60].replace("\n", " ")))
            tr.write(json.dumps({"model": model, "item": iid, "expected": exp,
                                 "vote": v, "ok": ok, "wall_s": round(wall, 2),
                                 "eval_count": body.get("eval_count"),
                                 "raw": text[:2000]}) + "\n")
            tr.flush()
            print(f"  [{iid}] {v:>4} exp={exp} wall={wall:.1f}s", flush=True)
        lat.sort()
        med = lat[len(lat) // 2] if lat else -1
        print(f"=> {model}: {correct}/{len(ITEMS)} med={med:.1f}s tok={toks} err={errs}", flush=True)
        for iid, v, raw in misses:
            print(f"   miss: {iid} -> {v} ({raw!r})", flush=True)
        totals[model] = [correct, round(med, 2), toks, errs]
        unload(model)
    tr.close()
    print("TOTALS-VOTER-ALL: " + json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
