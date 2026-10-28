#!/usr/bin/env python3
"""b9 stub for run_8q.py — contract-shaped, no network.

Emits a run_8q JSON object per contracts v1.2. Behaviour keyed off the model
name so bakeoff tests can drive pass/fail/infra paths:

  *PASS*  -> pass:true  (4/4 mixed answers)
  *FILTER* or *ALLYES* -> pass:false (always-agree)
  *INFRA* -> exit 2 + stderr reason (infrastructure error)
  *BADJSON* -> garbage to stdout, exit 0 (malformed)
  anything else -> pass:true
"""
import argparse
import json
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--fixture")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--questions")
    args = p.parse_args()
    m = args.model

    if "INFRA" in m:
        sys.stderr.write("backend down (stub infra error)\n")
        return 2
    if "BADJSON" in m:
        sys.stdout.write("this is not json\n")
        return 0

    if "FILTER" in m or "ALLYES" in m:
        answers = [{"q": i, "answer": "yes", "latency_s": 0.1} for i in range(8)]
        passed = False
        notes = "always-yes"
    else:
        answers = [
            {"q": i, "answer": "yes" if i % 2 == 0 else "no", "latency_s": 0.1}
            for i in range(8)
        ]
        passed = True
        notes = ""

    json.dump(
        {"tool": "run_8q", "model": m, "answers": answers, "pass": passed, "notes": notes},
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
