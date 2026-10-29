#!/usr/bin/env python3
"""Stdlib contract-conformance harness for scripts/mini_pull.py — run directly.

Drives the four guards with injected fixtures (fake df / ollama / probe) so
NOTHING is pulled and no network is touched. Also exercises the CLI exit
codes end to end. Prints a PASS count on exit.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINI_PULL = ROOT / "scripts" / "mini_pull.py"

# Import the module directly (hyphen-free path via spec loader).
_spec = importlib.util.spec_from_file_location("mini_pull", MINI_PULL)
mini_pull = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mini_pull)

GB = mini_pull.GB


def fake_disk(free_gb):
    return lambda _path="/": free_gb


def fake_size(bytes_value):
    return lambda _tag, _url: bytes_value


class SpecParsing(unittest.TestCase):
    def test_tag_spec(self):
        self.assertEqual(mini_pull.parse_spec("tag:granite4:micro-h"), ("tag", "granite4:micro-h"))

    def test_gguf_spec(self):
        kind, (url, fname) = mini_pull.parse_spec("gguf:https://h/f.gguf|f.gguf")
        self.assertEqual((kind, url, fname), ("gguf", "https://h/f.gguf", "f.gguf"))

    def test_bad_scheme(self):
        with self.assertRaises(mini_pull.GuardTrip):
            mini_pull.parse_spec("oci:whatever")

    def test_gguf_missing_pipe(self):
        with self.assertRaises(mini_pull.GuardTrip):
            mini_pull.parse_spec("gguf:https://h/f.gguf")


class GuardPipeline(unittest.TestCase):
    def _called(self):
        bag = {"pull": 0, "create": 0, "probe": 0}
        return bag

    def test_happy_path_tag(self):
        bag = self._called()

        def pull(tag, url):
            bag["pull"] += 1

        def probe(tag, url):
            bag["probe"] += 1
            return True

        report = mini_pull.guarded_pull(
            "tag:granite4:micro-h", 1.943, "http://x",
            disk_fn=fake_disk(50), pull_fn=pull,
            size_fn=fake_size(int(1.943 * GB)), probe_fn=probe,
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["size_ok"])
        self.assertTrue(report["probe_ok"])
        self.assertEqual(report["tag"], "granite4:micro-h")
        self.assertEqual((bag["pull"], bag["probe"]), (1, 1))

    def test_disk_guard_aborts_before_pull(self):
        bag = self._called()

        def pull(tag, url):
            bag["pull"] += 1

        with self.assertRaises(mini_pull.GuardTrip) as cm:
            mini_pull.guarded_pull(
                "tag:any", 2.0, "http://x",
                disk_fn=fake_disk(10), pull_fn=pull,
                size_fn=fake_size(int(2 * GB)), probe_fn=lambda *a: True,
            )
        self.assertIn("free disk", cm.exception.reason)
        self.assertEqual(bag["pull"], 0, "must NOT pull when disk is short")
        self.assertEqual(cm.exception.report["free_gb_before"], 10)

    def test_size_band_trip_reports_and_names_expected(self):
        # actual far above the +-20% band
        with self.assertRaises(mini_pull.GuardTrip) as cm:
            mini_pull.guarded_pull(
                "tag:big", 1.0, "http://x",
                disk_fn=fake_disk(50), pull_fn=lambda *a: None,
                size_fn=fake_size(int(2.0 * GB)), probe_fn=lambda *a: True,
            )
        self.assertIn("out of band", cm.exception.reason)
        rep = cm.exception.report
        self.assertFalse(rep["size_ok"])
        self.assertEqual(rep["actual_gb"], 2.0)
        self.assertEqual(rep["band_gb"], [0.8, 1.2])

    def test_size_band_edges_inclusive(self):
        # exactly +20% is still inside the band
        report = mini_pull.guarded_pull(
            "tag:edge", 1.0, "http://x",
            disk_fn=fake_disk(50), pull_fn=lambda *a: None,
            size_fn=fake_size(int(1.2 * GB)), probe_fn=lambda *a: True,
        )
        self.assertTrue(report["size_ok"])

    def test_probe_failure_trips_after_size_ok(self):
        with self.assertRaises(mini_pull.GuardTrip) as cm:
            mini_pull.guarded_pull(
                "tag:mute", 1.0, "http://x",
                disk_fn=fake_disk(50), pull_fn=lambda *a: None,
                size_fn=fake_size(int(1.0 * GB)), probe_fn=lambda *a: False,
            )
        self.assertIn("probe failed", cm.exception.reason)
        self.assertTrue(cm.exception.report["size_ok"])
        self.assertFalse(cm.exception.report["probe_ok"])

    def test_gguf_creates_modelfile_and_runs_create(self):
        tmp = tempfile.TemporaryDirectory(prefix="b9-gguf-")
        self.addCleanup(tmp.cleanup)
        bag = {"create": 0, "download": 0}

        def download(url, dest, timeout=1800):
            bag["download"] += 1
            with open(dest, "wb") as fh:
                fh.write(b"\x00" * 1024)
            return 1024

        def create(tag, modelfile, url):
            bag["create"] += 1
            self.assertTrue(os.path.exists(modelfile))
            self.assertIn("FROM ./SmolLM3.gguf", Path(modelfile).read_text())
            # weights must exist on disk before create is called
            self.assertTrue(os.path.exists(os.path.join(tmp.name, "SmolLM3.gguf")))

        report = mini_pull.guarded_pull(
            "gguf:https://h/SmolLM3.gguf|SmolLM3.gguf", 1.915, "http://x",
            disk_fn=fake_disk(50), create_fn=create, download_fn=download,
            size_fn=fake_size(int(1.915 * GB)), probe_fn=lambda *a: True,
            gguf_dir=tmp.name,
        )
        self.assertEqual((bag["download"], bag["create"]), (1, 1))
        self.assertEqual(report["downloaded_bytes"], 1024)
        self.assertTrue(report["ok"])
        self.assertEqual(report["kind"], "gguf")
        self.assertIn("gguf_url", report)

    def test_real_download_over_file_url(self):
        # Exercise the real download_gguf path using a file:// URL as source
        # (urlopen handles file://), so no network is touched.
        tmp = tempfile.TemporaryDirectory(prefix="b9-dl-")
        self.addCleanup(tmp.cleanup)
        src = Path(tmp.name) / "weights.gguf"
        src.write_bytes(b"GGUF" + b"\x01" * (2048 - 4))
        url = src.as_uri()  # file:///...
        dest = Path(tmp.name) / "fetched" / "weights.gguf"
        dest.parent.mkdir()
        written = mini_pull.download_gguf(url, str(dest))
        self.assertEqual(written, 2048)
        self.assertEqual(dest.read_bytes(), src.read_bytes())

    def test_download_zero_bytes_trips(self):
        tmp = tempfile.TemporaryDirectory(prefix="b9-dl0-")
        self.addCleanup(tmp.cleanup)
        src = Path(tmp.name) / "empty.gguf"
        src.write_bytes(b"")
        with self.assertRaises(mini_pull.GuardTrip) as cm:
            mini_pull.download_gguf(src.as_uri(), str(Path(tmp.name) / "out.gguf"))
        self.assertIn("0 bytes", cm.exception.reason)

    def test_gguf_download_runs_before_create_via_file_url(self):
        # Full gguf pipeline with a real file:// download feeding ollama create.
        tmp = tempfile.TemporaryDirectory(prefix="b9-gguf-e2e-")
        self.addCleanup(tmp.cleanup)
        srcdir = Path(tmp.name) / "src"
        srcdir.mkdir()
        gdir = Path(tmp.name) / "dest"
        gdir.mkdir()
        src = srcdir / "LFM2.5.gguf"
        src.write_bytes(b"GGUF" + b"\x02" * 4092)
        seen = {"create_file_exists": False}

        def create(tag, modelfile, url):
            seen["create_file_exists"] = os.path.exists(os.path.join(str(gdir), "LFM2.5.gguf"))

        report = mini_pull.guarded_pull(
            "gguf:%s|LFM2.5.gguf" % src.as_uri(), 0.731, "http://x",
            disk_fn=fake_disk(50), create_fn=create,
            size_fn=fake_size(int(0.731 * GB)), probe_fn=lambda *a: True,
            gguf_dir=str(gdir),
        )
        self.assertTrue(seen["create_file_exists"], "weights must exist before create")
        self.assertEqual(report["downloaded_bytes"], 4096)
        self.assertTrue(report["ok"])


class T91TagAndProbeFixes(unittest.TestCase):
    """T9.1: :latest-tolerant size lookup + embeddings probe fallback.

    Live-found on the Mini: `tag:bge-m3` pulled fine but the size lookup
    missed because /api/tags reports `bge-m3:latest`; embedding-only models
    also fail a /api/generate probe. No network: file:// tags fixtures and
    injected probe fakes.
    """

    def _tags_uri(self, models):
        tmp = tempfile.TemporaryDirectory(prefix="b9-tags-")
        self.addCleanup(tmp.cleanup)
        apidir = Path(tmp.name) / "api"
        apidir.mkdir()
        (apidir / "tags").write_text(json.dumps({"models": models}))
        return Path(tmp.name).as_uri()

    def test_size_lookup_tolerates_missing_latest(self):
        uri = self._tags_uri([{"name": "bge-m3:latest", "size": 1157672605}])
        self.assertEqual(mini_pull.ollama_size_bytes("bge-m3", uri), 1157672605)

    def test_size_lookup_exact_still_wins(self):
        uri = self._tags_uri([{"name": "qwen3:1.7b", "size": 1359293444}])
        self.assertEqual(mini_pull.ollama_size_bytes("qwen3:1.7b", uri), 1359293444)

    def test_size_lookup_missing_trips(self):
        uri = self._tags_uri([{"name": "other:tag", "size": 1}])
        with self.assertRaises(mini_pull.GuardTrip):
            mini_pull.ollama_size_bytes("nope", uri)

    def test_probe_generate_ok_skips_fallback(self):
        seen = {"emb": 0}

        def emb(tag, url):
            seen["emb"] += 1
            return True

        self.assertTrue(mini_pull.ollama_probe(
            "m", "http://x", gen_fn=lambda *a: True, emb_fn=emb))
        self.assertEqual(seen["emb"], 0)

    def test_probe_falls_back_to_embeddings(self):
        def gen(tag, url):
            raise OSError("generate refused")

        self.assertTrue(mini_pull.ollama_probe(
            "bge-m3", "http://x", gen_fn=gen, emb_fn=lambda *a: True))

    def test_probe_both_fail_raises(self):
        def boom(tag, url):
            raise OSError("down")

        with self.assertRaises(OSError):
            mini_pull.ollama_probe("m", "http://x", gen_fn=boom, emb_fn=boom)


class CliExitCodes(unittest.TestCase):
    """End-to-end CLI: bad spec / missing args surface exit 2 without pulling.

    A real `pull` subcommand would hit the network, so we only drive the paths
    that trip a guard BEFORE any pull (disk guard via a tiny monkeypatch env is
    not available to a subprocess, so we assert the no-pull guard-trips here by
    using an unparseable spec, which fails in parse_spec -> exit 2).
    """

    def _run(self, args):
        return subprocess.run([sys.executable, str(MINI_PULL)] + args,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def test_bad_spec_exit2(self):
        proc = self._run(["pull", "--spec", "oci:nope", "--expect-gb", "1.0"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"scheme", proc.stderr)

    def test_missing_subcommand_exit2(self):
        proc = self._run([])
        self.assertEqual(proc.returncode, 2)

    def test_gguf_missing_pipe_exit2(self):
        proc = self._run(["pull", "--spec", "gguf:https://h/f.gguf", "--expect-gb", "1.0"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"URL|FILE", proc.stderr)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print("\nPASS %d/%d (failures=%d errors=%d)"
          % (passed, result.testsRun, len(result.failures), len(result.errors)))
    sys.exit(0 if result.wasSuccessful() else 1)
