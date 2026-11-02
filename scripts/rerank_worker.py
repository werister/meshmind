#!/usr/bin/env python3
"""CPU cross-encoder rerank worker (T10). Runs under the Mini's .venv-rerank.

FROZEN interface (do not renegotiate):
  argv  : --model-dir <path>
  stdin : JSON object {"query": str, "passages": [{"id": ..., "text": str}, ...]}
  stdout: JSON object {"scores": [{"id": ..., "score": float}, ...]}

Scores are the cross-encoder relevance logits for (query, passage), one per
input passage, emitted in the SAME ORDER as the input (the endpoint owns the
descending/stable-sort and top_k). Empty passages -> {"scores": []}.

onnxruntime is imported lazily inside _load_session so this file imports with
the stdlib alone; the test suite injects a fake ONNX session object and never
touches real weights (no onnx exists on the build MacBook). No hardcoded cache
paths: the tokenizer/model are loaded strictly from --model-dir.

Errors are reported as a nonzero exit plus a JSON {"error": ...} on stdout so
the endpoint can turn any failure into a clean 503 rather than a crash.
"""
import argparse
import json
import os
import sys


def parse_args(argv):
    parser = argparse.ArgumentParser(description="rerank worker")
    parser.add_argument("--model-dir", dest="model_dir", required=True)
    return parser.parse_args(argv)


def read_request(stream):
    """Read and validate the stdin JSON request. Raises ValueError on bad input."""
    raw = stream.read()
    try:
        req = json.loads(raw or "{}")
    except (ValueError, TypeError) as exc:
        raise ValueError("request is not valid JSON: %s" % (exc,))
    if not isinstance(req, dict):
        raise ValueError("request must be a JSON object")
    query = req.get("query", "")
    passages = req.get("passages", [])
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if not isinstance(passages, list):
        raise ValueError("passages must be a list")
    clean = []
    for item in passages:
        if not isinstance(item, dict):
            raise ValueError("each passage must be an object")
        text = item.get("text", "")
        if not isinstance(text, str):
            raise ValueError("passage text must be a string")
        clean.append({"id": item.get("id"), "text": text})
    return query, clean


def _gelu_exact(x):
    """Exact GELU (torch default) via erf; x is a numpy array."""
    import math

    import numpy as _np

    erf = _np.vectorize(lambda v: math.erf(v / math.sqrt(2.0)))
    return 0.5 * x * (1.0 + erf(x))


def _layer_norm(x, weight, bias, eps=1e-5):
    """LayerNorm with PyTorch-default eps (sentence-transformers passes
    the torch default through; the module config carries no eps)."""
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    return (x - mean) / ((var + eps) ** 0.5) * weight + bias


class _OnnxReranker:
    """Thin wrapper over a tokenizer + ONNX session that yields one score/passage.

    The session is injected by the tests (a fake object exposing .run); in
    production _load_session builds a real onnxruntime.InferenceSession and a
    tokenizer, both loaded from model_dir with no hardcoded cache path.

    The Ettin onnx/model.onnx file is the transformer encoder only (it emits
    last_hidden_state [batch, seq, 256]), so the sentence-transformers head
    (CLS pool -> Dense+GELU -> LayerNorm -> Dense->1, per modules.json and the
    per-module configs) is applied here in numpy from the per-module
    model.safetensors files. `head=None` selects the fake-session test path.
    """

    def __init__(self, session, tokenizer=None, head=None):
        self.session = session
        self.tokenizer = tokenizer
        self.head = head

    def score(self, query, passages):
        if not passages:
            return []
        if self.tokenizer is not None:
            pairs = [(query, p["text"]) for p in passages]
            enc = self.tokenizer(
                [q for q, _ in pairs],
                [d for _, d in pairs],
                padding=True,
                truncation=True,
                return_tensors="np",
            )
            feeds = {k: v for k, v in enc.items()}
        else:
            # Fake-session path used by the tests: pass the raw pairs straight
            # through so the injected object fully controls the returned logits.
            feeds = {"query": query, "passages": [p["text"] for p in passages]}
        outputs = self.session.run(None, feeds)
        if self.head is not None:
            return self._score_head(outputs[0], len(passages))
        logits = outputs[0]
        scores = []
        for row in logits:
            try:
                scores.append(float(row[0]))
            except (TypeError, IndexError):
                scores.append(float(row))
        if len(scores) != len(passages):
            raise ValueError("session returned %d scores for %d passages" % (len(scores), len(passages)))
        return scores

    def _score_head(self, hidden, n):
        """Ettin head: CLS pool -> Dense+GELU -> LayerNorm -> Dense->1."""
        import numpy as _np

        vec = _np.asarray(hidden, dtype=_np.float64)[:, 0, :]
        if vec.shape[0] != n:
            raise ValueError("session returned %d rows for %d passages"
                             % (vec.shape[0], n))
        vec = _gelu_exact(vec @ self.head["dense2"].T)
        vec = _layer_norm(vec, self.head["ln_w"], self.head["ln_b"])
        logits = vec @ self.head["dense4"].T + self.head["dense4_b"]
        return [float(v) for v in logits.reshape(-1)]


def _load_session(model_dir):
    """Build a real onnxruntime session + tokenizer from model_dir (no cache path).

    Imported lazily so this module stays stdlib-only at import time and the
    tests never need onnxruntime installed.
    """
    import onnxruntime  # noqa: F401  (import-time check, real dependency)
    from transformers import AutoTokenizer

    onnx_path = os.path.join(model_dir, "model.onnx")
    session = onnxruntime.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    head = _load_head(model_dir)
    return _OnnxReranker(session, tokenizer, head=head)


def _load_head(model_dir):
    """Load the sentence-transformers head weights (per-module safetensors).

    Layout (from the Ettin repo): 2_Dense/model.safetensors (linear.weight,
    no bias), 3_LayerNorm/model.safetensors (norm.weight/bias),
    4_Dense/model.safetensors (linear.weight/bias). Shapes are asserted so a
    wrong model_dir fails loudly here, not as silent score garbage.
    """
    from safetensors.numpy import load_file

    def one(subdir):
        return load_file(os.path.join(model_dir, subdir, "model.safetensors"))

    d2 = one("2_Dense")["linear.weight"]
    ln = one("3_LayerNorm")
    d4 = one("4_Dense")
    assert d2.shape == (256, 256), d2.shape
    assert ln["norm.weight"].shape == (256,), ln["norm.weight"].shape
    assert ln["norm.bias"].shape == (256,), ln["norm.bias"].shape
    assert d4["linear.weight"].shape == (1, 256), d4["linear.weight"].shape
    assert d4["linear.bias"].shape == (1,), d4["linear.bias"].shape
    return {"dense2": d2, "ln_w": ln["norm.weight"], "ln_b": ln["norm.bias"],
            "dense4": d4["linear.weight"], "dense4_b": d4["linear.bias"]}


def run(reranker, query, passages):
    scores = reranker.score(query, passages)
    return {"scores": [{"id": p["id"], "score": s} for p, s in zip(passages, scores)]}


def main(argv=None, stdin=None, stdout=None, reranker=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    args = parse_args(argv)
    try:
        query, passages = read_request(stdin)
    except ValueError as exc:
        json.dump({"error": str(exc)}, stdout)
        return 2
    if not passages:
        json.dump({"scores": []}, stdout)
        return 0
    try:
        if reranker is None:
            reranker = _load_session(args.model_dir)
        result = run(reranker, query, passages)
    except Exception as exc:  # worker never crashes; the endpoint maps this to 503
        json.dump({"error": "rerank failed: %s" % (exc,)}, stdout)
        return 1
    json.dump(result, stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
