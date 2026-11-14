"""Re-probe granite-moe items 5-7 with raw capture + both parsers."""
import json
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
ITEMS = [
    "The Great Wall of China is visible from the Moon with the naked eye.",
    "Humans normally use only 10 percent of their brains.",
    "Bats are completely blind and navigate only by echolocation.",
]
SYS = "Answer with exactly one word: YES or NO."


def chat(q):
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps({
            "model": "granite3.1-moe:3b", "stream": False, "think": False,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": f"Question: {q}\nAnswer with exactly one word (YES or NO):"}],
            "options": {"temperature": 0, "num_predict": 8},
        }).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        body = json.loads(r.read().decode())
    return (body.get("message") or {}).get("content", "")


for q in ITEMS:
    t = chat(q)
    strict = "".join(ch if ch.isalnum() else " " for ch in t).upper().split()
    strict = strict[0] if strict else "?"
    naive = t.strip().upper().split()
    naive = naive[0] if naive and naive[0] in ("YES", "NO") else "?"
    print(f"raw={t!r} bench1parse={strict} stabilityparse={naive}")
