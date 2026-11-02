#!/usr/bin/env python3
"""code_bench.py -- coder-executables bench (ticket T11; BUILD, coordinator runs live).

Prompts each model with a Python task, extracts the FIRST code fence from the
reply, concatenates it with HIDDEN asserts the model never saw, and executes the
result in a subprocess (default 30s timeout). Records pass/fail + token counts
per model per task. Output findings JSON to stdout, a console table to stderr.

Usage:
    python3 scripts/code_bench.py --models T1,T2 [--ollama URL] [--tasks DIR]
                                  [--timeout S] [--fixture PATH] [--self-test]

Conventions (shared with the gateway harness, docs/GATEWAY-CONTRACTS.md):
  - JSON object to stdout.
  - Human-readable reasons/table to stderr.
  - exit 0 = the bench ran (per-task pass/fail lives inside the JSON).
  - exit 2 = infrastructure error (host down, missing/malformed task dir,
    missing fixture, guard trip).

Task file format (tests/fixtures/codebench/tasks/*.md), sections by '## ' head:
  ## prompt      -- the ONLY text the model sees
  ## reference   -- a reference solution (self-test; never sent to a model)
  ## asserts     -- hidden pytest-style asserts (never sent to a model)
The 'prompt' section may itself contain fenced buggy/smelly code (bugfix /
refactor tasks); that is part of the prompt and is sent verbatim.

A model that emits no code fence fails the task (note 'no_fence'), run
continues. Assert subprocess timeout fails the task (note 'timeout'). Neither
is fatal. Stdlib only. No third-party deps. No bare except.
"""
import argparse
import hashlib
import http.client
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_TASKS = "tests/fixtures/codebench/tasks"
DEFAULT_TIMEOUT = 30
X_AGENT = "code_bench"
EXIT_RAN = 0
EXIT_INFRA = 2

ROOT = Path(__file__).resolve().parents[1]

# Matches the first ```[lang]\n ... ``` fence. DOTALL so bodies span lines.
_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)

# Transport-layer failures that abort the whole run as infra (exit 2) when
# raised by ask_ollama or the unload calls. Deliberately broad: a paired run
# with a hole is worse than no run, and partial rows survive via --journal.
_NET_ERRORS = (urllib.error.URLError, OSError, ValueError,
               http.client.HTTPException)

# Row notes that mark a harness artifact rather than judged code: excluded
# from decisive cells (inferential) but kept in pass rates (descriptive).
_ARTIFACT_NOTES = ("no_fence", "timeout")


def fail_infra(reason):
    """Print a human reason to stderr and exit 2 (infrastructure error)."""
    print("code_bench: %s" % reason, file=sys.stderr)
    sys.exit(EXIT_INFRA)


def load_json_file(path, what):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail_infra("%s not found: %s" % (what, path))
    except (OSError, ValueError) as exc:
        fail_infra("%s unreadable (%s): %s" % (what, path, exc))


# --- task parsing --------------------------------------------------------

def _split_sections(text):
    """Split a task markdown body into a {heading: body} dict by '## ' heads."""
    sections = {}
    current = None
    buf = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip().lower()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _first_fence(text):
    """Return the body of the first fenced code block, or None if absent."""
    match = _FENCE_RE.search(text or "")
    if match is None:
        return None
    return match.group(1)


def load_tasks(tasks_dir):
    """Load and validate every *.md task. Malformed dir/task -> exit 2."""
    base = Path(tasks_dir)
    if not base.is_absolute():
        base = ROOT / base
    if not base.is_dir():
        fail_infra("task dir missing or not a directory: %s" % base)
    files = sorted(base.glob("*.md"))
    if not files:
        fail_infra("no task files (*.md) found in %s" % base)
    tasks = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            fail_infra("task unreadable (%s): %s" % (path, exc))
        sections = _split_sections(text)
        for required in ("prompt", "reference", "asserts"):
            if required not in sections or not sections[required]:
                fail_infra("task %s missing a '## %s' section" % (path.name, required))
        reference = _first_fence(sections["reference"])
        asserts = _first_fence(sections["asserts"])
        if reference is None:
            fail_infra("task %s '## reference' has no code fence" % path.name)
        if asserts is None:
            fail_infra("task %s '## asserts' has no code fence" % path.name)
        tasks.append({
            "name": path.stem,
            "prompt": sections["prompt"],
            "reference": reference,
            "asserts": asserts,
        })
    return tasks


# --- execution -----------------------------------------------------------

def run_code(solution, asserts, timeout):
    """Run solution + asserts in a subprocess. Returns (ok, note).

    ok is True only on a clean exit (all asserts held). note carries the
    reason on failure: 'timeout', 'assert_or_error'.
    """
    program = solution.rstrip() + "\n\n# --- hidden asserts ---\n" + asserts.rstrip() + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(program)
        tmp = handle.name
    try:
        proc = subprocess.run([sys.executable, tmp], capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        Path(tmp).unlink(missing_ok=True)
        return False, "timeout"
    Path(tmp).unlink(missing_ok=True)
    if proc.returncode == 0:
        return True, "ok"
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = tail[-1] if tail else "non-zero exit"
    return False, "assert_or_error: %s" % detail[:200]


# --- model replies -------------------------------------------------------

def ask_ollama(ollama_url, model, prompt, timeout, options=None):
    """One /api/chat turn (stream:false). Returns (content, prompt_tok, eval_tok).

    Any transport failure is raised so the caller can treat the host as down.
    options (seed/temperature) passes through to Ollama when given.
    """
    url = ollama_url.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "messages": [
            {"role": "system",
             "content": "You are a Python coding assistant. Reply with a single "
                        "Python code fence and nothing else."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
    }
    if options:
        body["options"] = options
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "X-Agent": X_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8", "replace"))
    message = data.get("message") or {}
    return (message.get("content"),
            data.get("prompt_eval_count"),
            data.get("eval_count"))


def _coerce_reply(entry, model, task_name):
    if isinstance(entry, str):
        return {"reply": entry, "prompt_tokens": None, "eval_tokens": None}
    if isinstance(entry, dict):
        return {
            "reply": entry.get("reply"),
            "prompt_tokens": entry.get("prompt_tokens"),
            "eval_tokens": entry.get("eval_tokens"),
        }
    fail_infra("fixture entry for %r/%r must be a string, object, or list of those"
               % (model, task_name))


def reply_from_fixture(fixture, model, task_name, rep=0):
    """Pull a canned reply for (model, task, rep) from a fixture.

    An entry may be one reply (reused every rep — the summary then flags
    fixture_duplicates) or a LIST of replies indexed by rep (wrapping), so
    paired machinery tests can use distinct draws per rep. A missing entry
    is an infra error -- fixtures must be complete for a deterministic test.
    """
    replies = fixture.get("replies") if isinstance(fixture, dict) else None
    if not isinstance(replies, dict):
        fail_infra("fixture must carry a 'replies' object keyed by model")
    per_model = replies.get(model)
    if not isinstance(per_model, dict):
        fail_infra("fixture has no replies for model %r" % model)
    entry = per_model.get(task_name)
    if entry is None:
        fail_infra("fixture missing reply for model %r task %r" % (model, task_name))
    if isinstance(entry, list):
        if not entry:
            fail_infra("fixture reply list for %r/%r is empty" % (model, task_name))
        return _coerce_reply(entry[rep % len(entry)], model, task_name)
    return _coerce_reply(entry, model, task_name)


def validate_fixture(fixture, models, tasks):
    """Pre-validate every models x tasks entry up front (fail before running)."""
    for model in models:
        for task in tasks:
            reply_from_fixture(fixture, model, task["name"])


# --- self-test -----------------------------------------------------------

def self_test(tasks, timeout):
    """Run every task's reference solution against its own asserts.

    Returns (all_green, rows). This is the T11 acceptance self-test: the shipped
    reference solutions must pass the hidden asserts, proving each task is
    internally consistent before any model is judged against it.
    """
    rows = []
    all_green = True
    for task in tasks:
        ok, note = run_code(task["reference"], task["asserts"], timeout)
        rows.append({"task": task["name"], "ok": ok, "note": note})
        if not ok:
            all_green = False
    return all_green, rows


# --- per (model, task) run -----------------------------------------------

def bench_task(task, reply_text, timeout):
    """Score one model reply on one task. Returns a result row (no tokens)."""
    fence = _first_fence(reply_text) if reply_text is not None else None
    if fence is None:
        return {"task": task["name"], "pass": False, "note": "no_fence"}
    ok, note = run_code(fence, task["asserts"], timeout)
    return {"task": task["name"], "pass": ok, "note": note}


def bench_model(model, tasks, timeout, fixture, ollama_url, options=None):
    """Run every task for one model. Returns (per_task_rows, model_down_bool)."""
    rows = []
    for task in tasks:
        prompt_tok = None
        eval_tok = None
        if fixture is not None:
            canned = reply_from_fixture(fixture, model, task["name"])
            reply_text = canned["reply"]
            prompt_tok = canned["prompt_tokens"]
            eval_tok = canned["eval_tokens"]
        else:
            try:
                reply_text, prompt_tok, eval_tok = ask_ollama(
                    ollama_url, model, task["prompt"], timeout, options)
            except _NET_ERRORS as exc:
                # Host unreachable (or malformed reply): abort the whole
                # bench as infra (exit 2), never a traceback (exit 1).
                fail_infra("ollama host unreachable at %s: %s" % (ollama_url, exc))
        row = bench_task(task, reply_text, timeout)
        row["prompt_tokens"] = prompt_tok
        row["eval_tokens"] = eval_tok
        rows.append(row)
    return rows


def _unload_others(ollama_url, models, keep):
    """Unload every listed model except `keep`, then verify via /api/ps.

    A failure raises so the caller fails infra rather than running a
    contaminated paired comparison. Verification polls /api/ps until the
    unloaded models are absent (Ollama evicts asynchronously); persistent
    presence is an infra failure, not a silent caveat.
    """
    for model in models:
        if model == keep:
            continue
        payload = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
        request = urllib.request.Request(
            ollama_url.rstrip("/") + "/api/generate", data=payload,
            headers={"Content-Type": "application/json", "X-Agent": X_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    deadline = time.time() + 15
    while time.time() < deadline:
        request = urllib.request.Request(
            ollama_url.rstrip("/") + "/api/ps",
            headers={"X-Agent": X_AGENT})
        with urllib.request.urlopen(request, timeout=15) as response:
            resident = json.loads(response.read().decode("utf-8", "replace"))
        names = [m.get("name", "") for m in resident.get("models", [])]
        left = [m for m in models
                if m != keep and any(n == m or n.startswith(m + ":")
                                     or m.startswith(n + ":") for n in names)]
        if not left:
            return
        time.sleep(2)
    raise OSError("unload unverified, still resident: %s" % ",".join(left))


def _score_turn(models, tasks, task, model, timeout, fixture, ollama_url,
                options, rep):
    """Run one (task, model) turn. Returns the filled row (no rep/turn)."""
    if fixture is not None:
        canned = reply_from_fixture(fixture, model, task["name"], rep)
        reply_text = canned["reply"]
        prompt_tok = canned["prompt_tokens"]
        eval_tok = canned["eval_tokens"]
    else:
        try:
            reply_text, prompt_tok, eval_tok = ask_ollama(
                ollama_url, model, task["prompt"], timeout, options)
        except _NET_ERRORS as exc:
            fail_infra("ollama host unreachable at %s: %s" % (ollama_url, exc))
    row = bench_task(task, reply_text, timeout)
    row["prompt_tokens"] = prompt_tok
    row["eval_tokens"] = eval_tok
    row["model"] = model
    return row


def bench_paired(models, tasks, timeout, fixture, ollama_url, reps, seed,
                 temp, unload, journal=None):
    """Interleaved paired runs: per (rep, task), models alternate AB/BA.

    Counterbalancing is on (task_index + rep), so every task sees both
    orders across reps — a task x order interaction cannot hide in a fixed
    slot. The pairing is the shared task/time/order, not the seed: the same
    seed aids reproducibility but maps to unrelated draws across different
    architectures. Each row records rep, turn, and which model went first.
    """
    rows = []
    turn = 0
    for rep in range(reps):
        options = {"seed": seed + rep, "temperature": temp}
        for i, task in enumerate(tasks):
            order = models if (i + rep) % 2 == 0 else list(reversed(models))
            for model in order:
                if fixture is None and unload:
                    try:
                        _unload_others(ollama_url, models, model)
                    except _NET_ERRORS as exc:
                        fail_infra("unload failed for paired run: %s" % exc)
                row = _score_turn(models, tasks, task, model, timeout,
                                  fixture, ollama_url, options, rep)
                row["rep"] = rep
                row["turn"] = turn
                row["first"] = order[0]
                turn += 1
                rows.append(row)
                if journal is not None:
                    journal.write(json.dumps(row, sort_keys=True) + "\n")
                    journal.flush()
    return rows


def _is_artifact(row):
    return row.get("note") in _ARTIFACT_NOTES


def _sign_p(wins_a, wins_b):
    """Exact two-sided sign-test tail over decisive units (full precision).

    The null (Binomial p=0.5) is symmetric, so doubling the one-sided tail
    is exact. The comparison p<0.05 always uses this unrounded value.
    """
    import math

    n = wins_a + wins_b
    if not n:
        return 1.0
    k = min(wins_a, wins_b)
    return min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k + 1)) / 2.0 ** n)


def paired_summary(rows, models):
    """Paired comparison for exactly two models.

    Unit of analysis is the TASK: reps of one task share prompt, difficulty
    and box state, so cells are not independent and must not be the test
    denominator. Each task favors A (net cell wins > 0), B (net < 0), or
    ties; the sign test runs over favoring tasks. Cell counts stay in the
    output as descriptives only.

    A cell is decisive only when complete (both models ran) AND neither
    side suffered a harness artifact (no_fence/timeout): superiority
    inference runs on comparable cells only. Pass rates still count
    artifacts as fails (descriptive). Parity splits, artifact losses per
    side, breadth (tasks behind the net), and the parity veto feed the
    T14 decision rule; see the ticket for clause definitions.
    """
    if len(models) != 2:
        raise ValueError("paired_summary needs exactly two models")
    a, b = models
    by_cell = {}
    for row in rows:
        by_cell.setdefault((row["rep"], row["task"]), {})[row["model"]] = row
    wins_a = wins_b = ties = incomplete = 0
    art_a = art_b = 0
    parity = {"a_first": {"a": 0, "b": 0}, "b_first": {"a": 0, "b": 0}}
    per_task = {}
    for key in sorted(by_cell):
        cell = by_cell[key]
        task = key[1]
        if a not in cell or b not in cell:
            incomplete += 1
            continue
        ra, rb = cell[a], cell[b]
        t = per_task.setdefault(task, {a: 0, b: 0, "ties": 0,
                                       "artifacts_" + a: 0,
                                       "artifacts_" + b: 0})
        fa, fb = _is_artifact(ra), _is_artifact(rb)
        if fa or fb:
            if fa:
                art_a += 1
                t["artifacts_" + a] += 1
            if fb:
                art_b += 1
                t["artifacts_" + b] += 1
            ties += 1
            t["ties"] += 1
            continue
        first = ra.get("first")
        slot = None
        if first == a:
            slot = "a_first"
        elif first == b:
            slot = "b_first"
        if ra["pass"] == rb["pass"]:
            ties += 1
            t["ties"] += 1
        elif ra["pass"]:
            wins_a += 1
            t[a] += 1
            if slot is not None:
                parity[slot]["a"] += 1
        else:
            wins_b += 1
            t[b] += 1
            if slot is not None:
                parity[slot]["b"] += 1
    favor_a = favor_b = favor_tie = 0
    for task, t in per_task.items():
        net = t[a] - t[b]
        if net > 0:
            favor_a += 1
        elif net < 0:
            favor_b += 1
        else:
            favor_tie += 1
    net = wins_a - wins_b
    leader = a if net > 0 else (b if net < 0 else None)
    # Parity veto: the overall loser must not lead either order subset by
    # >= 2 net (a win that reverses under one order is an order effect).
    veto = False
    if leader is not None:
        loser = b if leader == a else a
        for slot in ("a_first", "b_first"):
            la = parity[slot]["a"] - parity[slot]["b"]
            lead_loser = -la if leader == a else la
            if lead_loser >= 2:
                veto = True
    breadth = sum(1 for t in per_task.values() if t[a] - t[b] != 0)
    discriminating = sum(1 for t in per_task.values()
                         if t[a] + t[b] > 0)
    if leader == a:
        breadth_leader = favor_a
    elif leader == b:
        breadth_leader = favor_b
    else:
        breadth_leader = 0
    return {"models": [a, b], "cells": len(by_cell), "complete": len(by_cell) - incomplete,
            "incomplete": incomplete, "decisive": wins_a + wins_b,
            "wins_a": wins_a, "wins_b": wins_b, "ties": ties,
            "artifacts_a": art_a, "artifacts_b": art_b,
            "cell_p_two_sided_descriptive_only": _sign_p(wins_a, wins_b),
            "favor_a": favor_a, "favor_b": favor_b, "favor_tie": favor_tie,
            "task_p_two_sided": _sign_p(favor_a, favor_b),
            "net_cell_wins": net, "leader": leader,
            "parity": parity, "parity_veto": veto,
            "breadth_tasks": breadth, "breadth_leader": breadth_leader,
            "discriminating_tasks": discriminating,
            "per_task": per_task}


def render_paired(summary):
    """Build a compact paired-comparison table (stderr) from the summary."""
    a, b = summary["models"]
    lines = ["paired %s vs %s: %d cells (%d complete), %d decisive, %d ties, %d+%d artifacts" % (
        a, b, summary["cells"], summary["complete"], summary["decisive"],
        summary["ties"], summary["artifacts_a"], summary["artifacts_b"]),
             "  cell wins %s: %d | %s: %d (descriptive; cells are not independent)" % (
                 a, summary["wins_a"], b, summary["wins_b"]),
             "  task favor %s: %d | %s: %d | ties: %d | task p (two-sided): %s" % (
                 a, summary["favor_a"], b, summary["favor_b"],
                 summary["favor_tie"], summary["task_p_two_sided"]),
             "  parity a-first A:%d B:%d | b-first A:%d B:%d | veto: %s" % (
                 summary["parity"]["a_first"]["a"], summary["parity"]["a_first"]["b"],
                 summary["parity"]["b_first"]["a"], summary["parity"]["b_first"]["b"],
                 summary["parity_veto"]),
             "  breadth: %d tasks (leader %d) | discriminating: %d" % (
                 summary["breadth_tasks"], summary["breadth_leader"],
                 summary["discriminating_tasks"])]
    for task in sorted(summary["per_task"]):
        t = summary["per_task"][task]
        lines.append("  %-24s %s:%d %s:%d ties:%d art:%d+%d" % (
            task, a, t[a], b, t[b], t["ties"],
            t["artifacts_" + a], t["artifacts_" + b]))
    return "\n".join(lines)


def render_table(findings):
    """Build a compact human table (stderr) from the findings object."""
    lines = []
    for model_block in findings["models"]:
        model = model_block["model"]
        passed = sum(1 for r in model_block["tasks"] if r["pass"])
        total = len(model_block["tasks"])
        lines.append("model %s: %d/%d tasks passed" % (model, passed, total))
        for row in model_block["tasks"]:
            mark = "PASS" if row["pass"] else "FAIL"
            lines.append("  [%s] %-24s %s" % (mark, row["task"], row["note"]))
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Coder-executables bench (ticket T11).")
    parser.add_argument("--models", default=None,
                        help="comma-separated model tags under test")
    parser.add_argument("--ollama", default=DEFAULT_OLLAMA,
                        help="ollama base URL (default %(default)s)")
    parser.add_argument("--tasks", default=DEFAULT_TASKS,
                        help="task dir (default %(default)s)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="per-task subprocess timeout seconds (default %(default)s)")
    parser.add_argument("--fixture", default=None,
                        help="read canned model replies from PATH, touch no network")
    parser.add_argument("--self-test", action="store_true",
                        help="run reference solutions against their asserts and exit")
    parser.add_argument("--order", choices=("sequential", "interleave"),
                        default="sequential",
                        help="model order: whole-model blocks, or AB/BA "
                             "alternating per task (default %(default)s)")
    parser.add_argument("--reps", type=int, default=1,
                        help="paired repetitions per (task, model) (default %(default)s)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Ollama seed base; both models share seed+rep "
                             "for reproducibility (required in paired mode)")
    parser.add_argument("--temp", type=float, default=None,
                        help="Ollama temperature, explicit (required in paired "
                             "mode; server default otherwise)")
    parser.add_argument("--unload", action="store_true",
                        help="unload the idle model(s) before each turn/block "
                             "and verify via /api/ps (live only; skipped "
                             "under --fixture)")
    parser.add_argument("--journal", default=None,
                        help="append each scored row as JSONL (survives aborts)")
    return parser


def _tasks_hash(tasks):
    """Short stable hash of the task set (names + prompts + asserts)."""
    h = hashlib.sha256()
    for task in sorted(tasks, key=lambda t: t["name"]):
        h.update(task["name"].encode("utf-8"))
        h.update(b"\x00")
        h.update(task["prompt"].encode("utf-8"))
        h.update(b"\x00")
        h.update(task["asserts"].encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _model_digest(ollama_url, model):
    """Best-effort Ollama digest for a tag (null when unreachable)."""
    try:
        payload = json.dumps({"model": model}).encode("utf-8")
        request = urllib.request.Request(
            ollama_url.rstrip("/") + "/api/show", data=payload,
            headers={"Content-Type": "application/json", "X-Agent": X_AGENT})
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        details = data.get("details") or {}
        return details.get("parent_model") or data.get("digest")
    except Exception:
        return None


def _provenance(args, tasks, models, fixture_path):
    """Every knob that could change the numbers, recorded with the run."""
    live = fixture_path is None
    return {"argv": sys.argv[1:],
            "ollama": args.ollama if live else None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "fixture": fixture_path,
            "tasks_dir": args.tasks,
            "tasks_hash": _tasks_hash(tasks),
            "models": models,
            "digests": ({m: _model_digest(args.ollama, m) for m in models}
                        if live else {m: None for m in models})}


def main(argv=None):
    args = build_parser().parse_args(argv)
    tasks = load_tasks(args.tasks)

    if args.self_test:
        green, rows = self_test(tasks, args.timeout)
        out = {"tool": "code_bench", "mode": "self_test",
               "tasks_total": len(rows), "all_green": green, "results": rows}
        json.dump(out, sys.stdout)
        sys.stdout.write("\n")
        for row in rows:
            mark = "OK" if row["ok"] else "BAD"
            print("self-test [%s] %-24s %s" % (mark, row["task"], row["note"]),
                  file=sys.stderr)
        return EXIT_RAN

    if not args.models:
        fail_infra("--models is required (or pass --self-test)")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        fail_infra("--models parsed to an empty list")

    fixture = None
    if args.fixture is not None:
        fixture = load_json_file(args.fixture, "fixture file")
    if args.reps < 1:
        fail_infra("--reps must be >= 1")
    if args.order == "sequential" and args.reps > 1:
        fail_infra("--reps > 1 needs --order interleave "
                   "(sequential runs whole-model blocks once)")
    paired = args.order == "interleave"
    if paired:
        if len(models) != 2:
            fail_infra("paired mode needs exactly two --models")
        if models[0] == models[1]:
            fail_infra("paired models must differ")
        if args.seed is None or args.temp is None:
            fail_infra("paired mode requires explicit --seed and --temp")
        if args.temp == 0 and args.reps > 1:
            fail_infra("temp 0 is greedy: reps would duplicate draws; "
                       "use --reps 1 with temp 0")
    if fixture is not None:
        validate_fixture(fixture, models, tasks)
        if args.unload:
            print("note: --unload skipped (fixture mode performs no loads)",
                  file=sys.stderr)

    journal = None
    if args.journal is not None:
        try:
            journal = open(args.journal, "a", encoding="utf-8")
        except OSError as exc:
            fail_infra("cannot open --journal %s: %s" % (args.journal, exc))

    options = {}
    if args.seed is not None:
        options["seed"] = args.seed
    if args.temp is not None:
        options["temperature"] = args.temp
    options = options or None

    if paired:
        rows = bench_paired(models, tasks, args.timeout, fixture, args.ollama,
                            args.reps, args.seed, args.temp, args.unload,
                            journal)
        if journal is not None:
            journal.close()
        summary = paired_summary(rows, models)
        duplicates = False
        if fixture is not None and args.reps > 1:
            replies = fixture.get("replies", {})
            duplicates = any(
                not isinstance(replies.get(m, {}).get(t["name"]), list)
                for m in models for t in tasks)
        findings = {
            "tool": "code_bench",
            "mode": "paired",
            "tasks_total": len(tasks),
            "reps": args.reps,
            "seed": args.seed,
            "temp": args.temp,
            "unload": bool(args.unload) and fixture is None,
            "fixture_duplicates": duplicates,
            "provenance": _provenance(args, tasks, models, args.fixture),
            "rows": rows,
            "paired": summary,
        }
        json.dump(findings, sys.stdout)
        sys.stdout.write("\n")
        print(render_paired(summary), file=sys.stderr)
        return EXIT_RAN

    model_blocks = []
    for model in models:
        if fixture is None and args.unload:
            try:
                _unload_others(ollama_url=args.ollama, models=models, keep=model)
            except _NET_ERRORS as exc:
                fail_infra("unload failed: %s" % exc)
        rows = bench_model(model, tasks, args.timeout, fixture, args.ollama,
                           options)
        if journal is not None:
            for row in rows:
                stamped = dict(row)
                stamped["model"] = model
                journal.write(json.dumps(stamped, sort_keys=True) + "\n")
            journal.flush()
        model_blocks.append({"model": model, "tasks": rows})

    if journal is not None:
        journal.close()
    findings = {
        "tool": "code_bench",
        "tasks_total": len(tasks),
        "models": model_blocks,
        "provenance": _provenance(args, tasks, models, args.fixture),
    }
    json.dump(findings, sys.stdout)
    sys.stdout.write("\n")
    print(render_table(findings), file=sys.stderr)
    return EXIT_RAN


if __name__ == "__main__":
    sys.exit(main())
