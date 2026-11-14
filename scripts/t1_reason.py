"""Round-two T1: think-ON arbitration for the thinking-tier dispute.

qwen3:4b-thinking scored 0/18 as a voter with think=false (unfair test for a
thinking model). Fair retest: think=true + 900 budget, same 4 graded items and
same grader as lab_bench5_reason.py, plus the same-size instruct sibling as a
think=false control. Resume-safe. Transcript -> /tmp/t1_reason_transcript.jsonl.
"""
"""Provenance: built 2026-11-13 during the Nov 13-14 lab campaign (41-model sweeps);
landed in meshmind via feat/nov13-benchmarks. Lab: CPU-only Ollama Mini."""

import concurrent.futures
import json
import os
import re
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
TR_PATH = "/tmp/t1_reason_transcript.jsonl"

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
# Every model on the box that can think (instruct-only models hard-error on
# think=true server-side, so they stay out). think=None = default first with a
# think=true+900 fallback on empty (bench5 precedent). granite4.2 excluded:
# already measured 4/4 on these exact items.
MODELS = [
    ("qwen3:4b-thinking-2507-q4_K_M", True, 900),
    ("qwen3:8b", True, 900),
    ("qwen3:1.7b", True, 900),
    ("qwen3:0.6b", True, 900),
    ("nemotron-3-nano:4b", None, 300),
    ("rwkv7-g1g-proof:latest", None, 300),
    ("qwen3:4b-instruct-2507-q4_K_M", False, 300),
]


def post(path, payload, timeout=900):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, time.time() - t0


def post_hard(path, payload, timeout=900, deadline=960):
    """post() with an overall wall-clock deadline (trickle-proof).

    Daemon thread: abandoned calls leak but never block the sweep or
    process exit. (ThreadPoolExecutor.__exit__ waits -- must NOT be used.)
    """
    import threading
    box = {}

    def target():
        try:
            box["res"] = post(path, payload, timeout)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(deadline)
    if t.is_alive():
        raise TimeoutError(f"call exceeded hard deadline {deadline}s")
    if "err" in box:
        raise box["err"]
    return box["res"]


def ask(model, think, budget, prompt):
    payload = {"model": model, "stream": False,
               "messages": [{"role": "user", "content": prompt}],
               "options": {"temperature": 0, "num_predict": budget}}
    if think is not None:
        payload["think"] = think
    body, wall = post_hard("/api/chat", payload)
    text = (body.get("message") or {}).get("content", "")
    return text, wall, body.get("eval_count", 0)


def grade(text, expect):
    t = text.strip()
    if not t:
        return False, "empty"
    if expect.isdigit():
        nums = re.findall(r"-?\d+", t.replace(",", ""))
        return (nums and nums[-1] == expect), f"lastnum={nums[-1] if nums else None}"
    return (t.strip().upper().startswith(expect)), f"first={t.strip()[:8]!r}"


def unload(model):
    try:
        post("/api/generate", {"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def done_pairs():
    done = set()
    if os.path.exists(TR_PATH):
        for ln in open(TR_PATH, encoding="utf-8"):
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if row.get("model") and row.get("item"):
                done.add((row["model"], row["item"]))
    return done


def main():
    skip = done_pairs()
    print(f"resume: {len(skip)} pairs already complete", flush=True)
    tr = open(TR_PATH, "a", encoding="utf-8")
    totals = {}
    for model, think, budget in MODELS:
        print(f"=== {model} (think={think}) ===", flush=True)
        score, toks = 0, 0
        for it in ITEMS:
            if (model, it["id"]) in skip:
                print(f"  {it['id']}: skipped (done)", flush=True)
                continue
            try:
                text, wall, ec = ask(model, think, budget, it["prompt"])
            except Exception as exc:  # noqa: BLE001
                tr.write(json.dumps({"model": model, "item": it["id"],
                                     "error": str(exc)[:200]}) + "\n")
                tr.flush()
                print(f"  {it['id']}: ERROR {str(exc)[:100]}", flush=True)
                continue
            if not text.strip() and think is None:
                text, wall2, ec2 = ask(model, True, 900, it["prompt"])
                wall += wall2
                ec += ec2
                print(f"  {it['id']}: retried with think=true", flush=True)
            toks += ec
            good, note = grade(text, it["expect"])
            score += good
            tr.write(json.dumps({"model": model, "item": it["id"], "ok": good,
                                 "note": note, "wall_s": round(wall, 1),
                                 "raw": text[:2000]}) + "\n")
            tr.flush()
            print(f"  {it['id']}: {'OK' if good else 'MISS'} ({note}) wall={wall:.0f}s", flush=True)
        print(f"=> {model}: {score}/4 new-scored, {toks} tok", flush=True)
        totals[model] = [score, toks]
        unload(model)
    tr.close()
    print("TOTALS-T1: " + json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
