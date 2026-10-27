#!/usr/bin/env python3
"""Local AI lab sidecar: feedback receiver plus status/dashboard showcase.

POST /feedback {"agent","model","ok","note","tokens"} -> feedback.log (JSONL)
GET  /status    -> live JSON: availability, token totals, models, feedback
GET  /dashboard -> auto-refreshing HTML showcase page (mml Apple-light styling)
GET  /agents.md -> the agent quickstart doc, served over HTTPS
"""
import html
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LAB = os.path.join(os.path.expanduser("~"), "local-ai-lab")
FB = os.path.join(LAB, "feedback.log")
HEALTH = os.path.join(LAB, "health.log")
STATE = os.path.join(LAB, "monitor-state")
AGENTS_MD = os.path.join(LAB, "AGENTS.md")
OLLAMA = "http://127.0.0.1:11434"
STARTED = time.time()
MEASURED_MAX = {
    "functiongemma:latest": "16k",
    "gemma2:2b": "8k",
    "qwen2.5:0.5b": "4k",
    "qwen2.5:3b": "4k",
    "qwen2.5-coder:3b": "4k",
    "llama3.2:3b": "4k",
    "qwen3:4b": "4k",
    "phi4-mini:latest": "4k",
    "athena-slm:latest": "~2k",
    "phi3:latest": "~2k",
    "phi3.5:3.8b": "~2k",
    "deepseek-r1:8b": "untested",
    "qwen2.5:14b": "untested",
}

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def fmt_dur(s):
    s = int(s)
    if s < 90:
        return str(s) + "s"
    if s < 5400:
        return str(round(s / 60)) + "m"
    if s < 129600:
        return str(round(s / 3600)) + "h"
    return str(round(s / 86400)) + "d"

def read_last_line(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            n = f.tell()
            if n == 0:
                return ""
            step = min(n, 4096)
            f.seek(n - step)
            tail = f.read().decode("utf-8", "replace")
        lines = [x for x in tail.split("\n") if x.strip()]
        return lines[-1] if lines else ""
    except Exception:
        return ""

def read_int(path):
    try:
        with open(path) as f:
            t = f.read().strip()
        return int("".join([c for c in t if c.isdigit()]) or 0)
    except Exception:
        return 0

def feedback_full():
    n = 0
    toks = 0
    last = None
    per_model = {}
    recent = []
    try:
        with open(FB) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                n += 1
                t = 0
                try:
                    t = max(0, int(d.get("tokens", 0) or 0))
                except Exception:
                    pass
                toks += t
                last = d
                recent.append(d)
                m = str(d.get("model", "?"))
                if m not in ("", "?", "none"):
                    e = per_model.get(m, {"calls": 0, "tokens": 0, "last": ""})
                    e["calls"] += 1
                    e["tokens"] += t
                    e["last"] = str(d.get("ts", ""))
                    per_model[m] = e
    except Exception:
        pass
    return n, toks, last, per_model, recent[-5:][::-1]

def ollama_get(path, timeout=8):
    try:
        with urllib.request.urlopen(OLLAMA + path, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None

def parse_health(line):
    parts = line.split(" ")
    out = {"at": parts[0] if parts else ""}
    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            if k not in out:
                out[k] = v
    return out

def probe_history(n=24):
    vals = []
    try:
        with open(HEALTH) as f:
            for line in f:
                for part in line.split(" "):
                    if part.startswith("probe_tok_s="):
                        try:
                            vals.append(float(part.split("=", 1)[1]))
                        except Exception:
                            pass
    except Exception:
        pass
    return vals[-n:]

def sparkline(vals):
    blocks = "▁▂▃▄▅▆▇█"
    if not vals:
        return "—"
    lo = min(vals)
    hi = max(vals)
    if hi <= lo:
        return blocks[3] * len(vals)
    out = []
    for v in vals:
        idx = int((v - lo) / (hi - lo) * 7)
        out.append(blocks[idx])
    return "".join(out)

def build_status():
    ver = ollama_get("/api/version")
    ps = ollama_get("/api/ps") or {}
    tags = ollama_get("/api/tags") or {}
    h = parse_health(read_last_line(HEALTH))
    fbn, fbtoks, fblast, per_model, recent = feedback_full()
    ptot = read_int(STATE)
    loaded_names = {}
    for m in ps.get("models", []):
        loaded_names[m.get("name", "?")] = True
    models = []
    for t in tags.get("models", []):
        name = t.get("name", "?")
        det = t.get("details", {}) or {}
        pm = per_model.get(name, {"calls": 0, "tokens": 0, "last": ""})
        models.append({"name": name, "size_mb": round((t.get("size", 0) or 0) / 1048576), "params": det.get("parameter_size", "?") or "?", "max_ctx_measured": MEASURED_MAX.get(name, "?"), "loaded": name in loaded_names, "calls": pm["calls"], "tokens": pm["tokens"], "last_called": pm["last"]})
    models.sort(key=lambda m: (-m["calls"], m["name"]))
    hist = probe_history(24)
    return {
        "ts": utcnow(),
        "service_uptime_s": int(time.time() - STARTED),
        "ollama": {"up": ver is not None, "version": (ver or {}).get("version", "?"), "installed": len(models)},
        "health": {"local": h.get("local", "?"), "serve": h.get("serve", "?"), "at": h.get("at", "?"), "probe_tok_s": h.get("probe_tok_s", "?")},
        "tokens": {"probe_total": ptot, "feedback_total": fbtoks, "grand_total": ptot + fbtoks},
        "feedback": {"n": fbn, "latest": fblast, "recent": recent},
        "models": models,
        "activity": {"probe_tok_s_last24": hist},
    }

CSS = ":root{--bg:#F5F5F7;--surface:#FFFFFF;--surface2:#F2F2F2;--line:#E8E8ED;--fg:#1D1D1F;--fg2:#6E6E73;--accent:#0071E3;--accent-text:#0066CC;--green:#1F7A34;--red:#D70015;--radius:10px;--radius-sm:6px}*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg);color:var(--fg);font:17px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;padding:0 24px 96px}.wrap{max-width:800px;margin:0 auto}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}.dim{color:var(--fg2)}.hero{padding-top:56px;margin-bottom:40px}.kicker{font-size:12px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--fg2);margin-bottom:12px}h1{font-size:clamp(40px,5vw,56px);font-weight:700;letter-spacing:-.02em;line-height:1.05;margin:0 0 8px}h2{font-size:24px;font-weight:600;letter-spacing:-.01em;margin:0 0 16px}h2 .sub2{color:var(--fg2);font-size:14px;font-weight:400}.sub{color:var(--fg2);font-size:19px;margin:0 0 16px}.pill{display:inline-block;font-size:13px;font-weight:700;padding:6px 14px;border-radius:999px;background:var(--surface);border:1px solid var(--line)}.pill.ok{color:var(--green)}.pill.fail{color:var(--red)}.section{margin-bottom:56px}.bignum{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;font-size:clamp(56px,9vw,84px);font-weight:700;letter-spacing:-.03em;line-height:1}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px}.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px}.card .label{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--fg2);margin-bottom:6px}.card .value{font-size:30px;font-weight:700;letter-spacing:-.5px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;line-height:1.2}.verdict{background:var(--surface);border:1.5px solid var(--accent);border-radius:var(--radius);padding:20px 28px}.verdict .vtext{font-size:18px;font-weight:500;line-height:1.45}.verdict .vmetrics{color:var(--fg2);font-size:13px;margin-top:12px}.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface)}table{width:100%;border-collapse:collapse;font-size:13px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}th,td{text-align:left;padding:8px 14px;border-bottom:1px solid var(--line);white-space:nowrap}tr:last-child td{border-bottom:0}th{color:var(--fg2);font-weight:600;font-size:11px;letter-spacing:.05em;text-transform:uppercase;background:var(--surface2)}.loaded-dot{color:var(--green);font-weight:700}tbody tr:hover td{background:var(--surface2)}.trend-row{display:flex;gap:16px;align-items:center;padding:14px 0;border-bottom:1px solid var(--line)}.trend-row .tname{width:210px;color:var(--fg2);font-size:13px;flex-shrink:0}.spark{font-family:ui-monospace,SFMono-Regular,monospace;letter-spacing:1px;font-size:16px}.trend-verdict{color:var(--fg2);font-size:13px}.fb{border-bottom:1px solid var(--line);padding:10px 0;font-size:14px}.fb:last-child{border-bottom:0}.fb .who{font-weight:600}.fb .note{color:var(--fg2)}footer{color:var(--fg2);font-size:13px;margin-top:24px}a{color:var(--accent-text)}a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.small{font-size:13px}@media (max-width:600px){.trend-row{flex-wrap:wrap}.trend-row .tname{width:100%}}@media (prefers-color-scheme:dark){:root{--bg:#1D1D1F;--surface:#2C2C2E;--surface2:#3A3A3C;--line:#48484A;--fg:#F5F5F7;--fg2:#A1A1A6;--accent:#0A84FF;--accent-text:#409CFF;--green:#30D158;--red:#FF453A}}"

def build_dashboard(st):
    ok = st["health"]["local"] == "OK" and st["health"]["serve"] == "OK"
    pcls = "ok" if ok else "fail"
    pword = "ALL SYSTEMS GO" if ok else "DEGRADED"
    rows = []
    for m in st["models"]:
        dot = "<span class=\"loaded-dot\">● loaded</span>" if m["loaded"] else "<span class=\"dim\">idle</span>"
        calls = str(m["calls"]) if m["calls"] else "<span class=\"dim\">0</span>"
        rows.append("<tr><td>" + html.escape(m["name"]) + "</td><td>" + html.escape(str(m["params"])) + "</td><td>" + str(m["size_mb"]) + " MB</td><td>" + html.escape(str(m["max_ctx_measured"])) + "</td><td>" + calls + "</td><td>" + str(m["tokens"]) + "</td><td>" + dot + "</td></tr>")
    fbs = []
    for e in st["feedback"]["recent"]:
        mark = "yes" if e.get("ok") else "no"
        fbs.append("<div class=\"fb\"><span class=\"who\">" + html.escape(str(e.get("agent", "?"))) + "</span> on <span class=\"mono\">" + html.escape(str(e.get("model", "?"))) + "</span> [" + mark + "] <span class=\"note\">" + html.escape(str(e.get("note", ""))) + "</span> <span class=\"dim\">· " + str(e.get("tokens", 0)) + " tok</span></div>")
    if not fbs:
        fbs.append("<div class=\"fb dim\">No agent reports yet — be the first: POST /feedback.</div>")
    hist = st["activity"]["probe_tok_s_last24"]
    sp = sparkline(hist)
    if hist:
        trend_v = "last " + str(round(hist[-1], 1)) + " · max " + str(round(max(hist), 1)) + " tok/s"
    else:
        trend_v = "no samples yet"
    p = []
    p.append("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><meta http-equiv=\"refresh\" content=\"30\"><title>Local AI Lab — status</title><style>" + CSS + "</style></head><body><div class=\"wrap\">")
    p.append("<header class=\"hero\"><div class=\"kicker\">Local AI Lab · Mac Mini · tailnet-only</div><h1>Lab status</h1><div class=\"sub\">8 GB Intel box · CPU inference · updated " + html.escape(str(st["ts"])) + "</div><div class=\"pill " + pcls + "\">" + pword + "</div></header>")
    p.append("<section class=\"section\"><div class=\"bignum\">" + str(st["tokens"]["grand_total"]) + "</div><div class=\"dim\">tokens generated across " + str(st["feedback"]["n"]) + " agent reports plus monitor probes</div></section>")
    p.append("<section class=\"section\"><div class=\"cards\">")
    p.append("<div class=\"card\"><div class=\"label\">Probe speed</div><div class=\"value\">" + html.escape(str(st["health"]["probe_tok_s"])) + "</div><div class=\"dim small\">tok/s, 0.5B model</div></div>")
    p.append("<div class=\"card\"><div class=\"label\">Agent reports</div><div class=\"value\">" + str(st["feedback"]["n"]) + "</div><div class=\"dim small\">" + str(st["tokens"]["feedback_total"]) + " tokens</div></div>")
    p.append("<div class=\"card\"><div class=\"label\">Models</div><div class=\"value\">" + str(st["ollama"]["installed"]) + "</div><div class=\"dim small\">installed on box</div></div>")
    p.append("<div class=\"card\"><div class=\"label\">Sidecar uptime</div><div class=\"value\">" + fmt_dur(st["service_uptime_s"]) + "</div><div class=\"dim small\">Ollama " + html.escape(str(st["ollama"]["version"])) + "</div></div>")
    p.append("</div></section>")
    p.append("<section class=\"section\"><h2>Models <span class=\"sub2\">calls plus measured limits</span></h2><div class=\"table-wrap\"><table><thead><tr><th>Model</th><th>Params</th><th>Size</th><th>Max ctx</th><th>Calls</th><th>Tokens</th><th>State</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div><div class=\"dim small\" style=\"margin-top:8px\">Max context measured live 2026-10-26 (largest prompt evaluated in full). 8B/14B excluded per lab policy.</div></section>")
    p.append("<section class=\"section\"><h2>Activity</h2><div class=\"trend-row\"><span class=\"tname\">probe tok/s, last " + str(len(hist)) + " checks</span><span class=\"spark\">" + sp + "</span><span class=\"trend-verdict\">" + html.escape(trend_v) + "</span></div></section>")
    p.append("<section class=\"section\"><h2>Latest feedback</h2>" + "".join(fbs) + "</section>")
    p.append("<footer>Endpoints: <a href=\"/status\">status json</a> · <a href=\"/agents.md\">agent guide</a> · <a href=\"/api/tags\">model list</a> · refreshes every 30s</footer>")
    p.append("</div></body></html>")
    return "".join(p)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/feedback":
            self.send_response(404)
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n < 0 or n > 4096:
                raise ValueError("bad length")
            d = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(d, dict):
                raise ValueError("not an object")
        except Exception:
            self.send_json({"status": "bad-request"}, 400)
            return
        try:
            toks = int(d.get("tokens", 0) or 0)
        except Exception:
            toks = 0
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent": str(d.get("agent", "?"))[:64],
            "model": str(d.get("model", "?"))[:64],
            "ok": bool(d.get("ok", True)),
            "note": str(d.get("note", ""))[:280],
            "tokens": max(0, toks),
        }
        with open(FB, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self.send_json({"status": "ok"})
    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p == "/status":
            self.send_json(build_status())
        elif p == "" or p == "/dashboard":
            body = build_dashboard(build_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/agents.md":
            try:
                with open(AGENTS_MD, "rb") as f:
                    body = f.read()
            except Exception:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8081), H).serve_forever()
