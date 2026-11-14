"""Flappy via Qwen3-Coder-30B (colibri on Mini, OpenAI schema over /coli).

Warmup (fib, heats experts) -> R1 full file (prompt v3gen, temp 0) -> up to
3 patch-first repair rounds driven by v3 notes (FIRST failure only), with one
full-file fallback if a diff won't apply. Grades with grade3.cjs.
Saves /tmp/flappy/coli30b_r<N>.html + /tmp/flappy_coli30b.jsonl.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

BASE = "https://mac-mini-von-hugo-1.taild73e38.ts.net/coli/v1"
MODEL = "qwen3-coder-30b-a3b-colibri"
GRADER = "/tmp/flappy-harness/grade3.cjs"
HTML_DIR = "/tmp/flappy"
TR = "/tmp/flappy_coli30b.jsonl"
GEN_DEADLINE = 3600  # 30B @ ~1-3 tok/s needs room; partial harvested

_raw = open("/tmp/flappy_prompt_v3gen.txt", encoding="utf-8").read()
SYSTEM = _raw.split("USER:")[0].replace("SYSTEM:", "").strip()
PROMPT_V3 = _raw.split("USER:")[1].strip()


def chat(messages, max_tokens, tag):
    """Stream one chat completion. Returns dict(text, done, seconds, note)."""
    box = {"parts": [], "done": False, "error": None}

    def target():
        try:
            payload = {"model": MODEL, "stream": True, "temperature": 0,
                       "max_tokens": max_tokens, "messages": messages}
            req = urllib.request.Request(
                BASE + "/chat/completions", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=600) as r:
                for ln in r:
                    s = ln.decode(errors="replace").strip()
                    if not s.startswith("data:"):
                        continue
                    data = s[5:].strip()
                    if data == "[DONE]":
                        box["done"] = True
                        break
                    try:
                        ch = json.loads(data)
                    except ValueError:
                        continue
                    try:
                        d = ch["choices"][0].get("delta", {})
                    except (KeyError, IndexError):
                        continue
                    if d.get("content"):
                        box["parts"].append(d["content"])
                    if ch["choices"][0].get("finish_reason"):
                        box["done"] = True
                        break
            box["seconds"] = round(time.time() - t0, 1)
        except Exception as exc:  # noqa: BLE001
            box["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"

    t0 = time.time()
    t = threading.Thread(target=target, daemon=True)
    t.start()
    last_tick = 0
    while t.is_alive() and time.time() - t0 < GEN_DEADLINE:
        time.sleep(10)
        el = time.time() - t0
        if el - last_tick >= 120:
            print(f"  [{tag}] {len(''.join(box['parts']))} chars, "
                  f"{int(el)}s elapsed", flush=True)
            last_tick = el
    t.join(5)
    text = "".join(box["parts"])
    if t.is_alive():
        return {"text": text, "done": False, "seconds": GEN_DEADLINE,
                "note": "deadline-partial-kept"}
    if box["error"] and not text:
        return {"text": "", "done": False, "seconds": -1,
                "note": f"ERROR {box['error']}"}
    return {"text": text, "done": box["done"],
            "seconds": box.get("seconds", round(time.time() - t0, 1)),
            "note": "ok" if box["done"] else f"ERROR {box['error']}"}


def extract_html(text):
    import re
    fenced = re.findall(r"```(?:html)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        cands = sorted(fenced, key=len, reverse=True)
        for c in cands:
            if "canvas" in c.lower():
                return c.strip()
        return cands[0].strip()
    return text.strip()


def extract_diff(text):
    import re
    fenced = re.findall(r"```(?:diff|patch)?\s*(.*?)```", text, re.S | re.I)
    body = fenced[0].strip() if fenced else text.strip()
    i = body.find("--- ")
    return body[i:] if i >= 0 else body


def l0_of(html):
    l0 = (5 if len(html) > 500 else 0)
    l0 += (5 if "canvas" in html.lower() and "script" in html.lower() else 0)
    if "```" in html:
        l0 = max(0, l0 - 5)
    return l0


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


def record(tr, rnd, kind, g, path, total, gr):
    print(f"=> coli30b R{rnd} [{kind}]: TOTAL={total}/100 "
          f"(gen {g['seconds']}s, {len(g['text'])} chars, {g['note']})",
          flush=True)
    for n in gr.get("notes", [])[:6]:
        print(f"   note: {n}", flush=True)
    tr.write(json.dumps({"round": rnd, "kind": kind, "file": path,
                         "gen_s": g["seconds"], "gen_note": g["note"],
                         "chars": len(g["text"]), "grade": gr,
                         "total": total}) + "\n")
    tr.flush()


def apply_diff(current_path, diff_text, out_path):
    with open(current_path, encoding="utf-8") as f:
        cur = f.read()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(cur)
    with tempfile.NamedTemporaryFile("w", suffix=".patch",
                                     delete=False) as f:
        f.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        pf = f.name
    p = subprocess.run(["patch", "-p1", "--fuzz=3", "--forward",
                        out_path, pf], capture_output=True, text=True,
                       timeout=30)
    os.unlink(pf)
    with open(out_path, encoding="utf-8") as f:
        new = f.read()
    return p.returncode == 0 and new != cur


def main():
    tr = open(TR, "a", encoding="utf-8")
    print("=== warmup (fib, heats experts) ===", flush=True)
    w = chat([{"role": "user", "content": "Write a Python function fib(n): "
               "0-indexed Fibonacci, fib(0)=0, fib(1)=1. Code only."}],
             200, "warmup")
    print(f"  warmup: {len(w['text'])} chars in {w['seconds']}s ({w['note']})",
          flush=True)
    print("=== coli30b R1 (full file) ===", flush=True)
    g = chat([{"role": "system", "content": SYSTEM},
              {"role": "user", "content": PROMPT_V3}], 3000, "R1")
    html = extract_html(g["text"]) if g["text"] else ""
    path = os.path.join(HTML_DIR, "coli30b_r1.html")
    open(path, "w", encoding="utf-8").write(html)
    gr = grade(path) if html else {"checks": {}, "score": 0,
                                  "notes": ["empty-html"]}
    total = l0_of(html) + gr.get("score", 0)
    record(tr, 1, "full", g, path, total, gr)
    rnd = 1
    fallback_used = False
    while total < 100 and rnd < 4:
        fails = [n for n in gr.get("notes", [])
                 if not n.startswith("cap:") and "GRADER-FAIL" not in n]
        if not fails:
            break
        rnd += 1
        first = fails[0]
        print(f"=== coli30b R{rnd} (diff repair: {first[:90]}) ===",
              flush=True)
        cur_html = open(path, encoding="utf-8").read()
        rep = chat(
            [{"role": "system", "content": "You are an expert game "
              "programmer. Output ONLY a unified diff, no explanation."},
             {"role": "user", "content":
              "This single-file Flappy Bird game has ONE bug found by an "
              f"automated play-test:\n- {first}\n\nCurrent file:\n```html\n"
              f"{cur_html}\n```\n\nFix ONLY this bug with the smallest "
              "possible change. Reply with ONLY a unified diff "
              "(--- a/game.html / +++ b/game.html headers, @@ hunks), "
              "appliable with patch -p1. No markdown fences, no commentary."}],
            1500, f"R{rnd}")
        new_path = os.path.join(HTML_DIR, f"coli30b_r{rnd}.html")
        if rep["text"] and apply_diff(path, extract_diff(rep["text"]),
                                      new_path):
            kind = "diff"
            print(f"  diff applied cleanly", flush=True)
        elif not fallback_used:
            fallback_used = True
            print("  diff failed to apply; falling back to full file",
                  flush=True)
            rep = chat(
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": PROMPT_V3 + "\n\nYOUR PREVIOUS "
                  "ATTEMPT FAILED THIS AUTOMATED PLAY-TEST:\n- " + first +
                  "\nFix it with the smallest change that keeps everything "
                  "else working. Reply with HTML code only."}],
                3000, f"R{rnd}fb")
            html2 = extract_html(rep["text"]) if rep["text"] else ""
            open(new_path, "w", encoding="utf-8").write(html2)
            kind = "full-fallback"
        else:
            print("  diff failed, no fallback left; stopping", flush=True)
            break
        html = open(new_path, encoding="utf-8").read()
        gr = grade(new_path) if html else {"checks": {}, "score": 0,
                                          "notes": ["empty-html"]}
        total = l0_of(html) + gr.get("score", 0)
        path = new_path
        record(tr, rnd, kind, rep, path, total, gr)
    tr.close()
    print(f"COLI30B-DONE best_file={path} total={total}", flush=True)


if __name__ == "__main__":
    main()
