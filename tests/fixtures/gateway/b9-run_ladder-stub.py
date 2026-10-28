#!/usr/bin/env python3
"""b9 stub for run_ladder.py — contract-shaped, no network.

Emits a run_ladder JSON object per contracts v1.2. Behaviour keyed off model:

  *LADDERFAIL* -> a failed step, verdict:false (run continues upstream)
  *LADDERDOWN* -> exit 2 (infrastructure error)
  anything else -> two ok steps, verdict:true
"""
import argparse
import json
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--contexts", default="4096")
    p.add_argument("--parallel", default="1,2")
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--status", default="http://127.0.0.1:8081/status")
    p.add_argument("--fixture")
    p.add_argument("--step-timeout", type=int, default=600)
    args = p.parse_args()
    m = args.model

    if "LADDERDOWN" in m:
        sys.stderr.write("status host unreachable (stub)\n")
        return 2

    if "LADDERFAIL" in m:
        steps = [
            {"ctx": 4096, "parallel": 1, "prompt_tokens": 100, "gen_tokens": 50,
             "tok_s": 9.0, "mem_kb": 1048576, "ok": True, "notes": ""},
            {"ctx": 4096, "parallel": 2, "prompt_tokens": 100, "gen_tokens": 0,
             "tok_s": 0.0, "mem_kb": None, "ok": False, "notes": "oom"},
        ]
        verdict = False
    else:
        steps = [
            {"ctx": 4096, "parallel": 1, "prompt_tokens": 100, "gen_tokens": 50,
             "tok_s": 12.5, "mem_kb": 2097152, "ok": True, "notes": ""},
            {"ctx": 4096, "parallel": 2, "prompt_tokens": 100, "gen_tokens": 50,
             "tok_s": 7.3, "mem_kb": 1572864, "ok": True, "notes": "serialized"},
        ]
        verdict = True

    json.dump(
        {"tool": "run_ladder", "model": m, "num_ctx": 4096, "steps": steps, "verdict": verdict},
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
