"""Lab bench 7: embedding sanity (3 models) + native function-calling
(2 models x 2 tasks). Local only transcript."""
import json
import math
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TR = open("/tmp/lab_bench7_transcript.jsonl", "w")


def post(path, payload, timeout=300):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


print("== EMBEDDINGS ==", flush=True)
PAIRS = [
    ("The cat sits on the mat.", "A cat is sitting on a rug.", "para"),
    ("Water boils at 100 degrees.", "H2O reaches boiling point at 100C.", "para"),
    ("The cat sits on the mat.", "Quantum chromodynamics confines quarks.", "unrelated"),
    ("Water boils at 100 degrees.", "My portfolio needs rebalancing.", "unrelated"),
]
for model in ["nomic-embed-text:v1.5", "bge-m3:latest", "qwen3-embedding:0.6b"]:
    try:
        vecs = {}
        for s, _, _ in PAIRS:
            if s not in vecs:
                body, wall = post("/api/embed", {"model": model, "input": s})
                vecs[s] = body["embeddings"][0]
        dims = len(next(iter(vecs.values())))
        sims = [(kind, round(cos(vecs[a], vecs[b]), 3)) for a, b, kind in PAIRS]
        print(f"=> {model}: dim={dims} {sims}", flush=True)
        TR.write(json.dumps({"bench": "embed", "model": model, "dim": dims,
                             "sims": sims}) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"=> {model}: ERROR {exc}", flush=True)
        TR.write(json.dumps({"bench": "embed", "model": model, "error": str(exc)}) + "\n")
    TR.flush()

print("== NATIVE TOOLS ==", flush=True)
TOOLS = [{"type": "function", "function": {
    "name": "search_wikipedia",
    "description": "Search Wikipedia and return up to 5 title/url pairs.",
    "parameters": {"type": "object",
                   "properties": {"query": {"type": "string"}},
                   "required": ["query"]}}}]
TASKS = ["Search Wikipedia for Mixture of Experts.",
         "Look up Alan Turing on Wikipedia."]
for model in ["openbmb/minicpm5-2b:latest",
              "hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M"]:
    ok = 0
    for t in TASKS:
        try:
            body, wall = post("/api/chat", {
                "model": model, "stream": False, "think": False,
                "messages": [{"role": "user", "content": t}],
                "tools": TOOLS, "options": {"temperature": 0, "num_predict": 150},
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  {model}: ERROR {exc}", flush=True)
            continue
        msg = body.get("message") or {}
        calls = msg.get("tool_calls") or []
        good = any(c.get("function", {}).get("name") == "search_wikipedia"
                   and "query" in (c.get("function", {}).get("arguments") or {})
                   for c in calls)
        # arguments may be a dict already
        if not good:
            for c in calls:
                args = (c.get("function") or {}).get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:  # noqa: BLE001
                        args = {}
                if (c.get("function") or {}).get("name") == "search_wikipedia" and isinstance(args, dict) and "query" in args:
                    good = True
        ok += good
        TR.write(json.dumps({"bench": "nativetools", "model": model, "task": t[:30],
                             "ok": good, "calls": str(calls)[:300],
                             "content": msg.get("content", "")[:200]}) + "\n")
        TR.flush()
        print(f"  {model}: {'TOOLCALL' if good else 'no-call'} wall={wall:.0f}s", flush=True)
    print(f"=> {model}: {ok}/2 native tool calls", flush=True)
TR.close()
print("BENCH7-DONE", flush=True)
