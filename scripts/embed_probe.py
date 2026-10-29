#!/usr/bin/env python3
"""embed_probe.py — minimal embedding bake-off: nomic vs bge-m3 (coordinator runs on Mini).

Hand-step from the gateway runbook, scripted for repeatability. Embeds a
fixed similar/dissimilar triple through the metering proxy (measured,
X-Agent: embed-probe) and reports dims, latencies, and cosine sims.

  python3 scripts/embed_probe.py [--proxy URL] [--models M1,M2]

Exit 0 = ran (sanity pass/fail lives in the JSON), exit 2 = infra error.
"""
import argparse
import json
import sys
import time
import urllib.request

TEXTS = [
    "The database query failed with a connection timeout",
    "The SQL connection timed out during the query",
    "The cake recipe needs more sugar and flour",
]
DEFAULT_PROXY = "http://127.0.0.1:8081"
DEFAULT_MODELS = "nomic-embed-text:v1.5,bge-m3:latest"


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return None
    return round(dot / (na * nb), 4)


def embed(proxy, model, text, timeout=120):
    url = proxy.rstrip("/") + "/api/embeddings"
    body = json.dumps({"model": model, "prompt": text}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "X-Agent": "embed-probe"})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return payload.get("embedding"), round(time.monotonic() - started, 3)


def main(argv=None):
    args = parse_args(argv)
    out = {"tool": "embed_probe", "models": {}, "sanity_pass": None, "notes": []}
    try:
        for model in args.models.split(","):
            model = model.strip()
            if not model:
                continue
            vecs, lats = [], []
            for text in TEXTS:
                vec, lat = embed(args.proxy, model, text)
                if not vec:
                    raise RuntimeError("empty embedding for %s" % model)
                vecs.append(vec)
                lats.append(lat)
            out["models"][model] = {
                "dim": len(vecs[0]),
                "latency_s": lats,
                "cos_similar": cosine(vecs[0], vecs[1]),
                "cos_dissimilar": cosine(vecs[0], vecs[2]),
            }
    except Exception as exc:  # infra failure: report, exit 2
        sys.stderr.write("embed_probe infra error: %s\n" % exc)
        return 2
    sims = [(m, r["cos_similar"], r["cos_dissimilar"])
            for m, r in out["models"].items()]
    out["sanity_pass"] = all(s is not None and d is not None and s > d
                              for _, s, d in sims) or None
    if out["sanity_pass"] is None:
        out["sanity_pass"] = False
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


def parse_args(argv):
    p = argparse.ArgumentParser(description="Embedding mini-probe (runbook hand-step)")
    p.add_argument("--proxy", default=DEFAULT_PROXY)
    p.add_argument("--models", default=DEFAULT_MODELS)
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
