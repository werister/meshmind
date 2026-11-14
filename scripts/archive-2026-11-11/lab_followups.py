"""Followups: embed API shape + full embed run + LFM3 error capture."""
import json
import math
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"


def post(path, payload, timeout=120):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


print("== EMBED SHAPE ==", flush=True)
raw = post("/api/embed", {"model": "nomic-embed-text:v1.5", "input": "hello world"})
print("keys:", list(raw.keys()), flush=True)
emb = raw.get("embeddings", [raw.get("embedding")])[0]
print("dim:", len(emb), flush=True)

PAIRS = [
    ("The cat sits on the mat.", "A cat is sitting on a rug.", "para"),
    ("Water boils at 100 degrees.", "H2O reaches boiling point at 100C.", "para"),
    ("The cat sits on the mat.", "Quantum chromodynamics confines quarks.", "unrelated"),
    ("Water boils at 100 degrees.", "My portfolio needs rebalancing.", "unrelated"),
]


def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


for model in ["nomic-embed-text:v1.5", "bge-m3:latest", "qwen3-embedding:0.6b"]:
    try:
        vecs = {}
        for s in dict.fromkeys([a for a, _, _ in PAIRS] + [b for _, b, _ in PAIRS]):
            r = post("/api/embed", {"model": model, "input": s})
            vecs[s] = (r.get("embeddings") or [r.get("embedding")])[0]
        sims = [(k, round(cos(vecs[a], vecs[b]), 3)) for a, b, k in PAIRS]
        print(f"=> {model}: dim={len(next(iter(vecs.values())))} {sims}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"=> {model}: ERROR {exc!r}", flush=True)

print("== LFM3 ERROR ==", flush=True)
try:
    r = post("/api/chat", {
        "model": "hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M", "stream": False, "think": False,
        "messages": [{"role": "user", "content": "Say YES."}],
        "options": {"temperature": 0, "num_predict": 8}}, timeout=300)
    print("reply:", repr((r.get("message") or {}).get("content", ""))[:200], flush=True)
except Exception as exc:  # noqa: BLE001
    print(f"ERROR {exc!r}", flush=True)
