"""One-model Flappy retry with the hardened v2 prompt + v3 grader.

R1: prompt v2. If v3 total < 100: R2 repair with the v3 notes fed back.
Saves /tmp/flappy/<slug>_retry<N>.html (never overwrites R1/R2), grades with
grade3.cjs, unloads the model after. Lab use: 1-2 serial generations.
Usage: flappy_retry1.py <model>   (model reasoning -> think:true)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/tmp")
from flappy_run import slug, extract_html, unload  # noqa: E402

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
PROMPT = open("/tmp/flappy_prompt_v2.txt", encoding="utf-8").read()
GRADER = "/tmp/flappy-harness/grade3.cjs"
HTML_DIR = "/tmp/flappy"
DEADLINE = 1500

REASONING = ("nemotron-3-nano", "qwen3:", "qwq", "deepseek-r1", "r1-",
             "thinking", "rwkv7-g1g", "marco", "openthinker")


def generate(model, prompt):
    box = {"parts": [], "eval_count": None, "done": False, "error": None,
           "think_chars": 0}

    def target():
        try:
            think = any(s in model for s in REASONING)
            payload = {"model": model, "stream": True, "think": think,
                       "messages": [{"role": "user", "content": prompt}],
                       "options": {"temperature": 0, "num_predict": 3500,
                                   "num_ctx": 8192}}
            print(f"  gen opts: think={think} num_ctx=8192 num_predict=3500",
                  flush=True)
            req = urllib.request.Request(
                BASE + "/api/chat", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=600) as r:
                for ln in r:
                    try:
                        chunk = json.loads(ln.decode())
                    except ValueError:
                        continue
                    msg = chunk.get("message") or {}
                    if msg.get("thinking"):
                        box["think_chars"] += len(msg["thinking"])
                    if msg.get("content"):
                        box["parts"].append(msg["content"])
                    if chunk.get("eval_count") is not None:
                        box["eval_count"] = chunk["eval_count"]
                    if chunk.get("done"):
                        box["done"] = True
                        break
            box["seconds"] = round(time.time() - t0, 1)
        except Exception as exc:  # noqa: BLE001
            box["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"

    import threading
    t0 = time.time()
    t = threading.Thread(target=target, daemon=True)
    t.start()
    while t.is_alive() and time.time() - t0 < DEADLINE:
        time.sleep(5)
        n = len("".join(box["parts"]))
        if n:
            print(f"  ... {n} chars ({int(time.time()-t0)}s)", flush=True)
            break
    t.join(max(0, DEADLINE - (time.time() - t0)))
    text = "".join(box["parts"])
    if t.is_alive():
        return {"text": text, "done": False, "note": "deadline-partial-kept",
                "eval_count": box["eval_count"], "seconds": DEADLINE,
                "think_chars": box["think_chars"]}
    return {"text": text, "done": box["done"], "eval_count": box["eval_count"],
            "seconds": box.get("seconds", round(time.time() - t0, 1)),
            "think_chars": box["think_chars"],
            "note": "ok" if box["done"] else f"ERROR {box['error']}"}


def grade(path):
    env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = "/tmp/pw-browsers"
    try:
        p = subprocess.run(["node", GRADER, path], capture_output=True,
                           text=True, timeout=240, cwd="/tmp/flappy-harness",
                           env=env)
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"checks": {}, "score": 0,
                "notes": [f"GRADER-FAIL {type(exc).__name__}"]}


def main():
    model = sys.argv[1]
    print(f"retry1: {model} with prompt-v2 + grade3", flush=True)
    notes_feed = ""
    for rnd in (1, 2):
        prompt = PROMPT if rnd == 1 else (
            PROMPT + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE AUTOMATED "
            "PLAY-TESTS:\n" + notes_feed +
            "\nRewrite the complete game fixing ALL of them. Reply with HTML code only.")
        print(f"=== {model} retry-R{rnd} ===", flush=True)
        g = generate(model, prompt)
        print(f"  gen: done={g['done']} chars={len(g['text'])} "
              f"think_chars={g['think_chars']} s={g['seconds']} ({g['note']})",
              flush=True)
        html = extract_html(g["text"]) if g["text"] else ""
        path = os.path.join(HTML_DIR, slug(model) + f"_retry{rnd}.html")
        open(path, "w", encoding="utf-8").write(html)
        l0 = ((5 if len(html) > 500 else 0)
              + (5 if "canvas" in html.lower() and "script" in html.lower()
                 else 0))
        if "```" in html:
            l0 = max(0, l0 - 5)
        gr = grade(path) if html else {"checks": {}, "score": 0,
                                      "notes": ["empty-html"]}
        total = l0 + gr.get("score", 0)
        print(f"=> {model} retry-R{rnd}: L0={l0} grade={gr.get('score', 0)} "
              f"TOTAL={total}/100", flush=True)
        for n in gr.get("notes", [])[:6]:
            print(f"   note: {n}", flush=True)
        open("/tmp/flappy_retry1.jsonl", "a", encoding="utf-8").write(
            json.dumps({"model": model, "round": rnd, "prompt": "v2",
                        "gen_s": g["seconds"], "think_chars": g["think_chars"],
                        "l0": l0, "grade": gr, "total": total}) + "\n")
        if total >= 100:
            print("RETRY-PERFECT", flush=True)
            break
        notes_feed = "\n".join(f"- {n}" for n in gr.get("notes", []))
    unload(model)
    print("RETRY-DONE", flush=True)


if __name__ == "__main__":
    main()
