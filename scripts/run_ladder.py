#!/usr/bin/env python3
"""run_ladder.py -- headroom ladder stage of the gateway bake-off protocol.

Implements docs/GATEWAY-CONTRACTS.md v1.2 (FROZEN) exactly.

Usage:
    python3 scripts/run_ladder.py --model TAG [--contexts 4096]
            [--parallel 1,2] [--ollama URL] [--status URL]
            [--fixture PATH] [--step-timeout S]

Conventions (shared across the three harness tools):
  - JSON object to stdout.
  - Human-readable reasons to stderr.
  - exit 0 = the run ran (verdict lives inside the JSON).
  - exit 2 = infrastructure error (host down, missing/invalid file, guard trip).

stdout shape:
  {"tool":"run_ladder","model":TAG,"num_ctx":4096,
   "steps":[{"ctx":I,"parallel":I,"prompt_tokens":I,"gen_tokens":I,
             "tok_s":F,"mem_kb":I|null,"ok":B,"notes":S}],
   "verdict":B}

mem_kb = mem_free_mb * 1024, read from /status (the T6 field) when reachable;
otherwise null + a note. Never fabricated, never zero-filled. A failed step
sets ok:false and verdict:false, and the run continues to the next step.

Stdlib only. No third-party deps. No bare except.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_STATUS = "http://127.0.0.1:8081/status"
DEFAULT_CONTEXTS = "4096"
DEFAULT_PARALLEL = "1,2"
DEFAULT_STEP_TIMEOUT = 600
NUM_CTX = 4096
STATUS_TIMEOUT = 15  # bounded read for the sidecar /status probe
EXIT_RAN = 0
EXIT_INFRA = 2

LADDER_PROMPT = "Count from one to twenty in words, comma separated."


def fail_infra(reason):
    print("run_ladder: %s" % reason, file=sys.stderr)
    sys.exit(EXIT_INFRA)


def load_json_file(path, what):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail_infra("%s not found: %s" % (what, path))
    except (OSError, ValueError) as exc:
        fail_infra("%s unreadable (%s): %s" % (what, path, exc))


def parse_int_list(raw, flag):
    values = []
    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            values.append(int(chunk))
        except ValueError:
            fail_infra("%s expects comma-separated integers, got %r" % (flag, raw))
    if not values:
        fail_infra("%s produced no values" % flag)
    return values


def read_mem_kb(status_url):
    """Return (mem_kb|None, note).

    mem_kb is mem_free_mb * 1024 when /status is reachable AND carries the
    T6 field. Unreachable or field-absent -> None with a distinguishing note.
    Never fabricated, never zero-filled.
    """
    request = urllib.request.Request(status_url, headers={"X-Agent": "run_ladder"})
    try:
        with urllib.request.urlopen(request, timeout=STATUS_TIMEOUT) as response:
            raw = response.read()
    except (urllib.error.URLError, OSError) as exc:
        return None, "status unreachable at %s (%s); mem_kb null" % (status_url, exc)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        return None, "status not JSON (%s); mem_kb null" % exc
    if not isinstance(data, dict) or "mem_free_mb" not in data:
        return None, "status reachable but mem_free_mb absent (pre-T6); mem_kb null"
    mem_free_mb = data["mem_free_mb"]
    if not isinstance(mem_free_mb, (int, float)) or isinstance(mem_free_mb, bool):
        return None, "mem_free_mb present but not numeric (%r); mem_kb null" % (mem_free_mb,)
    return int(mem_free_mb * 1024), "mem_free_mb=%s -> mem_kb=%d" % (mem_free_mb, int(mem_free_mb * 1024))


def read_mem_kb_from_fixture(fixture):
    """Mirror read_mem_kb against a canned /status object (no network)."""
    status = fixture.get("status") if isinstance(fixture, dict) else None
    if status is None:
        return None, "fixture carries no status object; mem_kb null"
    if status == "UNREACHABLE":
        return None, "status unreachable (fixture); mem_kb null"
    if not isinstance(status, dict) or "mem_free_mb" not in status:
        return None, "status reachable but mem_free_mb absent (pre-T6); mem_kb null"
    mem_free_mb = status["mem_free_mb"]
    if not isinstance(mem_free_mb, (int, float)) or isinstance(mem_free_mb, bool):
        return None, "mem_free_mb present but not numeric (%r); mem_kb null" % (mem_free_mb,)
    return int(mem_free_mb * 1024), "mem_free_mb=%s -> mem_kb=%d" % (mem_free_mb, int(mem_free_mb * 1024))


def run_step_network(ollama_url, model, ctx, parallel, step_timeout):
    """Run one ladder step against the live host.

    Returns (prompt_tokens, gen_tokens, tok_s, ok, notes). A timeout or
    transport failure on the step returns ok:false (verdict will flip false)
    but does NOT raise -- the run continues to the next step.
    """
    url = ollama_url.rstrip("/") + "/api/chat"

    def one_client():
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": LADDER_PROMPT}],
            "stream": False,
            "think": False,
            "options": {"num_ctx": NUM_CTX},
        }).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json",
                                        "X-Agent": "run_ladder"})
        with urllib.request.urlopen(request, timeout=step_timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    started = time.monotonic()
    results = []
    # --parallel N measures N concurrent clients against the DEPLOYED server
    # config. If the server serializes, this simply queues -- we record the
    # observed wall-clock behavior and never touch server env.
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(one_client) for _ in range(parallel)]
            for future in concurrent.futures.as_completed(futures, timeout=step_timeout):
                results.append(future.result())
    except concurrent.futures.TimeoutError:
        return 0, 0, 0.0, False, "step timed out after %ss (ctx=%d parallel=%d)" % (
            step_timeout, ctx, parallel)
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError):
            return 0, 0, 0.0, False, "step timed out (ctx=%d parallel=%d)" % (ctx, parallel)
        return 0, 0, 0.0, False, "step transport error: %s" % exc
    except ValueError as exc:
        return 0, 0, 0.0, False, "step response not JSON: %s" % exc
    elapsed = time.monotonic() - started
    prompt_tokens = sum(int(r.get("prompt_eval_count", 0) or 0) for r in results)
    gen_tokens = sum(int(r.get("eval_count", 0) or 0) for r in results)
    tok_s = round(gen_tokens / elapsed, 3) if elapsed > 0 else 0.0
    return prompt_tokens, gen_tokens, tok_s, True, "ok (%d client(s), %.2fs)" % (parallel, elapsed)


def run_step_fixture(fixture, ctx, parallel):
    """Pull one canned step result from a fixture, keyed by 'ctx:parallel'."""
    steps = fixture.get("steps") if isinstance(fixture, dict) else None
    if not isinstance(steps, dict):
        fail_infra("fixture must carry a 'steps' object keyed 'ctx:parallel'")
    key = "%d:%d" % (ctx, parallel)
    entry = steps.get(key)
    if not isinstance(entry, dict):
        fail_infra("fixture missing step %s" % key)
    if entry.get("timeout") is True:
        return 0, 0, 0.0, False, "step timed out (fixture, ctx=%d parallel=%d)" % (ctx, parallel)
    prompt_tokens = int(entry.get("prompt_tokens", 0))
    gen_tokens = int(entry.get("gen_tokens", 0))
    tok_s = float(entry.get("tok_s", 0.0))
    ok = bool(entry.get("ok", True))
    notes = str(entry.get("notes", "ok (fixture)"))
    return prompt_tokens, gen_tokens, tok_s, ok, notes


def build_parser():
    parser = argparse.ArgumentParser(
        description="4k / two-parallel headroom ladder (gateway contracts v1.2).")
    parser.add_argument("--model", required=True, help="model tag under test")
    parser.add_argument("--contexts", default=DEFAULT_CONTEXTS,
                        help="comma-separated context sizes (default %(default)s)")
    parser.add_argument("--parallel", default=DEFAULT_PARALLEL,
                        help="comma-separated client counts (default %(default)s)")
    parser.add_argument("--ollama", default=DEFAULT_OLLAMA,
                        help="ollama base URL (default %(default)s)")
    parser.add_argument("--status", default=DEFAULT_STATUS,
                        help="sidecar /status URL (default %(default)s)")
    parser.add_argument("--fixture", default=None,
                        help="read canned steps + status from PATH, touch no network")
    parser.add_argument("--step-timeout", type=float, default=DEFAULT_STEP_TIMEOUT,
                        help="per-step timeout seconds (default %(default)s)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    contexts = parse_int_list(args.contexts, "--contexts")
    parallels = parse_int_list(args.parallel, "--parallel")

    fixture = None
    if args.fixture is not None:
        fixture = load_json_file(args.fixture, "fixture file")

    # One mem reading informs the whole ladder (the box is the box).
    if fixture is not None:
        mem_kb, mem_note = read_mem_kb_from_fixture(fixture)
    else:
        mem_kb, mem_note = read_mem_kb(args.status)

    steps = []
    verdict = True
    for ctx in contexts:
        for parallel in parallels:
            if fixture is not None:
                prompt_tokens, gen_tokens, tok_s, ok, notes = run_step_fixture(
                    fixture, ctx, parallel)
            else:
                prompt_tokens, gen_tokens, tok_s, ok, notes = run_step_network(
                    args.ollama, args.model, ctx, parallel, args.step_timeout)
            if not ok:
                verdict = False
            steps.append({
                "ctx": ctx,
                "parallel": parallel,
                "prompt_tokens": prompt_tokens,
                "gen_tokens": gen_tokens,
                "tok_s": tok_s,
                "mem_kb": mem_kb,
                "ok": ok,
                "notes": ("%s; %s" % (notes, mem_note)) if mem_note else notes,
            })

    out = {
        "tool": "run_ladder",
        "model": args.model,
        "num_ctx": NUM_CTX,
        "steps": steps,
        "verdict": verdict,
    }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return EXIT_RAN


if __name__ == "__main__":
    sys.exit(main())
