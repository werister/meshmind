#!/usr/bin/env python3
"""Local AI lab sidecar: feedback receiver plus status/dashboard showcase.

POST /feedback {"agent","model","ok","note","tokens"} -> feedback.log (JSONL)
GET  /status    -> live JSON: availability, token totals, models, feedback
GET  /dashboard -> auto-refreshing HTML showcase page (mml Apple-light styling)
GET  /agents.md -> the agent quickstart doc, served over HTTPS
"""
import html
import http.client
import json
import os
import tempfile
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

LAB = os.path.join(os.path.expanduser("~"), "local-ai-lab")
FB = os.path.join(LAB, "feedback.log")
HEALTH = os.path.join(LAB, "health.log")
STATE = os.path.join(LAB, "monitor-state")
AGENTS_MD = os.path.join(LAB, "AGENTS.md")
EVAL_LOG = os.path.join(LAB, "eval-weekly.jsonl")
OLLAMA = "http://127.0.0.1:11434"
UPSTREAM = urlsplit(os.environ.get("OLLAMA_URL", OLLAMA))
PROXY_PORT = int(os.environ.get("FEEDBACK_SERVER_PORT", "8081"))
METER_DIR = os.environ.get("METER_DIR", LAB)
CALLS = os.path.join(METER_DIR, "calls.log")
PROXY_TOTAL = os.path.join(METER_DIR, "proxy-token-total")
CALLS_MAX = int(os.environ.get("CALLS_MAX_BYTES", str(50 * 1024 * 1024)))
RING_SIZE = 256
BODY_CAP = 2 * 1024 * 1024
TAIL_SIZE = 64 * 1024
PROXY_PATHS = {"/api/chat", "/api/generate", "/api/embeddings", "/v1/chat/completions", "/v1/completions", "/v1/embeddings"}
CALLS_RING = deque(maxlen=RING_SIZE)
METER_LOCK = threading.Lock()
PROXY_SEM = threading.BoundedSemaphore(16)
UNMETERED_STREAM_CALLS = 0
BACKEND_UP = False
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

def _nonnegative_int(value):
    try:
        return max(0, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None

def _load_calls():
    try:
        with open(CALLS, "rb") as f:
            f.seek(max(0, os.path.getsize(CALLS) - 1024 * 1024))
            if f.tell():
                f.readline()
            for line in f:
                try:
                    CALLS_RING.append(json.loads(line))
                except (ValueError, UnicodeDecodeError):
                    pass
    except OSError:
        pass

def _read_call_count():
    try:
        with open(PROXY_TOTAL) as f:
            d = json.load(f)
        return int(d.get("calls_total", 0))
    except (OSError, ValueError, TypeError):
        return len(CALLS_RING)

def _total_tokens(key):
    try:
        with open(PROXY_TOTAL) as f:
            d = json.load(f)
        return int(d.get(key + "_total", 0))
    except (OSError, ValueError, TypeError):
        return 0

def _record_call(call):
    """Best-effort metering persistence; never affects bytes already relayed."""
    with METER_LOCK:
        try:
            os.makedirs(METER_DIR, exist_ok=True)
            if os.path.exists(CALLS) and os.path.getsize(CALLS) >= CALLS_MAX:
                rotated = CALLS + ".1"
                try:
                    os.unlink(rotated)
                except FileNotFoundError:
                    pass
                os.replace(CALLS, rotated)
            with open(CALLS, "a", encoding="utf-8") as f:
                f.write(json.dumps(call, separators=(",", ":")) + "\n")
            total = _read_call_count() + 1
            state = {"calls_total": total,
                     "prompt_tokens_total": _total_tokens("prompt_tokens") + (call.get("prompt_tokens") or 0),
                     "eval_tokens_total": _total_tokens("eval_tokens") + (call.get("eval_tokens") or 0)}
            fd, tmp = tempfile.mkstemp(prefix="proxy-token-total.", dir=METER_DIR)
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(state, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, PROXY_TOTAL)
            finally:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
            CALLS_RING.append(dict(call))
        except Exception:
            pass

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

def tail_lines(path, max_lines, max_bytes=262144):
    """Return the last max_lines non-empty lines of a file (bounded tail read)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            n = f.tell()
            step = min(n, max_bytes)
            f.seek(n - step)
            blob = f.read().decode("utf-8", "replace")
    except Exception:
        return []
    lines = [x for x in blob.split("\n") if x.strip()]
    return lines[-max_lines:]


def read_calls_ring(limit):
    """Newest-first metered-call rows from the proxy ring (calls.log tail).

    Numbers only; the sidecar proxy (T1) writes these. Absent file -> empty.
    """
    rows = []
    for line in tail_lines(CALLS, RING_SIZE):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict):
            rows.append(d)
    rows = rows[::-1]  # newest first
    return rows[:limit]


def read_eval_summary():
    """Latest weekly-eval run_summary (read-only tail of eval-weekly.jsonl).

    JSONL per run is: N model_summary lines, then one run_summary line. We take
    the last run_summary and the N model_summary lines immediately before it.
    """
    lines = tail_lines(EVAL_LOG, 128)
    recs = []
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict):
            recs.append(d)
    # index of the last run_summary
    last_run_idx = None
    for i in range(len(recs) - 1, -1, -1):
        if recs[i].get("kind") == "run_summary":
            last_run_idx = i
            break
    if last_run_idx is None:
        return None
    run = recs[last_run_idx]
    per_model = []
    for d in recs[:last_run_idx]:
        if d.get("kind") == "model_summary":
            per_model.append(
                {
                    "model": d.get("model", "?"),
                    "verdict": d.get("verdict", "?"),
                    "passed": d.get("passed", 0),
                    "total": d.get("total", 0),
                    "avg_tok_s": d.get("avg_tok_s", 0),
                }
            )
    want = run.get("models", 0)
    tail_models = per_model[-want:] if want else per_model
    out = dict(run)
    out["per_model"] = tail_models
    return out


def streaks(daily):
    """current + longest consecutive-active-day streaks from daily buckets."""
    cur = 0
    longest = 0
    run = 0
    for d in daily:
        if (d.get("count", 0) or 0) > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    # current streak = trailing run of active days
    for d in reversed(daily):
        if (d.get("count", 0) or 0) > 0:
            cur += 1
        else:
            break
    return cur, longest


def daily_activity(days=14):
    """Per-day probe counts from the health log, oldest-first, last `days`."""
    from collections import Counter

    counts = Counter()
    for line in tail_lines(HEALTH, 5000):
        parts = line.split(" ")
        if not parts:
            continue
        at = parts[0]
        if "probe_tok_s=" not in line:
            continue
        day = at[:10]
        if len(day) == 10 and day[4] == "-":
            counts[day] += 1
    if not counts:
        return []
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(days - 1, -1, -1):
        d = today.fromordinal(today.toordinal() - i)
        key = d.isoformat()
        out.append({"date": key, "count": counts.get(key, 0)})
    return out


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
    daily = daily_activity(14)
    cur_streak, long_streak = streaks(daily)
    return {
        "ts": utcnow(),
        "service_uptime_s": int(time.time() - STARTED),
        "ollama": {"up": ver is not None, "version": (ver or {}).get("version", "?"), "installed": len(models)},
        "health": {"local": h.get("local", "?"), "serve": h.get("serve", "?"), "at": h.get("at", "?"), "probe_tok_s": h.get("probe_tok_s", "?")},
        "tokens": {"probe_total": ptot, "feedback_total": fbtoks, "grand_total": ptot + fbtoks},
        "metering": {"calls_total": _read_call_count(), "prompt_tokens_total": _total_tokens("prompt_tokens"),
                     "eval_tokens_total": _total_tokens("eval_tokens"), "ring_len": len(CALLS_RING),
                     "backend_up": BACKEND_UP, "unmetered_stream_calls": UNMETERED_STREAM_CALLS},
        "feedback": {"n": fbn, "latest": fblast, "recent": recent},
        "calls": read_calls_ring(12),
        "eval": read_eval_summary(),
        "models": models,
        "activity": {"probe_tok_s_last24": hist, "daily": daily, "current_streak": cur_streak, "longest_streak": long_streak},
    }

CSS = ":root{--bg:#F5F5F7;--surface:#FFFFFF;--surface2:#F2F2F2;--line:#E8E8ED;--fg:#1D1D1F;--fg2:#6E6E73;--accent:#0071E3;--accent-text:#0066CC;--green:#1F7A34;--red:#D70015;--radius:10px;--radius-sm:6px}*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg);color:var(--fg);font:17px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;padding:0 24px 96px}.wrap{max-width:800px;margin:0 auto}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}.dim{color:var(--fg2)}.hero{padding-top:56px;margin-bottom:40px}.kicker{font-size:12px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--fg2);margin-bottom:12px}h1{font-size:clamp(40px,5vw,56px);font-weight:700;letter-spacing:-.02em;line-height:1.05;margin:0 0 8px}h2{font-size:24px;font-weight:600;letter-spacing:-.01em;margin:0 0 16px}h2 .sub2{color:var(--fg2);font-size:14px;font-weight:400}.sub{color:var(--fg2);font-size:19px;margin:0 0 16px}.pill{display:inline-block;font-size:13px;font-weight:700;padding:6px 14px;border-radius:999px;background:var(--surface);border:1px solid var(--line)}.pill.ok{color:var(--green)}.pill.fail{color:var(--red)}.section{margin-bottom:56px}.bignum{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;font-size:clamp(56px,9vw,84px);font-weight:700;letter-spacing:-.03em;line-height:1}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px}.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px}.card .label{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--fg2);margin-bottom:6px}.card .value{font-size:30px;font-weight:700;letter-spacing:-.5px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;line-height:1.2}.verdict{background:var(--surface);border:1.5px solid var(--accent);border-radius:var(--radius);padding:20px 28px}.verdict .vtext{font-size:18px;font-weight:500;line-height:1.45}.verdict .vmetrics{color:var(--fg2);font-size:13px;margin-top:12px}.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface)}table{width:100%;border-collapse:collapse;font-size:13px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}th,td{text-align:left;padding:8px 14px;border-bottom:1px solid var(--line);white-space:nowrap}tr:last-child td{border-bottom:0}th{color:var(--fg2);font-weight:600;font-size:11px;letter-spacing:.05em;text-transform:uppercase;background:var(--surface2)}.loaded-dot{color:var(--green);font-weight:700}tbody tr:hover td{background:var(--surface2)}.trend-row{display:flex;gap:16px;align-items:center;padding:14px 0;border-bottom:1px solid var(--line)}.trend-row .tname{width:210px;color:var(--fg2);font-size:13px;flex-shrink:0}.spark{font-family:ui-monospace,SFMono-Regular,monospace;letter-spacing:1px;font-size:16px}.trend-verdict{color:var(--fg2);font-size:13px}.fb{border-bottom:1px solid var(--line);padding:10px 0;font-size:14px}.fb:last-child{border-bottom:0}.fb .who{font-weight:600}.fb .note{color:var(--fg2)}footer{color:var(--fg2);font-size:13px;margin-top:24px}a{color:var(--accent-text)}a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.small{font-size:13px}@media (max-width:600px){.trend-row{flex-wrap:wrap}.trend-row .tname{width:100%}}.metering{border-left:3px solid var(--accent)}.metering .value{color:var(--accent-text)}.badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 7px;border-radius:999px;vertical-align:middle;margin-left:8px}.badge.measured{background:rgba(0,113,227,.12);color:var(--accent-text);border:1px solid var(--accent)}.badge.declared{background:var(--surface2);color:var(--fg2);border:1px dashed var(--line)}.srcnote{font-size:12px;color:var(--fg2);margin:6px 0 16px}.heat{display:flex;gap:4px;flex-wrap:wrap;margin:4px 0 10px}.heat .cell{width:20px;height:20px;border-radius:4px;background:var(--surface2);border:1px solid var(--line)}.heat .cell.l1{background:#C6E2FF}.heat .cell.l2{background:#7FBEFF}.heat .cell.l3{background:#3B9BFF}.heat .cell.l4{background:#0071E3}.heatlabels{display:flex;gap:4px;flex-wrap:wrap;font-size:10px;color:var(--fg2)}.heatlabels span{width:20px;text-align:center}.streaks{display:flex;gap:28px;margin-top:10px}.streaks .s .n{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;font-size:26px;font-weight:700}.streaks .s .l{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--fg2)}.feed{border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);overflow:hidden}.feed .row{display:flex;gap:12px;align-items:baseline;padding:9px 14px;border-bottom:1px solid var(--line);font-size:13px}.feed .row:last-child{border-bottom:0}.feed .row .t{color:var(--fg2);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;flex-shrink:0}.feed .row .ag{font-weight:600;flex-shrink:0}.feed .row .md{color:var(--fg2);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}.feed .row .tk{margin-left:auto;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;flex-shrink:0}.feed .row.err{background:rgba(215,0,21,.05)}.feed .row .flag{color:var(--fg2);font-size:11px}.evalgrid{display:grid;grid-template-columns:1fr auto auto;gap:0;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;background:var(--surface);font-size:13px}.evalgrid>div{padding:8px 14px;border-bottom:1px solid var(--line)}.evalgrid .hd{color:var(--fg2);font-size:11px;letter-spacing:.05em;text-transform:uppercase;background:var(--surface2)}.evalgrid .mono{font-variant-numeric:tabular-nums}.vp{color:var(--green);font-weight:700}.vf{color:var(--red);font-weight:700}.vs{color:var(--fg2);font-weight:700}@media (prefers-color-scheme:dark){:root{--bg:#1D1D1F;--surface:#2C2C2E;--surface2:#3A3A3C;--line:#48484A;--fg:#F5F5F7;--fg2:#A1A1A6;--accent:#0A84FF;--accent-text:#409CFF;--green:#30D158;--red:#FF453A}}"

def heat_level(count, hi):
    if count <= 0 or hi <= 0:
        return 0
    frac = count / hi
    if frac >= 0.75:
        return 4
    if frac >= 0.5:
        return 3
    if frac >= 0.25:
        return 2
    return 1


def render_metering(st):
    m = st.get("metering")
    if not m:
        return ""
    p = []
    p.append("<section class=\"section\"><h2>Metered traffic <span class=\"badge measured\">measured</span></h2>")
    p.append("<div class=\"srcnote\">Counted at the proxy tap on real inference calls. Kept separate from self-reported feedback below &mdash; the two are never added together.</div>")
    p.append("<div class=\"cards\">")
    p.append("<div class=\"card metering\"><div class=\"label\">Metered calls</div><div class=\"value\">" + str(m.get("calls_total", 0)) + "</div><div class=\"dim small\">ring holds " + str(m.get("ring_len", 0)) + "</div></div>")
    p.append("<div class=\"card metering\"><div class=\"label\">Eval tokens</div><div class=\"value\">" + str(m.get("eval_tokens_total", 0)) + "</div><div class=\"dim small\">measured output</div></div>")
    p.append("<div class=\"card metering\"><div class=\"label\">Prompt tokens</div><div class=\"value\">" + str(m.get("prompt_tokens_total", 0)) + "</div><div class=\"dim small\">measured input</div></div>")
    bu = "up" if m.get("backend_up") else "down"
    p.append("<div class=\"card metering\"><div class=\"label\">Backend</div><div class=\"value\">" + bu + "</div><div class=\"dim small\">" + str(m.get("unmetered_stream_calls", 0)) + " no-usage streams</div></div>")
    p.append("</div></section>")
    return "".join(p)


def render_calls(st):
    calls = st.get("calls") or []
    p = []
    p.append("<section class=\"section\"><h2>Recent calls <span class=\"sub2\">newest first, from the metering ring</span></h2>")
    if not calls:
        p.append("<div class=\"feed\"><div class=\"row dim\">No metered calls yet &mdash; proxy ring is empty.</div></div></section>")
        return "".join(p)
    p.append("<div class=\"feed\">")
    for c in calls:
        err = "" if c.get("ok", True) else " err"
        t = html.escape(str(c.get("ts", ""))[11:19])
        ag = html.escape(str(c.get("agent", "unknown")))
        md = html.escape(str(c.get("model", "?")))
        path = html.escape(str(c.get("path", "")))
        et = c.get("eval_tokens", None)
        if c.get("no_usage") or et is None:
            tk = "<span class=\"flag\">no-usage</span>"
        else:
            tk = str(et) + " tok"
        if c.get("partial"):
            tk += " <span class=\"flag\">partial</span>"
        if not c.get("ok", True):
            tk = "<span class=\"vf\">" + str(c.get("status", 502)) + "</span>"
        p.append("<div class=\"row" + err + "\"><span class=\"t\">" + t + "</span><span class=\"ag\">" + ag + "</span><span class=\"md\">" + md + " " + path + "</span><span class=\"tk\">" + tk + "</span></div>")
    p.append("</div></section>")
    return "".join(p)


def render_activity(st):
    act = st.get("activity", {})
    hist = act.get("probe_tok_s_last24", [])
    daily = act.get("daily", [])
    cur = act.get("current_streak", 0)
    longest = act.get("longest_streak", 0)
    sp = sparkline(hist)
    if hist:
        trend_v = "last " + str(round(hist[-1], 1)) + " \u00b7 max " + str(round(max(hist), 1)) + " tok/s"
    else:
        trend_v = "no samples yet"
    p = []
    p.append("<section class=\"section\"><h2>Activity</h2>")
    if daily:
        hi = max((d.get("count", 0) or 0) for d in daily) or 1
        cells = []
        labels = []
        for d in daily:
            lvl = heat_level(d.get("count", 0) or 0, hi)
            cls = "cell" + ((" l" + str(lvl)) if lvl else "")
            cells.append("<span class=\"" + cls + "\" title=\"" + html.escape(d.get("date", "")) + ": " + str(d.get("count", 0)) + " probes\"></span>")
            labels.append("<span>" + html.escape(d.get("date", "")[8:10]) + "</span>")
        p.append("<div class=\"heat\">" + "".join(cells) + "</div>")
        p.append("<div class=\"heatlabels\">" + "".join(labels) + "</div>")
        p.append("<div class=\"streaks\"><div class=\"s\"><div class=\"n\">" + str(cur) + "</div><div class=\"l\">current streak</div></div><div class=\"s\"><div class=\"n\">" + str(longest) + "</div><div class=\"l\">longest streak</div></div></div>")
    p.append("<div class=\"trend-row\"><span class=\"tname\">probe tok/s, last " + str(len(hist)) + " checks</span><span class=\"spark\">" + sp + "</span><span class=\"trend-verdict\">" + html.escape(trend_v) + "</span></div>")
    p.append("</section>")
    return "".join(p)


def render_eval(st):
    ev = st.get("eval")
    if not ev:
        return ""
    p = []
    p.append("<section class=\"section\"><h2>Weekly eval <span class=\"sub2\">last run " + html.escape(str(ev.get("ts", ""))[:10]) + "</span></h2>")
    p.append("<div class=\"evalgrid\"><div class=\"hd\">Model</div><div class=\"hd mono\">Passed</div><div class=\"hd mono\">tok/s</div>")
    for r in ev.get("per_model", []):
        v = r.get("verdict", "?")
        vcls = {"PASS": "vp", "FAIL": "vf", "SKIP": "vs"}.get(v, "dim")
        p.append("<div>" + html.escape(str(r.get("model", "?"))) + "</div>")
        p.append("<div class=\"mono\"><span class=\"" + vcls + "\">" + html.escape(str(r.get("passed", 0))) + "/" + html.escape(str(r.get("total", 0))) + "</span></div>")
        p.append("<div class=\"mono\">" + html.escape(str(r.get("avg_tok_s", 0))) + "</div>")
    p.append("</div>")
    p.append("<div class=\"dim small\" style=\"margin-top:8px\">" + str(ev.get("passed_models", 0)) + " passed, " + str(ev.get("failed_models", 0)) + " failed, " + str(ev.get("skipped_models", 0)) + " skipped \u00b7 " + str(ev.get("wall_s", 0)) + "s</div></section>")
    return "".join(p)


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
    p = []
    p.append("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><meta http-equiv=\"refresh\" content=\"30\"><title>Local AI Lab — status</title><style>" + CSS + "</style></head><body><div class=\"wrap\">")
    p.append("<header class=\"hero\"><div class=\"kicker\">Local AI Lab · Mac Mini · tailnet-only</div><h1>Lab status</h1><div class=\"sub\">8 GB Intel box · CPU inference · updated " + html.escape(str(st["ts"])) + "</div><div class=\"pill " + pcls + "\">" + pword + "</div></header>")
    p.append("<section class=\"section\"><div class=\"bignum\">" + str(st["tokens"]["grand_total"]) + "</div><div class=\"dim\">tokens across monitor probes plus self-reported agent totals (feedback). Metered traffic is tracked separately below and is never folded into this number.</div></section>")
    p.append("<section class=\"section\"><div class=\"cards\">")
    p.append("<div class=\"card\"><div class=\"label\">Probe speed</div><div class=\"value\">" + html.escape(str(st["health"]["probe_tok_s"])) + "</div><div class=\"dim small\">tok/s, 0.5B model</div></div>")
    p.append("<div class=\"card\"><div class=\"label\">Agent reports <span class=\"badge declared\">self-declared</span></div><div class=\"value\">" + str(st["feedback"]["n"]) + "</div><div class=\"dim small\">" + str(st["tokens"]["feedback_total"]) + " tokens, X-Agent self-declared</div></div>")
    p.append("<div class=\"card\"><div class=\"label\">Models</div><div class=\"value\">" + str(st["ollama"]["installed"]) + "</div><div class=\"dim small\">installed on box</div></div>")
    p.append("<div class=\"card\"><div class=\"label\">Sidecar uptime</div><div class=\"value\">" + fmt_dur(st["service_uptime_s"]) + "</div><div class=\"dim small\">Ollama " + html.escape(str(st["ollama"]["version"])) + "</div></div>")
    p.append("</div></section>")
    p.append(render_metering(st))
    p.append(render_calls(st))
    p.append("<section class=\"section\"><h2>Models <span class=\"sub2\">calls plus measured limits</span></h2><div class=\"table-wrap\"><table><thead><tr><th>Model</th><th>Params</th><th>Size</th><th>Max ctx</th><th>Calls</th><th>Tokens</th><th>State</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div><div class=\"dim small\" style=\"margin-top:8px\">Max context measured live 2026-10-26 (largest prompt evaluated in full). 8B/14B excluded per lab policy.</div></section>")
    p.append(render_eval(st))
    p.append(render_activity(st))
    p.append("<section class=\"section\"><h2>Latest feedback <span class=\"badge declared\">self-declared</span></h2>" + "".join(fbs) + "</section>")
    p.append("<footer>Endpoints: <a href=\"/status\">status json</a> · <a href=\"/calls\">calls json</a> · <a href=\"/agents.md\">agent guide</a> · <a href=\"/api/tags\">model list</a> · refreshes every 30s</footer>")
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
    def _proxy(self, metered=False):
        global BACKEND_UP, UNMETERED_STREAM_CALLS
        started = time.time()
        path = self.path
        call = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "path": path, "status": None,
                "agent": (self.headers.get("X-Agent") or "unknown")[:64], "model": "unknown",
                "prompt_tokens": None, "eval_tokens": None, "ok": False,
                "stream": False, "partial": False, "truncated": False}
        length = 0
        capture = bytearray()
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length < 0:
                raise ValueError()
        except ValueError:
            self.send_json({"error": "invalid content length"}, 400)
            return
        if not PROXY_SEM.acquire(blocking=False):
            call["error"] = "proxy concurrency limit"
            call["status"] = 503
            try:
                self.send_error(503, "proxy busy")
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
            if metered:
                _record_call(call)
            return
        if metered:
            # Read and forward in bounded pieces; retain only a small JSON prefix.
            try:
                # Parse at most 64 KB of request metadata without buffering the body.
                needed = min(length, 65536)
                while len(capture) < needed:
                    part = self.rfile.read(min(8192, needed - len(capture)))
                    if not part:
                        break
                    capture.extend(part)
                payload = json.loads(capture) if len(capture) == length else json.loads(capture[:65536])
                call["model"] = str(payload.get("model", "unknown"))[:128]
                call["stream"] = bool(payload.get("stream", False))
            except Exception:
                payload = {}
                call["meter_parse_failed"] = True
            call["truncated"] = length > BODY_CAP
        else:
            payload = {}
        conn = None
        try:
            conn = http.client.HTTPConnection(UPSTREAM.hostname or "127.0.0.1", UPSTREAM.port or 80,
                                              timeout=300 if metered else 15)
            conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for key, value in self.headers.items():
                if key.lower() not in ("host", "connection", "x-agent", "transfer-encoding"):
                    conn.putheader(key, value)
            conn.putheader("Host", "127.0.0.1:11434")
            conn.putheader("Connection", "close")
            conn.endheaders()
            if capture:
                conn.send(capture)
            remaining = length - len(capture)
            while remaining > 0:
                part = self.rfile.read(min(65536, remaining))
                if not part:
                    raise ConnectionError("client request ended early")
                conn.send(part)
                remaining -= len(part)
            upstream = conn.getresponse()
            BACKEND_UP = True
            call["status"] = upstream.status
            self.send_response(upstream.status, upstream.reason)
            for key, value in upstream.getheaders():
                if key.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            tail = bytearray()
            response_size = 0
            try:
                while True:
                    chunk = upstream.read1(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if metered:
                        response_size += len(chunk)
                        tail.extend(chunk)
                        if len(tail) > TAIL_SIZE:
                            del tail[:-TAIL_SIZE]
            except (BrokenPipeError, ConnectionResetError):
                call["partial"] = True
                return
            call["ok"] = 200 <= upstream.status < 400
            if metered:
                found_usage = False
                for line in reversed(bytes(tail).splitlines()):
                    line = line.strip()
                    if line.startswith(b"data:"):
                        line = line[5:].strip()
                    if not line or line == b"[DONE]":
                        continue
                    try:
                        frame = json.loads(line)
                    except Exception:
                        continue
                    if path.startswith("/api/") and frame.get("done"):
                        call["prompt_tokens"] = _nonnegative_int(frame.get("prompt_eval_count"))
                        call["eval_tokens"] = _nonnegative_int(frame.get("eval_count"))
                        found_usage = True
                        break
                    usage = frame.get("usage")
                    if usage is not None:
                        call["prompt_tokens"] = _nonnegative_int(usage.get("prompt_tokens"))
                        call["eval_tokens"] = _nonnegative_int(usage.get("completion_tokens"))
                        found_usage = True
                        break
                if not found_usage:
                    if call["stream"] and path.startswith("/v1/"):
                        call["no_usage"] = True
                        UNMETERED_STREAM_CALLS += 1
                    else:
                        call["meter_parse_failed"] = True
                call["truncated"] = call["truncated"] or response_size > BODY_CAP
        except (OSError, http.client.HTTPException, TimeoutError, ConnectionError):
            BACKEND_UP = False
            if call["status"] is None:
                call["status"] = 502
            try:
                self.send_error(502, "backend unavailable")
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            if conn:
                conn.close()
            PROXY_SEM.release()
            if metered:
                call["duration_ms"] = int((time.time() - started) * 1000)
                _record_call(call)
    def do_POST(self):
        path = urlsplit(self.path).path
        if path in PROXY_PATHS:
            self._proxy(True)
            return
        if path.startswith(("/api/", "/v1/")):
            self._proxy(False)
            return
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
    def _other_proxy_method(self):
        if urlsplit(self.path).path.startswith(("/api/", "/v1/")):
            self._proxy(False)
        else:
            self.send_error(501, "unsupported method")
    def do_HEAD(self):
        self._other_proxy_method()
    def do_PUT(self):
        self._other_proxy_method()
    def do_PATCH(self):
        self._other_proxy_method()
    def do_DELETE(self):
        self._other_proxy_method()
    def do_OPTIONS(self):
        self._other_proxy_method()
    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p == "/calls":
            try:
                limit = max(0, min(RING_SIZE, int(parse_qs(urlsplit(self.path).query).get("limit", ["50"])[0])))
            except ValueError:
                limit = 50
            with METER_LOCK:
                calls = list(reversed(CALLS_RING))[:limit]
            self.send_json(calls)
        elif p.startswith(("/api/", "/v1/")):
            self._proxy(False)
        elif p == "/status":
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
    os.makedirs(METER_DIR, exist_ok=True)
    _load_calls()
    ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), H).serve_forever()
