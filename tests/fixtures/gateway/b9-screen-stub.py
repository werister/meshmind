#!/usr/bin/env python3
"""b9 stub for the mml-stack logprob screen — contract-shaped, no network.

Invoked by bakeoff via --screen-cmd 'python3 .../b9-screen-stub.py --model {model}'.
Emits a small JSON object with auc/kappa. Model name 'SCREENFAIL' -> exit 2.
"""
import argparse
import json
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    args = p.parse_args()
    if "SCREENFAIL" in args.model:
        sys.stderr.write("screen harness error (stub)\n")
        return 2
    json.dump({"tool": "screen", "model": args.model, "auc": 0.71, "kappa": 0.68}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
