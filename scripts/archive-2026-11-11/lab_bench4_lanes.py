"""Lab bench 4: tools lane (3 models x 6 tasks, 1 live exec each) +
fib retest with raws (3 models) + voter stability rerun (3 models x 8).
Transcript -> /tmp/lab_bench4_transcript.jsonl (local only)."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TR = open("/tmp/lab_bench4_transcript.jsonl", "w")

TOOL_SYSTEM = (
    "You call tools by replying with exactly one JSON object, no other text. "
    "Tools: {\"op\":\"fetch\",\"url\":...} fetches page text (http/https only); "
    "{\"op\":\"search\",\"query\":...} searches Wikipedia (max 5 results)."
)
TOOL_TASKS = [
    ("Fetch the front page of example.com.", "fetch", "https://example.com"),
    ("Search Wikipedia for Mixture of Experts.", "search", "Mixture of Experts"),
    ("Get the text of https://example.org/about.", "fetch", "https://example.org/about"),
    ("Look up Alan Turing on Wikipedia.", "search", "Alan Turing"),
    ("Fetch http://neverssl.com/ for its text.", "fetch", "http://neverssl.com/"),
    ("Search Wikipedia for Fibonacci number.", "search", "Fibonacci number"),
]
TOOL_MODELS = ["hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M",
               "phi4-mini:latest", "openbmb/minicpm5-2b:latest"]
FIB_MODELS = ["opencoder:1.5b", "granite-code:3b", "openbmb/minicpm5-2b:latest"]
STAB_MODELS = ["granite3.1-moe:3b", "qwen2.5:0.5b", "gemma3:1b-it-q4_K_M"]
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
SYS = "Answer with exactly one word: YES or NO."


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
    return (body.get("message") or {}).get("content", ""), wall, body.get("eval_count", 0)


def unload(model):
    try:
        post("/api/generate", {"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def grade_tool(text, op, arg):
    """Valid JSON, right op, arg substring present in url/query."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except Exception:  # noqa: BLE001
        return False, "bad-json"
    if obj.get("op") != op:
        return False, "wrong-op"
    hay = obj.get("url", "") if op == "fetch" else obj.get("query", "")
    if not isinstance(hay, str) or arg.lower() not in hay.lower():
        return False, "wrong-arg"
    return True, "ok"


print("== TOOLS ==", flush=True)
tool_toks = {}
for model in TOOL_MODELS:
    ok, toks = 0, 0
    first_good = None
    for i, (task, op, arg) in enumerate(TOOL_TASKS):
        try:
            text, wall, ec = chat(model, TOOL_SYSTEM, task, 150)
        except Exception as exc:  # noqa: BLE001
            print(f"  {model} t{i}: ERROR {exc}", flush=True)
            continue
        toks += ec
        good, note = grade_tool(text, op, arg)
        ok += good
        if good and first_good is None:
            first_good = text
        TR.write(json.dumps({"bench": "tools", "model": model, "task": i,
                             "ok": good, "note": note, "raw": text[:300]}) + "\n")
        TR.flush()
        print(f"  {model} t{i}: {'OK' if good else note} wall={wall:.0f}s", flush=True)
    # live exec of first valid call through the real sidecar
    live = "skipped"
    if first_good:
        try:
            s, e = first_good.index("{"), first_good.rindex("}") + 1
            body, _ = post("/fetch", json.loads(first_good[s:e]), timeout=60)
            live = f"ok={body.get('ok')}"
        except Exception as exc:  # noqa: BLE001
            live = f"ERR {exc}"
    print(f"=> {model}: {ok}/6 tools, live-exec {live}, {toks} tok", flush=True)
    tool_toks[model] = toks
    unload(model)

print("== FIB RETEST (raws kept) ==", flush=True)
for model in FIB_MODELS:
    text, wall, ec = chat(model, "Reply with Python code only.",
                          "Define fib(n): 0-indexed Fibonacci, fib(0)=0, fib(1)=1.", 200)
    has_def = "def fib(" in text
    TR.write(json.dumps({"bench": "fib-retest", "model": model,
                         "has_def_fib": has_def, "raw": text[:600]}) + "\n")
    TR.flush()
    print(f"=> {model}: def fib present={has_def} wall={wall:.0f}s", flush=True)
    print(f"   raw: {text[:200]!r}", flush=True)
    unload(model)

print("== STABILITY RERUN ==", flush=True)
for model in STAB_MODELS:
    votes = []
    for i, (q, exp) in enumerate(ITEMS):
        text, wall, ec = chat(model, SYS, f"Question: {q}\nAnswer with exactly one word (YES or NO):", 8)
        toks = text.strip().upper().split()
        v = toks[0] if toks and toks[0] in ("YES", "NO") else "?"
        votes.append(v)
        TR.write(json.dumps({"bench": "stability", "model": model, "item": i,
                             "vote": v, "expected": exp}) + "\n")
        TR.flush()
    correct = sum(1 for v, (_, exp) in zip(votes, ITEMS) if v.lower() == exp)
    print(f"=> {model}: rerun {correct}/8 votes={''.join(w[0] for w in votes)}", flush=True)
    unload(model)
TR.close()
print("TOOLS-TOKENS:", json.dumps(tool_toks), flush=True)
