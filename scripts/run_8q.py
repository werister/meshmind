#!/usr/bin/env python3
"""run_8q.py -- yes/no filter stage of the gateway bake-off protocol.

Implements docs/GATEWAY-CONTRACTS.md v1.2 (FROZEN) exactly.

Usage:
    python3 scripts/run_8q.py --model TAG [--ollama URL] [--fixture PATH]
                              [--timeout S] [--questions PATH]

Conventions (shared across the three harness tools):
  - JSON object to stdout.
  - Human-readable reasons to stderr.
  - exit 0 = the probe ran (pass/fail lives inside the JSON "pass" field).
  - exit 2 = infrastructure error (host down, missing/invalid file, guard trip).

stdout shape:
  {"tool":"run_8q","model":TAG,
   "answers":[{"q":N,"answer":"yes|no|null","latency_s":F} x8],
   "pass":B,"notes":S}

pass=false when any answer is null, is non-yes/no (recorded as null), or when
all 8 answers agree (always-yes / always-no filter). "all agree" is only valid
on a mixed-truth set, so the question set MUST be a 4 yes / 4 no split; a set
that is not 4/4 is an infrastructure error (exit 2), not an ambiguous result.

Stdlib only. No third-party deps. No bare except.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 120
EXIT_RAN = 0
EXIT_INFRA = 2

# PLACEHOLDER question set shipped with the tool. Clearly marked; the
# coordinator swaps in the reviewed set via --questions without rebuilding.
# Mixed ground truth, 4 yes / 4 no.
PLACEHOLDER_QUESTIONS = [
    {"q": "Is the digit 2 an even number?", "expect_yes": True},
    {"q": "Is water wet under normal conditions?", "expect_yes": True},
    {"q": "Does the sun rise in the east?", "expect_yes": True},
    {"q": "Is ice colder than boiling water?", "expect_yes": True},
    {"q": "Is the digit 3 an even number?", "expect_yes": False},
    {"q": "Is the moon larger than the sun?", "expect_yes": False},
    {"q": "Can a fish breathe air out of water indefinitely?", "expect_yes": False},
    {"q": "Is 10 less than 5?", "expect_yes": False},
]


def fail_infra(reason):
    """Print a human reason to stderr and exit 2 (infrastructure error)."""
    print("run_8q: %s" % reason, file=sys.stderr)
    sys.exit(EXIT_INFRA)


def load_json_file(path, what):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail_infra("%s not found: %s" % (what, path))
    except (OSError, ValueError) as exc:
        fail_infra("%s unreadable (%s): %s" % (what, path, exc))


def load_questions(path):
    """Load and validate the 8-question set. Enforce the 4/4 mixed-truth rule."""
    if path is None:
        questions = PLACEHOLDER_QUESTIONS
    else:
        data = load_json_file(path, "questions file")
        if isinstance(data, dict) and "questions" in data:
            questions = data["questions"]
        elif isinstance(data, list):
            questions = data
        else:
            fail_infra("questions file must be a list or {\"questions\": [...]}: %s" % path)
    if not isinstance(questions, list) or len(questions) != 8:
        fail_infra("question set must contain exactly 8 questions (got %s)"
                   % (len(questions) if isinstance(questions, list) else "non-list"))
    yes_count = 0
    no_count = 0
    for idx, item in enumerate(questions, start=1):
        if not isinstance(item, dict) or "q" not in item or "expect_yes" not in item:
            fail_infra("question %d must be an object with 'q' and 'expect_yes'" % idx)
        if not isinstance(item["expect_yes"], bool):
            fail_infra("question %d 'expect_yes' must be a boolean" % idx)
        if item["expect_yes"]:
            yes_count += 1
        else:
            no_count += 1
    if yes_count != 4 or no_count != 4:
        fail_infra("question set must be a mixed 4 yes / 4 no split "
                   "(got %d yes / %d no); 'all agree' is otherwise ambiguous"
                   % (yes_count, no_count))
    return questions


def parse_answer(reply):
    """Map a raw model reply to 'yes', 'no', or None (non-yes/no)."""
    if reply is None:
        return None
    text = str(reply).strip().lower()
    if not text:
        return None
    # Look at the first alphabetic token so "Yes." / "YES, it does." normalize.
    head = ""
    for char in text:
        if char.isalpha():
            head += char
        elif head:
            break
    if head == "yes":
        return "yes"
    if head == "no":
        return "no"
    return None


def ask_ollama(ollama_url, model, question, timeout):
    """Ask one question over /api/chat (stream:false). Returns (reply|None, latency_s).

    reply is None on timeout. Any transport failure that is NOT a timeout
    is raised so the caller can treat the host as down (exit 2).
    """
    url = ollama_url.rstrip("/") + "/api/chat"
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system",
             "content": "Answer with exactly one word: yes or no."},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "think": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json",
                                    "X-Agent": "run_8q"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except TimeoutError:
        return None, round(time.monotonic() - started, 3)
    except (urllib.error.URLError, OSError) as exc:
        # socket.timeout is a subclass of OSError on older pythons.
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError):
            return None, round(time.monotonic() - started, 3)
        raise
    latency = round(time.monotonic() - started, 3)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None, latency
    message = data.get("message") or {}
    return message.get("content"), latency


def answers_from_fixture(fixture, questions):
    """Build the answer rows from a canned fixture, touching no network."""
    canned = fixture.get("answers") if isinstance(fixture, dict) else None
    if not isinstance(canned, dict):
        fail_infra("fixture must carry an 'answers' object keyed by question number")
    rows = []
    for idx in range(1, len(questions) + 1):
        entry = canned.get(str(idx))
        if not isinstance(entry, dict):
            fail_infra("fixture missing answer for question %d" % idx)
        if entry.get("timeout") is True:
            rows.append({"q": idx, "answer": None,
                         "latency_s": float(entry.get("latency_s", 0.0))})
            continue
        answer = parse_answer(entry.get("reply"))
        rows.append({"q": idx, "answer": answer,
                     "latency_s": float(entry.get("latency_s", 0.0))})
    return rows


def answers_from_network(ollama_url, model, questions, timeout):
    """Probe the live host. A transport failure (host down) exits 2."""
    rows = []
    for idx, item in enumerate(questions, start=1):
        try:
            reply, latency = ask_ollama(ollama_url, model, item["q"], timeout)
        except (urllib.error.URLError, OSError) as exc:
            fail_infra("ollama host unreachable at %s: %s" % (ollama_url, exc))
        answer = None if reply is None else parse_answer(reply)
        rows.append({"q": idx, "answer": answer, "latency_s": latency})
    return rows


def verdict(rows):
    """Return (pass_bool, notes_str) per the contract."""
    answers = [row["answer"] for row in rows]
    nulls = sum(1 for a in answers if a not in ("yes", "no"))
    if nulls:
        return False, "%d of %d answers null or non-yes/no" % (nulls, len(answers))
    distinct = set(answers)
    if len(distinct) == 1:
        only = distinct.pop()
        return False, "all %d answers agree (always-%s filter tripped)" % (len(answers), only)
    yes = answers.count("yes")
    no = answers.count("no")
    return True, "mixed answers (%d yes / %d no), filter passed" % (yes, no)


def build_parser():
    parser = argparse.ArgumentParser(
        description="8-question yes/no filter (gateway contracts v1.2).")
    parser.add_argument("--model", required=True, help="model tag under test")
    parser.add_argument("--ollama", default=DEFAULT_OLLAMA,
                        help="ollama base URL (default %(default)s)")
    parser.add_argument("--fixture", default=None,
                        help="read canned answers from PATH, touch no network")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="per-question timeout seconds (default %(default)s)")
    parser.add_argument("--questions", default=None,
                        help="JSON question set (defaults to the PLACEHOLDER 4/4 set)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    questions = load_questions(args.questions)
    if args.fixture is not None:
        fixture = load_json_file(args.fixture, "fixture file")
        rows = answers_from_fixture(fixture, questions)
    else:
        rows = answers_from_network(args.ollama, args.model, questions, args.timeout)
    passed, notes = verdict(rows)
    out = {
        "tool": "run_8q",
        "model": args.model,
        "answers": rows,
        "pass": passed,
        "notes": notes,
    }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return EXIT_RAN


if __name__ == "__main__":
    sys.exit(main())
