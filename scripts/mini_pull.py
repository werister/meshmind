#!/usr/bin/env python3
"""mini_pull.py — guarded single-model pull (coordinator runs this on the Mini).

Implements docs/GATEWAY-CONTRACTS.md v1.2 (FROZEN):

  python3 scripts/mini_pull.py pull --spec SPEC --expect-gb F [--ollama URL]

Guards IN ORDER:
  1. free disk >= 15 GB        (abort BEFORE any pull if short)
  2. ollama pull/create        (tag:NAME -> pull; gguf:URL|FILE -> create)
  3. size within +-20% of expect-gb
  4. 1-token probe
  -> report JSON to stdout.

Any guard trip: human reason to stderr, exit 2, no partial state hidden (a
pulled-but-wrong-size model is REPORTED, the coordinator decides whether to
`ollama rm`). exit 0 = ran clean. exit 2 = guard trip / infrastructure error.

--spec grammar: `tag:NAME` or `gguf:URL|FILE`. For gguf, FILE is the local
filename the Modelfile references; the created tag is derived from FILE stem.

The subprocess/HTTP boundaries are injectable so the unit tests drive the
guards with fixtures (fake df, fake ollama, fake probe) and NEVER pull.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

MIN_FREE_GB = 15.0
SIZE_BAND = 0.20  # +-20%
GB = 1_000_000_000  # decimal GB, matches PULLPACK expect-gb (manifest bytes / 1e9)


class GuardTrip(Exception):
    """Raised when a guard fails; carries a report dict for stderr + stdout."""

    def __init__(self, reason, report=None):
        super().__init__(reason)
        self.reason = reason
        self.report = report or {}


# --- injectable primitives (overridden in tests) ---------------------------

def free_disk_gb(path="/"):
    """Free bytes on the filesystem holding `path`, in decimal GB."""
    usage = shutil.disk_usage(path)
    return usage.free / GB


def ollama_pull(tag, ollama_url):
    """Pull a library tag. Returns None on success, raises GuardTrip on failure."""
    proc = subprocess.run(
        ["ollama", "pull", tag],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_ollama_env(ollama_url),
    )
    if proc.returncode != 0:
        raise GuardTrip(
            "ollama pull failed: %s"
            % proc.stderr.decode("utf-8", "replace").strip()[:200]
        )


def ollama_create(tag, modelfile_path, ollama_url):
    proc = subprocess.run(
        ["ollama", "create", tag, "-f", modelfile_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_ollama_env(ollama_url),
    )
    if proc.returncode != 0:
        raise GuardTrip(
            "ollama create failed: %s"
            % proc.stderr.decode("utf-8", "replace").strip()[:200]
        )


def download_gguf(url, dest, timeout=1800):
    """Stream-download a GGUF to `dest` in chunks, progress notes to stderr.

    urlopen follows HF `resolve/main` -> CDN redirects transparently. Returns
    the number of bytes written. Raises GuardTrip on a transport error or a
    zero-byte result so nothing proceeds to `ollama create` on an empty file.
    """
    chunk = 1 << 20  # 1 MiB
    written = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mini_pull/1.2"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = resp.headers.get("Content-Length")
            total = int(total) if total and total.isdigit() else None
            next_mark = 0
            with open(dest, "wb") as fh:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    fh.write(buf)
                    written += len(buf)
                    if written >= next_mark:
                        if total:
                            sys.stderr.write(
                                "  download %s: %.1f/%.1f MB\n"
                                % (os.path.basename(dest), written / 1e6, total / 1e6)
                            )
                        else:
                            sys.stderr.write(
                                "  download %s: %.1f MB\n"
                                % (os.path.basename(dest), written / 1e6)
                            )
                        sys.stderr.flush()
                        next_mark = written + 64 * chunk  # note every ~64 MiB
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GuardTrip("gguf download failed: %s: %s" % (exc.__class__.__name__, exc))
    if written <= 0:
        raise GuardTrip("gguf download produced 0 bytes from %s" % url)
    sys.stderr.write("  download %s: done, %d bytes\n" % (os.path.basename(dest), written))
    return written


def ollama_size_bytes(tag, ollama_url):
    """Resolved on-disk size of a local tag via GET /api/tags."""
    url = ollama_url.rstrip("/") + "/api/tags"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    names = {tag} | ({tag + ":latest"} if ":" not in tag else set())
    for model in data.get("models", []):
        if model.get("name") in names:
            return model.get("size")
    raise GuardTrip("model %r not found in /api/tags after pull" % tag)


def _generate_ok(tag, ollama_url):
    """True when a 1-token /api/generate call answers (raises otherwise)."""
    url = ollama_url.rstrip("/") + "/api/generate"
    body = json.dumps(
        {"model": tag, "prompt": "ping", "stream": False, "options": {"num_predict": 1}}
    ).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return bool(payload.get("response") is not None or payload.get("done"))


def _embeddings_ok(tag, ollama_url):
    """True when /api/embeddings returns a non-empty vector (raises otherwise)."""
    url = ollama_url.rstrip("/") + "/api/embeddings"
    body = json.dumps({"model": tag, "prompt": "ping"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return bool(payload.get("embedding"))


def ollama_probe(tag, ollama_url, gen_fn=_generate_ok, emb_fn=_embeddings_ok):
    """Probe a pulled model. Generators answer /api/generate; embedding-only
    models fail there, so any generate failure falls back to /api/embeddings
    (model-agnostic: no name heuristics). Returns True when either answers."""
    try:
        return bool(gen_fn(tag, ollama_url))
    except Exception:
        return bool(emb_fn(tag, ollama_url))


def _ollama_env(ollama_url):
    env = os.environ.copy()
    if ollama_url:
        host = ollama_url.replace("http://", "").replace("https://", "")
        env["OLLAMA_HOST"] = host
    return env


# --- spec parsing -----------------------------------------------------------

def parse_spec(spec):
    """Return (kind, payload). kind in {'tag','gguf'}.

    tag:NAME          -> ('tag', 'NAME')
    gguf:URL|FILE     -> ('gguf', (URL, FILE))
    """
    if spec.startswith("tag:"):
        name = spec[len("tag:"):].strip()
        if not name:
            raise GuardTrip("empty tag in --spec")
        return "tag", name
    if spec.startswith("gguf:"):
        rest = spec[len("gguf:"):]
        if "|" not in rest:
            raise GuardTrip("gguf spec must be gguf:URL|FILE")
        url, _, fname = rest.partition("|")
        url, fname = url.strip(), fname.strip()
        if not url or not fname:
            raise GuardTrip("gguf spec missing URL or FILE")
        return "gguf", (url, fname)
    raise GuardTrip("unknown --spec scheme (expected tag: or gguf:)")


def _derive_tag(fname):
    stem = os.path.basename(fname)
    if stem.lower().endswith(".gguf"):
        stem = stem[: -len(".gguf")]
    return (stem.lower() + ":bakeoff").replace("_", "-")


# --- guard pipeline ---------------------------------------------------------

def guarded_pull(
    spec,
    expect_gb,
    ollama_url="http://127.0.0.1:11434",
    *,
    disk_fn=free_disk_gb,
    pull_fn=ollama_pull,
    create_fn=ollama_create,
    download_fn=download_gguf,
    size_fn=ollama_size_bytes,
    probe_fn=ollama_probe,
    gguf_dir=".",
):
    """Run the four guards in order. Returns a report dict on success.

    Raises GuardTrip (with a partial report) on any failure so nothing is
    hidden: a pulled-but-wrong-size model is reported, not silently removed.
    """
    kind, payload = parse_spec(spec)
    report = {"spec": spec, "expect_gb": expect_gb, "kind": kind}

    # Guard 1: free disk BEFORE any pull.
    free_gb = disk_fn("/")
    report["free_gb_before"] = round(free_gb, 3)
    if free_gb < MIN_FREE_GB:
        raise GuardTrip(
            "free disk %.2f GB < %.0f GB floor; aborting before pull"
            % (free_gb, MIN_FREE_GB),
            report,
        )

    # Guard 2: pull / create.
    if kind == "tag":
        tag = payload
        pull_fn(tag, ollama_url)
    else:
        url, fname = payload
        # Basename-sanitize: never let the spec's FILE escape gguf_dir.
        safe_name = os.path.basename(fname)
        if not safe_name or safe_name in (".", ".."):
            raise GuardTrip("gguf spec FILE has no usable basename: %r" % fname)
        tag = _derive_tag(safe_name)
        modelfile = os.path.join(gguf_dir, tag.replace(":", "_") + ".Modelfile")
        local_gguf = os.path.join(gguf_dir, safe_name)
        report["gguf_url"] = url
        report["gguf_file"] = local_gguf
        report["modelfile"] = modelfile
        # Fetch the weights BEFORE create, else `ollama create` fails on a
        # missing FROM file (the real gap: LFM2.5 + SmolLM3 are gguf lines).
        downloaded = download_fn(url, local_gguf)
        report["downloaded_bytes"] = downloaded
        with open(modelfile, "w") as fh:
            fh.write("FROM ./%s\n" % safe_name)
        create_fn(tag, modelfile, ollama_url)
    report["tag"] = tag

    # Guard 3: size within +-20% of expect.
    actual_bytes = size_fn(tag, ollama_url)
    report["actual_bytes"] = actual_bytes
    expect_bytes = expect_gb * GB
    report["actual_gb"] = round((actual_bytes or 0) / GB, 3)
    low, high = expect_bytes * (1 - SIZE_BAND), expect_bytes * (1 + SIZE_BAND)
    report["band_gb"] = [round(low / GB, 3), round(high / GB, 3)]
    if actual_bytes is None or not (low <= actual_bytes <= high):
        report["size_ok"] = False
        raise GuardTrip(
            "post-pull size %.3f GB out of band [%.3f, %.3f] for expect %.3f GB; "
            "coordinator decides keep/revert (ollama rm %s)"
            % (report["actual_gb"], low / GB, high / GB, expect_gb, tag),
            report,
        )
    report["size_ok"] = True

    # Guard 4: 1-token probe.
    probe_ok = bool(probe_fn(tag, ollama_url))
    report["probe_ok"] = probe_ok
    if not probe_ok:
        raise GuardTrip("1-token probe failed for %s" % tag, report)

    report["ok"] = True
    return report


def parse_args(argv):
    p = argparse.ArgumentParser(description="Guarded Mini pull (contracts v1.2)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pull = sub.add_parser("pull", help="guarded single-model pull")
    pull.add_argument("--spec", required=True, help="tag:NAME or gguf:URL|FILE")
    pull.add_argument("--expect-gb", required=True, type=float, dest="expect_gb")
    pull.add_argument("--ollama", default="http://127.0.0.1:11434")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.cmd != "pull":
        sys.stderr.write("unknown command\n")
        return 2
    try:
        report = guarded_pull(args.spec, args.expect_gb, args.ollama)
    except GuardTrip as trip:
        sys.stderr.write(trip.reason + "\n")
        if trip.report:
            json.dump(trip.report, sys.stdout)
            sys.stdout.write("\n")
        return 2
    json.dump(report, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
