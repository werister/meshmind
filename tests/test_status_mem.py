#!/usr/bin/env python3
"""T6 — memory + swap telemetry tests. Stdlib only, no network, no Mini.

Covers the three required cases from the ticket:
  * additive-keys   — the three new fields are TOP-LEVEL keys of /status
                      (run_ladder.py reads data["mem_free_mb"]) and NONE of the
                      pre-existing top-level/`tokens` keys changed; no nested
                      "memory" block (old readers unaffected).
  * types/sanity    — fields are int|null; free <= total; swap >= 0.
  * parse-drift     — a mutated vm_stat / swapusage body (new macOS line, missing
                      header) yields null fields, never an exception, and read_mem()
                      always returns a well-formed dict.

Run:  python3 tests/test_status_mem.py   -> exit 0 with an explicit PASS count.
"""
import importlib.util
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "status-mem.json")
# 8 GB box (AGENTS.md). Used only as the sanity ceiling for free memory.
TOTAL_RAM_MB = 8192

# Representative macOS `vm_stat` output (page size 16384 on Apple silicon / 4096 intel;
# we use 4096 here so the arithmetic is easy to assert). Numbers are illustrative.
VM_STAT_OK = """Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free:                              190000.
Pages active:                            300000.
Pages inactive:                          120000.
Pages speculative:                         5000.
Pages wired down:                        210000.
Pages occupied by compressor:            760000.
"""
SWAP_OK = "vm.swapusage: total = 2048.00M  used = 1536.00M  free = 512.00M"


def load_server():
    spec = importlib.util.spec_from_file_location("fbserver_mem", os.path.join(ROOT, "feedback-server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def jload(path):
    with open(path) as f:
        return json.load(f)


MOD = load_server()


class AdditiveKeys(unittest.TestCase):
    """The committed fixture proves the shape old readers see is unchanged."""

    def setUp(self):
        self.st = jload(FIXTURE)

    def test_three_new_fields_are_top_level(self):
        # run_ladder.py (merged to main) reads data["mem_free_mb"] etc. at the
        # top level, so the fields must be top-level keys, not nested.
        for k in MOD.MEM_FIELDS:
            self.assertIn(k, self.st, "%s is a top-level /status key" % k)
        self.assertEqual(set(MOD.MEM_FIELDS),
                         {"mem_free_mb", "mem_compressed_mb", "swap_used_mb"})

    def test_no_nested_memory_block(self):
        # one placement only: top-level, never folded into a sub-object
        self.assertNotIn("memory", self.st)
        self.assertNotIn("memory", self.st["tokens"])

    def test_preexisting_blocks_are_untouched(self):
        # Additive means: no rename, no removal of the blocks old readers key on.
        for block in ("ts", "ollama", "health", "tokens", "metering"):
            self.assertIn(block, self.st, "pre-existing key %s still present" % block)
        # the tokens block keeps its exact old keys and does not absorb the new fields
        self.assertEqual(set(self.st["tokens"]), {"probe_total", "feedback_total", "grand_total"})


class TypesAndSanity(unittest.TestCase):
    def setUp(self):
        self.st = jload(FIXTURE)

    def test_fields_are_int_or_null(self):
        for k in MOD.MEM_FIELDS:
            v = self.st[k]
            self.assertTrue(v is None or (isinstance(v, int) and not isinstance(v, bool)),
                            "%s is int|null, got %r" % (k, v))

    def test_free_within_total_and_swap_nonnegative(self):
        free = self.st["mem_free_mb"]
        if free is not None:
            self.assertGreaterEqual(free, 0)
            self.assertLessEqual(free, TOTAL_RAM_MB, "free <= total")
        comp = self.st["mem_compressed_mb"]
        if comp is not None:
            self.assertGreaterEqual(comp, 0)
        swap = self.st["swap_used_mb"]
        if swap is not None:
            self.assertGreaterEqual(swap, 0)


class ParseHappyPath(unittest.TestCase):
    def test_vm_stat_pages_to_mb(self):
        free_mb, comp_mb = MOD.parse_vm_stat(VM_STAT_OK)
        # 190000 pages * 4096 / 1048576 = 742 MB ; 760000 -> 2968 MB
        self.assertEqual(free_mb, round(190000 * 4096 / 1048576))
        self.assertEqual(comp_mb, round(760000 * 4096 / 1048576))

    def test_swapusage_megabytes(self):
        self.assertEqual(MOD.parse_swapusage(SWAP_OK), 1536)

    def test_swapusage_gigabytes_unit(self):
        self.assertEqual(MOD.parse_swapusage("vm.swapusage: total = 4.00G  used = 2.00G  free = 2.00G"), 2048)


class ParseDrift(unittest.TestCase):
    """New/absent macOS lines must degrade to null, never raise."""

    def test_missing_page_size_header(self):
        drifted = "\n".join(l for l in VM_STAT_OK.splitlines() if "page size" not in l)
        self.assertEqual(MOD.parse_vm_stat(drifted), (None, None))

    def test_unknown_future_line_is_ignored_not_fatal(self):
        mutated = VM_STAT_OK + "Pages quantum-entangled:                 123456.\n"
        free_mb, comp_mb = MOD.parse_vm_stat(mutated)
        self.assertEqual(free_mb, round(190000 * 4096 / 1048576))
        self.assertEqual(comp_mb, round(760000 * 4096 / 1048576))

    def test_renamed_free_line_yields_null_for_that_field_only(self):
        mutated = VM_STAT_OK.replace("Pages free:", "Pages gratis:")
        free_mb, comp_mb = MOD.parse_vm_stat(mutated)
        self.assertIsNone(free_mb)                      # renamed -> null
        self.assertEqual(comp_mb, round(760000 * 4096 / 1048576))

    def test_empty_and_garbage_inputs(self):
        self.assertEqual(MOD.parse_vm_stat(""), (None, None))
        self.assertEqual(MOD.parse_vm_stat(None), (None, None))
        self.assertEqual(MOD.parse_vm_stat("totally unrelated text"), (None, None))
        self.assertIsNone(MOD.parse_swapusage(""))
        self.assertIsNone(MOD.parse_swapusage(None))
        self.assertIsNone(MOD.parse_swapusage("vm.swapusage: no numbers here"))

    def test_read_mem_always_returns_well_formed_dict(self):
        # Force both tools to "fail" by pointing _run_cmd at nonexistent argv.
        orig = MOD._run_cmd
        MOD._run_cmd = lambda argv, timeout=5: None
        err = io.StringIO()
        orig_stderr = sys.stderr
        sys.stderr = err
        try:
            out = MOD.read_mem()
        finally:
            sys.stderr = orig_stderr
            MOD._run_cmd = orig
        self.assertEqual(set(out), set(MOD.MEM_FIELDS))
        self.assertTrue(all(out[k] is None for k in MOD.MEM_FIELDS))
        self.assertIn("null", err.getvalue(), "a stderr note was emitted on failure")


def main():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    print("PASS %d/%d (failures=%d errors=%d skipped=%d)" % (
        passed, result.testsRun, len(result.failures), len(result.errors), len(result.skipped)))
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
