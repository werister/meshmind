"""Lab bench 5: reasoning tier. 3 models x 4 graded multi-step items.
granite4.2: think=true + 900 budget (house lane). nemotron: default first,
think:true+900 fallback on empty. minicpm: think=false.
Transcript -> /tmp/lab_bench5_transcript.jsonl (local only)."""
import json
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TR = open("/tmp/lab_bench5_transcript.jsonl", "w")

ITEMS = [
    {"id": "apples", "expect": "20",
     "prompt": "A store sells apples in bags of 6. Maria buys 8 bags, eats 8 apples, then gives away exactly half of what remains. How many apples does she have left? Reply with the number only."},
    {"id": "train", "expect": "4",
     "prompt": "A train travels 120 km at 60 km/h, then 180 km at 90 km/h. How many hours is the total trip? Reply with the number only."},
    {"id": "syllogism", "expect": "C",
     "prompt": "All bloops are razzes. Some razzes are zazzes. Which MUST be true? A) Some bloops are zazzes. B) All zazzes are bloops. C) None of the above can be concluded. Reply with the letter only."},
    {"id": "batball", "expect": "5",
     "prompt": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How many cents does the ball cost? Reply with the number only."},
]
MODELS = [
    ("granite4.2:3b-q4_K_M", True, 900),
    ("nemotron-3-nano:4b", None, 300),
    ("openbmb/minicpm5-2b:latest", False, 300),
]


def post(path, payload, timeout=900):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def ask(model, think, budget, prompt):
    payload = {"model": model, "stream": False,
               "messages": [{"role": "user", "content": prompt}],
               "options": {"temperature": 0, "num_predict": budget}}
    if think is not None:
        payload["think"] = think
    body, wall = post("/api/chat", payload)
    text = (body.get("message") or {}).get("content", "")
    return text, wall, body.get("eval_count", 0)


def grade(text, expect):
    t = text.strip()
    if not t:
        return False, "empty"
    if expect.isdigit():
        import re
        nums = re.findall(r"-?\d+", t.replace(",", ""))
        return (nums and nums[-1] == expect), f"lastnum={nums[-1] if nums else None}"
    return (t.strip().upper().startswith(expect)), f"first={t.strip()[:8]!r}"


def unload(model):
    try:
        post("/api/generate", {"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


totals = {}
for model, think, budget in MODELS:
    print(f"=== {model} (think={think}) ===", flush=True)
    score, toks = 0, 0
    for it in ITEMS:
        try:
            text, wall, ec = ask(model, think, budget, it["prompt"])
        except Exception as exc:  # noqa: BLE001
            print(f"  {it['id']}: ERROR {exc}", flush=True)
            continue
        if not text.strip() and think is None:
            text, wall2, ec2 = ask(model, True, 900, it["prompt"])
            wall += wall2
            ec += ec2
            print(f"  {it['id']}: retried with think=true", flush=True)
        toks += ec
        good, note = grade(text, it["expect"])
        score += good
        TR.write(json.dumps({"model": model, "item": it["id"], "ok": good,
                             "note": note, "wall_s": round(wall, 1),
                             "raw": text[:300]}) + "\n")
        TR.flush()
        print(f"  {it['id']}: {'OK' if good else 'MISS'} ({note}) wall={wall:.0f}s", flush=True)
    print(f"=> {model}: {score}/4, {toks} tok", flush=True)
    totals[model] = [score, toks]
    unload(model)
TR.close()
print("TOTALS-REASON:", json.dumps(totals), flush=True)
