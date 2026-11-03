#!/usr/bin/env python3
"""Local AI lab sidecar: feedback receiver plus status/dashboard showcase.

POST /feedback {"agent","model","ok","note","tokens"} -> feedback.log (JSONL)
POST /fetch {"op":"fetch","url":...} | {"op":"search","query":...} -> web text
GET  /status    -> live JSON: availability, token totals, models, feedback
GET  /tools     -> machine-readable tool registry (T12 schema format)
GET  /dashboard -> auto-refreshing HTML showcase page (mml Apple-light styling)
GET  /agents.md -> the agent quickstart doc, served over HTTPS
"""
import html
import http.client
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "scripts"))
try:
    import web_tools
except ImportError:
    web_tools = None  # old deploy without scripts/: /fetch answers 501

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
# Per-model / per-agent / per-day metered rollups. Bumped once per finalized call,
# like proxy-token-total; never recomputed from calls.log (rotation would break it).
METER_AGG = os.path.join(METER_DIR, "metering-aggregates.json")
AGG_DAYS = 14
AGG_MAX_KEYS = 64  # X-Agent and model are caller-controlled: cap distinct keys
AGG_OTHER = "(other)"
CALLS_MAX = int(os.environ.get("CALLS_MAX_BYTES", str(50 * 1024 * 1024)))
RING_SIZE = 256
BODY_CAP = 2 * 1024 * 1024
TAIL_SIZE = 64 * 1024
PROXY_PATHS = {"/api/chat", "/api/generate", "/api/embeddings", "/v1/chat/completions", "/v1/completions", "/v1/embeddings"}
# Machine-readable tool registry for lab-provided tools (GET /tools).
# Same {name, description, parameters} schema FORMAT as the T12 bench
# catalog -- not the same file: T12's fixture stays a fixed fake-backend
# set, this is the live registry agents auto-wire against.
TOOLS_CATALOG = [
    {"name": "web_fetch",
     "description": "Fetch a public web page and return its text "
                    "(256 KB cap, SSRF-guarded: no localhost, LAN, tailnet, "
                    "metadata, or non-80/443 ports).",
     "parameters": {"url": {"type": "string", "required": True}},
     "endpoint": "/fetch", "method": "POST", "op": "fetch"},
    {"name": "web_search",
     "description": "Keyless web search; returns up to 5 title/url pairs.",
     "parameters": {"query": {"type": "string", "required": True}},
     "endpoint": "/fetch", "method": "POST", "op": "search"},
]
# --- rerank endpoint (T10, additive) ----------------------------------------
# POST /rerank {query, passages:[{id,text}], top_k?} -> {scores, model, latency_s}.
# Served + metered like the proxy paths (agent tag `rerank`). The endpoint shells
# out to scripts/rerank_worker.py (subprocess list-args, never shell) which runs
# under the Mini's onnxruntime venv; worker missing/slow/garbage -> HTTP 503.
RERANK_MAX_PASSAGES = 20
RERANK_MAX_CHARS = 2000
RERANK_MAX_TOP_K = 20
RERANK_TIMEOUT_S = int(os.environ.get("RERANK_TIMEOUT_S", "60"))
RERANK_MAX_BODY = 1024 * 1024  # request body hard cap (20 x 2000 chars + overhead)
RERANK_MODEL = os.environ.get("RERANK_MODEL", "ettin-17m")
RERANK_MODEL_DIR = os.environ.get("RERANK_MODEL_DIR", os.path.join(LAB, "ettin-17m"))
RERANK_WORKER = os.environ.get(
    "RERANK_WORKER",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "rerank_worker.py"),
)
RERANK_PYTHON = os.environ.get("RERANK_PYTHON", os.path.join(LAB, ".venv-rerank", "bin", "python3"))
CALLS_RING = deque(maxlen=RING_SIZE)
METER_LOCK = threading.Lock()
PROXY_SEM = threading.BoundedSemaphore(16)
FETCH_SEM = threading.BoundedSemaphore(4)
FETCH_RATE = 30
FETCH_GLOBAL_RATE = 120
FETCH_WINDOW = 60.0
_FETCH_BUCKETS = {}
_FETCH_LOCK = threading.Lock()
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
            try:
                _bump_aggregates(call)
            except Exception:
                pass  # fail-open: a rollup failure never costs the ring or the totals
            CALLS_RING.append(dict(call))
        except Exception:
            pass


def _atomic_write_json(path, obj):
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _empty_agg():
    return {"version": 1, "since": None, "per_model": {}, "per_agent": {}, "daily": {},
            "failures": {"total": 0, "by_status": {}}}


def _read_agg():
    try:
        with open(METER_AGG) as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("version") == 1:
            return d
    except (OSError, ValueError):
        pass
    return _empty_agg()


def _new_counts():
    return {"calls": 0, "prompt_tokens": 0, "eval_tokens": 0, "failed": 0, "no_usage": 0}


def _bucket(table, key):
    if key not in table and len(table) >= AGG_MAX_KEYS:
        key = AGG_OTHER
    return table.setdefault(key, _new_counts()), key


def _is_failure(call):
    # A client hanging up mid-stream (partial) is not a backend failure;
    # neither is a guard-blocked fetch (policy outcome, not an outage).
    return (not call.get("ok") and not call.get("partial")
            and not call.get("blocked"))


def _bump_counts(e, call):
    e["calls"] += 1
    for src, dst in (("prompt_tokens", "prompt_tokens"), ("eval_tokens", "eval_tokens")):
        v = call.get(src)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            e[dst] += v  # nulls never enter sums
    if _is_failure(call):
        e["failed"] += 1
    if call.get("no_usage"):
        e["no_usage"] += 1


def _bump_aggregates(call):
    """Read-modify-write the rollup state file. Caller holds METER_LOCK."""
    agg = _read_agg()
    agg["since"] = agg.get("since") or call.get("ts")
    entry, model_key = _bucket(agg["per_model"], str(call.get("model") or "unknown")[:128])
    _bump_counts(entry, call)
    entry, _ = _bucket(agg["per_agent"], str(call.get("agent") or "unknown")[:64])
    _bump_counts(entry, call)
    day = str(call.get("ts", ""))[:10]
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        d = None
    if d is not None:
        de = agg["daily"].setdefault(day, dict(_new_counts(), by_model={}))
        _bump_counts(de, call)
        et = call.get("eval_tokens")
        if isinstance(et, int) and not isinstance(et, bool) and et > 0:
            de["by_model"][model_key] = de["by_model"].get(model_key, 0) + et
        cutoff = (d - timedelta(days=AGG_DAYS - 1)).isoformat()
        for k in [k for k in agg["daily"] if k < cutoff]:
            del agg["daily"][k]
    if _is_failure(call):
        f = agg["failures"]
        f["total"] += 1
        s = str(call.get("status") or "none")
        f["by_status"][s] = f["by_status"].get(s, 0) + 1
    _atomic_write_json(METER_AGG, agg)


def metering_breakdown(today=None):
    """The /status view of the rollups: sorted lists, 14 zero-filled days (oldest first)."""
    with METER_LOCK:
        agg = _read_agg()
    today = today or datetime.now(timezone.utc).date()

    def rows(table, key):
        out = [dict({key: name}, **{k: int(v.get(k, 0)) for k in _new_counts()}) for name, v in table.items()]
        return sorted(out, key=lambda r: (-r["eval_tokens"], -r["calls"], r[key]))

    daily = []
    for i in range(AGG_DAYS - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        e = agg["daily"].get(day, {})
        row = {"date": day}
        row.update({k: int(e.get(k, 0)) for k in _new_counts()})
        row["by_model"] = {m: int(v) for m, v in sorted(e.get("by_model", {}).items())}
        daily.append(row)
    fails = agg.get("failures") or {}
    return {"since": agg.get("since"), "per_model": rows(agg["per_model"], "model"),
            "per_agent": rows(agg["per_agent"], "agent"), "daily": daily,
            "failures": {"total": int(fails.get("total", 0)),
                         "by_status": {k: int(v) for k, v in sorted((fails.get("by_status") or {}).items())}}}

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


# ---- memory + swap telemetry (T6, additive) --------------------------------
# Samples macOS `vm_stat` and `sysctl vm.swapusage`, both stdlib-only via
# subprocess, and reports MB. Any parse drift or missing tool -> the affected
# field is null and a one-line note goes to stderr; the server keeps running.
# The three fields are spread as TOP-LEVEL keys of /status (run_ladder.py reads
# data["mem_free_mb"] etc.) and are purely additive -- old readers unaffected.
MEM_FIELDS = ("mem_free_mb", "mem_compressed_mb", "swap_used_mb")


def _run_cmd(argv, timeout=5):
    """Run a short command, return stdout text or None (never raises)."""
    try:
        out = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        return None


def parse_vm_stat(text):
    """Parse `vm_stat` output -> (mem_free_mb, mem_compressed_mb).

    vm_stat reports counts in pages; the header line declares the page size.
    Returns (None, None) on drift/absence; a single missing field is null on
    its own. Pure function so the parse-drift test can feed a mutated fixture.
    """
    if not text:
        return None, None
    page_size = None
    header = text.splitlines()[0] if text.splitlines() else ""
    m = re.search(r"page size of (\d+) bytes", header)
    if m:
        page_size = int(m.group(1))
    free_pages = None
    compressed_pages = None
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        digits = re.sub(r"[^0-9]", "", val)
        if not digits:
            continue
        pages = int(digits)
        if key == "pages free":
            free_pages = pages
        elif key == "pages occupied by compressor":
            compressed_pages = pages
    if page_size is None:
        return None, None

    def to_mb(pages):
        if pages is None:
            return None
        return round(pages * page_size / 1048576)

    return to_mb(free_pages), to_mb(compressed_pages)


def parse_swapusage(text):
    """Parse `sysctl vm.swapusage` -> swap_used_mb (None on drift/absence)."""
    if not text:
        return None
    m = re.search(r"used\s*=\s*([0-9.]+)([KMG]?)", text)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2)
    mb = {"K": val / 1024, "M": val, "G": val * 1024, "": val / 1048576}.get(unit)
    if mb is None:
        return None
    return round(mb)


def read_mem():
    """Sample memory + swap. Returns a dict with the three additive fields.

    Any failure leaves the affected field null and emits one stderr note; the
    caller (build_status) always gets a well-formed dict.
    """
    out = {k: None for k in MEM_FIELDS}
    vm_text = _run_cmd(["vm_stat"])
    try:
        free_mb, compressed_mb = parse_vm_stat(vm_text)
        out["mem_free_mb"] = free_mb
        out["mem_compressed_mb"] = compressed_mb
    except Exception as e:  # defensive: parse_vm_stat should not raise
        print("T6 mem: vm_stat parse failed: %r" % (e,), file=sys.stderr)
    if out["mem_free_mb"] is None or out["mem_compressed_mb"] is None:
        print("T6 mem: vm_stat unavailable or unparseable; mem fields null",
              file=sys.stderr)
    swap_text = _run_cmd(["sysctl", "vm.swapusage"])
    try:
        out["swap_used_mb"] = parse_swapusage(swap_text)
    except Exception as e:  # defensive
        print("T6 mem: swapusage parse failed: %r" % (e,), file=sys.stderr)
    if out["swap_used_mb"] is None:
        print("T6 mem: vm.swapusage unavailable or unparseable; swap field null",
              file=sys.stderr)
    return out


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
        **read_mem(),
        "metering": {"calls_total": _read_call_count(), "prompt_tokens_total": _total_tokens("prompt_tokens"),
                     "eval_tokens_total": _total_tokens("eval_tokens"), "ring_len": len(CALLS_RING),
                     "backend_up": BACKEND_UP, "unmetered_stream_calls": UNMETERED_STREAM_CALLS},
        "metering_breakdown": metering_breakdown(),
        "feedback": {"n": fbn, "latest": fblast, "recent": recent},
        "calls": read_calls_ring(12),
        "eval": read_eval_summary(),
        "models": models,
        "activity": {"probe_tok_s_last24": hist, "daily": daily, "current_streak": cur_streak, "longest_streak": long_streak},
    }

# ======================================================================== dashboard (round 4b)
# Zero-JS, no external assets. Measured, self-declared, estimated and sample numbers are
# tagged separately and never summed into one figure. mockups/build-mockup.py renders the
# same template with mockup=True; tests pin that output byte-for-byte to the committed mockup.

RAM_MB = 8192
PROBE_MODEL = "qwen2.5:0.5b"
DO_NOT_RUN = {"qwen2.5:14b", "deepseek-r1:8b"}  # AGENTS.md: too big for the 8 GB box
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
SERIES_VARS = ["m1", "m2", "m3", "m4"]
# Reference rates in USD per 1M tokens (input, output). Assumptions, not quotes.
RATES = [("Low", 0.05, 0.10), ("Base", 0.15, 0.60), ("High", 3.00, 15.00)]
# Sample mix: used only when /status carries totals but no metering_breakdown. The shares
# are scaled onto the live totals with largest-remainder, so the parts always sum exactly.
SAMPLE_MODELS = [("qwen3:4b", "m1", 13420, "Qwen", "qwen3:4b"),
                 ("llama3.2:3b", "m2", 5260, "Meta", "llama3.2:3b"),
                 ("qwen2.5:0.5b", "m3", 2890, "Qwen", "qwen2.5:0.5b"),
                 ("gemma2:2b", "m4", 1190, "Google", "gemma2:2b"),
                 ("phi4-mini + 1 more", "m0", 350, "Microsoft, Qwen", "phi4-mini")]
SAMPLE_AGENTS = [("kiro-spar", 11200), ("codex-spar", 7050), ("muse-status", 3120), ("unknown", 1740)]
SAMPLE_BEND = [lambda i: 0.45 + i / 13,
               lambda i: max(0.15, 1 - abs(i - 8) / 7),
               lambda i: 1.6 - i / 11,
               lambda i: 1.0 if i < 9 else 0.35,
               lambda i: 1.0 if i >= 10 else 0.0]
MAKERS = {"qwen": "Qwen", "meta": "Meta", "gemma": "Google", "microsoft": "Microsoft"}

# Mono marks from lobehub/lobe-icons (MIT, packages/static-svg/icons/*.svg), fill=currentColor.
# Logos remain trademarks of their owners; used only to identify each model's maker.
LOGOS = {
    "qwen": ("Qwen", "M19.713 2.825h-5.907c0-.251-.066-.503-.196-.728L12.819.728A1.46 1.46 0 0 0 11.559 0h-1.58c-.52 0-1 .275-1.26.728l-2.42 4.19a1.45 1.45 0 0 0 0 1.453l.791 1.37c.26.448.74.727 1.26.727h11.36c.52 0 1-.275 1.26-.728l.79-1.37a1.45 1.45 0 0 0 0-1.451l-.79-1.37a1.46 1.46 0 0 0-1.26-.728zM.195 9.905l2.951 5.115a1.46 1.46 0 0 0-.531.531l-.791 1.37a1.45 1.45 0 0 0 0 1.452l.79 1.37c.26.448.74.727 1.26.727h4.84c.52 0 1-.275 1.26-.728l.79-1.37a1.45 1.45 0 0 0 0-1.451L5.086 7.083a1.46 1.46 0 0 0-1.26-.728h-1.58c-.52 0-1 .276-1.26.728l-.79 1.37a1.45 1.45 0 0 0 0 1.452m15.888 13.367 2.951-5.115c.217.125.469.196.728.196h1.582c.52 0 1-.275 1.26-.728l.79-1.37a1.45 1.45 0 0 0 0-1.451l-2.42-4.191a1.46 1.46 0 0 0-1.259-.728h-1.582c-.52 0-1 .276-1.259.728l-5.678 9.838a1.45 1.45 0 0 0 0 1.452l.79 1.37c.26.448.74.727 1.26.727h1.582c.52 0 1-.275 1.26-.728z"),
    "meta": ("Meta", "M6.897 4c1.915 0 3.516.932 5.43 3.376l.282-.373c.19-.246.383-.484.58-.71l.313-.35C14.588 4.788 15.792 4 17.225 4c1.273 0 2.469.557 3.491 1.516l.218.213c1.73 1.765 2.917 4.71 3.053 8.026l.011.392.002.25c0 1.501-.28 2.759-.818 3.7l-.14.23-.108.153c-.301.42-.664.758-1.086 1.009l-.265.142-.087.04a3.493 3.493 0 01-.302.118 4.117 4.117 0 01-1.33.208c-.524 0-.996-.067-1.438-.215-.614-.204-1.163-.56-1.726-1.116l-.227-.235c-.753-.812-1.534-1.976-2.493-3.586l-1.43-2.41-.544-.895-1.766 3.13-.343.592C7.597 19.156 6.227 20 4.356 20c-1.21 0-2.205-.42-2.936-1.182l-.168-.184c-.484-.573-.837-1.311-1.043-2.189l-.067-.32a8.69 8.69 0 01-.136-1.288L0 14.468c.002-.745.06-1.49.174-2.23l.1-.573c.298-1.53.828-2.958 1.536-4.157l.209-.34c1.177-1.83 2.789-3.053 4.615-3.16L6.897 4zm-.033 2.615l-.201.01c-.83.083-1.606.673-2.252 1.577l-.138.199-.01.018c-.67 1.017-1.185 2.378-1.456 3.845l-.004.022a12.591 12.591 0 00-.207 2.254l.002.188c.004.18.017.36.04.54l.043.291c.092.503.257.908.486 1.208l.117.137c.303.323.698.492 1.17.492 1.1 0 1.796-.676 3.696-3.641l2.175-3.4.454-.701-.139-.198C9.11 7.3 8.084 6.616 6.864 6.616zm10.196-.552l-.176.007c-.635.048-1.223.359-1.82.933l-.196.198c-.439.462-.887 1.064-1.367 1.807l.266.398c.18.274.362.56.55.858l.293.475 1.396 2.335.695 1.114c.583.926 1.03 1.6 1.408 2.082l.213.262c.282.326.529.54.777.673l.102.05c.227.1.457.138.718.138.176.002.35-.023.518-.073.338-.104.61-.32.813-.637l.095-.163.077-.162c.194-.459.29-1.06.29-1.785l-.006-.449c-.08-2.871-.938-5.372-2.2-6.798l-.176-.189c-.67-.683-1.444-1.074-2.27-1.074z"),
    "gemma": ("Gemma", "M12.34 5.953a8.233 8.233 0 01-.247-1.125V3.72a8.25 8.25 0 015.562 2.232H12.34zm-.69 0c.113-.373.199-.755.257-1.145V3.72a8.25 8.25 0 00-5.562 2.232h5.304zm-5.433.187h5.373a7.98 7.98 0 01-.267.696 8.41 8.41 0 01-1.76 2.65L6.216 6.14zm-.264-.187H2.977v.187h2.915a8.436 8.436 0 00-2.357 5.767H0v.186h3.535a8.436 8.436 0 002.357 5.767H2.977v.186h2.976v2.977h.187v-2.915a8.436 8.436 0 005.767 2.357V24h.186v-3.535a8.436 8.436 0 005.767-2.357v2.915h.186v-2.977h2.977v-.186h-2.915a8.436 8.436 0 002.357-5.767H24v-.186h-3.535a8.436 8.436 0 00-2.357-5.767h2.915v-.187h-2.977V2.977h-.186v2.915a8.436 8.436 0 00-5.767-2.357V0h-.186v3.535A8.436 8.436 0 006.14 5.892V2.977h-.187v2.976zm6.14 14.326a8.25 8.25 0 005.562-2.233H12.34c-.108.367-.19.743-.247 1.126v1.107zm-.186-1.087a8.015 8.015 0 00-.258-1.146H6.345a8.25 8.25 0 005.562 2.233v-1.087zm-8.186-7.285h1.107a8.23 8.23 0 001.125-.247V6.345a8.25 8.25 0 00-2.232 5.562zm1.087.186H3.72a8.25 8.25 0 002.232 5.562v-5.304a8.012 8.012 0 00-1.145-.258zm15.47-.186a8.25 8.25 0 00-2.232-5.562v5.315c.367.108.743.19 1.126.247h1.107zm-1.086.186c-.39.058-.772.144-1.146.258v5.304a8.25 8.25 0 002.233-5.562h-1.087zm-1.332 5.69V12.41a7.97 7.97 0 00-.696.267 8.409 8.409 0 00-2.65 1.76l3.346 3.346zm0-6.18v-5.45l-.012-.013h-5.451c.076.235.162.468.26.696a8.698 8.698 0 001.819 2.688 8.698 8.698 0 002.688 1.82c.228.097.46.183.696.259zM6.14 17.848V12.41c.235.078.468.167.696.267a8.403 8.403 0 012.688 1.799 8.404 8.404 0 011.799 2.688c.1.228.19.46.267.696H6.152l-.012-.012zm0-6.245V6.326l3.29 3.29a8.716 8.716 0 01-2.594 1.728 8.14 8.14 0 01-.696.259zm6.257 6.257h5.277l-3.29-3.29a8.716 8.716 0 00-1.728 2.594 8.135 8.135 0 00-.259.696zm-2.347-7.81a9.435 9.435 0 01-2.88 1.96 9.14 9.14 0 012.88 1.94 9.14 9.14 0 011.94 2.88 9.435 9.435 0 011.96-2.88 9.14 9.14 0 012.88-1.94 9.435 9.435 0 01-2.88-1.96 9.434 9.434 0 01-1.96-2.88 9.14 9.14 0 01-1.94 2.88z"),
    "microsoft": ("Microsoft", "M11.49 2H2v9.492h9.492V2h-.002zM22 2h-9.492v9.492H22V2zM11.49 12.508H2V22h9.492v-9.492h-.002zM22 12.508h-9.492V22H22v-9.492z"),
}
OLLAMA_MARK = "M7.905 1.09c.216.085.411.225.588.41.295.306.544.744.734 1.263.191.522.315 1.1.362 1.68a5.054 5.054 0 012.049-.636l.051-.004c.87-.07 1.73.087 2.48.474.101.053.2.11.297.17.05-.569.172-1.134.36-1.644.19-.52.439-.957.733-1.264a1.67 1.67 0 01.589-.41c.257-.1.53-.118.796-.042.401.114.745.368 1.016.737.248.337.434.769.561 1.287.23.934.27 2.163.115 3.645l.053.04.026.019c.757.576 1.284 1.397 1.563 2.35.435 1.487.216 3.155-.534 4.088l-.018.021.002.003c.417.762.67 1.567.724 2.4l.002.03c.064 1.065-.2 2.137-.814 3.19l-.007.01.01.024c.472 1.157.62 2.322.438 3.486l-.006.039a.651.651 0 01-.747.536.648.648 0 01-.54-.742c.167-1.033.01-2.069-.48-3.123a.643.643 0 01.04-.617l.004-.006c.604-.924.854-1.83.8-2.72-.046-.779-.325-1.544-.8-2.273a.644.644 0 01.18-.886l.009-.006c.243-.159.467-.565.58-1.12a4.229 4.229 0 00-.095-1.974c-.205-.7-.58-1.284-1.105-1.683-.595-.454-1.383-.673-2.38-.61a.653.653 0 01-.632-.371c-.314-.665-.772-1.141-1.343-1.436a3.288 3.288 0 00-1.772-.332c-1.245.099-2.343.801-2.67 1.686a.652.652 0 01-.61.425c-1.067.002-1.893.252-2.497.703-.522.39-.878.935-1.066 1.588a4.07 4.07 0 00-.068 1.886c.112.558.331 1.02.582 1.269l.008.007c.212.207.257.53.109.785-.36.622-.629 1.549-.673 2.44-.05 1.018.186 1.902.719 2.536l.016.019a.643.643 0 01.095.69c-.576 1.236-.753 2.252-.562 3.052a.652.652 0 01-1.269.298c-.243-1.018-.078-2.184.473-3.498l.014-.035-.008-.012a4.339 4.339 0 01-.598-1.309l-.005-.019a5.764 5.764 0 01-.177-1.785c.044-.91.278-1.842.622-2.59l.012-.026-.002-.002c-.293-.418-.51-.953-.63-1.545l-.005-.024a5.352 5.352 0 01.093-2.49c.262-.915.777-1.701 1.536-2.269.06-.045.123-.09.186-.132-.159-1.493-.119-2.73.112-3.67.127-.518.314-.95.562-1.287.27-.368.614-.622 1.015-.737.266-.076.54-.059.797.042zm4.116 9.09c.936 0 1.8.313 2.446.855.63.527 1.005 1.235 1.005 1.94 0 .888-.406 1.58-1.133 2.022-.62.375-1.451.557-2.403.557-1.009 0-1.871-.259-2.493-.734-.617-.47-.963-1.13-.963-1.845 0-.707.398-1.417 1.056-1.946.668-.537 1.55-.849 2.485-.849zm0 .896a3.07 3.07 0 00-1.916.65c-.461.37-.722.835-.722 1.25 0 .428.21.829.61 1.134.455.347 1.124.548 1.943.548.799 0 1.473-.147 1.932-.426.463-.28.7-.686.7-1.257 0-.423-.246-.89-.683-1.256-.484-.405-1.14-.643-1.864-.643zm-5.04-1.919c.478 0 .867.39.867.871a.87.87 0 01-.868.871.87.87 0 01-.867-.87.87.87 0 01.867-.872zm8.706 0c.48 0 .868.39.868.871a.87.87 0 01-.868.871.87.87 0 01-.867-.87.87.87 0 01.867-.872z"

CSS = """:root{
  color-scheme:light dark;
  --ground:#F5F5F7;--surface:#FFFFFF;--raised:#F9F9FA;
  --border:#E5E5EA;--rule:#F0F0F2;--control:#D1D1D6;
  --text:#1D1D1F;--muted:#5E5E63;--faint:#6E6E73;
  --accent:#0071E3;--accent-ink:#0066CC;--accent-track:#E8F1FC;
  --primary:#1D1D1F;--on-primary:#FFFFFF;
  --pos-bg:#E3F5E7;--pos-ink:#0B3D17;--pos:#1F7A34;
  --neg:#C4242A;--neg-bg:#FFEDEA;--neg-ink:#831C1E;
  --warn-bg:#FFF8E6;--warn-ink:#8A4B00;--warn-line:#F5D58A;
  --est-bg:#F3EEFF;--est-ink:#5B3FA8;--est-line:#D9CCF7;
  --grid:#ECECF0;--focus:#0071E3;
  /* model series: 4 hues + neutral "other" (taste: <= 4 hues per chart) */
  --m1:#0071E3;--m2:#0E8A7E;--m3:#D9730D;--m4:#C9356B;--m0:#AEAEB2;
  --r-card:12px;--r-ctl:8px;--gap:16px;--pad:20px;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Helvetica,Arial,sans-serif;
  --fs-xs:12px;--fs-s:13px;--fs-m:15px;--fs-l:20px;--fs-xl:26px;--fs-hero:40px;
  /* one family for every word and figure; mono is reserved for code (endpoint paths) */
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  /* motion identity (motion-design skill, "Corporate"): one curve, three durations */
  --ease:cubic-bezier(.2,0,0,1);--t1:120ms;--t2:240ms;--t3:360ms;
}
@media (prefers-color-scheme:dark){:root{
  --ground:#000000;--surface:#161618;--raised:#1F1F22;
  --border:#2A2A2D;--rule:#222225;--control:#3A3A3E;
  --text:#F5F5F7;--muted:#AEAEB2;--faint:#98989D;
  --accent:#0A84FF;--accent-ink:#4DA3FF;--accent-track:#0E2238;
  --primary:#F5F5F7;--on-primary:#000000;
  --pos-bg:#11291A;--pos-ink:#5BE07F;--pos:#30D158;
  --neg:#FF6B61;--neg-bg:#3A1715;--neg-ink:#FF8A80;
  --warn-bg:#2E2208;--warn-ink:#FFC75A;--warn-line:#5C4512;
  --est-bg:#221A38;--est-ink:#C4B2FF;--est-line:#3D3166;
  --grid:#232326;--focus:#4DA3FF;
  --m1:#0A84FF;--m2:#40C8B5;--m3:#FF9F0A;--m4:#FF5C8A;--m0:#636366;
}}
@media (prefers-contrast:more){:root{--border:#8E8E93;--rule:#C7C7CC;--muted:#3A3A3C;--faint:#48484A}}

*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--ground);color:var(--text);font:400 var(--fs-m)/1.5 var(--font);font-variant-numeric:tabular-nums;-webkit-text-size-adjust:100%}
.num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
code{font-family:var(--mono);font-size:var(--fs-s)}
b,strong{font-weight:600}
.muted{color:var(--muted)}
a{color:var(--accent-ink);text-decoration:none}
a:hover{text-decoration:underline}
a:focus-visible,summary:focus-visible,.scroll:focus-visible,.wide-chart:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}

.shell{max-width:1320px;margin:0 auto;padding:0 clamp(16px,3vw,40px) 56px}
.top{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding:14px 0}
.brand{display:flex;align-items:center;gap:10px}
.mark{display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:var(--surface);border:1px solid var(--border)}
.scope{color:var(--muted)}
.spacer{flex:1}
.stamp{color:var(--muted);font-size:var(--fs-s)}
.btn{display:inline-flex;align-items:center;min-height:44px;padding:0 16px;border-radius:var(--r-ctl);font-weight:500;font-size:var(--fs-m)}
.btn-primary{background:var(--primary);color:var(--on-primary)}
.btn-primary:hover{text-decoration:none;opacity:.88}
.notice{font-size:var(--fs-xs);color:var(--warn-ink);background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:6px;padding:4px 10px;margin:0 0 16px;display:inline-block}

.chip{flex:none;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-size:var(--fs-xs);font-weight:500;line-height:18px;padding:0 7px;border-radius:999px;border:1px solid transparent;vertical-align:1px}
.chip .g{font-size:8px}
.chip-ok{background:var(--pos-bg);color:var(--pos-ink)}
.chip-bad{background:var(--neg-bg);color:var(--neg-ink)}
.chip-warn{background:var(--warn-bg);color:var(--warn-ink);border-color:var(--warn-line)}
.chip-measured{background:var(--accent-track);color:var(--accent-ink);border-color:var(--accent)}
.chip-declared{color:var(--muted);border:1px dashed var(--control)}
.chip-est{background:var(--est-bg);color:var(--est-ink);border:1px dashed var(--est-line)}
.chip-sample{color:var(--warn-ink);border:1px dashed var(--warn-line)}

.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:var(--gap)}
.s12{grid-column:span 12}.s8{grid-column:span 8}.s7{grid-column:span 7}.s5{grid-column:span 5}.s4{grid-column:span 4}
.col{display:flex;flex-direction:column;gap:var(--gap);min-width:0}
.col>.panel:last-child{flex:1}
@media (max-width:1080px){.grid{grid-template-columns:minmax(0,1fr)}.s12,.s8,.s7,.s5,.s4{grid-column:1/-1}}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-card);min-width:0}
.ph{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;padding:16px var(--pad) 8px}
.ph h2{font-size:var(--fs-m);font-weight:600}
.ph .meta{font-size:var(--fs-s);color:var(--muted)}
.ph .end{margin-left:auto;font-size:var(--fs-s)}
.pb{padding:4px var(--pad) var(--pad)}
.fine{font-size:var(--fs-xs);color:var(--faint);margin-top:8px}

/* KPI strip: one container, hairline dividers, lead figure 1.5x siblings */
.kpis{display:grid;grid-template-columns:1.6fr repeat(3,1fr) 1.2fr}
.kpi{padding:18px var(--pad);min-width:0}
.kpi+.kpi{border-left:1px solid var(--border)}
.kpi.declared{border-left-style:dashed;background:var(--raised);border-radius:0 var(--r-card) var(--r-card) 0}
.kl{font-size:var(--fs-s);color:var(--muted);display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kv{font-size:var(--fs-xl);font-weight:500;line-height:1.2;margin-top:6px;letter-spacing:-.01em}
.kpi.lead .kv{font-size:var(--fs-hero);font-weight:600;letter-spacing:-.02em}
.kv .u{font-size:var(--fs-s);color:var(--muted);margin-left:5px;letter-spacing:0}
.ks{font-size:var(--fs-xs);color:var(--muted);margin-top:4px}
.bad-t{color:var(--neg)}
@media (max-width:1080px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi.lead{grid-column:1/-1}.kpi+.kpi{border-left:0;border-top:1px solid var(--border)}.kpi.declared{grid-column:1/-1;border-top-style:dashed;border-radius:0 0 var(--r-card) var(--r-card)}}

/* charts */
.chart{display:block;width:100%;height:auto;overflow:visible}
.chart .gl{stroke:var(--grid);stroke-width:1}
.chart .axis{stroke:var(--control);stroke-width:1.5}
.chart .tick{fill:var(--faint);font:400 calc(var(--fs-xs) * var(--s,1)) var(--font)}
.chart .ann{fill:var(--text);font:400 calc(var(--fs-s) * var(--s,1)) var(--font)}
.chart .line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.chart .area{fill:var(--accent);fill-opacity:.1}
.chart .now{fill:var(--accent)}
.chart .low{fill:var(--surface);stroke:var(--text);stroke-width:1.5}
.chart rect{shape-rendering:crispEdges}
.chart .col rect{stroke:var(--surface);stroke-width:1}
.chart .lbl{fill:var(--text);font:500 calc(var(--fs-s) * var(--s,1)) var(--font)}
.chart .lbl2{fill:var(--muted);font:400 calc(var(--fs-xs) * var(--s,1)) var(--font)}
.chart .acc{fill:var(--accent-ink);font:600 calc(var(--fs-xs) * var(--s,1)) var(--font)}
.chart .meter{fill:var(--accent)}
.chart .lg{color:var(--text)}
.chart .leak{stroke:var(--faint);stroke-width:1.5;stroke-dasharray:4 3}
.chart .rng{fill:var(--est-bg);stroke:var(--est-line)}
.chart .base-dot{fill:var(--est-ink);stroke:var(--surface);stroke-width:2}
.chart .empty{fill:none;stroke:var(--border);stroke-dasharray:3 3}
.chart .hc{fill:var(--text);font:400 calc(var(--fs-xs) * var(--s,1)) var(--font)}
.chart .hc.on{fill:#FFFFFF;font-weight:500}

/* leaderboard (OpenRouter-style ranked list) */
.board{list-style:none;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:0 32px;margin-top:12px;border-top:1px solid var(--rule)}
.board li{display:grid;grid-template-columns:22px 32px minmax(0,1fr) 10px auto;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--rule)}
.board .rk{color:var(--faint);font-size:var(--fs-s)}
.board .nm{display:flex;flex-direction:column;min-width:0}
.board .nm b{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.board .nm span{font-size:var(--fs-xs);color:var(--muted)}
.board .dot{width:8px;height:8px;border-radius:50%}
.board .val{display:flex;flex-direction:column;align-items:flex-end}
.board .val b{font-weight:500}
.board .val span{font-size:var(--fs-xs);color:var(--muted)}
.logo{display:inline-grid;place-items:center;color:var(--text);flex:none}
.logo.tile{width:32px;height:32px;border-radius:8px;background:var(--raised);border:1px solid var(--border)}
.mono-tile{width:16px;height:16px;border-radius:4px;background:var(--raised);border:1px solid var(--border);font:600 var(--fs-xs) var(--font)}
.logo.tile.mono-tile{width:32px;height:32px;font-size:var(--fs-s)}
.mc{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;font-size:var(--fs-s)}

/* cost + ring */
.big{font:600 var(--fs-xl)/1.2 var(--font);letter-spacing:-.01em;color:var(--est-ink)}
.big2{font:500 var(--fs-l)/1.2 var(--font)}
.big3{font-size:var(--fs-l);font-weight:500}
.legend{display:flex;gap:16px;font-size:var(--fs-xs);color:var(--muted);margin-top:2px}
.legend i{display:inline-block;width:14px;height:8px;border-radius:4px;margin-right:6px;vertical-align:0}
.lg-rng{background:var(--est-bg);border:1px solid var(--est-line)}
.lg-dot{width:8px!important;background:var(--est-ink)}
details{margin-top:10px;font-size:var(--fs-s)}
summary{cursor:pointer;color:var(--accent-ink);min-height:32px;display:inline-flex;align-items:center}
.mini{width:100%;border-collapse:collapse;font-size:var(--fs-xs);margin-top:4px}
.mini th,.mini td{padding:4px 0;border-bottom:1px solid var(--rule);text-align:left;font-weight:400}
.mini th{color:var(--muted)}
.r{text-align:right!important}
.ringrow{display:flex;align-items:center;gap:20px}
.ring{width:112px;height:112px;flex:none}
.ring-t{fill:none;stroke:var(--rule);stroke-width:10}
.ring-v{fill:none;stroke:var(--accent);stroke-width:10;stroke-linecap:round}
.ring-n{fill:var(--text);font:600 var(--fs-l) var(--font)}
.ring-l{fill:var(--muted);font:400 var(--fs-xs) var(--font)}

.ramfit{list-style:none;border-top:1px solid var(--rule)}
.ramfit li{display:grid;grid-template-columns:minmax(0,1fr) 96px 56px 78px;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--rule);font-size:var(--fs-xs)}
.ramfit li>span:nth-child(3){text-align:right}
.ramfit li>span:last-child{justify-self:end}
.fit{position:relative;height:6px;border-radius:3px;background:var(--rule)}
.fit i{position:absolute;inset:0 auto 0 0;border-radius:3px;background:var(--faint)}
.fit.on i{background:var(--accent)}
.fit.over i{background:var(--neg)}
.fit.over::after{content:"";position:absolute;right:-4px;top:-3px;width:2px;height:12px;background:var(--neg)}
/* tables */
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:var(--fs-s)}
th{font-weight:500;font-size:var(--fs-xs);color:var(--muted);text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:0 12px;height:44px;border-bottom:1px solid var(--rule);white-space:nowrap}
tr:last-child td{border-bottom:0}
th:first-child,td:first-child{padding-left:var(--pad)}th:last-child,td:last-child{padding-right:var(--pad)}
td.id{font-weight:500}
.dash{color:var(--faint)}
tbody tr{transition:background-color var(--t1) var(--ease)}
tbody tr:hover{background:var(--raised)}

.evals{list-style:none;padding:0 var(--pad) 12px}
.evals li{font-size:var(--fs-s);display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;align-items:center;padding:10px 0;border-bottom:1px solid var(--rule)}
.evals li:last-child{border-bottom:0}
.pds{display:inline-flex;align-items:center;gap:4px;justify-self:end}
.pds .num{margin-left:6px;font-size:var(--fs-s)}
.pd{width:10px;height:10px;border-radius:50%;background:var(--pos)}
.pd.miss{background:none;border:1.5px solid var(--neg)}
.evals .num.muted{font-size:var(--fs-xs)}
.evals .chip,.evals li>.muted:last-child{justify-self:end}

.links{display:flex;flex-wrap:wrap;gap:8px;padding:20px 0 0}
.links a{display:inline-flex;flex-direction:column;justify-content:center;min-height:44px;padding:6px 14px;border:1px solid var(--border);border-radius:var(--r-ctl);background:var(--surface);color:var(--text)}
.links a:hover{text-decoration:none;border-color:var(--control)}
.links code{font-size:var(--fs-s);color:var(--accent-ink)}
.links span{font-size:var(--fs-xs);color:var(--muted)}
footer{margin-top:14px;font-size:var(--fs-xs);color:var(--faint)}

/* motion: primary = columns grow from the baseline (transform only, 30 ms wave, 420 ms budget),
   secondary = leaderboard rows settle in, ambient = slow pulse on the live dot. */
@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
@keyframes settle{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes breathe{0%,100%{opacity:1}50%{opacity:.35}}
.chart .col{transform-box:fill-box;transform-origin:50% 100%;animation:grow var(--t3) var(--ease) both;animation-delay:calc(var(--i) * 30ms)}
.board li{animation:settle var(--t2) var(--ease) both;animation-delay:calc(200ms + var(--i) * 40ms)}
.pulse{animation:breathe 2.4s ease-in-out infinite}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
@media (max-width:640px){.spacer{display:none}.ringrow{gap:12px}.ramfit li{grid-template-columns:minmax(0,1fr) 56px 78px}.ramfit .fit{display:none}.wide-chart{overflow-x:auto}.wide-chart>.chart{min-width:600px}}
"""


def esc(v):
    return html.escape(str(v), quote=True)


def n(v):
    return "{:,}".format(v)


def usd(v):
    if v < 0.01:
        return "$%.3f" % v
    if v < 1:
        return "$%.2f" % v if v >= 0.1 else "$%.3f" % v
    return "${:,.2f}".format(v)


def largest_remainder(total, weights):
    """Split an integer total by weights; parts are integers that sum exactly to total."""
    s = sum(weights)
    if total <= 0 or s <= 0:
        return [0] * len(weights)
    raw = [total * w / s for w in weights]
    out = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: (-(raw[i] - out[i]), i))[:total - sum(out)]:
        out[i] += 1
    return out


def _intval(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def provider_of(model):
    m = str(model).lower()
    if m.startswith("qwen"):
        return "qwen"
    if "gemma" in m:
        return "gemma"
    if m.startswith("llama"):
        return "meta"
    if m.startswith("phi"):
        return "microsoft"
    return None


def sprite():
    out = ['<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>']
    for key, (_, d) in LOGOS.items():
        out.append('<symbol id="lg-%s" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="%s"/></symbol>' % (key, d))
    out.append('<symbol id="lg-ollama" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="%s"/></symbol>' % OLLAMA_MARK)
    out.append("</defs></svg>")
    return "".join(out)


def logo(model, size=20, cls="logo"):
    p = provider_of(model)
    if not p:
        return '<span class="%s mono-tile" aria-hidden="true">%s</span>' % (cls, esc(str(model)[:1].upper() or "?"))
    return '<span class="%s" title="%s"><svg width="%d" height="%d" aria-hidden="true" focusable="false"><use href="#lg-%s"/></svg></span>' % (cls, LOGOS[p][0], size, size, p)


def _day(iso):
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _abbr(iso):
    d = _day(iso)
    return ("%s %d" % (MONTHS[d.month - 1][:3], d.day)) if d else esc(str(iso)[:10])


def _span_words(dates):
    a, b = _day(dates[0]), _day(dates[-1])
    if not a or not b:
        return ""
    if a.month == b.month:
        return "%d to %d %s" % (a.day, b.day, MONTHS[b.month - 1])
    return "%d %s to %d %s" % (a.day, MONTHS[a.month - 1], b.day, MONTHS[b.month - 1])


def _parse_ts(s):
    s = str(s or "")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _ago(seconds):
    s = int(seconds)
    if s < 90:
        return "%d s" % s
    if s < 5400:
        return "%d min" % round(s / 60)
    return "%d h" % round(s / 3600)


def _nice_step(x):
    if x <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= x:
            v = m * mag
            return int(v) if v >= 1 and float(v).is_integer() else v
    return 10 * mag


def _tick(v):
    if v >= 1000:
        k = v / 1000
        return "%dk" % k if float(k).is_integer() else ("%.1fk" % k)
    return "%d" % v if float(v).is_integer() else "%.1f" % v


def _chip(kind, word, glyph=None):
    g = '<span class="g" aria-hidden="true">%s</span>' % glyph if glyph else ""
    return '<span class="chip chip-%s">%s%s</span>' % (kind, g, word)


def token_mix(st):
    """Per-model / per-day / per-agent token split for the diagram panels.

    Real when /status carries metering_breakdown (state-file rollups since `since`);
    otherwise a Sample: the live total split by SAMPLE_* shares (largest-remainder).
    """
    m = st.get("metering") or {}
    bd = st.get("metering_breakdown")
    calls = st.get("calls") or []
    if bd is not None:
        pm = [r for r in bd.get("per_model", []) if (_intval(r.get("eval_tokens")) or 0) > 0]
        top, rest = pm[:4], pm[4:]
        models = [(r["model"], SERIES_VARS[i], r["eval_tokens"], MAKERS.get(provider_of(r["model"]), "unknown maker"), r["model"])
                  for i, r in enumerate(top)]
        if rest:
            label = rest[0]["model"] if len(rest) == 1 else "%s + %d more" % (rest[0]["model"], len(rest) - 1)
            makers = []
            for r in rest:
                mk = MAKERS.get(provider_of(r["model"]), "unknown maker")
                if mk not in makers:
                    makers.append(mk)
            models.append((label, "m0", sum(r["eval_tokens"] for r in rest), ", ".join(makers), rest[0]["model"]))
        daily = bd.get("daily", [])
        dates = [d.get("date", "") for d in daily]
        rows = [[_intval((d.get("by_model") or {}).get(r["model"])) or 0 for d in daily] for r in top]
        if rest:
            names = {r["model"] for r in rest}
            rows.append([sum(v for k, v in (d.get("by_model") or {}).items() if k in names) for d in daily])
        pa = [r for r in bd.get("per_agent", []) if (_intval(r.get("eval_tokens")) or 0) > 0]
        agents = [(r["agent"], r["eval_tokens"]) for r in pa[:4]]
        if pa[4:]:
            agents.append(("%d more" % len(pa[4:]), sum(r["eval_tokens"] for r in pa[4:])))
        fails = bd.get("failures") or {}
        by_status = fails.get("by_status") or {}
        return {"sample": False, "models": models, "rows": rows, "dates": dates, "agents": agents,
                "total": sum(x[2] for x in models), "failed": _intval(fails.get("total")) or 0,
                "statuses": sorted(by_status, key=lambda s: (-by_status[s], s)),
                "no_usage": sum(_intval(r.get("no_usage")) or 0 for r in bd.get("per_model", [])),
                "since": bd.get("since")}
    total = _intval(m.get("eval_tokens_total")) or 0
    tots = largest_remainder(total, [x[2] for x in SAMPLE_MODELS])
    models = [(name, var, t, maker, lg) for (name, var, _, maker, lg), t in zip(SAMPLE_MODELS, tots)]
    daily = (st.get("activity") or {}).get("daily") or []
    dates = [d.get("date", "") for d in daily]
    dcount = [_intval(d.get("count")) or 0 for d in daily]
    rows = []
    for (_, _, t, _, _), f in zip(models, SAMPLE_BEND):
        w = [dcount[i] * f(i) for i in range(len(dcount))]
        if not w or sum(w) <= 0:
            rows.append([0] * len(dcount))
            continue
        row = [round(t * x / sum(w)) for x in w]
        last = max(i for i in range(len(w)) if w[i] > 0)
        row[last] += t - sum(row)
        if min(row) < 0:
            row = largest_remainder(t, w)
        rows.append(row)
    agents = list(zip([a for a, _ in SAMPLE_AGENTS], largest_remainder(total, [w for _, w in SAMPLE_AGENTS])))
    failed = [c for c in calls if not c.get("ok", True) and not c.get("partial")]
    statuses = []
    for c in failed:
        s = str(c.get("status") or "unknown status")
        if s not in statuses:
            statuses.append(s)
    return {"sample": True, "models": models, "rows": rows, "dates": dates, "agents": agents, "total": total,
            "failed": len(failed), "statuses": statuses,
            "no_usage": _intval(m.get("unmetered_stream_calls")) or 0, "since": None}


def stacked_chart(mix):
    rows, dates = mix["rows"], mix["dates"]
    days = len(dates)
    cols = [sum(r[i] for r in rows) for i in range(days)]
    step = _nice_step(max(cols) / 3)
    ticks = max(1, math.ceil(max(cols) / step))
    top = ticks * step
    x0, x1, yb, yt = 48, 632, 196, 16
    slot = (x1 - x0) / days
    bw = slot - 12
    Y = lambda v: (yb - yt) * v / top
    busy = max(range(days), key=lambda i: (cols[i], i))
    bd = _day(dates[busy])
    lead = "Sample: generated" if mix["sample"] else "Generated"
    p = ['<svg class="chart" style="--s:.82" viewBox="0 0 640 224" role="img" aria-labelledby="use-t">',
         '<title id="use-t">%s tokens per day by model, %s; busiest day %s with %s.</title>' % (
             lead, _span_words(dates), ("%d %s" % (bd.day, MONTHS[bd.month - 1])) if bd else esc(dates[busy]), n(cols[busy]))]
    for j in range(1, ticks + 1):
        v = step * j
        y = yb - Y(v)
        p.append('<line class="gl" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/><text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>' % (x0, y, x1, y, x0 - 8, y + 5, _tick(v)))
    p.append('<text class="tick" x="%d" y="%d" text-anchor="end">0</text>' % (x0 - 8, yb + 5))
    for i in range(days):
        x = x0 + i * slot + 6
        y = yb
        seg = []
        for (name, var, _, _, _), row in zip(mix["models"], rows):
            h = Y(row[i])
            if h <= 0:
                continue
            y -= h
            seg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="var(--%s)"><title>%s: %s</title></rect>' % (x, y, bw, h, var, esc(name), n(row[i])))
        if seg:
            p.append('<g class="col" style="--i:%d"><title>%s: %s tokens</title>%s</g>' % (i, _abbr(dates[i]), n(cols[i]), "".join(seg)))
    p.append('<line class="axis" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (x0, yb, x1, yb))
    for i in sorted(range(days - 1, -1, -3)):
        p.append('<text class="tick" x="%.1f" y="218" text-anchor="middle">%s</text>' % (x0 + i * slot + slot / 2, _abbr(dates[i])))
    p.append("</svg>")
    return "".join(p)


def leaderboard(mix):
    total = mix["total"] or 1
    li = []
    for rank, (name, var, tok, maker, lg) in enumerate(mix["models"], 1):
        li.append('<li style="--i:%d"><span class="rk num">%d.</span>%s<span class="nm"><b>%s</b><span>by %s</span></span><span class="dot" style="background:var(--%s)" aria-hidden="true"></span><span class="val"><b class="num">%s</b><span class="num">%.1f%%</span></span></li>'
                  % (rank, rank, logo(lg, 18, "logo tile"), esc(name), esc(maker), var, n(tok), 100 * tok / total))
    return '<ol class="board">' + "".join(li) + "</ol>"


def _leak_text(mix):
    parts = []
    if mix["no_usage"]:
        parts.append("%d stream%s without usage" % (mix["no_usage"], "" if mix["no_usage"] == 1 else "s"))
    if mix["failed"]:
        parts.append("%d failed (%s)" % (mix["failed"], ", ".join(esc(s) for s in mix["statuses"])))
    return (" · ".join(parts) + " · not counted") if parts else ""


def sankey(mix):
    W, H = 760, 320
    total = mix["total"]
    k = 236 / total
    lx, mx, rx = 132, 372, 600
    lead = "Sample: generated" if mix["sample"] else "Generated"
    out = ['<svg class="chart" style="--s:1.12" viewBox="0 0 %d %d" role="img" aria-labelledby="flow-t">' % (W, H),
           '<title id="flow-t">%s tokens flow from agents through the metering proxy into models. %s</title>' % (lead, "; ".join("%s %s" % (esc(a), n(v)) for a, v in mix["agents"]))]

    def band(xa, a0, a1, xb, b0, b1, fill, op):
        xm = (xa + xb) / 2
        return '<path d="M%.1f %.1f C%.1f %.1f %.1f %.1f %.1f %.1f L%.1f %.1f C%.1f %.1f %.1f %.1f %.1f %.1fZ" fill="%s" fill-opacity="%s"/>' % (
            xa, a0, xm, a0, xm, b0, xb, b0, xb, b1, xm, b1, xm, a1, xa, a1, fill, op)

    y, my = 20, 32
    for a, v in mix["agents"]:
        h = v * k
        label = a if len(a) <= 18 else a[:17] + "…"
        out.append(band(lx + 6, y, y + h, mx, my, my + h, "var(--muted)", ".16"))
        out.append('<rect x="%d" y="%.1f" width="6" height="%.1f" rx="1" fill="var(--muted)"/>' % (lx, y, h))
        out.append('<text class="lbl" x="%d" y="%.1f" text-anchor="end">%s <tspan class="lbl2 num">%s</tspan></text>' % (lx - 10, y + h / 2 + 5, esc(label), n(v)))
        y += max(h, 18) + 10
        my += h
    out.append('<rect class="meter" x="%d" y="32" width="12" height="%.1f" rx="2"/>' % (mx, total * k))
    out.append('<text class="lbl acc" x="%d" y="22" text-anchor="middle">proxy tap · measured</text>' % (mx + 6))
    y, my = 14, 32
    for (name, var, tok, _, lg) in mix["models"]:
        h = tok * k
        out.append(band(mx + 12, my, my + h, rx, y, y + h, "var(--%s)" % var, ".28"))
        out.append('<rect x="%d" y="%.1f" width="6" height="%.1f" rx="1" fill="var(--%s)"/>' % (rx, y, max(h, 2), var))
        cy = y + max(h, 2) / 2
        p = provider_of(lg)
        if p:
            out.append('<use href="#lg-%s" x="%d" y="%.1f" width="16" height="16" class="lg"/>' % (p, rx + 14, cy - 8))
        label = name if len(name) <= 18 else name[:17] + "…"
        out.append('<text class="lbl" x="%d" y="%.1f">%s <tspan class="lbl2 num">%s</tspan></text>' % (rx + 36, cy + 5, esc(label), n(tok)))
        y += max(h, 2) + (12 if h > 20 else 18)
        my += h
    leak = _leak_text(mix)
    if leak:
        ly = 32 + total * k + 12
        out.append('<path d="M%d %.1f V%.1f" class="leak"/>' % (mx + 6, ly - 6, ly + 14))
        out.append('<text class="lbl2" x="%d" y="%.1f" text-anchor="middle">%s</text>' % (mx + 6, ly + 34, leak))
    out.append("</svg>")
    return "".join(out)


def cost_estimate(m):
    return {k: ((_intval(m.get("prompt_tokens_total")) or 0) * i + (_intval(m.get("eval_tokens_total")) or 0) * o) / 1e6 for k, i, o in RATES}


def _decade_label(e):
    if e >= 0:
        return "$" + "{:,}".format(10 ** e)
    if e == -1:
        return "$0.10"
    return "$%.*f" % (-e, 10.0 ** e)


def cost_range(cost):
    lo, base, hi = cost["Low"], cost["Base"], cost["High"]
    a = math.floor(math.log10(lo))
    b = max(a + 1, math.ceil(math.log10(hi)))
    X = lambda v: 14 + (math.log10(v) - a) / (b - a) * 332
    p = ['<svg class="chart" style="--s:1" viewBox="0 0 360 74" role="img" aria-labelledby="cost-t"><title id="cost-t">Estimated cloud-equivalent cost avoided: low %s, base %s, high %s.</title>' % (usd(lo), usd(base), usd(hi))]
    p.append('<line class="axis" x1="14" y1="30" x2="346" y2="30"/>')
    for e in range(a, b + 1):
        v = 10.0 ** e
        p.append('<line class="gl" x1="%.1f" y1="24" x2="%.1f" y2="36"/><text class="tick" x="%.1f" y="66" text-anchor="middle">%s</text>' % (X(v), X(v), X(v), _decade_label(e)))
    p.append('<rect class="rng" x="%.1f" y="25" width="%.1f" height="10" rx="5"/>' % (X(lo), X(hi) - X(lo)))
    p.append('<circle class="base-dot" cx="%.1f" cy="30" r="7"/>' % X(base))
    p.append("</svg>")
    return "".join(p)


def ring(models):
    loaded = [m for m in models if m.get("loaded")]
    mb = sum(_intval(m.get("size_mb")) or 0 for m in loaded)
    frac = min(1.0, mb / RAM_MB)
    r, c = 44, 2 * math.pi * 44
    return ('<svg class="ring" style="--s:1.07" viewBox="0 0 120 120" role="img" aria-label="%s MB of 8 GB RAM held by loaded model weights">'
            '<circle cx="60" cy="60" r="%d" class="ring-t"/>%s'
            '<text x="60" y="58" text-anchor="middle" class="ring-n num">%.1f%%</text><text x="60" y="76" text-anchor="middle" class="ring-l">of 8 GB</text></svg>') % (
        n(mb), r, ('<circle cx="60" cy="60" r="%d" class="ring-v" stroke-dasharray="%.1f %.1f" transform="rotate(-90 60 60)"/>' % (r, c * frac, c)) if frac > 0 else "",
        100 * frac), mb, loaded


def too_big(models):
    return [m for m in models if (_intval(m.get("size_mb")) or 0) > RAM_MB or m.get("name") in DO_NOT_RUN]


def ramfit(models):
    """Loaded models plus the three largest that fit, then the ones over 8 GB."""
    fits = sorted([m for m in models if (_intval(m.get("size_mb")) or 0) <= RAM_MB], key=lambda m: -(_intval(m.get("size_mb")) or 0))
    over = sorted([m for m in models if (_intval(m.get("size_mb")) or 0) > RAM_MB], key=lambda m: -(_intval(m.get("size_mb")) or 0))
    keep = set(id(m) for m in fits[:3]) | set(id(m) for m in fits if m.get("loaded"))
    rows = []
    for m in [m for m in fits if id(m) in keep] + over:
        size = _intval(m.get("size_mb")) or 0
        is_over = size > RAM_MB
        w = min(100.0, 100 * size / RAM_MB)
        cls = "over" if is_over else ("on" if m.get("loaded") else "")
        if is_over:
            note = _chip("bad", "Too big", "■")
        elif m.get("loaded"):
            note = _chip("ok", "Loaded", "●")
        elif m.get("name") in DO_NOT_RUN:
            note = _chip("bad", "Do not run", "■")
        else:
            note = ""
        name = str(m.get("name", "?"))
        short = name[:-7] if name.endswith(":latest") else name
        label = esc(short) if len(short) <= 12 else '<span title="%s">%s…</span>' % (esc(name), esc(short[:11]))
        rows.append('<li><span class="mc">%s<span>%s</span></span><span class="fit %s" aria-hidden="true"><i style="width:%.1f%%"></i></span><span class="num">%.1f GB</span><span>%s</span></li>' % (logo(name, 14, "logo"), label, cls, w, size / 1024, note))
    return '<ul class="ramfit">' + "".join(rows) + '</ul><p class="fine">Weights on disk against the 8 GB box; KV cache and macOS need the rest.</p>'


def heat(daily):
    dcount = [_intval(d.get("count")) or 0 for d in daily]
    hi = max(dcount) or 1
    p = ['<svg class="chart" style="--s:1.2" viewBox="0 0 560 64" role="img" aria-labelledby="heat-t"><title id="heat-t">Probe checks per day: %s.</title>' % ", ".join("%s %d" % (_abbr(d.get("date", "")), c) for d, c in zip(daily, dcount))]
    for i, (d, c) in enumerate(zip(daily, dcount)):
        x = i * 40
        lvl = 0 if c == 0 else min(4, 1 + int(3.999 * c / hi))
        op = [0, .22, .45, .7, 1][lvl]
        if lvl:
            p.append('<rect x="%d" y="0" width="36" height="36" rx="6" fill="var(--accent)" fill-opacity="%s"/>' % (x, op))
        else:
            p.append('<rect x="%.1f" y=".5" width="35" height="35" rx="6" class="empty"/>' % (x + .5))
        p.append('<text x="%d" y="23" text-anchor="middle" class="hc num%s">%d</text>' % (x + 18, " on" if lvl >= 3 else "", c))
        dd = _day(d.get("date", ""))
        p.append('<text x="%d" y="58" text-anchor="middle" class="tick">%s</text>' % (x + 18, dd.day if dd else "?"))
    p.append("</svg>")
    return "".join(p)


def throughput(v):
    x0, x1, yb, yt = 40, 552, 104, 10
    last = len(v) - 1 or 1
    top = 120 if max(v) <= 120 else 2 * _nice_step(max(v) / 2)
    X = lambda i: x0 + i * (x1 - x0) / last
    Y = lambda val: yb - val / top * (yb - yt)
    pts = " ".join("%.1f,%.1f" % (X(i), Y(a)) for i, a in enumerate(v))
    area = "M%.1f %d L%s L%.1f %dZ" % (X(0), yb, " L".join("%.1f %.1f" % (X(i), Y(a)) for i, a in enumerate(v)), X(last), yb)
    lo = v.index(min(v))
    span = (len(v) - 1) * 5  # minutes, at the 5-minute monitor cadence
    since = ("≈ −%d h" % round(span / 60)) if span >= 60 else ("≈ −%d min" % span)
    return ('<svg class="chart" style="--s:1.2" viewBox="0 0 560 128" role="img" aria-labelledby="tp-t"><title id="tp-t">Probe throughput, last %d checks: median %.1f, low %.1f, latest %.1f tok/s.</title>'
            '<line class="gl" x1="40" y1="%.1f" x2="552" y2="%.1f"/><text class="tick" x="32" y="%.1f" text-anchor="end">%s</text>'
            '<line class="gl" x1="40" y1="%.1f" x2="552" y2="%.1f"/><text class="tick" x="32" y="%.1f" text-anchor="end">%s</text>'
            '<line class="axis" x1="40" y1="%d" x2="552" y2="%d"/><text class="tick" x="32" y="%d" text-anchor="end">0</text>'
            '<path d="%s" class="area"/><polyline points="%s" class="line"/>'
            '<circle cx="%.1f" cy="%.1f" r="5" class="low"/><text class="ann" x="%.1f" y="%.1f">low %.1f</text>'
            '<circle cx="%.1f" cy="%.1f" r="5" class="now"/>'
            '<text class="tick" x="40" y="124">%s</text><text class="tick" x="552" y="124" text-anchor="end">now</text></svg>') % (
        len(v), statistics.median(v), min(v), v[-1], Y(top), Y(top), Y(top) + 5, _tick(top), Y(top / 2), Y(top / 2), Y(top / 2) + 5, _tick(top / 2),
        yb, yb, yb + 5, area, pts, X(lo), Y(v[lo]), X(lo) + 12, Y(v[lo]) + 20, v[lo], X(last), Y(v[-1]), since)


def call_rows(calls):
    rows = []
    for c in calls:
        et = _intval(c.get("eval_tokens"))
        pt = _intval(c.get("prompt_tokens"))
        if not c.get("ok", True):
            res = _chip("bad", ("Failed %s" % esc(c["status"])) if c.get("status") is not None else "Failed", "■")
        elif c.get("no_usage") or et is None:
            res = _chip("warn", "No usage", "▲")
        else:
            res = '<span class="muted">ok</span>'
        dash = '<span class="dash" aria-label="no count">—</span>'
        rows.append('<tr><td class="num muted">%s</td><td><span class="mc">%s<span>%s</span></span></td><td class="id">%s</td><td class="r num">%s</td><td class="r num">%s</td><td>%s</td></tr>'
                    % (esc(str(c.get("ts", ""))[11:19]), logo(c.get("model", "?"), 16, "logo"), esc(c.get("model", "?")), esc(c.get("agent", "unknown")),
                       dash if pt is None else n(pt), dash if et is None else n(et), res))
    return "".join(rows)


def eval_rows(ev):
    rows = []
    for r in ev.get("per_model", []):
        passed, total = _intval(r.get("passed")) or 0, _intval(r.get("total")) or 0
        dots = "".join('<span class="pd%s" aria-hidden="true"></span>' % ("" if i < passed else " miss") for i in range(total))
        verdict = _chip("bad", "Fail", "■") if r.get("verdict") == "FAIL" else ('<span class="muted">Pass</span>' if r.get("verdict") == "PASS" else '<span class="muted">%s</span>' % esc(str(r.get("verdict", "?")).title()))
        try:
            tps = "%.1f" % float(r.get("avg_tok_s", 0))
        except (TypeError, ValueError):
            tps = "—"
        rows.append('<li><span class="mc">%s<span>%s</span></span><span class="pds">%s<span class="num">%d/%d</span></span><span class="num muted">%s tok/s</span>%s</li>' % (
            logo(r.get("model", "?"), 16, "logo"), esc(r.get("model", "?")), dots, passed, total, tps, verdict))
    return "".join(rows)


def _empty(text):
    return '<p class="fine">%s</p>' % text


def render_dashboard(st, mockup=False, extra_models=(), too_big_count=None):
    """The round-4b dashboard. mockup=True reproduces mockups/dashboard-round4b.html."""
    m = st.get("metering")
    health = st.get("health") or {}
    ollama = st.get("ollama") or {}
    tokens = st.get("tokens") or {}
    fb = st.get("feedback") or {}
    act = st.get("activity") or {}
    calls = st.get("calls") or []
    models = list(st.get("models") or []) + list(extra_models)
    ok = health.get("local") == "OK" and health.get("serve") == "OK" and ollama.get("up", True)
    mix = token_mix(st) if m else None

    snap = _parse_ts(st.get("ts"))
    probe = _parse_ts(health.get("at"))
    stamp = 'Snapshot <time class="num" datetime="%s">%s</time> UTC' % (esc(st.get("ts", "")), esc(str(st.get("ts", ""))[11:19]))
    if snap and probe:
        stamp += " · probe %s ago" % _ago(max(0, (snap - probe).total_seconds()))
    status_chip = ('<span class="chip chip-ok live"><span class="g pulse" aria-hidden="true">●</span>Operational</span>' if ok
                   else '<span class="chip chip-bad"><span class="g" aria-hidden="true">■</span>Degraded</span>')

    h = ['<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="color-scheme" content="light dark">\n']
    if mockup:
        h.append('<title>Lab status · Local AI Lab (round 4b mockup)</title>\n<!-- Generated by mockups/build-mockup.py from tests/fixtures/status-metered.json. Static, zero-JS. -->\n')
    else:
        h.append('<meta http-equiv="refresh" content="30">\n<title>Lab status · Local AI Lab</title>\n')
    h.append('<style>' + CSS + '</style>\n</head>\n<body>\n' + sprite() + '\n<div class="shell">\n')
    if not mockup:
        h.append('<h1 style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap">Lab status</h1>\n')
    h.append('<header class="top">\n  <div class="brand">\n    <span class="mark" aria-hidden="true"><svg width="22" height="22"><use href="#lg-ollama"/></svg></span>\n'
             '    <span><b>Local AI Lab</b> <span class="scope">Mac Mini · 8 GB · tailnet</span></span>\n  </div>\n  ' + status_chip + '\n  <span class="spacer"></span>\n'
             '  <span class="stamp">' + stamp + '</span>\n  <a class="btn btn-primary" href="/agents.md">Agent guide</a>\n</header>\n')
    if mockup:
        h.append('<p class="notice">Mockup from a recorded fixture. Panels tagged <b>Sample</b> split the real totals with synthetic per-day and per-model data.</p>\n')
    h.append('\n<main class="grid">\n\n')

    # --- headline strip: measured | measured | measured | probe | self-declared (never summed)
    if m:
        cost = cost_estimate(m)
        failed = mix["failed"]
        fail_txt = ('<span class="bad-t">%d failed</span>' % failed) if failed else "0 failed"
        lead = ('<div class="kv num">' + n(m.get("eval_tokens_total", 0)) + '</div>\n      <div class="ks"><span class="num">≈ ' + usd(cost["Base"]) +
                '</span> cloud cost avoided <span class="chip chip-est">Estimated</span></div>')
        prompt = n(m.get("prompt_tokens_total", 0))
        calls_kpi = n(m.get("calls_total", 0))
        calls_ks = fail_txt + " · %d without usage" % (_intval(m.get("unmetered_stream_calls")) or 0)
    else:
        cost = None
        lead = '<div class="kv num">—</div>\n      <div class="ks">proxy metering not reporting</div>'
        prompt, calls_kpi, calls_ks = "—", "—", "proxy metering not reporting"
    speed = health.get("probe_tok_s", "?")
    speed = esc(speed) if speed not in (None, "", "?") else "—"
    h.append('  <section class="panel s12 kpis" aria-label="Headline numbers">\n    <div class="kpi lead">\n      <div class="kl">Tokens generated' + (' <span class="chip chip-measured">Measured</span>' if m else '') + '</div>\n      ' + lead + '\n    </div>\n'
             '    <div class="kpi"><div class="kl">Prompt tokens</div><div class="kv num">' + prompt + '</div><div class="ks">measured input</div></div>\n'
             '    <div class="kpi"><div class="kl">Calls</div><div class="kv num">' + calls_kpi + '</div><div class="ks">' + calls_ks + '</div></div>\n'
             '    <div class="kpi"><div class="kl">Speed</div><div class="kv num">' + speed + '<span class="u">tok/s</span></div><div class="ks">last probe · ' + PROBE_MODEL + '</div></div>\n'
             '    <div class="kpi declared"><div class="kl">Agent reports <span class="chip chip-declared">Self-declared</span></div><div class="kv num">' + n(_intval(tokens.get("feedback_total")) or 0) +
             '<span class="u">tok</span></div><div class="ks">' + n(_intval(fb.get("n")) or 0) + ' reports · never added to the above</div></div>\n  </section>\n\n')

    # --- tokens by model
    # A provenance tag only when there is data to tag; an empty panel claims nothing.
    tag = "" if not mix else (_chip("sample", "Sample") if mix["sample"] else _chip("measured", "Measured"))
    h.append('  <section class="panel s8" aria-labelledby="h-use">\n    <div class="ph"><h2 id="h-use">Tokens by model</h2>' + tag + '<span class="meta">generated, per day, last 14 days</span></div>\n    <div class="pb">')
    if mix and mix["total"] > 0 and mix["dates"] and any(any(r) for r in mix["rows"]):
        h.append('<div class="wide-chart" role="region" aria-label="Tokens per day chart" tabindex="0">' + stacked_chart(mix) + "</div>" + leaderboard(mix))
    elif mix and mix["total"] > 0:
        h.append(leaderboard(mix) + _empty("No per-day history in this snapshot."))
    else:
        h.append(_empty("No metered tokens yet." if m else "Proxy metering is not reporting."))
    h.append(_mix_note(mix, m, mockup) + '</div>\n  </section>\n\n')

    # --- cost + memory rail
    h.append('  <div class="s4 col">\n    <section class="panel" aria-labelledby="h-cost">\n      <div class="ph"><h2 id="h-cost">Cost avoided</h2><span class="chip chip-est">Estimated</span></div>\n      <div class="pb">\n')
    if cost and cost["Low"] > 0:
        total_tok = (_intval(m.get("prompt_tokens_total")) or 0) + (_intval(m.get("eval_tokens_total")) or 0)
        h.append('        <div class="big num">' + usd(cost["Base"]) + '</div>\n        <div class="ks">if these ' + n(total_tok) + ' tokens had gone to a hosted API</div>\n        ' + cost_range(cost) +
                 '\n        <div class="legend"><span><i class="lg-rng"></i>range <span class="num">' + usd(cost["Low"]) + " – " + usd(cost["High"]) + '</span></span><span><i class="lg-dot"></i>base</span></div>\n'
                 '        <details><summary>Assumed rates</summary>\n          <table class="mini"><thead><tr><th></th><th class="r">in / 1M</th><th class="r">out / 1M</th><th class="r">total</th></tr></thead><tbody>')
        h.append("".join('<tr><td>%s</td><td class="r num">$%.2f</td><td class="r num">$%.2f</td><td class="r num">%s</td></tr>' % (k, i, o, usd(cost[k])) for k, i, o in RATES))
        h.append('</tbody></table>\n          <p class="fine">Reference rates, not quotes. Gross: electricity and hardware are not netted.</p>\n        </details>\n')
    else:
        h.append('        ' + _empty("Nothing to estimate until metered tokens arrive.") + '\n')
    h.append('      </div>\n    </section>\n')
    ring_svg, ring_mb, loaded = ring(models)
    if loaded:
        more = (" +%d" % (len(loaded) - 1)) if len(loaded) > 1 else ""
        who = '<span class="mc">' + logo(loaded[0].get("name", "?"), 16, "logo") + "<span>" + esc(loaded[0].get("name", "?")) + more + "</span></span> loaded"
    else:
        who = "Nothing loaded"
    big = too_big_count if too_big_count is not None else len(too_big(models))
    inst = "%d installed" % (_intval(ollama.get("installed")) or len(st.get("models") or []))
    if big:
        inst += " · %d too big for this box" % big
    h.append('    <section class="panel ringp" aria-labelledby="h-ram">\n      <div class="ph"><h2 id="h-ram">Memory in use</h2></div>\n      <div class="pb ringrow">' + ring_svg +
             '<div><div class="big2 num">' + n(ring_mb) + ' MB</div><div class="ks">' + who + '</div><div class="ks">' + inst + '</div></div></div>\n'
             '      <div class="pb" style="padding-top:0">' + ramfit(models) + '</div>\n    </section>\n  </div>\n\n')

    # --- flow
    h.append('  <section class="panel s7" aria-labelledby="h-flow">\n    <div class="ph"><h2 id="h-flow">Where tokens go</h2>' + tag + '<span class="meta">agent → proxy tap → model</span></div>\n    <div class="pb">')
    if mix and mix["total"] > 0 and mix["agents"]:
        h.append('<div class="wide-chart" role="region" aria-label="Token flow diagram" tabindex="0">' + sankey(mix) + '</div>')
    else:
        h.append(_empty("No metered tokens to trace yet."))
    h.append('<p class="fine">Agent names come from the X-Agent header: self-declared, not verified.</p></div>\n  </section>\n\n')

    # --- throughput + activity
    v = [x for x in (act.get("probe_tok_s_last24") or []) if isinstance(x, (int, float))]
    h.append('  <div class="s5 col">\n    <section class="panel" aria-labelledby="h-tp">\n      <div class="ph"><h2 id="h-tp">Throughput</h2><span class="meta">tok/s, last %d probes</span>' % len(v))
    if v:
        h.append('<span class="end num big3">%.1f</span></div>\n      <div class="pb">' % v[-1] + throughput(v) + '</div>\n    </section>\n')
    else:
        h.append('</div>\n      <div class="pb">' + _empty("No probe samples yet.") + '</div>\n    </section>\n')
    daily = act.get("daily") or []
    cur = _intval(act.get("current_streak"))
    if cur is None:
        cur = streaks(daily)[0]
    h.append('    <section class="panel" aria-labelledby="h-act">\n      <div class="ph"><h2 id="h-act">Activity</h2><span class="meta">probes per day</span><span class="end"><b class="num">%d</b> <span class="muted">day streak</span></span></div>\n      <div class="pb">' % cur)
    h.append((heat(daily) if daily else _empty("No daily probe history in this snapshot.")) + '</div>\n    </section>\n  </div>\n\n')

    # --- calls + eval
    total_calls = n(m.get("calls_total", 0)) if m else str(len(calls))
    h.append('  <section class="panel s8" aria-labelledby="h-calls">\n    <div class="ph"><h2 id="h-calls">Recent calls</h2><span class="meta">%d of %s</span><a class="end" href="/calls">All calls</a></div>\n' % (len(calls), total_calls))
    if calls:
        h.append('    <div class="scroll" role="region" aria-labelledby="h-calls" tabindex="0"><table>\n      <thead><tr><th>Time</th><th>Model</th><th>Agent <span class="chip chip-declared">Self-declared</span></th><th class="r">In</th><th class="r">Out</th><th>Result</th></tr></thead>\n      <tbody>' + call_rows(calls) + '</tbody></table></div>\n  </section>\n\n')
    else:
        h.append('    <div class="pb">' + _empty("No metered calls yet — proxy ring is empty.") + '</div>\n  </section>\n\n')
    ev = st.get("eval")
    h.append('  <section class="panel s4" aria-labelledby="h-eval">\n    <div class="ph"><h2 id="h-eval">Weekly eval</h2><span class="meta num">%s</span></div>\n' % (esc(str(ev.get("ts", ""))[:10]) if ev else "—"))
    h.append(('    <ul class="evals">' + eval_rows(ev) + '</ul>\n') if ev else ('    <div class="pb">' + _empty("No weekly eval run recorded yet.") + '</div>\n'))
    h.append('  </section>\n\n</main>\n<nav class="links" aria-label="Endpoints">\n  <a href="/status"><code>/status</code><span>live JSON</span></a>\n  <a href="/calls"><code>/calls</code><span>metered ring</span></a>\n'
             '  <a href="/agents.md"><code>/agents.md</code><span>agent guide</span></a>\n  <a href="/api/tags"><code>/api/tags</code><span>models</span></a>\n  <a href="/api/ps"><code>/api/ps</code><span>loaded now</span></a>\n</nav>\n'
             '<footer>Provider marks: lobehub/lobe-icons (MIT); trademarks of their owners. Zero JavaScript.</footer>\n</div>\n</body>\n</html>\n')
    return "".join(h)


def _mix_note(mix, m, mockup):
    """Honest provenance line under the per-model panel (empty in the mockup)."""
    if mockup or not mix:
        return ""
    if mix["sample"]:
        return _empty("Sample: the measured total split by a fixed mix; this snapshot has no per-model metering.")
    lifetime = _intval((m or {}).get("eval_tokens_total")) or 0
    if mix["since"] and mix["total"] < lifetime:
        return _empty("Counted since %s: %s of %s generated tokens. Earlier traffic is in the totals only." % (
            esc(str(mix["since"])[:10]), n(mix["total"]), n(lifetime)))
    return ""


def build_dashboard(st):
    return render_dashboard(st)


def validate_rerank_request(payload):
    """Validate a /rerank body against the input caps.

    Returns (query, passages, top_k). Raises ValueError with a caller-safe
    reason string on any cap violation or malformed field -> HTTP 400.
    """
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    query = payload.get("query", "")
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    passages = payload.get("passages", [])
    if not isinstance(passages, list):
        raise ValueError("passages must be a list")
    if len(passages) > RERANK_MAX_PASSAGES:
        raise ValueError("too many passages: %d > %d" % (len(passages), RERANK_MAX_PASSAGES))
    clean = []
    for i, item in enumerate(passages):
        if not isinstance(item, dict):
            raise ValueError("passage %d must be an object" % i)
        text = item.get("text", "")
        if not isinstance(text, str):
            raise ValueError("passage %d text must be a string" % i)
        if len(text) > RERANK_MAX_CHARS:
            raise ValueError("passage %d too long: %d > %d chars" % (i, len(text), RERANK_MAX_CHARS))
        clean.append({"id": item.get("id"), "text": text})
    top_k = payload.get("top_k")
    if top_k is not None:
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise ValueError("top_k must be an integer")
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if top_k > RERANK_MAX_TOP_K:
            raise ValueError("top_k too large: %d > %d" % (top_k, RERANK_MAX_TOP_K))
    return query, clean, top_k


def run_rerank_worker(query, passages, worker_argv=None, timeout=RERANK_TIMEOUT_S):
    """Shell out to the rerank worker (list-args, never shell=True).

    Returns the parsed {"scores": [...]} dict. Raises RuntimeError on any
    failure (missing worker, timeout, nonzero exit, unparseable stdout) so the
    endpoint maps every failure to a single clean 503 and never crashes.
    """
    if worker_argv is None:
        runner = RERANK_PYTHON if os.path.exists(RERANK_PYTHON) else sys.executable
        worker_argv = [runner, RERANK_WORKER, "--model-dir", RERANK_MODEL_DIR]
    request = json.dumps({"query": query, "passages": passages})
    try:
        proc = subprocess.run(
            worker_argv,
            input=request.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("rerank worker timed out after %ss" % timeout)
    except (OSError, ValueError) as exc:
        raise RuntimeError("rerank worker could not be launched: %s" % (exc,))
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:200]
        try:
            err = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
            if isinstance(err, dict) and err.get("error"):
                detail = str(err["error"])[:200]
        except (ValueError, TypeError):
            pass
        raise RuntimeError("rerank worker failed (exit %s): %s" % (proc.returncode, detail))
    try:
        result = json.loads(proc.stdout.decode("utf-8", "replace"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("rerank worker returned unparseable output: %s" % (exc,))
    if not isinstance(result, dict) or not isinstance(result.get("scores"), list):
        raise RuntimeError("rerank worker returned malformed result")
    norm = []
    for row in result["scores"]:
        if not isinstance(row, dict) or "score" not in row:
            raise RuntimeError("rerank worker returned a malformed score row")
        try:
            score = float(row["score"])
        except (TypeError, ValueError):
            raise RuntimeError("rerank worker returned a non-numeric score")
        norm.append({"id": row.get("id"), "score": score})
    return {"scores": norm}


def rerank(query, passages, top_k, worker_argv=None, timeout=RERANK_TIMEOUT_S):
    """Score passages via the worker, then stable-sort descending and apply top_k.

    Empty passages short-circuit to {"scores": []} without touching the worker.
    """
    if not passages:
        return {"scores": []}
    result = run_rerank_worker(query, passages, worker_argv=worker_argv, timeout=timeout)
    scores = result["scores"]
    # Stable, descending by score: enumerate() index as tie-breaker keeps the
    # original relative order for equal scores (Python's sort is stable).
    ordered = sorted(enumerate(scores), key=lambda pair: -pair[1]["score"])
    rows = [row for _, row in ordered]
    if top_k is not None:
        rows = rows[:top_k]
    return {"scores": rows}


class H(BaseHTTPRequestHandler):
    timeout = 30  # idle clients (e.g. Content-Length with no body) die here, not forever
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
    def _rerank(self):
        """POST /rerank: validate -> worker -> metered row. 400 over-cap, 503 on worker failure."""
        started = time.time()
        call = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "path": "/rerank", "status": None,
                "agent": (self.headers.get("X-Agent") or "rerank")[:64],
                "model": RERANK_MODEL,
                "prompt_tokens": None, "eval_tokens": None, "ok": False,
                "stream": False, "partial": False, "truncated": False}
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length < 0:
                raise ValueError()
        except ValueError:
            self.send_json({"error": "invalid content length"}, 400)
            return
        if length > RERANK_MAX_BODY:
            call["status"] = 400
            call["truncated"] = True
            self.send_json({"error": "request body too large"}, 400)
            _record_call(call)
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}")
        except (ValueError, TypeError):
            call["status"] = 400
            self.send_json({"error": "body is not valid JSON"}, 400)
            _record_call(call)
            return
        try:
            query, passages, top_k = validate_rerank_request(payload)
        except ValueError as exc:
            call["status"] = 400
            self.send_json({"error": str(exc)}, 400)
            _record_call(call)
            return
        # Passage/score counts ride a dedicated field: token columns stay
        # null so rerank traffic never pollutes the public token totals.
        call["passages"] = len(passages)
        if not passages:
            call["status"] = 200
            call["ok"] = True
            call["duration_ms"] = int((time.time() - started) * 1000)
            self.send_json({"scores": [], "model": RERANK_MODEL,
                            "latency_s": round(time.time() - started, 4)})
            _record_call(call)
            return
        try:
            result = rerank(query, passages, top_k)
        except RuntimeError as exc:
            call["status"] = 503
            call["error"] = str(exc)[:200]
            self.send_json({"error": "rerank unavailable", "detail": str(exc)[:200]}, 503)
            _record_call(call)
            return
        scores = result["scores"]
        call["status"] = 200
        call["ok"] = True
        call["duration_ms"] = int((time.time() - started) * 1000)
        self.send_json({"scores": scores, "model": RERANK_MODEL,
                        "latency_s": round(time.time() - started, 4)})
        _record_call(call)

    def _fetch_key(self):
        # Rate key is the network peer, never the self-declared X-Agent
        # header (caller-controlled: rotatable for unlimited rate, or
        # spoofable to lock a victim's name out). X-Forwarded-For is
        # honored only from loopback (Caddy on the same box).
        peer = self.client_address[0]
        fwd = self.headers.get("X-Forwarded-For")
        if fwd and peer in ("127.0.0.1", "::1"):
            peer = fwd.split(",")[0].strip()[:64] or peer
        return "ip:" + peer

    def _fetch_allowed(self, key):
        now = time.monotonic()
        with _FETCH_LOCK:
            for known, (_, start) in list(_FETCH_BUCKETS.items()):
                if now - start >= FETCH_WINDOW:
                    del _FETCH_BUCKETS[known]
            for bucket, cap in (("*global*", FETCH_GLOBAL_RATE),
                                (key, FETCH_RATE)):
                count, start = _FETCH_BUCKETS.get(bucket, (0, now))
                if count >= cap:
                    return False, max(0, int(start + FETCH_WINDOW - now))
            for bucket in ("*global*", key):
                count, start = _FETCH_BUCKETS.get(bucket, (0, now))
                _FETCH_BUCKETS[bucket] = (count + 1, start)
            return True, 0

    def _fetch(self):
        # Metering label only; the rate key is the peer IP (_fetch_key).
        agent = (self.headers.get("X-Agent") or "unknown")[:64]
        if web_tools is None:
            self.send_json({"ok": False, "error": "fetch backend unavailable"},
                           501)
            return
        # Order: semaphore first (a busy 429 must not spend rate budget),
        # then the rate check, then the body read (cheap rejects first).
        if not FETCH_SEM.acquire(blocking=False):
            self.send_json({"ok": False, "error": "busy"}, 429)
            return
        try:
            allowed, retry = self._fetch_allowed(self._fetch_key())
            if not allowed:
                self.send_json({"ok": False, "error": "rate_limited",
                                "retry_after_s": retry}, 429)
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n < 0 or n > 8192:
                    raise ValueError("bad length")
                d = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(d, dict):
                    raise ValueError("not an object")
                op = d.get("op", "fetch")
                if op not in ("fetch", "search"):
                    raise ValueError("bad op")
            except Exception:
                self.send_json({"ok": False, "error": "bad-request"}, 400)
                return
            start = time.monotonic()
            try:
                if op == "fetch":
                    url = d.get("url", "")
                    if not isinstance(url, str) or not url:
                        self.send_json({"ok": False, "error": "url required"},
                                       400)
                        return
                    res = web_tools.fetch_url(url[:2000])
                    model = "web_fetch"
                else:
                    query = d.get("query", "")
                    if not isinstance(query, str) or not query:
                        self.send_json({"ok": False, "error": "query required"},
                                       400)
                        return
                    res = web_tools.web_search(query[:500])
                    model = "web_search"
            except Exception:
                # Belt-and-braces: a backend escape must drop one request as
                # ok:false, never kill the connection with a traceback.
                res = {"ok": False, "error": "fetch failed"}
                model = "web_fetch" if op == "fetch" else "web_search"
            elapsed_ms = int((time.monotonic() - start) * 1000)
        finally:
            FETCH_SEM.release()
        ok = bool(res.get("ok"))
        text = res.get("text", "") if isinstance(res.get("text"), str) else ""
        # Numeric status (we always reply 200 here); guard blocks ride the
        # blocked flag so failure rollups don't count policy as outage.
        _record_call({"ts": utcnow(), "path": "/fetch",
                      "status": 200,
                      "agent": agent, "model": model,
                      "prompt_tokens": None, "eval_tokens": None, "ok": ok,
                      "blocked": bool(res.get("blocked")),
                      "stream": False, "partial": False,
                      "truncated": len(text) >= 8000,
                      "duration_ms": elapsed_ms,
                      "bytes": len(text.encode("utf-8", "replace"))})
        out = {"ok": ok, "op": op, "elapsed_ms": elapsed_ms}
        for key in ("url", "text", "error", "query", "source", "results",
                    "blocked"):
            if key in res:
                out[key] = res[key]
        self.send_json(out)

    def do_POST(self):
        path = urlsplit(self.path).path
        if self.path.split("?")[0].rstrip("/") == "/fetch":
            self._fetch()
            return
        if path == "/rerank":
            self._rerank()
            return
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
        elif p == "/tools":
            self.send_json({"tools": TOOLS_CATALOG})
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
