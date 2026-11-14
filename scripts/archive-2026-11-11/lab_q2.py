"""Q2: exact bench prompt rerun of 'Is 17 an even number?' on granite-moe."""
import json
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
req = urllib.request.Request(
    BASE + "/api/chat",
    data=json.dumps({
        "model": "granite3.1-moe:3b", "stream": False, "think": False,
        "messages": [
            {"role": "system", "content": "Answer with exactly one word: YES or NO."},
            {"role": "user", "content": "Question: Is 17 an even number?\nAnswer with exactly one word (YES or NO):"},
        ],
        "options": {"temperature": 0, "num_predict": 8},
    }).encode(), headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=300) as r:
    body = json.loads(r.read().decode())
text = (body.get("message") or {}).get("content", "")
toks = "".join(ch if ch.isalnum() else " " for ch in text).upper().split()
print(f"RAW: {text!r}")
print(f"FIRST-TOKEN: {toks[0] if toks else '?'} (truth: NO)")
print(f"EVAL: {body.get('eval_count')}")
