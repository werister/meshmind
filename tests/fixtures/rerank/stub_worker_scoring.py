#!/usr/bin/env python3
"""STUB rerank worker (T10 tests): honours the FROZEN interface, no onnx.

argv --model-dir, stdin JSON {query, passages}, stdout JSON {scores:[{id,score}]}.
Deterministic score = len(text) so the endpoint's descending/stable sort and
top_k are testable without real weights. Scores are emitted in INPUT order
(the endpoint owns sorting); equal-length texts keep input order so the
endpoint's stable sort is observable.
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", dest="model_dir", required=True)
    parser.parse_args()
    req = json.loads(sys.stdin.read() or "{}")
    passages = req.get("passages", [])
    scores = [{"id": p.get("id"), "score": float(len(p.get("text", "")))} for p in passages]
    json.dump({"scores": scores}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
