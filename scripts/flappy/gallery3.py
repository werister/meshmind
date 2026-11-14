"""Regenerate /tmp/flappy/index.html with v1+v2+v3 columns + colibri row.

Sources: /tmp/flappy_transcript.jsonl (v1), /tmp/flappy_v2.jsonl,
/tmp/flappy_v3.jsonl, /tmp/flappy_coli30b.jsonl. Re-run after new rows land.
"""
import json
import os
import re

SRC = os.environ.get("FLAPPY_SRC", "/tmp")
OUT = os.environ.get("FLAPPY_GALLERY_OUT", "/tmp/flappy/index.html")


def slug(name):
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")[:80]


def load(path, tkey="total"):
    d = {}
    try:
        for ln in open(path, encoding="utf-8"):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("model") and r.get("round"):
                d[(r["model"], r["round"])] = r.get(tkey)
    except FileNotFoundError:
        pass
    return d


v1 = load(os.path.join(SRC, "flappy_transcript.jsonl"))
v2 = load(os.path.join(SRC, "flappy_v2.jsonl"))
v3 = load(os.path.join(SRC, "flappy_v3.jsonl"))

models = sorted({m for (m, _) in set(v1) | set(v2) | set(v3)},
                key=lambda m: -max(v3.get((m, 1), -1), v3.get((m, 2), -1)))

rows = []
for m in models:
    b1, b2 = v3.get((m, 1)), v3.get((m, 2))
    best = max([x for x in (b1, b2) if x is not None], default=-1)
    cls = " class=hi" if best >= 60 else ""

    def cell(d, rnd, bestv):
        v = d.get((m, rnd))
        if v is None:
            return "-"
        s = str(v)
        if d is v3 and v == bestv:
            s = f"<b>{s}</b>"
        return s

    s = slug(m)
    play = (f'<a href="{s}_r1.html">R1</a> '
            f'<a href="{s}_r2.html">R2</a>')
    rows.append(
        f"<tr{cls}><td>{m}</td><td>{v1.get((m, 1), '-')}</td>"
        f"<td>{v1.get((m, 2), '-')}</td><td>{v2.get((m, 1), '-')}</td>"
        f"<td>{v2.get((m, 2), '-')}</td><td>{cell(v3, 1, best)}</td>"
        f"<td>{cell(v3, 2, best)}</td><td>{play}</td></tr>")

coli = []
try:
    for ln in open(os.path.join(SRC, "flappy_coli30b.jsonl"), encoding="utf-8"):
        r = json.loads(ln)
        if "total" in r:
            coli.append(r)
except FileNotFoundError:
    pass
if coli:
    links = " ".join(
        f'<a href="coli30b_r{r["round"]}.html">R{r["round"]} '
        f'({r["total"]})</a>' for r in coli)
    best_c = max(r["total"] for r in coli)
    rows.insert(0, f'<tr class=hi><td>Qwen3-Coder-30B (colibri) &#9733; '
                   f'human crown</td><td>-</td><td>-</td><td>-</td><td>-</td>'
                   f'<td colspan=2><b>{best_c}</b> (prompt v3gen)</td>'
                   f'<td>{links}</td></tr>')

html = """<!DOCTYPE html><html><head><meta charset=utf-8><title>Flappy lab benchmark FINAL (v3)</title>
<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px 8px;text-align:left}th{background:#f0f0f0}.hi{background:#e6f4ea}.banner{background:#fff8e1;border:1px solid #e0c36a;padding:10px 14px;border-radius:6px}</style></head><body>
<h1>Flappy Bird lab benchmark &mdash; final (38 Ollama models + Qwen3-Coder-30B)</h1>
<div class=banner><b>Honesty banner.</b> v1 graded mechanics only and crowned decorative games (see v3 collapse below).
v2 added visibility, paced scoring, bounded physics. <b>v3 is input-causal:</b> control-vs-treatment flap test, hands-off-vs-autopilot scoring arms,
flight filter (scores count only from lives where the bird flew), floor-death check, and hard caps (no input response &rarr; max 35, nothing flown+scored &rarr; max 50).
Machine tie at 90 (gemma4 R1, coli30b R1) broken by owner play-test: <b>coli30b R1 crowned &ldquo;by far the best&rdquo; (2026-11-14)</b>.
Known calibration wrinkle: the <tt>visible</tt> gate samples the first 600ms, so legit tap-to-start screens fail it &mdash; both 90s fail only that gate.</div>
<p>v3 = input-causal grade (best of R1/R2 bolded). R1 = single shot, R2 = repair with failure feedback (note: repairs sometimes HURT &mdash; gemma4 R1 90 &rarr; R2 35).
Click to play. 30B run: research-built prompt v3gen, temp 0, patch-first repairs.</p>
<table><tr><th>model</th><th>v1 R1</th><th>v1 R2</th><th>v2 R1</th><th>v2 R2</th><th>v3 R1</th><th>v3 R2</th><th>play</th></tr>
""" + "\n".join(rows) + """
</table>
<p><small>Grader: grade3.cjs (control-treatment physics, two-arm input-causal scoring, flight filter, floor check, hard caps).
Ref calibration: ref-good 90/90 twice, ref-bad 10. Transcripts: flappy_transcript.jsonl (v1), flappy_v2.jsonl, flappy_v3.jsonl, flappy_coli30b.jsonl.</small></p>
</body></html>
"""
open(OUT, "w", encoding="utf-8").write(html)
print(f"gallery: {len(rows)} rows -> {OUT}")
