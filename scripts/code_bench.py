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

def ask_ollama(ollama_url, model, prompt, timeout):
    """One /api/chat turn (stream:false). Returns (content, prompt_tok, eval_tok).

    Any transport failure is raised so the caller can treat the host as down.
    """
    url = ollama_url.rstrip("/") + "/api/chat"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system",
             "content": "You are a Python coding assistant. Reply with a single "
                        "Python code fence and nothing else."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
    }).encode("utf-8")
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


def reply_from_fixture(fixture, model, task_name):
    """Pull a canned reply for (model, task) from a fixture. Returns a dict with
    keys: reply (str|None), prompt_tokens, eval_tokens. A missing entry is an
    infra error -- fixtures must be complete for a deterministic test.
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
    if isinstance(entry, str):
        return {"reply": entry, "prompt_tokens": None, "eval_tokens": None}
    if isinstance(entry, dict):
        return {
            "reply": entry.get("reply"),
            "prompt_tokens": entry.get("prompt_tokens"),
            "eval_tokens": entry.get("eval_tokens"),
        }
    fail_infra("fixture entry for %r/%r must be a string or object" % (model, task_name))


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


def bench_model(model, tasks, timeout, fixture, ollama_url):
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
                    ollama_url, model, task["prompt"], timeout)
            except (urllib.error.URLError, OSError) as exc:
                # Host unreachable: abort the whole bench as infra (exit 2).
                fail_infra("ollama host unreachable at %s: %s" % (ollama_url, exc))
        row = bench_task(task, reply_text, timeout)
        row["prompt_tokens"] = prompt_tok
        row["eval_tokens"] = eval_tok
        rows.append(row)
    return rows


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
    return parser


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

    model_blocks = []
    for model in models:
        rows = bench_model(model, tasks, args.timeout, fixture, args.ollama)
        model_blocks.append({"model": model, "tasks": rows})

    findings = {
        "tool": "code_bench",
        "tasks_total": len(tasks),
        "models": model_blocks,
    }
    json.dump(findings, sys.stdout)
    sys.stdout.write("\n")
    print(render_table(findings), file=sys.stderr)
    return EXIT_RAN


if __name__ == "__main__":
    sys.exit(main())
