"""Flappy Bird end-to-end benchmark: every lab model writes a complete game.

One fixed prompt (/tmp/flappy_prompt.txt): single-file HTML5 Flappy Bird.
Generation: /api/chat stream:true (partial kept on deadline), think:false,
temp 0, num_predict 3500 (~3.75k total context: within the 4k house cap).
Grading: node /tmp/flappy-harness/grade.mjs (L1-L4, 90pts) + L0 static (10).
Outputs: /tmp/flappy/<slug>.html + /tmp/flappy_transcript.jsonl (resume-safe).
Usage: flappy_run.py [--models sub1,sub2]  (substring filter; default: all chat models)
"""
"""Provenance: built 2026-11-14 during the Nov 13-14 lab campaign (Flappy end-to-end app bench);
landed in meshmind via feat/nov13-benchmarks. Lab: CPU-only Ollama Mini."""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net"
ROOT = os.path.dirname(os.path.abspath(__file__))
PROMPT = open(os.path.join(ROOT, "prompt.txt"), encoding="utf-8").read()
TR_PATH = os.environ.get("FLAPPY_TRANSCRIPT", os.path.join(ROOT, "flappy_transcript.jsonl"))
HTML_DIR = os.path.join(ROOT, "games")
GRADER = os.path.join(ROOT, "grade.cjs")
GEN_DEADLINE = 1500  # 25 min per model max; partial kept
EMBED_SKIP = ("qwen3-embedding", "bge-m3", "nomic-embed-text")


def get_tags():
    with urllib.request.urlopen(BASE + "/api/tags", timeout=30) as r:
        return json.loads(r.read().decode()).get("models", [])


def slug(name):
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")[:80]


REPAIR_HINTS = {
    "no_errors": "your code threw JavaScript errors; fix them",
    "has_canvas": "include a <canvas> element",
    "animates": "drive the game continuously (requestAnimationFrame loop)",
    "hooks": "expose window.__flappy = {y, score, over} updated every frame",
    "gravity": "the bird must fall when there is no input",
    "flap": "Space/click must make the bird rise",
    "scores": "passing a pipe must increment score",
    "gameover": "collision or ground must end the run (over=true)",
    "restart": "after game over, click or R must restart with score 0",
}


def build_repair_prompt(checks):
    failed = [f"- {k}: {REPAIR_HINTS[k]}" for k in REPAIR_HINTS if not checks.get(k)]
    return (PROMPT + "\n\nYOUR PREVIOUS ATTEMPT FAILED THESE CHECKS:\n"
            + "\n".join(failed)
            + "\nRewrite the complete game fixing ALL of them. Reply with HTML code only.")


def generate(model, prompt=None):
    """Stream one generation. Returns dict(text, done, eval_count, seconds, note).

    Partial text is harvested even on deadline (shared parts list), so slow
    models still grade what they produced instead of losing everything.
    """
    box = {"parts": [], "eval_count": None, "done": False, "error": None}

    def target():
        try:
            payload = {"model": model, "stream": True, "think": False,
                       "messages": [{"role": "user", "content": prompt or PROMPT}],
                       "options": {"temperature": 0, "num_predict": 3500}}
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

    t0 = time.time()
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(GEN_DEADLINE)
    text = "".join(box["parts"])
    if t.is_alive():
        return {"text": text, "done": False, "eval_count": box["eval_count"],
                "seconds": GEN_DEADLINE, "note": "gen-deadline-partial-kept"}
    if box["error"] and not text:
        return {"text": "", "done": False, "eval_count": None, "seconds": -1,
                "note": f"ERROR {box['error']}"}
    return {"text": text, "done": box["done"], "eval_count": box["eval_count"],
            "seconds": box.get("seconds", round(time.time() - t0, 1)),
            "note": "ok" if box["done"] else ("stream-ended-early" if not box["error"]
                                              else f"ERROR {box['error']}")}


def unload(model):
    def target():
        try:
            urllib.request.urlopen(urllib.request.Request(
                BASE + "/api/generate",
                data=json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode(),
                headers={"Content-Type": "application/json"}, method="POST"), timeout=60)
        except Exception:  # noqa: BLE001 - best effort
            pass

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(45)


def extract_html(text):
    fenced = re.findall(r"```(?:html)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        # prefer the largest fenced block containing canvas
        cands = sorted(fenced, key=len, reverse=True)
        for c in cands:
            if "canvas" in c.lower():
                return c.strip()
        return cands[0].strip()
    return text.strip()


def grade_file(path):
    env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = "/tmp/pw-browsers"
    try:
        p = subprocess.run(["node", GRADER, path], capture_output=True, text=True,
                           timeout=240, cwd="/tmp/flappy-harness", env=env)
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"checks": {}, "score": 0, "notes": [f"GRADER-FAIL {type(exc).__name__}"]}


def grade_and_record(tr, model, rnd, g):
    html = extract_html(g["text"]) if g["text"] else ""
    path = os.path.join(HTML_DIR, slug(model) + f"_r{rnd}.html")
    open(path, "w", encoding="utf-8").write(html)
    l0 = (5 if len(html) > 500 else 0) + (5 if "canvas" in html.lower() and "script" in html.lower() else 0)
    gr = grade_file(path) if html else {"checks": {}, "score": 0, "notes": ["empty-html"]}
    total = l0 + gr.get("score", 0)
    print(f"=> {model} R{rnd}: L0={l0} grade={gr.get('score', 0)} TOTAL={total}/100 "
          f"notes={gr.get('notes', [])[:2]}", flush=True)
    tr.write(json.dumps({"model": model, "round": rnd, "done": g["done"],
                         "chars": len(g["text"]), "eval_count": g["eval_count"],
                         "gen_s": g["seconds"], "gen_note": g["note"],
                         "l0": l0, "grade": gr, "total": total}) + "\n")
    tr.flush()
    return total, gr.get("checks", {})


def done_models():
    done = set()
    if os.path.exists(TR_PATH):
        for ln in open(TR_PATH, encoding="utf-8"):
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if not row.get("model"):
                continue
            if row.get("round") == 2:
                done.add(row["model"])
            elif row.get("round") == 1 and row.get("total") == 100:
                done.add(row["model"])  # perfect single-shot: no repair round
    return done


def main():
    filt = []
    if len(sys.argv) > 1 and sys.argv[1] == "--models":
        filt = sys.argv[2].split(",")
    tags = get_tags()
    models = [m["name"] for m in tags
              if not any(s in m["name"] for s in EMBED_SKIP)]
    models.sort(key=lambda n: next((m.get("size", 0) for m in tags if m["name"] == n), 0))
    if filt:
        models = [m for m in models if any(s in m for s in filt)]
    print(f"flappy: {len(models)} models (embeds excluded)", flush=True)
    os.makedirs(HTML_DIR, exist_ok=True)
    skip = done_models()
    print(f"resume: {len(skip)} already graded", flush=True)
    tr = open(TR_PATH, "a", encoding="utf-8")
    for model in models:
        if model in skip:
            print(f"=== {model} (skipped, done) ===", flush=True)
            continue
        print(f"=== {model} R1 ===", flush=True)
        g = generate(model)
        print(f"  gen: done={g['done']} chars={len(g['text'])} eval={g['eval_count']} "
              f"s={g['seconds']} ({g['note']})", flush=True)
        total1, checks1 = grade_and_record(tr, model, 1, g)
        if total1 < 100:
            print(f"=== {model} R2 (repair) ===", flush=True)
            g2 = generate(model, build_repair_prompt(checks1))
            print(f"  gen: done={g2['done']} chars={len(g2['text'])} eval={g2['eval_count']} "
                  f"s={g2['seconds']} ({g2['note']})", flush=True)
            grade_and_record(tr, model, 2, g2)
        unload(model)
    tr.close()
    print("FLAPPY-DONE", flush=True)


if __name__ == "__main__":
    main()
