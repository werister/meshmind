#!/usr/bin/env python3
"""tool_bench.py -- 6-point tool-calling bench (ticket T12; BUILD, coordinator runs live).

Drives scripted turns against a FIXED 4-tool catalog (get_weather, calc,
file_read, send_message -- fake, deterministic backends) and scores
Perplexity's six points per scenario:

  1 correct tool selection         4 correct no-tool decisions
  2 exact argument values/types    5 recovery after tool errors
  3 abstention when args absent     6 correct use of tool results next turn

Each scenario is a JSON file (tests/fixtures/toolbench/scenarios/*.json) with a
list of turns. A turn carries the user prompt, the model reply, an 'expect'
clause the runner scores, and (for 2-turn scenarios) a scripted 'tool_result'
fed back as the next turn's context. The builder ships canned replies so the
suite runs with NO live calls; the coordinator passes --models/--ollama --live
to drive real models through the proxy (X-Agent: tool_bench) instead.

Scoring note -- failures are split into two kinds, never blurred:
  * REASONING failures: wrong_tool, wrong_args, should_abstain, unexpected_tool,
    bad_json, no_recovery, missing_result. The model ran but answered wrong.
  * ENDPOINT failures: endpoint_error. The transport/template broke (live POST
    failed for a turn); the model was never fairly judged. Counted separately.

Conventions (shared with the gateway harness, docs/GATEWAY-CONTRACTS.md):
  - JSON object to stdout. Human reasons/table to stderr.
  - exit 0 = the bench ran (per-scenario pass/fail lives in the JSON).
  - exit 2 = infrastructure error (host down on live, missing/malformed
    scenario dir or catalog, guard trip).

Usage:
    python3 scripts/tool_bench.py --models T1,T2 [--ollama URL]
            [--scenarios DIR] [--catalog PATH] [--live] [--timeout S]

Stdlib only. No third-party deps. No bare except.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_SCENARIOS = "tests/fixtures/toolbench/scenarios"
DEFAULT_CATALOG = "tests/fixtures/toolbench/catalog.json"
DEFAULT_TIMEOUT = 120
X_AGENT = "tool_bench"
EXIT_RAN = 0
EXIT_INFRA = 2

ROOT = Path(__file__).resolve().parents[1]

EXPECT_KINDS = {"tool_call", "abstain", "no_tool", "recover", "use_result"}
REASONING_NOTES = {"wrong_tool", "wrong_args", "should_abstain", "unexpected_tool",
                   "bad_json", "no_recovery", "missing_result"}
# Matches the first ```[lang]\n ... ``` fence; tool calls are emitted this way.
_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)


def fail_infra(reason):
    """Print a human reason to stderr and exit 2 (infrastructure error)."""
    print("tool_bench: %s" % reason, file=sys.stderr)
    sys.exit(EXIT_INFRA)


def load_json_file(path, what):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail_infra("%s not found: %s" % (what, path))
    except (OSError, ValueError) as exc:
        fail_infra("%s unreadable (%s): %s" % (what, path, exc))


# --- catalog -------------------------------------------------------------

def load_catalog(path):
    """Load and validate the fixed 4-tool catalog. Returns {name: param_spec}."""
    base = Path(path)
    if not base.is_absolute():
        base = ROOT / base
    data = load_json_file(base, "catalog file")
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list) or not tools:
        fail_infra("catalog must carry a non-empty 'tools' list")
    catalog = {}
    for tool in tools:
        if not isinstance(tool, dict) or "name" not in tool or "parameters" not in tool:
            fail_infra("each catalog tool needs 'name' and 'parameters'")
        if not isinstance(tool["parameters"], dict):
            fail_infra("tool %r parameters must be an object" % tool.get("name"))
        catalog[tool["name"]] = tool["parameters"]
    expected = {"get_weather", "calc", "file_read", "send_message"}
    if set(catalog) != expected:
        fail_infra("catalog must define exactly the fixed 4 tools %s (got %s)"
                   % (sorted(expected), sorted(catalog)))
    return catalog


# --- scenarios -----------------------------------------------------------

def _validate_scenario(obj, filename, catalog):
    """Validate one scenario object. Any problem -> exit 2 naming the file."""
    if not isinstance(obj, dict):
        fail_infra("scenario %s is not a JSON object" % filename)
    for key in ("name", "point", "turns"):
        if key not in obj:
            fail_infra("scenario %s missing required key %r" % (filename, key))
    if not isinstance(obj["point"], int) or not (1 <= obj["point"] <= 6):
        fail_infra("scenario %s 'point' must be an int 1-6 (got %r)"
                   % (filename, obj.get("point")))
    turns = obj["turns"]
    if not isinstance(turns, list) or not turns:
        fail_infra("scenario %s 'turns' must be a non-empty list" % filename)
    for idx, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict):
            fail_infra("scenario %s turn %d is not an object" % (filename, idx))
        if "user" not in turn or "expect" not in turn:
            fail_infra("scenario %s turn %d needs 'user' and 'expect'"
                       % (filename, idx))
        if "canned_reply" not in turn:
            fail_infra("scenario %s turn %d needs 'canned_reply' "
                       "(the offline reply source)" % (filename, idx))
        expect = turn["expect"]
        if not isinstance(expect, dict) or expect.get("kind") not in EXPECT_KINDS:
            fail_infra("scenario %s turn %d 'expect.kind' must be one of %s"
                       % (filename, idx, sorted(EXPECT_KINDS)))
        tool = expect.get("tool")
        if tool is not None and tool not in catalog:
            fail_infra("scenario %s turn %d references unknown tool %r "
                       "(not in the fixed catalog)" % (filename, idx, tool))
        if expect["kind"] == "use_result":
            if not isinstance(expect.get("must_include"), list) or not expect["must_include"]:
                fail_infra("scenario %s turn %d use_result needs a non-empty "
                           "'must_include' list" % (filename, idx))


def load_scenarios(scenarios_dir, catalog):
    """Load and validate every *.json scenario. Malformed -> exit 2 naming file."""
    base = Path(scenarios_dir)
    if not base.is_absolute():
        base = ROOT / base
    if not base.is_dir():
        fail_infra("scenario dir missing or not a directory: %s" % base)
    files = sorted(base.glob("*.json"))
    if not files:
        fail_infra("no scenario files (*.json) found in %s" % base)
    scenarios = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            fail_infra("scenario unreadable (%s): %s" % (path.name, exc))
        try:
            obj = json.loads(text)
        except ValueError as exc:
            fail_infra("scenario %s is not valid JSON: %s" % (path.name, exc))
        _validate_scenario(obj, path.name, catalog)
        obj["_file"] = path.name
        scenarios.append(obj)
    return scenarios


# --- tool-call parsing ---------------------------------------------------

def _extract_braced(text, start):
    """Balanced-brace substring starting at text[start] == '{'.

    String-aware (double quotes + backslash escapes). Returns the substring,
    or None when the braces never balance.
    """
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return None


def _coerce_call(parsed):
    """Validate a parsed candidate the same way for fenced and bare JSON."""
    if not isinstance(parsed, dict) or "tool" not in parsed:
        return "bad_json", None
    if parsed.get("tool") is None:
        return "none", None
    args = parsed.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return "bad_json", None
    return "call", {"tool": parsed["tool"], "args": args}


def _parse_bare_call(reply):
    """Bare-JSON fallback: a tool object without a code fence.

    Only a balanced object containing a "tool" key counts as an attempted
    call (anything else is plain text as far as scoring is concerned).
    """
    pos = 0
    while True:
        start = reply.find("{", pos)
        if start < 0:
            return "none", None
        chunk = _extract_braced(reply, start)
        if chunk is None:
            return "none", None
        if '"tool"' in chunk:
            try:
                parsed = json.loads(chunk)
            except ValueError:
                return "bad_json", None
            if isinstance(parsed, dict) and "tool" in parsed:
                return _coerce_call(parsed)
            return "bad_json", None
        pos = start + 1


def parse_tool_call(reply):
    """Extract a tool call from a model reply.

    A fenced JSON block wins when present; otherwise a bare JSON object
    with a "tool" key is accepted (some models emit valid calls unfenced).

    Returns one of:
      ("call", {"tool": str, "args": dict})  -- a well-formed tool call
      ("none", None)                          -- no tool call present
      ("bad_json", None)                      -- an attempted call, unparseable
    """
    if reply is None:
        return "none", None
    match = _FENCE_RE.search(reply)
    if match is not None:
        body = match.group(1).strip()
        try:
            parsed = json.loads(body)
        except ValueError:
            return "bad_json", None
        return _coerce_call(parsed)
    return _parse_bare_call(reply)


def _types_match(expected, actual):
    """Exact value + type match, with JSON's int/float/bool quirks respected.

    bool is NOT accepted where a plain int is expected (True == 1 in Python,
    so guard it explicitly) and vice versa.
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if type(expected) is not type(actual):
        # allow int/float equality only when values are equal AND neither is bool
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            return expected == actual
        return False
    return expected == actual


def args_exact(expected_args, actual_args):
    """True iff actual args equal expected args in keys, values, and types."""
    if set(expected_args) != set(actual_args):
        return False
    for key, exp in expected_args.items():
        if not _types_match(exp, actual_args[key]):
            return False
    return True


# --- scoring one turn ----------------------------------------------------

def score_turn(expect, reply):
    """Score a single turn's reply against its expect clause.

    Returns (passed_bool, note_str). note is 'ok' on pass, else a REASONING note.
    """
    kind = expect["kind"]
    status, call = parse_tool_call(reply)

    if kind in ("tool_call", "recover"):
        if status == "bad_json":
            return False, "bad_json"
        if status == "none":
            return False, ("no_recovery" if kind == "recover" else "wrong_tool")
        if expect.get("tool") is not None and call["tool"] != expect["tool"]:
            return False, ("no_recovery" if kind == "recover" else "wrong_tool")
        if "args" in expect and not args_exact(expect["args"], call["args"]):
            return False, "wrong_args"
        return True, "ok"

    if kind == "abstain":
        if status == "call":
            return False, "should_abstain"
        # bad_json or none both mean "did not fire a valid tool call" -> abstained
        return True, "ok"

    if kind == "no_tool":
        if status == "call":
            return False, "unexpected_tool"
        return True, "ok"

    if kind == "use_result":
        if status == "call":
            # still calling a tool instead of answering from the result
            return False, "missing_result"
        text = reply or ""
        for needle in expect["must_include"]:
            if str(needle) not in text:
                return False, "missing_result"
        return True, "ok"

    return False, "unknown_kind"  # unreachable: validated earlier


# --- driving a scenario --------------------------------------------------

def ask_ollama(ollama_url, model, messages, timeout):
    """One /api/chat turn (stream:false). Returns the message content string.

    Transport failures are raised to the caller (endpoint error handling).
    """
    url = ollama_url.rstrip("/") + "/api/chat"
    payload = json.dumps({
        "model": model,
        "messages": messages,
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
    return message.get("content")


def _system_prompt(catalog):
    names = ", ".join(sorted(catalog))
    return ("You can call tools. Available tools: %s. To call a tool, reply with "
            "a single JSON code fence {\"tool\": NAME, \"args\": {...}}. If a "
            "required argument is missing, do NOT guess -- ask for it. If no tool "
            "is needed, answer in plain text." % names)


def run_scenario(scenario, model, catalog, live, ollama_url, timeout):
    """Drive one scenario for one model. Returns a result dict:
       {name, point, pass, note, endpoint_error, turns:[{expect,note,pass}]}.
    """
    messages = [{"role": "system", "content": _system_prompt(catalog)}]
    turn_rows = []
    endpoint_error = False
    scenario_pass = True
    scenario_note = "ok"

    for turn in scenario["turns"]:
        messages.append({"role": "user", "content": turn["user"]})
        reply = turn.get("canned_reply")
        if live:
            try:
                reply = ask_ollama(ollama_url, model, messages, timeout)
            except (urllib.error.URLError, OSError) as exc:
                # A per-turn transport/template failure is an ENDPOINT failure,
                # recorded separately from reasoning. The host being entirely
                # down is surfaced by the caller as exit 2 before we get here.
                endpoint_error = True
                turn_rows.append({"expect": turn["expect"]["kind"],
                                  "pass": False, "note": "endpoint_error",
                                  "detail": str(exc)[:120]})
                scenario_pass = False
                scenario_note = "endpoint_error"
                break
        passed, note = score_turn(turn["expect"], reply)
        turn_rows.append({"expect": turn["expect"]["kind"],
                          "pass": passed, "note": note})
        messages.append({"role": "assistant", "content": reply or ""})
        if not passed:
            scenario_pass = False
            if scenario_note == "ok":
                scenario_note = note
        # Feed the scripted tool result back as the next turn's context.
        if "tool_result" in turn:
            messages.append({"role": "tool",
                             "content": json.dumps(turn["tool_result"])})

    return {
        "name": scenario["name"],
        "point": scenario["point"],
        "pass": scenario_pass,
        "note": scenario_note,
        "endpoint_error": endpoint_error,
        "turns": turn_rows,
    }


def aggregate(results):
    """Per-point aggregates + endpoint-vs-reasoning split for one model."""
    points = {}
    reasoning_fail = 0
    endpoint_fail = 0
    for res in results:
        slot = points.setdefault(res["point"], {"total": 0, "passed": 0})
        slot["total"] += 1
        if res["pass"]:
            slot["passed"] += 1
        elif res["endpoint_error"]:
            endpoint_fail += 1
        else:
            reasoning_fail += 1
    return {
        "per_point": {str(p): points[p] for p in sorted(points)},
        "reasoning_failures": reasoning_fail,
        "endpoint_failures": endpoint_fail,
        "scenarios_passed": sum(1 for r in results if r["pass"]),
        "scenarios_total": len(results),
    }


def render_table(findings):
    lines = []
    for block in findings["models"]:
        agg = block["aggregates"]
        lines.append("model %s: %d/%d scenarios passed "
                     "(reasoning fails %d, endpoint fails %d)"
                     % (block["model"], agg["scenarios_passed"],
                        agg["scenarios_total"], agg["reasoning_failures"],
                        agg["endpoint_failures"]))
        for point in sorted(agg["per_point"], key=int):
            slot = agg["per_point"][point]
            lines.append("  point %s: %d/%d" % (point, slot["passed"], slot["total"]))
        for res in block["scenarios"]:
            mark = "PASS" if res["pass"] else "FAIL"
            tag = " (endpoint)" if res["endpoint_error"] else ""
            lines.append("  [%s] p%d %-30s %s%s"
                         % (mark, res["point"], res["name"], res["note"], tag))
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="6-point tool-calling bench (ticket T12).")
    parser.add_argument("--models", required=True,
                        help="comma-separated model tags under test")
    parser.add_argument("--ollama", default=DEFAULT_OLLAMA,
                        help="ollama base URL (default %(default)s)")
    parser.add_argument("--scenarios", default=DEFAULT_SCENARIOS,
                        help="scenario dir (default %(default)s)")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG,
                        help="fixed tool catalog (default %(default)s)")
    parser.add_argument("--live", action="store_true",
                        help="drive real models over --ollama (default: canned replies)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="per-turn timeout seconds when --live (default %(default)s)")
    return parser


def _preflight_live(ollama_url, timeout):
    """On --live, confirm the host answers before scoring; down -> exit 2."""
    url = ollama_url.rstrip("/") + "/api/tags"
    request = urllib.request.Request(url, headers={"X-Agent": X_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=min(timeout, 15)) as response:
            response.read()
    except (urllib.error.URLError, OSError) as exc:
        fail_infra("ollama host unreachable at %s: %s" % (ollama_url, exc))


def main(argv=None):
    args = build_parser().parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        fail_infra("--models parsed to an empty list")
    catalog = load_catalog(args.catalog)
    scenarios = load_scenarios(args.scenarios, catalog)
    if args.live:
        _preflight_live(args.ollama, args.timeout)

    model_blocks = []
    for model in models:
        results = [run_scenario(s, model, catalog, args.live, args.ollama, args.timeout)
                   for s in scenarios]
        model_blocks.append({
            "model": model,
            "scenarios": results,
            "aggregates": aggregate(results),
        })

    findings = {
        "tool": "tool_bench",
        "scenarios_total": len(scenarios),
        "catalog": sorted(catalog),
        "models": model_blocks,
    }
    json.dump(findings, sys.stdout)
    sys.stdout.write("\n")
    print(render_table(findings), file=sys.stderr)
    return EXIT_RAN


if __name__ == "__main__":
    sys.exit(main())
