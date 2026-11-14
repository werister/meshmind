"""Lab bench 9: strict-prompt retest (yi, opencoder) + speed table (7) +
minicpm Chinese (4) + minicpm native tool live-exec + 4k/8k boundary."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TR = open("/tmp/lab_bench9_transcript.jsonl", "w")
ITEMS8 = [
    ("Water boils at 100 degrees Celsius at sea level.", "yes"),
    ("Paris is the capital of France.", "yes"),
    ("The human heart has four chambers.", "yes"),
    ("Light travels faster than sound in air.", "yes"),
    ("The Great Wall of China is visible from the Moon with the naked eye.", "no"),
    ("Humans normally use only 10 percent of their brains.", "no"),
    ("Bats are completely blind and navigate only by echolocation.", "no"),
    ("The Pacific is the smallest of the world's oceans.", "no"),
]
STRICT = "Reply with ONLY the word YES or the word NO. Nothing else. No punctuation, no explanation."
TOKS = {}


def post(path, payload, timeout=600):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def chat(model, system, user, num_predict, timeout=600):
    body, wall = post("/api/chat", {
        "model": model, "stream": False, "think": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "options": {"temperature": 0, "num_predict": num_predict},
    }, timeout)
    TOKS[model] = TOKS.get(model, 0) + body.get("eval_count", 0)
    return (body.get("message") or {}).get("content", ""), wall


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


print("== STRICT RETEST ==", flush=True)
for model in ["yi-coder:1.5b", "opencoder:1.5b"]:
    votes = []
    for q, exp in ITEMS8:
        t, _ = chat(model, STRICT, f"Question: {q}", 8)
        v = parse(t)
        votes.append((v, exp, t[:60].replace("\n", " ")))
    correct = sum(1 for v, exp, _ in votes if v == exp)
    print(f"=> {model}: strict {correct}/8", flush=True)
    for v, exp, raw in votes:
        if v != exp:
            print(f"   miss exp={exp}: {raw!r}", flush=True)
    TR.write(json.dumps({"bench": "strict", "model": model,
                         "correct": correct}) + "\n")
    TR.flush()
    unload(model)

print("== SPEED TABLE (64 tok, warm) ==", flush=True)
PROMPT = "Explain in one paragraph why the sky appears blue during daytime."
for model in ["openbmb/minicpm5-2b:latest", "qwen2.5-coder:1.5b", "falcon3:3b",
              "nemotron-3-nano:4b", "voter-granite-moe:3b",
              "huggingfacetb-smollm3-3b-q4-k-m:bakeoff", "granite3.1-moe:3b"]:
    try:
        chat(model, "Be concise.", PROMPT, 64)  # warmup
        body, wall = post("/api/chat", {
            "model": model, "stream": False, "think": False,
            "messages": [{"role": "user", "content": PROMPT}],
            "options": {"temperature": 0, "num_predict": 64},
        })
        ec = body.get("eval_count", 0)
        ed = (body.get("eval_duration") or 1) / 1e9
        TOKS[model] = TOKS.get(model, 0) + ec
        print(f"=> {model}: {ec / ed:.1f} tok/s (wall {wall:.0f}s)", flush=True)
        TR.write(json.dumps({"bench": "speed", "model": model,
                             "tps": round(ec / ed, 1)}) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"=> {model}: ERROR {exc}", flush=True)
    TR.flush()
    unload(model)

print("== MINICPM CHINESE ==", flush=True)
ZH = [("巴黎是法国的首都。", "yes"), ("水在海平面100摄氏度沸腾。", "yes"),
      ("人类只使用了10%的大脑。", "no"), ("太平洋是最小的洋。", "no")]
zs = 0
for q, exp in ZH:
    t, _ = chat("openbmb/minicpm5-2b:latest", STRICT, f"问题：{q}", 8)
    v = parse(t)
    zs += v == exp
    print(f"  {q[:12]}... -> {v} exp={exp} raw={t[:40]!r}", flush=True)
print(f"=> minicpm chinese: {zs}/4", flush=True)
TR.write(json.dumps({"bench": "chinese", "correct": zs}) + "\n")
TR.flush()

print("== MINICPM NATIVE TOOL EXEC ==", flush=True)
body, _ = post("/api/chat", {
    "model": "openbmb/minicpm5-2b:latest", "stream": False, "think": False,
    "messages": [{"role": "user", "content": "Search Wikipedia for Mixture of Experts."}],
    "tools": [{"type": "function", "function": {
        "name": "search_wikipedia", "description": "Search Wikipedia.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}}],
    "options": {"temperature": 0, "num_predict": 150},
})
msg = body.get("message") or {}
calls = msg.get("tool_calls") or []
print(f"  calls={str(calls)[:200]}", flush=True)
if calls:
    args = (calls[0].get("function") or {}).get("arguments") or {}
    if isinstance(args, str):
        args = json.loads(args)
    r2, _ = post("/fetch", {"op": "search", "query": args.get("query", "")}, timeout=60)
    print(f"  live exec ok={r2.get('ok')} results={len(r2.get('results', []) or [])}", flush=True)
    TR.write(json.dumps({"bench": "toolexec", "ok": r2.get("ok")}) + "\n")
    TR.flush()
unload("openbmb/minicpm5-2b:latest")

print("== CTX BOUNDARY (granite-moe) ==", flush=True)
para = ("The local AI lab serves small models on an 8 GB Intel Mac Mini over "
        "the tailnet. Each request names its model explicitly. ")
for name, reps in [("4k", 73), ("8k", 146)]:
    big = para * reps
    try:
        body, wall = post("/api/chat", {
            "model": "granite3.1-moe:3b", "stream": False, "think": False,
            "messages": [
                {"role": "system", "content": "Answer with exactly one word: YES or NO."},
                {"role": "user", "content": f"Text: {big}\nDoes the text say each request names its model? Answer YES or NO:"}],
            "options": {"temperature": 0, "num_predict": 8},
        }, timeout=900)
        text = (body.get("message") or {}).get("content", "")
        print(f"  {name}: vote={parse(text)} wall={wall:.0f}s prompt_eval={body.get('prompt_eval_count')}", flush=True)
        TR.write(json.dumps({"bench": "ctx", "size": name, "vote": parse(text),
                             "prompt_eval": body.get("prompt_eval_count")}) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"  {name}: ERROR {str(exc)[:100]}", flush=True)
        TR.write(json.dumps({"bench": "ctx", "size": name, "error": str(exc)[:100]}) + "\n")
    TR.flush()
unload("granite3.1-moe:3b")
TR.close()
print("TOKENS9:", json.dumps(TOKS), flush=True)
