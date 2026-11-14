"""Tiny lab login/inference test: list models, then one small chat completion."""
import json
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.status, json.loads(r.read().decode())

def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, json.loads(r.read().decode())

status, models = get("/v1/models")
ids = [m["id"] for m in models.get("data", [])]
print("models_count:", len(ids))
print("has_phi4_mini:", "phi4-mini:latest" in ids)
print("has_qwen05b:", "qwen2.5:0.5b" in ids)

# Use the already-resident model (seen in /api/ps) so this test loads nothing.
model = "qwen2.5:0.5b" if "qwen2.5:0.5b" in ids else ids[0]
print("test_model:", model)
status, resp = post("/v1/chat/completions", {
    "model": model,
    "messages": [
        {"role": "system", "content": "Answer with exactly one word: YES or NO."},
        {"role": "user", "content": "Question: Is Paris the capital of France?\nAnswer with exactly one word (YES or NO):"},
    ],
    "max_tokens": 8,
    "temperature": 0,
})
choice = resp["choices"][0]["message"]["content"]
usage = resp.get("usage", {})
print("http:", status)
print("reply:", repr(choice))
print("usage:", json.dumps(usage))
