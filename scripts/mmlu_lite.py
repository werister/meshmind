#!/usr/bin/env python3
"""mmlu_lite.py -- durable MMLU-lite runner (20Q fixed-offset sample).

Fetches rows from the HF datasets-server JSON API (dataset cais/mmlu,
config all, split test) at fixed strided offsets, prompts each model with
a letter-only prompt (question + A-D choices, "Reply with only the
letter"), and scores by the first A-D letter in the reply.

Row sources (first hit wins per offset): the --rows file (default: the 5
committed fixture rows in tests/fixtures/mmlu_lite/rows.json, sitting on
the first five strided offsets), the local cache dir, then the API
(fetched only on --live; a dry-run never touches the network).

Sidecar-to-dashboard wiring mirrors scripts/tool_bench.py exactly: every
lane call carries X-Agent: mmlu_lite so the sidecar meters it into /calls
and the dashboard; findings JSON to stdout, human table to stderr;
exit 0 = the bench ran, exit 2 = infrastructure error. No new sidecar
surface was invented for this bench.

Safety: temp 0 always; think:false on every /api/chat call (AGENTS.md
think-off default -- the granite think:true lane is out of scope here);
models x questions run strictly serially (this CPU box melts otherwise);
the finished model is unloaded before the next starts.

Usage:
    python3 scripts/mmlu_lite.py --models gemma3:4b [--n 20] [--live]
        [--base-url URL] [--out PATH] [--timeout S]

Stdlib only. No third-party deps. No bare except.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATASET = "cais/mmlu"
CONFIG = "all"
SPLIT = "test"
API_URL = "https://datasets-server.huggingface.co/rows"
X_AGENT = "mmlu_lite"
DEFAULT_N = 20
STRIDE = 700
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 120
DEFAULT_CACHE_DIR = os.path.expanduser("~/.cache/local-ai-lab/mmlu_lite")
DEFAULT_ROWS = "tests/fixtures/mmlu_lite/rows.json"
TEMPERATURE = 0
THINK = False
NUM_PREDICT = 16
LETTERS = "ABCD"
PROMPT_TAIL = "Reply with only the letter (A, B, C, or D)."
EXIT_RAN = 0
EXIT_INFRA = 2
FETCH_TIMEOUT = 30
ROOT = Path(__file__).resolve().parents[1]

_LETTER_RE = re.compile(r"[A-Da-d]")


def fail_infra(reason):
    """Print a human reason to stderr and exit 2 (infrastructure error)."""
    print("mmlu_lite: %s" % reason, file=sys.stderr)
    sys.exit(EXIT_INFRA)


def think_for_model(model):
    """Explicit per-model think flag. Always False in this bench.

    AGENTS.md thinking policy: think-off is the default everywhere; the
    only think:true lane is granite4.2:3b with num_predict >= 900, which is
    out of scope for this temp-0 scoring harness. Never send think:true to
    instruct-only models -- the server hard-errors with "does not support
    thinking".
    """
    return THINK


def offsets_for_n(n):
    """Fixed strided offsets: spread across subjects, stable across runs."""
    return [i * STRIDE for i in range(n)]


def build_prompt(question, choices):
    lines = [question.strip(), ""]
    for letter, choice in zip(LETTERS, choices):
        lines.append("%s. %s" % (letter, str(choice).strip()))
    lines.extend(["", PROMPT_TAIL])
    return "\n".join(lines)


def first_letter(text):
    """First A-D letter in a reply (uppercased), or None."""
    if not text:
        return None
    match = _LETTER_RE.search(text)
    return match.group(0).upper() if match else None


def score_reply(reply, gold_idx):
    """Score one reply against the gold index (0-3).

    Returns (passed_bool, note). Notes: ok | wrong_answer | no_letter.
    """
    pred = first_letter(reply)
    if pred is None:
        return False, "no_letter"
    if pred != LETTERS[gold_idx]:
        return False, "wrong_answer"
    return True, "ok"


# --- rows: fixtures file + cache + API ---------------------------------

def _validate_entry(entry, what):
    if not isinstance(entry, dict):
        fail_infra("%s has a non-object row" % what)
    question = entry.get("question")
    choices = entry.get("choices")
    answer = entry.get("answer")
    if not question or not isinstance(choices, list) or len(choices) != 4:
        fail_infra("%s row offset %s needs 'question' + 4 'choices'"
                   % (what, entry.get("offset")))
    if answer not in (0, 1, 2, 3):
        fail_infra("%s row offset %s 'answer' must be 0-3"
                   % (what, entry.get("offset")))
    try:
        offset = int(entry.get("offset"))
    except (TypeError, ValueError):
        fail_infra("%s row needs an int 'offset'" % what)
    return {"offset": offset, "question": question,
            "subject": entry.get("subject", "?"), "choices": choices,
            "answer": answer}


def load_rows_file(path, what):
    """Load a rows file. Returns (entries, num_rows_total_or_None)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        fail_infra("%s not found: %s" % (what, path))
    except (OSError, ValueError) as exc:
        fail_infra("%s unreadable (%s): %s" % (what, path, exc))
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        fail_infra("%s must carry a non-empty 'rows' list" % what)
    out = [_validate_entry(entry, what) for entry in rows]
    total = data.get("num_rows_total") if isinstance(data, dict) else None
    return out, total


def cache_path(cache_dir):
    return os.path.join(cache_dir, "rows.json")


def load_cache(cache_dir):
    """Tolerant cache read: missing/corrupt cache is just empty."""
    try:
        with open(cache_path(cache_dir), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}, None
    rows = {}
    if isinstance(data, dict) and isinstance(data.get("rows"), dict):
        for key, entry in data["rows"].items():
            try:
                offset = int(key)
            except (TypeError, ValueError):
                continue
            if (isinstance(entry, dict) and entry.get("question")
                    and isinstance(entry.get("choices"), list)
                    and len(entry["choices"]) == 4
                    and entry.get("answer") in (0, 1, 2, 3)):
                rows[offset] = {
                    "question": entry["question"],
                    "subject": entry.get("subject", "?"),
                    "choices": entry["choices"], "answer": entry["answer"]}
    total = data.get("num_rows_total") if isinstance(data, dict) else None
    return rows, total


def save_cache(cache_dir, cached, num_total):
    try:
        os.makedirs(cache_dir, exist_ok=True)
        tmp = cache_path(cache_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"dataset": DATASET, "config": CONFIG, "split": SPLIT,
                       "num_rows_total": num_total,
                       "rows": {str(k): v for k, v in sorted(cached.items())}},
                      handle)
        os.replace(tmp, cache_path(cache_dir))
    except OSError as exc:
        fail_infra("cannot write cache %s: %s" % (cache_path(cache_dir), exc))


def fetch_one(offset):
    """One datasets-server row. Returns (row dict, num_rows_total)."""
    params = urllib.parse.urlencode({"dataset": DATASET, "config": CONFIG,
                                     "split": SPLIT, "offset": offset,
                                     "length": 1})
    request = urllib.request.Request(
        API_URL + "?" + params,
        headers={"User-Agent": "local-ai-lab-mmlu-lite/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        fail_infra("datasets-server fetch failed (offset %d): %s"
                   % (offset, exc))
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) != 1:
        fail_infra("datasets-server returned no row (offset %d)" % offset)
    item = rows[0]
    if not isinstance(item, dict) or not isinstance(item.get("row"), dict):
        fail_infra("datasets-server row malformed (offset %d)" % offset)
    row = item["row"]
    entry = _validate_entry({"offset": item.get("row_idx", offset),
                             "question": row.get("question"),
                             "subject": row.get("subject", "?"),
                             "choices": row.get("choices"),
                             "answer": row.get("answer")},
                            "datasets-server (offset %d)" % offset)
    if entry["offset"] != offset:
        fail_infra("datasets-server returned offset %d for %d"
                   % (entry["offset"], offset))
    total = data.get("num_rows_total") if isinstance(data, dict) else None
    return ({"question": entry["question"], "subject": entry["subject"],
             "choices": entry["choices"], "answer": entry["answer"]}, total)


def resolve_rows(n, rows_arg, cache_dir):
    """Fixed-offset rows in offset order. Live-only: may fetch + cache."""
    want = offsets_for_n(n)
    have = {}
    rows_path = rows_arg or str(ROOT / DEFAULT_ROWS)
    file_rows, file_total = load_rows_file(rows_path, "rows file")
    for entry in file_rows:
        have[entry["offset"]] = entry
    cached, cache_total = load_cache(cache_dir)
    for offset, entry in cached.items():
        have.setdefault(offset, {"offset": offset, **entry})
    num_total = cache_total or file_total
    missing = [o for o in want if o not in have]
    for offset in missing:
        entry, total = fetch_one(offset)
        if total is not None:
            num_total = total
        cached[offset] = entry
        have[offset] = {"offset": offset, **entry}
    if missing:
        save_cache(cache_dir, cached, num_total)
        still = [o for o in want if o not in have]
        if still:
            fail_infra("API did not return offsets %s" % still[:5])
    if num_total is not None:
        for offset in want:
            if offset >= num_total:
                fail_infra("offset %d >= split size %d" % (offset, num_total))
    return [{"offset": o, **have[o]} for o in want], num_total


# --- driving the models ------------------------------------------------

def ask_ollama(base_url, model, prompt, timeout):
    """One /api/chat turn (stream:false, temp 0, think:false).

    Returns (content, prompt_tok, eval_tok). Transport failures are raised
    to the caller (per-question endpoint-error handling).
    """
    url = base_url.rstrip("/") + "/api/chat"
    body = {"model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": think_for_model(model),
            "options": {"temperature": TEMPERATURE,
                        "num_predict": NUM_PREDICT}}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Agent": X_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8", "replace"))
    message = data.get("message") or {}
    return (message.get("content"), data.get("prompt_eval_count"),
            data.get("eval_count"))


def preflight_live(base_url, timeout):
    """On --live, confirm the host answers before scoring; down -> exit 2."""
    request = urllib.request.Request(base_url.rstrip("/") + "/api/tags",
                                     headers={"X-Agent": X_AGENT})
    try:
        with urllib.request.urlopen(request,
                                    timeout=min(timeout, 15)) as response:
            response.read()
    except (urllib.error.URLError, OSError) as exc:
        fail_infra("ollama host unreachable at %s: %s" % (base_url, exc))


def unload_model(base_url, model):
    """Best-effort keep_alive:0 so the next model starts from clean RAM."""
    try:
        payload = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
        request = urllib.request.Request(
            base_url.rstrip("/") + "/api/generate", data=payload,
            headers={"Content-Type": "application/json", "X-Agent": X_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except Exception:
        pass  # hygiene only; never fails the bench


def run_model(model, rows, base_url, timeout):
    """Score every row for one model, strictly serially."""
    results = []
    for entry in rows:
        try:
            reply, prompt_tok, eval_tok = ask_ollama(
                base_url, model,
                build_prompt(entry["question"], entry["choices"]), timeout)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            results.append({"offset": entry["offset"], "pass": False,
                            "note": "endpoint_error",
                            "detail": str(exc)[:120],
                            "prompt_tokens": None, "eval_tokens": None})
            continue
        passed, note = score_reply(reply, entry["answer"])
        results.append({"offset": entry["offset"], "pass": passed,
                        "note": note, "pred": first_letter(reply),
                        "gold": LETTERS[entry["answer"]],
                        "subject": entry.get("subject", "?"),
                        "prompt_tokens": prompt_tok,
                        "eval_tokens": eval_tok})
    return results


def aggregate(results):
    passed = sum(1 for r in results if r["pass"])
    return {"passed": passed, "total": len(results),
            "accuracy": round(passed / len(results), 4) if results else 0.0,
            "endpoint_failures": sum(1 for r in results
                                     if r["note"] == "endpoint_error")}


def render_table(findings):
    lines = []
    for block in findings["models"]:
        agg = block["aggregates"]
        lines.append("model %s: %d/%d correct (accuracy %.3f, "
                     "endpoint fails %d)"
                     % (block["model"], agg["passed"], agg["total"],
                        agg["accuracy"], agg["endpoint_failures"]))
        for res in block["results"]:
            mark = "PASS" if res["pass"] else "FAIL"
            lines.append("  [%s] q%-5d pred=%s gold=%s %s (%s)"
                         % (mark, res["offset"], res.get("pred"),
                            res.get("gold"), res["note"],
                            res.get("subject", "?")))
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="MMLU-lite runner (durable standard bench).")
    parser.add_argument("--models", required=True,
                        help="comma-separated model tags under test")
    parser.add_argument("--n", type=int, default=DEFAULT_N,
                        help="questions at fixed strided offsets "
                             "(default %(default)s)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help="Ollama base URL (default %(default)s)")
    parser.add_argument("--live", action="store_true",
                        help="drive real models + fetch missing rows "
                             "(default: dry-run plan only)")
    parser.add_argument("--out", default=None,
                        help="append findings JSON as one JSONL line")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="per-question timeout seconds when --live "
                             "(default %(default)s)")
    parser.add_argument("--rows", default=None,
                        help="rows JSON file (default: committed fixtures)")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                        help="local API cache dir (default %(default)s)")
    return parser


def dry_run_plan(args, models):
    """Human plan. Pure offline: rows file + cache reads only, no network."""
    rows_path = args.rows or str(ROOT / DEFAULT_ROWS)
    file_rows, _ = load_rows_file(rows_path, "rows file")
    cached, _ = load_cache(args.cache_dir)
    offsets = offsets_for_n(args.n)
    return "\n".join([
        "mmlu_lite dry-run plan (no network, no model calls):",
        "  models: %s" % ", ".join(models),
        "  questions: %d of %s/%s/%s at fixed offsets "
        "(stride %d): %s%s"
        % (args.n, DATASET, CONFIG, SPLIT, STRIDE,
           ", ".join(str(o) for o in offsets[:6]),
           ", ..." if len(offsets) > 6 else ""),
        "  rows file: %s (%d rows)" % (rows_path, len(file_rows)),
        "  cache: %s (%d rows)" % (args.cache_dir, len(cached)),
        "  prompt: <question> + A-D choices + %r" % PROMPT_TAIL,
        "  scoring: first A-D letter vs gold",
        "  sampling: temp 0, think:false, serial, unload-between-models",
        "  live target: %s" % args.base_url,
        "pass --live to run.",
    ])


def main(argv=None):
    args = build_parser().parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        fail_infra("--models parsed to an empty list")
    if args.n < 1:
        fail_infra("--n must be >= 1")
    if not args.live:
        print(dry_run_plan(args, models))
        return EXIT_RAN
    preflight_live(args.base_url, args.timeout)
    rows, num_total = resolve_rows(args.n, args.rows, args.cache_dir)
    blocks = []
    for model in models:  # serial always: this CPU box melts otherwise
        results = run_model(model, rows, args.base_url, args.timeout)
        blocks.append({"model": model, "results": results,
                       "aggregates": aggregate(results)})
        unload_model(args.base_url, model)
    findings = {"tool": "mmlu_lite", "dataset": DATASET, "config": CONFIG,
                "split": SPLIT, "n": args.n, "num_rows_total": num_total,
                "offsets": [r["offset"] for r in rows], "models": blocks}
    json.dump(findings, sys.stdout)
    sys.stdout.write("\n")
    print(render_table(findings), file=sys.stderr)
    if args.out:
        try:
            with open(args.out, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(findings, sort_keys=True) + "\n")
        except OSError as exc:
            fail_infra("cannot append --out %s: %s" % (args.out, exc))
    return EXIT_RAN


if __name__ == "__main__":
    sys.exit(main())
